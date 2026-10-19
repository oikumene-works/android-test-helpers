#!/usr/bin/env python3
"""Build a signed preserving UI dumper with an installed Android SDK/JDK, offline."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, type=Path, help="Installed SDK platform directory")
    parser.add_argument("--build-tools", required=True, type=Path, help="Installed SDK build-tools directory")
    parser.add_argument("--output", required=True, type=Path, help="New absolute APK path; never overwritten")
    args = parser.parse_args()
    android = args.platform / "android.jar"
    tools = {name: args.build_tools / name for name in ("d8", "aapt2", "zipalign", "apksigner")}
    if not android.is_absolute() or not android.is_file() or not all(
            p.is_absolute() and p.is_file() and os.access(p, os.X_OK) for p in tools.values()):
        parser.error("absolute installed SDK paths are required; this tool downloads nothing")
    receipt_path = args.output.with_suffix(".build.json")
    if (not args.output.is_absolute() or not args.output.parent.is_dir()
            or args.output.exists() or receipt_path.exists()):
        parser.error("--output and its .build.json receipt must be new files in an existing directory")
    source = Path(__file__).resolve().parent / "ui-preserve"
    env = dict(os.environ, CAPTURE_SIGNING_PASSWORD=secrets.token_urlsafe(24))

    def run(command, capture=False):
        return subprocess.run([str(arg) for arg in command], check=True, env=env, timeout=60,
                              stdout=subprocess.PIPE if capture else None, text=capture)

    with tempfile.TemporaryDirectory(prefix="fdroid-ui-preserve-build-") as temporary:
        work = Path(temporary)
        key = work / "temporary.keystore"
        run(["javac", "--release", "8", "-cp", android, "-d", work, source / "DumpInstrumentation.java"])
        run([tools["d8"], "--min-api", "24", "--lib", android, "--output", work,
             *sorted(work.rglob("*.class"))])
        run([tools["aapt2"], "link", "-I", android, "--manifest", source / "AndroidManifest.xml",
             "-o", work / "unsigned.apk"])
        with zipfile.ZipFile(work / "unsigned.apk", "a") as archive:
            archive.write(work / "classes.dex", "classes.dex")
        run([tools["zipalign"], "-p", "4", work / "unsigned.apk", work / "aligned.apk"])
        run(["keytool", "-genkeypair", "-keystore", key, "-storepass:env", "CAPTURE_SIGNING_PASSWORD",
             "-keypass:env", "CAPTURE_SIGNING_PASSWORD", "-alias", "capture", "-keyalg", "RSA",
             "-keysize", "2048", "-validity", "2", "-dname", "CN=Temporary preserving capture helper"])
        run([tools["apksigner"], "sign", "--ks", key, "--ks-pass", "env:CAPTURE_SIGNING_PASSWORD",
             "--out", work / "signed.apk", work / "aligned.apk"])
        verification = run([tools["apksigner"], "verify", "--verbose", "--print-certs", work / "signed.apk"], True)
        with args.output.open("xb") as output, (work / "signed.apk").open("rb") as apk:
            shutil.copyfileobj(apk, output)
        receipt = {"package": "qa.capture.preserve", "component": "qa.capture.preserve/.DumpInstrumentation",
                   "apk_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                   "sources_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.iterdir()) if p.is_file()},
                   "signer_verification": verification.stdout, "temporary_key_path": str(key),
                   "temporary_build_directory": str(work), "scope": "Local test dependency; no network permission"}
    receipt["temporary_key_and_build_directory_removed"] = not key.exists() and not work.exists()
    with receipt_path.open("x") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    print(args.output)
    print(receipt_path)


if __name__ == "__main__":
    main()
