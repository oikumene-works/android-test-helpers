#!/usr/bin/env python3
"""Strict local ADB double. Never delegates to an installed adb or a device."""

import json
import hashlib
import os
from pathlib import Path
import signal
import struct
import sys
import time
import zlib


root = Path(os.environ["CAPTURE_TEST_ROOT"])
scenario = os.environ.get("CAPTURE_TEST_SCENARIO", "success")
args = sys.argv[1:]
if args[:6] != ["-H", "127.0.0.1", "-P", "42117", "-s", "test-device-1"]:
    sys.exit("unexpected connection/device selection")
if any(key in os.environ for key in ("ADB_SERVER_SOCKET", "ANDROID_SERIAL",
                                     "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT")):
    sys.exit("inherited connection/device environment")
command = args[6:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(command) + "\n")


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def remote(path):
    if not path.startswith("/data/local/tmp/fdroid-phase-"):
        sys.exit("unexpected remote path")
    return root / "remote" / path.removeprefix("/data/local/tmp/")

helper = root / "preserve"
helper.mkdir(exist_ok=True)
helper_package = "qa.capture.preserve"
helper_apk = "/data/app/~~capture/base.apk"


if command == ["get-state"]:
    if scenario == "offline":
        print("error: device offline", file=sys.stderr)
        sys.exit(1)
    if scenario == "interrupt":
        os.kill(os.getppid(), signal.SIGINT)
        time.sleep(1)
    print("device")
elif command == ["exec-out", "screencap", "-p"]:
    if scenario == "screenshot_error":
        print("screencap permission denied", file=sys.stderr)
        sys.stdout.buffer.write(b"partial")
        sys.exit(1)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + chunk(b"IEND", b""))
    if scenario == "truncated_png":
        png = png[:-6]
    elif scenario == "bad_png_crc":
        png = png[:29] + bytes([png[29] ^ 1]) + png[30:]
    sys.stdout.buffer.write(png)
elif command == ["shell", "am", "get-current-user"]:
    print("10" if scenario == "preserve_other_user" else "0")
elif command == ["shell", "pm", "path", "--user", "0", helper_package]:
    if scenario != "preserve_missing_helper": print("package:" + helper_apk)
elif command == ["shell", "sha256sum", helper_apk]:
    digest = hashlib.sha256(b"simulated preserving helper").hexdigest()
    print(("0" * 64 if scenario == "preserve_wrong_apk" else digest) + "  " + helper_apk)
elif command[:3] == ["shell", "run-as", helper_package]:
    operation = command[3:]
    if operation == ["mkdir", "fdroid-capture-lock"]:
        if scenario == "preserve_lock_busy":
            (helper / "fdroid-capture-lock").mkdir(exist_ok=True)
            (helper / "fdroid-capture-lock/other-owner.txt").write_text("keep")
            sys.exit("File exists")
        (helper / "fdroid-capture-lock").mkdir()
        if scenario == "preserve_lock_timeout": time.sleep(3)
        if scenario == "preserve_lock_interrupt":
            os.kill(os.getppid(), signal.SIGINT)
            time.sleep(1)
    elif operation[:2] == ["rm", "-f"]:
        if scenario == "preserve_cleanup_error": sys.exit("permission denied")
        (helper / operation[2]).unlink(missing_ok=True)
    elif operation[:3] == ["test", "!", "-e"]:
        sys.exit(1 if (helper / operation[3]).exists() else 0)
    elif operation == ["rmdir", "fdroid-capture-lock"]:
        (helper / "fdroid-capture-lock").rmdir()
    else:
        sys.exit("unexpected helper operation")
elif command[:3] == ["exec-out", "run-as", helper_package]:
    assert command[3] == "cat"
    sys.stdout.buffer.write((helper / command[4]).read_bytes())
elif command[:3] == ["shell", "am", "instrument"]:
    assert command[3:7] == ["--user", "0", "-w", "-r"]
    assert command[-1] == helper_package + "/.DumpInstrumentation"
    assert (helper / "fdroid-capture-lock").is_dir()
    token = command[command.index("capture_id") + 1]
    package = command[command.index("expected_package") + 1]
    assert package == "org.example.test"
    (helper / "running").write_text("1234")
    if scenario == "preserve_timeout":
        print("instrumentation started", flush=True)
        time.sleep(3)
    if scenario == "preserve_interrupt":
        os.kill(os.getppid(), signal.SIGINT)
        time.sleep(1)
    if scenario == "preserve_instrument_error":
        print("INSTRUMENTATION_RESULT: error=Unexpected active package\nINSTRUMENTATION_CODE: 1")
    else:
        xml_token = "old" if scenario == "preserve_stale_tree" else token
        flags = "0" if scenario == "preserve_wrong_flags" else "1"
        package = "org.other.app" if scenario == "preserve_wrong_package" else package
        xml = f'<hierarchy capture_id="{xml_token}" connection_flags="{flags}"><node package="{package}" text="fresh preserve"/></hierarchy>'
        if scenario == "preserve_empty_tree": xml = '<hierarchy/>'
        if scenario != "preserve_missing_tree":
            (helper / "files").mkdir(exist_ok=True)
            (helper / ("files/tree-" + token + ".xml")).write_text(xml)
        print("INSTRUMENTATION_CODE: -1")
    (helper / "running").unlink()
elif command == ["shell", "am", "force-stop", "--user", "0", helper_package]:
    if scenario == "preserve_stop_error": sys.exit("stop failed")
    (helper / "running").unlink(missing_ok=True)
