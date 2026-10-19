#!/usr/bin/env python3
"""Build the optional no-idle dumper with an already installed Android SDK/JDK."""

import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, type=Path,
                        help="Installed SDK platform directory containing android.jar and uiautomator.jar")
    parser.add_argument("--build-tools", required=True, type=Path, help="Installed SDK build-tools directory")
    parser.add_argument("--output", required=True, type=Path, help="New absolute JAR path; never overwritten")
    args = parser.parse_args()
    android, ui, d8 = args.platform / "android.jar", args.platform / "uiautomator.jar", args.build_tools / "d8"
    junit = args.platform / "optional" / "android.test.base.jar"
    if not all(p.is_absolute() and p.is_file() for p in (android, ui, junit, d8)):
        parser.error("absolute installed SDK paths are required; this tool downloads nothing")
    if not args.output.is_absolute() or not args.output.parent.is_dir() or args.output.exists():
        parser.error("--output must be a new absolute file in an existing directory")
    source = Path(__file__).resolve().parent / "ui-dump" / "NoIdleDump.java"
    with tempfile.TemporaryDirectory(prefix="fdroid-ui-dump-build-") as temporary:
        root = Path(temporary)
        subprocess.run(["javac", "--release", "8", "-cp", f"{android}:{ui}:{junit}",
                        "-d", str(root), str(source)], check=True, timeout=60)
        subprocess.run([str(d8), "--min-api", "23", "--lib", str(android), "--classpath", str(ui),
                        "--classpath", str(junit),
                        "--output", str(root), str(root / "qa" / "NoIdleDump.class")],
                       check=True, timeout=60)
        # Exclusive output creation prevents replacing a helper used by a previous run.
        with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as jar:
            jar.write(root / "classes.dex", "classes.dex")
    print(args.output)


if __name__ == "__main__":
    main()
