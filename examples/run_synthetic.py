#!/usr/bin/env python3
"""Codex-authored, device-free examples. All receipts and device data are invented."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[1]
PROBE = "synthetic_probe_0123456789"


def save(directory, name, data):
    if not isinstance(data, bytes):
        data = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    (directory / name).write_bytes(data)
    return {"file": name, "sha256": hashlib.sha256(data).hexdigest()}


def network_example(directory, outcome):
    directory.mkdir(parents=True)
    body = f"Network coverage check\nProbe: {PROBE}\nReceipt: {'a' * 32}\n".encode()
    request = f"GET /coverage/{PROBE} HTTP/1.1\r\nHost: 10.0.2.2:18080\r\nConnection: close\r\n\r\n".encode()
    # Invented Ethernet/IPv4/TCP framing; never transmitted. Checksums are zero.
    tcp = struct.pack("!HHIIBBHHH", 43000, 18080, 10, 0, 0x50, 0x18, 65535, 0, 0) + request
    loopback = bytes((127, 0, 0, 1))
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0x4000, 64, 6, 0, loopback, loopback)
    frame = bytes(12) + b"\x08\x00" + ip + tcp
    pcap = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    if outcome != "verified_gap":
        pcap += struct.pack("<IIII", 1792029602, 0, len(frame), len(frame)) + frame
    server = {"schema": "network-server-receipt/v1", "run_id": "synthetic-run", "probe_id": PROBE,
              "method": "GET", "host": "10.0.2.2:18080", "path": "/coverage/" + PROBE,
              "status": 200, "received_at": "2026-10-15T02:00:02Z", "response_nonce": "a" * 32,
              "response_body_sha256": hashlib.sha256(body).hexdigest(),
              "local_ipv4": "127.0.0.1", "local_port": 18080,
              "peer_ipv4": "127.0.0.1", "peer_port": 43000}
    proof = {"schema": "network-probe/v1", "run_id": "synthetic-run", "probe_id": PROBE,
             "evidence_kind": "synthetic",
             "route": {"verified": True, "transport": "direct-ipv4-http", "description": "Invented route for a file-only example",
                       "evidence": save(directory, "route.txt", b"SYNTHETIC fixture. No route or connectivity was measured.\n")},
             "request": {"method": "GET", "host": "10.0.2.2:18080", "ipv4": "10.0.2.2",
                         "port": 18080, "path": "/coverage/" + PROBE},
             "server_receipt": save(directory, "server.json", server),
             "client": {"source": "android-shell-nc", "exit_code": 0,
                        "started_at": "2026-10-15T02:00:01Z", "finished_at": "2026-10-15T02:00:03Z",
                        "response": save(directory, "client.http", b"HTTP/1.0 200 OK\r\nContent-Length: "
                                         + str(len(body)).encode() + b"\r\n\r\n" + body)}}
    recording = {"schema": "network-recording/v1", "run_id": "synthetic-run", "probe_id": PROBE,
                 "evidence_kind": "synthetic", "started_at": "2026-10-15T02:00:00Z",
                 "ended_at": "2026-10-15T02:00:04Z", "clock": "host-utc", "ready": outcome != "inconclusive",
                 "closed_cleanly": True, "dropped_packets": 0, "point": "Synthetic Ethernet PCAP",
                 "destination_ipv4": "127.0.0.1", "destination_port": 18080,
                 "filter": "ipv4 tcp port 18080", "pcap": save(directory, "capture.pcap", pcap)}
    save(directory, "proof.json", proof)
    save(directory, "recording.json", recording)
    result = subprocess.run([sys.executable, "-B", str(REPOSITORY / "tools/check_network_coverage.py"),
                             "--proof", str(directory / "proof.json"),
                             "--recording", str(directory / "recording.json")],
                            capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    expected_code = {"observed": 0, "verified_gap": 1, "inconclusive": 2}[outcome]
    if data["status"] != outcome or result.returncode != expected_code:
        raise RuntimeError(f"Unexpected network example: {data!r}, {result.stderr}")
    save(directory, "result.json", data)
    return {"status": outcome, "exit_code": result.returncode}


def capture_example(directory, mode):
    directory.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="android-helpers-example-") as temporary:
        fake_root = Path(temporary)
        fake = fake_root / "fake-adb"
        shutil.copyfile(REPOSITORY / "tools/tests/fake_adb.py", fake)
        fake.chmod(0o700)
        env = dict(os.environ, CAPTURE_TEST_ROOT=str(fake_root),
                   CAPTURE_TEST_SCENARIO="ui_error" if mode == "no-idle" else "success")
        command = [sys.executable, "-B", str(REPOSITORY / "tools/capture_phase.py"),
                   "--adb", str(fake), "--server-host", "127.0.0.1", "--server-port", "42117",
                   "--serial", "test-device-1", "--package", "org.example.test",
                   "--phase", "SYNTHETIC-" + mode, "--output", str(directory), "--timeout", "1"]
        if mode != "missing-notes":
            command += ["--app-language-note", "Synthetic English UI; no device was observed",
                        "--input-note", "Synthetic example; no input was sent to any device"]
        if mode == "no-idle":
            jar = fake_root / "fake.jar"
            jar.write_bytes(b"simulated helper; never sent to a device")
            command += ["--ui-fallback-jar", str(jar)]
        elif mode == "preserve":
            apk = fake_root / "fake.apk"
            apk.write_bytes(b"simulated preserving helper")
            command += ["--ui-preserve-apk", str(apk)]
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
        expected_code = 1 if mode == "missing-notes" else 0
        expected_status = "partial" if mode == "missing-notes" else "complete"
        captures = list(directory.glob("*/metadata.json"))
        if len(captures) != 1:
            raise RuntimeError(f"Missing example capture: {result.stdout}\n{result.stderr}")
        data = json.loads(captures[0].read_text())
        if result.returncode != expected_code or data["status"] != expected_status:
            raise RuntimeError(f"Unexpected capture example: {result.stdout}\n{result.stderr}")
        if data["cleanup"]["status"] != "ok":
            raise RuntimeError("Synthetic device cleanup was not verified")
        return {"status": data["status"], "exit_code": result.returncode,
                "metadata": str(captures[0].relative_to(directory))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New output directory; never overwritten")
    args = parser.parse_args()
    output = args.output.absolute()
    try:
        output.mkdir(mode=0o700)  # No replacement of a file, directory or symlink.
    except OSError as error:
        parser.error(f"Use a new directory with an existing parent: {error}")
    (output / "SYNTHETIC.txt").write_text(
        "Codex-authored synthetic examples. No device or network connection was used.\n"
        "All device data, receipts, route statements, timestamps and PCAP bytes are invented.\n")
    summary = {"evidence_kind": "synthetic", "capture": {}, "network": {}}
    for mode in ("stock", "no-idle", "preserve", "missing-notes"):
        summary["capture"][mode] = capture_example(output / "capture" / mode, mode)
    for outcome in ("observed", "verified_gap", "inconclusive"):
        summary["network"][outcome] = network_example(output / "network" / outcome, outcome)
    save(output, "results.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"Synthetic output: {output}")


if __name__ == "__main__":
    main()