elif command == ["shell", "pidof", helper_package]:
    if scenario == "preserve_pid_error": sys.exit("pid query failed")
    if scenario == "preserve_still_running" or (helper / "running").exists(): print("1234")
    else: sys.exit(1)
elif command[:2] == ["shell", "mkdir"] and len(command) == 3:
    remote(command[2]).mkdir(parents=True, exist_ok=False)
elif command[:3] == ["shell", "uiautomator", "dump"] and len(command) == 4:
    if scenario == "ui_timeout":
        print("uiautomator started", flush=True)
        time.sleep(3)
    if scenario == "ui_error" or scenario.startswith("fallback_"):
        print("ERROR: could not get idle state", file=sys.stderr)
        sys.exit(1)
    xml = '<hierarchy rotation="0"><node text="Test note" focused="true" /></hierarchy>'
    if scenario == "bad_xml":
        xml = "<hierarchy><node"
    elif scenario == "empty_xml":
        xml = '<hierarchy rotation="0" />'
    remote(command[3]).write_text(xml)
    print("UI hierarchy dumped")
elif command[:2] == ["exec-out", "cat"] and len(command) == 3:
    sys.stdout.buffer.write(remote(command[2]).read_bytes())
elif command[:1] == ["push"] and len(command) == 3:
    if scenario == "fallback_push_error":
        sys.exit("simulated push failure")
    remote(command[2]).write_bytes(Path(command[1]).read_bytes())
elif command[:2] == ["shell", "env"]:
    assert command[3:7] == ["app_process", "/system/bin", "com.android.commands.uiautomator.Launcher", "runtest"]
    assert command[7:12] == ["-c", "qa.NoIdleDump", "-s", "-e", "output"]
    assert remote(command[2].split(":")[-1]).is_file()
    if scenario == "fallback_timeout":
        print("fallback started", flush=True)
        time.sleep(3)
    if scenario == "fallback_interrupt":
        os.kill(os.getppid(), signal.SIGINT)
        time.sleep(1)
    if scenario != "fallback_missing_xml":
        path = remote("/data/local/tmp/" + command[12])
        assert not path.exists()
        path.write_text('<hierarchy/>' if scenario == "fallback_empty_xml" else
                        '<hierarchy rotation="0"><node text="fresh fallback"/></hierarchy>')
    print("OK (1 test)")
elif command[:3] == ["shell", "rm", "-f"] and len(command) >= 4:
    if scenario == "cleanup_error":
        print("permission denied", file=sys.stderr)
        sys.exit(1)
    for path in command[3:]:
        remote(path).unlink(missing_ok=True)
elif command[:2] == ["shell", "rmdir"] and len(command) == 3:
    remote(command[2]).rmdir()
elif command[:2] == ["shell", "getprop"] and len(command) == 3:
    values = {"ro.product.model": "Simulated device", "ro.build.version.release": "16",
              "ro.build.version.sdk": "36", "persist.sys.locale": "en-US",
              "persist.sys.timezone": "Europe/Helsinki"}
    if command[2] == "persist.sys.locale" and scenario.startswith("locale_fallback"):
        if scenario == "locale_fallback_property_error":
            print("property read failed", file=sys.stderr)
            sys.exit(1)
        print("")
    else:
        print(values[command[2]])
elif command == ["shell", "am", "get-config"]:
    if scenario == "locale_fallback_error":
        print("configuration unavailable", file=sys.stderr)
        sys.exit(1)
    elif scenario == "locale_fallback_unknown":
        print("config: unrecognized-format\nabi: x86_64")
    elif scenario == "locale_fallback_multilingual":
        print("config: mcc310-mnc004-fi-rFI,b+sr+Latn+RS-ldltr-sw320dp-v36\nabi: x86_64")
    else:
        print("config: en-rUS-ldltr-sw320dp-w320dp-h533dp-normal-long-v36\nabi: x86_64")
elif command == ["shell", "pm", "path", "--user", "current", "org.example.test"]:
    if scenario != "package_missing":
        print("package:/data/app/org.example.test/base.apk")
elif command == ["shell", "cmd", "locale", "get-app-locales", "org.example.test", "--user", "current"]:
    if scenario == "locale_unsupported":
        print("Can't find service: locale", file=sys.stderr)
        sys.exit(1)
    print("Locales for org.example.test for user 0 are []")
elif command == ["shell", "wm", "size"]:
    print("Physical size: 1080x1920\nOverride size: 480x640")
elif command == ["shell", "wm", "density"]:
    print("Physical density: 420\nOverride density: 160")
elif command[:2] == ["shell", "settings"] and len(command) == 5:
    values = {("system", "font_scale"): "1.0",
              ("secure", "default_input_method"): "org.example.ime/.Keyboard",
              ("global", "auto_time"): "0", ("global", "auto_time_zone"): "0",
              ("system", "time_12_24"): "24"}
    print("null" if ((scenario == "missing_metadata" and command[4] == "font_scale")
                    or (scenario == "default_time_format" and command[4] == "time_12_24"))
          else values[tuple(command[3:])])
elif command == ["shell", "date", "+%Y-%m-%dT%H:%M:%S%z"]:
    print("2026-10-12T05:00:00+0300")
elif command == ["shell", "dumpsys", "input_method"]:
    print("mInputShown=true mShowRequested=true\nmCurrentSubtype=en_US\nunrelated line")
elif command == ["shell", "dumpsys", "window"]:
    if scenario == "window_focus_missing":
        print("unrelated line")
    else:
        print("mCurrentFocus=Window{sample org.example.test/.Main}\nunrelated line")
else:
    print(f"unexpected ADB command: {command!r}", file=sys.stderr)
    sys.exit(77)
