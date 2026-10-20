#!/usr/bin/env python3
"""Capture one named Android test phase; no navigation or result interpretation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib

PRESERVE_PACKAGE = "qa.capture.preserve"
PRESERVE_COMPONENT = PRESERVE_PACKAGE + "/.DumpInstrumentation"
PRESERVE_LOCK = "fdroid-capture-lock"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def active_locale_qualifiers(output):
    """Read the locale segment of am get-config; preserve Android's format."""
    locale = r"(?:[a-z]{2,3}(?:-r(?:[A-Z]{2}|[0-9]{3}))?|b\+[A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*)"
    match = re.search(
        rf"^config:\s*(?:mcc[0-9]+-)?(?:mnc[0-9]+-)?({locale}(?:,{locale})*)-ld(?:ltr|rtl)(?:-|$)",
        output, re.MULTILINE)
    if not match:
        raise ValueError("active locale qualifiers not recognized; inspect raw configuration")
    return match.group(1)


def png_dimensions(data):
    """Check PNG chunk framing/CRCs, not decoded pixels or screen content."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    pos, kinds, dimensions = 8, [], None
    while pos + 12 <= len(data):
        size = struct.unpack_from(">I", data, pos)[0]
        end = pos + 12 + size
        if end > len(data):
            raise ValueError("truncated PNG chunk")
        kind, body = data[pos + 4:pos + 8], data[pos + 8:end - 4]
        if zlib.crc32(kind + body) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("PNG CRC mismatch")
        if not kinds:
            if kind != b"IHDR" or size != 13:
                raise ValueError("missing PNG header")
            dimensions = struct.unpack_from(">II", body)
            if not all(dimensions):
                raise ValueError("empty PNG dimensions")
        kinds.append(kind)
        pos = end
        if kind == b"IEND":
            if size or pos != len(data) or b"IDAT" not in kinds:
                raise ValueError("incomplete PNG")
            return list(dimensions)
    raise ValueError("missing PNG end")


class Capture:
    def __init__(self, args):
        self.args = args
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.token = uuid.uuid4().hex
        self.directory = args.output / f"{stamp}-{args.phase}-{self.token[:8]}"
        self.directory.mkdir(mode=0o700)  # Exclusive: never reuse an older capture.
        self.base = [str(args.adb), "-H", args.server_host, "-P",
                     str(args.server_port), "-s", args.serial]
        self.env = os.environ.copy()
        for key in ("ADB_SERVER_SOCKET", "ANDROID_SERIAL",
                    "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
            self.env.pop(key, None)
        self.data = {
            "schema_version": 1, "phase": args.phase, "started_at_utc": now(),
            "status": "in_progress", "adb_command_prefix": self.base,
            "package_requested": args.package, "command_timeout_seconds": args.timeout,
            "captures": {}, "metadata": {}, "commands": {}, "errors": [],
            "ui_dump": {"requested": ("preserve_services" if args.ui_preserve_apk else
                                      "stock_with_no_idle_fallback" if args.ui_fallback_jar else "stock"),
                        "attempts": []},
            "cleanup": {"status": "not_needed"},
            "provided_context": {
                name: {"status": "provided" if value else "missing", "value": value}
                for name, value in (("app_language", args.app_language_note),
                                    ("input_method_and_input", args.input_note))
            },
            "limits": [
                "Sequential captures, not an atomic snapshot.",
                "Provided context is not verified by this tool.",
                "PNG structure and XML parsing do not verify the visible test result.",
                "System/app locale settings do not establish the actual UI language.",
                "Clock preferences do not establish the app's displayed clock format.",
                "Package path does not establish APK provenance or foreground identity.",
            ],
        }
        self.save()

    def save(self):
        temporary = self.directory / "metadata.json.tmp"
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.directory / "metadata.json")

    def run(self, name, *command, suffix="txt"):
        record = {"argv": self.base + list(command), "started_at_utc": now(),
                  "status": "in_progress", "stdout": f"{name}.{suffix}",
                  "stderr": f"{name}.stderr.txt", "returncode": None}
        self.data["commands"][name] = record
        self.save()
        try:
            with (self.directory / record["stdout"]).open("xb") as out, \
                    (self.directory / record["stderr"]).open("xb") as err:
                result = subprocess.run(record["argv"], stdout=out, stderr=err,
                                        stdin=subprocess.DEVNULL, env=self.env,
                                        timeout=self.args.timeout, check=False)
            record.update(returncode=result.returncode,
                          status="ok" if result.returncode == 0 else "failed")
            if result.returncode:
                record["error"] = f"command exited with {result.returncode}"
        except subprocess.TimeoutExpired:
            record.update(status="failed", error="timeout; remote completion is unknown")
        except OSError as exc:
            record.update(status="failed", error=str(exc))
        except KeyboardInterrupt:
            record.update(status="failed", error="interrupted; remote completion is unknown")
            raise
        finally:
            record["finished_at_utc"] = now()
            self.save()
        return record

    def output(self, record):
        path = self.directory / record["stdout"]
        return path.read_bytes() if path.exists() else b""

    def artifact(self, name, record):
        item = {"status": record["status"], "file": record["stdout"], "command": name}
        if record["status"] == "ok":
            try:
                payload = self.output(record)
                if name == "screenshot":
                    item["dimensions"] = png_dimensions(payload)
                    item["validation"] = "PNG chunks and CRCs; pixels not decoded"
                else:
                    root = ET.fromstring(payload)
                    if root.tag != "hierarchy" or not list(root.iter("node")):
                        raise ValueError("missing UI hierarchy nodes")
                    item.update(rotation=root.get("rotation"),
                                node_count=sum(1 for _ in root.iter("node")))
            except (ValueError, ET.ParseError) as exc:
                item.update(status="failed", error=str(exc))
        else:
            item["error"] = record.get("error")
        self.data["captures"][name] = item
        return item

    def capture_tree(self):
        if self.args.ui_preserve_apk:
            self.capture_preserving_tree()
            return
        remote_dir = f"/data/local/tmp/fdroid-phase-{self.token}"
        remote_file = remote_dir + "/ui.xml"
        fallback_file = remote_dir + "/fallback.xml"
        remote_jar = remote_dir + "/no-idle.jar"
        self.data["cleanup"] = {"status": "unverified", "remote_directory": remote_dir}
        created = self.run("ui_directory", "shell", "mkdir", remote_dir)
        if created["status"] != "ok":
            # An uncertain mkdir must not authorize deletion of an unconfirmed directory.
            self.data["cleanup"]["status"] = "unverified"
            self.data["captures"]["ui_tree"] = {
                "status": "failed", "command": "ui_directory", "error": created.get("error")}
            return
        dump = None
        fallback_started = False
        try:
            dump = self.run("ui_dump", "shell", "uiautomator", "dump", remote_file)
            if dump["status"] == "ok":
                tree = self.run("ui_tree", "exec-out", "cat", remote_file, suffix="xml")
                self.artifact("ui_tree", tree)
            else:
                self.data["captures"]["ui_tree"] = {
                    "status": "failed", "command": "ui_dump", "error": dump.get("error")}
            primary = self.data["captures"]["ui_tree"]
            primary["method"] = "stock"
            self.data["ui_dump"]["attempts"].append(dict(primary))
            if primary["status"] != "ok" and self.args.ui_fallback_jar:
                if dump.get("returncode") is None or dump["returncode"] < 0:
                    self.data["ui_dump"]["fallback_skipped"] = "stock command completion is unknown"
                else:
                    fallback_started = True
                    self.data["ui_dump"]["fallback_jar_sha256"] = hashlib.sha256(
                        self.args.ui_fallback_jar.read_bytes()).hexdigest()
                    pushed = self.run("ui_fallback_push", "push", str(self.args.ui_fallback_jar), remote_jar)
                    result = {"status": "failed", "method": "no_idle",
                              "command": "ui_fallback_push", "error": pushed.get("error")}
                    if pushed["status"] == "ok":
                        # The shell wrapper changes ANDROID_DATA for shell users, also
                        # changing UiDevice's output base. Use its Java runner directly.
                        classpath = "/system/framework/android.test.runner.jar:/system/framework/uiautomator.jar:" + remote_jar
                        quick = self.run("ui_fallback_dump", "shell", "env", "CLASSPATH=" + classpath,
                                         "app_process", "/system/bin", "com.android.commands.uiautomator.Launcher",
                                         "runtest", "-c", "qa.NoIdleDump", "-s", "-e", "output",
                                         f"fdroid-phase-{self.token}/fallback.xml")
                        result.update(command="ui_fallback_dump", error=quick.get("error"))
                        if quick["status"] == "ok":
                            tree = self.run("ui_fallback_tree", "exec-out", "cat", fallback_file, suffix="xml")
                            # Keep the failed stock file and reference the selected artifact by name.
                            result = self.artifact("ui_tree", tree)
                            result["command"] = "ui_fallback_tree"
                            result["method"] = "no_idle"
                    self.data["captures"]["ui_tree"] = result
                    self.data["ui_dump"]["attempts"].append(dict(result))
            self.data["ui_dump"]["selected_method"] = (
                self.data["captures"]["ui_tree"].get("method")
                if self.data["captures"]["ui_tree"]["status"] == "ok" else None)
        finally:
            removed = self.run("ui_remove", "shell", "rm", "-f", remote_file)
            fallback_removed = None
            if fallback_started:
                fallback_removed = self.run("ui_fallback_remove", "shell", "rm", "-f", fallback_file, remote_jar)
            directory_removed = self.run("ui_rmdir", "shell", "rmdir", remote_dir)
            uncertain_dump = (dump is None or any(
                record.get("returncode") is None or record["returncode"] < 0
                for record in [dump] + [self.data["commands"][key]
                                        for key in ("ui_fallback_push", "ui_fallback_dump")
                                        if key in self.data["commands"]]))
            clean = (removed["status"] == directory_removed["status"] == "ok"
                     and not uncertain_dump
                     and (fallback_removed is None or fallback_removed["status"] == "ok"))
            self.data["cleanup"]["status"] = "ok" if clean else "unverified"
            self.save()

    def capture_preserving_tree(self):
        """Use an explicitly prepared helper; never install, replace, or stock-dump."""
        file = f"files/tree-{self.token}.xml"
        result = {"status": "failed", "method": "preserve_services"}
        self.data["captures"]["ui_tree"] = result
        self.data["cleanup"] = {"status": "not_needed", "helper_package": PRESERVE_PACKAGE,
                                "helper_retained": "preinstalled test dependency"}
        acquired = False
        try:
            owner = self.run("ui_preserve_user", "shell", "am", "get-current-user")
            if owner["status"] != "ok" or self.output(owner).strip() != b"0":
                raise ValueError("preserving capture currently supports Android owner user 0 only")
            apk = self.run("ui_preserve_path", "shell", "pm", "path", "--user", "0", PRESERVE_PACKAGE)
            match = re.fullmatch(rb"package:(/data/app/[A-Za-z0-9_./=+~-]+\.apk)\s*", self.output(apk))
            if apk["status"] != "ok" or not match:
                raise ValueError("prepared preserving helper APK not found or unexpected/split APK path")
            checksum = self.run("ui_preserve_identity", "shell", "sha256sum", match[1].decode())
            expected = hashlib.sha256(self.args.ui_preserve_apk.read_bytes()).hexdigest()
            self.data["ui_dump"]["preserve_apk_sha256"] = expected
            if checksum["status"] != "ok" or not re.fullmatch(
                    re.escape(expected.encode()) + rb"\s+" + re.escape(match[1]) + rb"\s*", self.output(checksum)):
                raise ValueError("installed preserving helper differs from the reference APK")
            self.data["cleanup"].update(status="unverified", lock=PRESERVE_LOCK)
            lock = self.run("ui_preserve_lock", "shell", "run-as", PRESERVE_PACKAGE, "mkdir", PRESERVE_LOCK)
            if lock["status"] != "ok":
                if lock.get("returncode") is not None and lock["returncode"] >= 0:
                    self.data["cleanup"]["status"] = "not_needed"
                raise ValueError("helper lock unavailable; no instrumentation or force-stop attempted")
            acquired = True
            self.data["cleanup"].update(status="unverified", lock=PRESERVE_LOCK, remote_file=file)
            dump = self.run("ui_preserve_dump", "shell", "am", "instrument", "--user", "0", "-w", "-r",
                            "-e", "capture_id", self.token, "-e", "expected_package", self.args.package,
                            PRESERVE_COMPONENT)
            result["command"] = "ui_preserve_dump"
            if dump["status"] != "ok" or not re.search(rb"^INSTRUMENTATION_CODE: -1\s*$", self.output(dump), re.M):
                raise ValueError(dump.get("error", "instrumentation did not report success; inspect its output"))
            tree = self.run("ui_preserve_tree", "exec-out", "run-as", PRESERVE_PACKAGE, "cat", file, suffix="xml")
            result = self.artifact("ui_tree", tree)
            result["method"] = "preserve_services"
            if result["status"] == "ok":
                root = ET.fromstring(self.output(tree))
                if (root.get("capture_id") != self.token or root.get("connection_flags") != "1"
                        or next(root.iter("node")).get("package") != self.args.package):
                    raise ValueError("tree identity, connection flag or active package does not match this capture")
        except (OSError, ValueError) as exc:
            result.update(status="failed", error=str(exc))
        except KeyboardInterrupt:
            result.update(status="failed", error="interrupted; cleanup attempted for owned helper lock")
            raise
        finally:
            self.data["captures"]["ui_tree"] = result
            self.data["ui_dump"]["attempts"].append(dict(result))
            self.data["ui_dump"]["selected_method"] = "preserve_services" if result["status"] == "ok" else None
            if acquired:
                # Only the dedicated helper is stopped, while its exclusive lock is ours.
                # Confirm it is gone before deleting a file an uncertain writer could recreate.
                stopped = self.run("ui_preserve_stop", "shell", "am", "force-stop", "--user", "0", PRESERVE_PACKAGE)
                processes = self.run("ui_preserve_process", "shell", "pidof", PRESERVE_PACKAGE)
                gone = (stopped["status"] == "ok" and processes.get("returncode") == 1
                        and not self.output(processes).strip()
                        and not (self.directory / processes["stderr"]).read_bytes().strip())
                if gone:
                    removed = self.run("ui_preserve_remove", "shell", "run-as", PRESERVE_PACKAGE, "rm", "-f", file)
                    absent = self.run("ui_preserve_absent", "shell", "run-as", PRESERVE_PACKAGE, "test", "!", "-e", file)
                    unlocked = self.run("ui_preserve_unlock", "shell", "run-as", PRESERVE_PACKAGE, "rmdir", PRESERVE_LOCK)
                    if all(item["status"] == "ok" for item in (removed, absent, unlocked)):
                        self.data["cleanup"]["status"] = "ok"
                else:
                    self.data["cleanup"]["error"] = "helper stop not verified; file and lock retained for inspection"
            self.save()

    def probe(self, name, command, pattern=None):
        record = self.run(name, "shell", *command)
        item = {"status": record["status"], "command": name, "value": None}
        if record["status"] == "ok":
            value = self.output(record).decode("utf-8", errors="replace").strip()
            if pattern:
                value = "\n".join(line.strip() for line in value.splitlines()
                                  if re.search(pattern, line))
            if not value or value == "null":
                item.update(status="missing", error="no usable value in command output")
            else:
                item["value"] = value
        else:
            item["error"] = record.get("error")
        self.data["metadata"][name] = item
        return item

    def time_format(self):
        item = self.probe("time_format", ["settings", "get", "system", "time_12_24"])
        record = self.data["commands"]["time_format"]
        if record["status"] != "ok":
            return
        value = self.output(record).decode("utf-8", errors="replace").strip()
        if value == "null":
            # Android falls back to the context's locale when no preference is set.
            item.update(status="ok", value=None, mode="locale_default")
            item.pop("error", None)
        elif value in ("12", "24"):
            item["mode"] = "explicit"
        elif value:
            item.update(status="missing", value=None,
                        error="unrecognized time format; expected 12, 24 or null")

    def system_locale(self):
        primary = self.probe("system_locale", ["getprop", "persist.sys.locale"])
        primary["value_format"] = "locale_property"
        if primary["status"] == "ok":
            return
        record = self.run("system_locale_configuration", "shell", "am", "get-config")
        item = {"status": record["status"], "command": "system_locale_configuration",
                "value": None, "value_format": "android_locale_resource_qualifiers",
                "primary_probe": primary}
        if record["status"] == "ok":
            try:
                item["value"] = active_locale_qualifiers(
                    self.output(record).decode("utf-8", errors="replace"))
            except ValueError as exc:
                item.update(status="missing", error=str(exc))
        else:
            item["error"] = record.get("error")
        self.data["metadata"]["system_locale"] = item

    def execute(self):
        interrupted = False
        try:
            state = self.run("device_state", "get-state")
            if state["status"] != "ok" or self.output(state).strip() != b"device":
                raise ValueError("selected device is not ready; no captures attempted")
            shot = self.run("screenshot", "exec-out", "screencap", "-p", suffix="png")
            self.artifact("screenshot", shot)
            self.capture_tree()
            probes = {
                "device_model": ["getprop", "ro.product.model"],
                "android_release": ["getprop", "ro.build.version.release"],
                "android_api": ["getprop", "ro.build.version.sdk"],
                "package_path": ["pm", "path", "--user", "current", self.args.package],
                "app_locales": ["cmd", "locale", "get-app-locales", self.args.package,
                                "--user", "current"],
                "display_size": ["wm", "size"],
                "display_density": ["wm", "density"],
                "font_scale": ["settings", "get", "system", "font_scale"],
                "input_method": ["settings", "get", "secure", "default_input_method"],
                "device_time": ["date", "+%Y-%m-%dT%H:%M:%S%z"],
                "device_timezone": ["getprop", "persist.sys.timezone"],
                "automatic_time": ["settings", "get", "global", "auto_time"],
                "automatic_timezone": ["settings", "get", "global", "auto_time_zone"],
            }
            for name, command in probes.items():
                self.probe(name, command)
            self.time_format()
            self.system_locale()
            self.probe("input_state", ["dumpsys", "input_method"],
                       r"mInputShown=|mShowRequested=|mCurMethodId=|mCurrentSubtype=|mCurFocusedWindow=")
            self.probe("window_focus", ["dumpsys", "window"],
                       r"mCurrentFocus=|mFocusedApp=|mImeInputTarget=|mInputMethodTarget=")
        except KeyboardInterrupt:
            interrupted = True
            self.data["errors"].append("interrupted")
        except (OSError, ValueError) as exc:
            self.data["errors"].append(str(exc))
        finally:
            for name in ("screenshot", "ui_tree"):
                self.data["captures"].setdefault(name, {"status": "not_captured"})
            captured = [item["status"] == "ok" for item in self.data["captures"].values()]
            metadata_ok = (bool(self.data["metadata"])
                           and all(item["status"] == "ok" for item in self.data["metadata"].values())
                           and all(item["status"] == "provided"
                                   for item in self.data["provided_context"].values()))
            self.data["metadata_status"] = "ok" if metadata_ok else "incomplete"
            complete = (all(captured) and metadata_ok and not self.data["errors"]
                        and self.data["cleanup"]["status"] in ("ok", "not_needed"))
            self.data["status"] = "complete" if complete else ("partial" if any(captured) else "failed")
            self.data["finished_at_utc"] = now()
            self.save()
        return 130 if interrupted else {"complete": 0, "partial": 1, "failed": 2}[self.data["status"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, type=Path, help="Current adb executable (absolute path)")
    parser.add_argument("--server-host", required=True)
    parser.add_argument("--server-port", required=True, type=int)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--phase", required=True, help="Short test phase ID, e.g. TC03-after-save")
    parser.add_argument("--output", required=True, type=Path, help="Existing evidence directory")
    parser.add_argument("--app-language-note", help="Actual UI language observed; not inferred from settings")
    parser.add_argument("--input-note", help="Input method and relevant intended text/key sequence")
    parser.add_argument("--timeout", type=float, default=15, help="Seconds per ADB command (default: 15)")
    methods = parser.add_mutually_exclusive_group()
    methods.add_argument("--ui-fallback-jar", type=Path,
                        help="Opt in to one no-idle UI dump after a completed but unusable stock dump; absolute path")
    methods.add_argument("--ui-preserve-apk", type=Path,
                         help="Use the preinstalled service-preserving helper instead of stock; reference signed APK path")
    args = parser.parse_args()
    if not args.adb.is_absolute() or not args.adb.is_file() or not os.access(args.adb, os.X_OK):
        parser.error("--adb must be an absolute path to an executable file")
    if not args.output.is_absolute() or not args.output.is_dir():
        parser.error("--output must be an absolute path to an existing directory")
    if not 1 <= args.server_port <= 65535 or not args.server_host.strip() or not args.serial.strip():
        parser.error("a nonempty server host, port 1..65535 and serial are required")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", args.package):
        parser.error("--package must be an Android package ID")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.phase):
        parser.error("--phase must be 1..80 letters, digits, dots, underscores or hyphens")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and greater than zero")
    if args.ui_fallback_jar and (not args.ui_fallback_jar.is_absolute()
                                or not args.ui_fallback_jar.is_file()):
        parser.error("--ui-fallback-jar must be an absolute path to the built helper JAR")
    if args.ui_preserve_apk:
        if not args.ui_preserve_apk.is_absolute() or not args.ui_preserve_apk.is_file():
            parser.error("--ui-preserve-apk must be an absolute path to the prepared helper APK")
        if args.package == PRESERVE_PACKAGE:
            parser.error("the preserving helper cannot also be the app being captured")
    try:
        capture = Capture(args)
        print(capture.directory, flush=True)
        code = capture.execute()
        print(f"{capture.data['status']}: {capture.directory / 'metadata.json'}", flush=True)
        if capture.data["status"] != "complete":
            incomplete = [f"{group}.{name}={item['status']}"
                          for group in ("captures", "metadata", "provided_context")
                          for name, item in capture.data[group].items()
                          if item["status"] not in ("ok", "provided")]
            if capture.data["cleanup"]["status"] == "unverified":
                incomplete.append("cleanup=unverified")
            print("Needs review: " + "; ".join(incomplete + capture.data["errors"]), flush=True)
        return code
    except OSError as exc:
        print(f"capture storage error: {exc}; preserve any partial directory", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
