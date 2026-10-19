"""Synthetic classification checks; these are not emulator observations."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("coverage_check", Path(__file__).parents[1] / "check_network_coverage.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
PROBE = "synthetic_probe_0123456789"


def frame(payload, sport=43000):
    tcp = struct.pack("!HHIIBBHHH", sport, 18080, 10, 0, 0x50, 0x18, 65535, 0, 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0x4000, 64, 6, 0,
                     socket.inet_aton("127.0.0.1"), socket.inet_aton("127.0.0.1"))
    return bytes(12) + b"\x08\x00" + ip + tcp


def pcap(payload, sport=43000):
    packet = frame(payload, sport)
    header = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    return header + struct.pack("<IIII", 1792029602, 0, len(packet), len(packet)) + packet


class Classification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.body = f"Network coverage check\nProbe: {PROBE}\nReceipt: {'a' * 32}\n".encode()
        self.request = f"GET /coverage/{PROBE} HTTP/1.1\r\nHost: 10.0.2.2:18080\r\nConnection: close\r\n\r\n".encode()
        self.server = {"schema": "network-server-receipt/v1", "run_id": "synthetic-run", "probe_id": PROBE,
                       "method": "GET", "host": "10.0.2.2:18080", "path": "/coverage/" + PROBE,
                       "status": 200, "received_at": "2026-10-15T02:00:02Z", "response_nonce": "a" * 32,
                       "response_body_sha256": hashlib.sha256(self.body).hexdigest(),
                       "local_ipv4": "127.0.0.1", "local_port": 18080,
                       "peer_ipv4": "127.0.0.1", "peer_port": 43000}
        self.proof = {"schema": "network-probe/v1", "run_id": "synthetic-run", "probe_id": PROBE,
                      "evidence_kind": "synthetic",
                      "route": {"verified": True, "transport": "direct-ipv4-http", "description": "Synthetic route",
                                "evidence": self.save("route.txt", b"Synthetic route fixture, not a live route.")},
                      "request": {"method": "GET", "host": "10.0.2.2:18080", "ipv4": "10.0.2.2",
                                  "port": 18080, "path": "/coverage/" + PROBE},
                      "server_receipt": self.save("server.json", json.dumps(self.server).encode()),
                      "client": {"source": "android-shell-nc", "exit_code": 0,
                                 "started_at": "2026-10-15T02:00:01Z", "finished_at": "2026-10-15T02:00:03Z",
                                 "response": self.save("client.http", b"HTTP/1.0 200 OK\r\nContent-Length: "
                                                       + str(len(self.body)).encode() + b"\r\n\r\n" + self.body)}}
        self.recording = {"schema": "network-recording/v1", "run_id": "synthetic-run", "probe_id": PROBE,
                          "evidence_kind": "synthetic", "started_at": "2026-10-15T02:00:00Z",
                          "ended_at": "2026-10-15T02:00:04Z", "clock": "host-utc", "ready": True,
                          "closed_cleanly": True, "dropped_packets": 0, "point": "Synthetic Ethernet PCAP",
                          "destination_ipv4": "127.0.0.1", "destination_port": 18080,
                          "filter": "ipv4 tcp port 18080",
                          "pcap": self.save("capture.pcap", pcap(self.request))}

    def save(self, name, data):
        (self.root / name).write_bytes(data)
        return {"file": name, "sha256": hashlib.sha256(data).hexdigest()}

    def evaluate(self):
        self.save("proof.json", json.dumps(self.proof).encode())
        self.save("recording.json", json.dumps(self.recording).encode())
        return CHECK.evaluate(self.root / "proof.json", self.root / "recording.json")

    def expect(self, status):
        result = self.evaluate()
        self.assertEqual(result["status"], status, result)
        self.assertTrue(result["reasons"])

    def test_observed(self):
        self.expect("observed")

    def test_verified_gap_with_independent_success_and_valid_active_capture(self):
        # A valid finalized empty capture plus independent success proves a gap.
        self.recording["pcap"] = self.save("capture.pcap", pcap(b"")[:24])
        self.expect("verified_gap")

    def test_tcp_connection_without_http_header_is_still_observed(self):
        self.recording["pcap"] = self.save("capture.pcap", pcap(b""))
        self.expect("observed")
        self.assertFalse(self.evaluate()["request_header_observed"])

    def test_missing_and_hash_mismatched_capture(self):
        (self.root / "capture.pcap").unlink()
        self.expect("inconclusive")
        (self.root / "capture.pcap").write_bytes(b"corrupt")
        self.expect("inconclusive")

    def test_corrupt_and_unsupported_capture_even_with_updated_hash(self):
        good = pcap(self.request)
        for data in (b"", b"not pcap", good[:23], good[:30], good[:-1],
                     good[:20] + struct.pack("<I", 101) + good[24:],
                     good[:32] + struct.pack("<I", 99999999) + good[36:]):
            with self.subTest(length=len(data)):
                self.recording["pcap"] = self.save("capture.pcap", data)
                self.expect("inconclusive")

    def test_split_request_is_not_a_gap(self):
        self.recording["pcap"] = self.save("capture.pcap", pcap(self.request[:30]))
        self.expect("inconclusive")

    def test_connection_identity_mismatch(self):
        for key in ("run_id", "probe_id", "evidence_kind"):
            with self.subTest(key=key):
                old = self.recording[key]
                self.recording[key] = "different-connection"
                self.expect("inconclusive")
                self.recording[key] = old
        self.recording["pcap"] = self.save("capture.pcap", pcap(self.request, sport=43001))
        self.expect("inconclusive")
        self.recording["pcap"] = self.save("capture.pcap", pcap(b"", sport=43001))
        self.expect("inconclusive")

    def test_wrong_server_or_client_proof(self):
        for key in ("run_id", "probe_id", "host", "path", "method", "response_nonce"):
            with self.subTest(key=key):
                bad = deepcopy(self.server)
                bad[key] = "different-connection"
                self.proof["server_receipt"] = self.save("server.json", json.dumps(bad).encode())
                self.expect("inconclusive")
        self.proof["server_receipt"] = self.save("server.json", json.dumps(self.server).encode())
        self.proof["client"]["response"] = self.save("client.http", b"HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\nwrong")
        self.expect("inconclusive")

    def test_missing_or_corrupt_independent_proof(self):
        for name in ("server.json", "client.http", "route.txt"):
            with self.subTest(name=name):
                old = (self.root / name).read_bytes()
                (self.root / name).unlink()
                self.expect("inconclusive")
                (self.root / name).write_bytes(b"damaged")
                self.expect("inconclusive")
                (self.root / name).write_bytes(old)

    def test_unverified_recording_cannot_succeed_or_prove_gap(self):
        for key, value in (("ready", False), ("closed_cleanly", False), ("dropped_packets", 1),
                           ("dropped_packets", None), ("clock", "unknown"),
                           ("started_at", "2026-10-15T02:00:02Z"),
                           ("ended_at", "2026-10-15T02:00:02Z"),
                           ("filter", "unknown"),
                           ("destination_ipv4", "127.0.0.2")):
            with self.subTest(key=key, value=value):
                old = self.recording[key]
                self.recording[key] = value
                self.expect("inconclusive")
                self.recording[key] = old

    def test_client_failure_or_route_uncertainty(self):
        self.proof["client"]["exit_code"] = 1
        self.expect("inconclusive")
        self.proof["client"]["exit_code"] = 0
        self.proof["route"]["verified"] = False
        self.expect("inconclusive")

    def test_invalid_endpoint_is_not_a_gap(self):
        self.recording["pcap"] = self.save("capture.pcap", pcap(b""))
        for key, value in (("local_ipv4", "invalid"), ("peer_ipv4", "invalid"),
                           ("peer_port", True), ("peer_port", 70000), ("local_port", "18080")):
            with self.subTest(key=key, value=value):
                bad = deepcopy(self.server)
                bad[key] = value
                self.proof["server_receipt"] = self.save("server.json", json.dumps(bad).encode())
                self.expect("inconclusive")

    def test_malformed_http_header_is_not_observed(self):
        self.recording["pcap"] = self.save("capture.pcap", pcap(self.request.replace(b"Connection: close", b"Bad header")))
        self.expect("inconclusive")

    def test_other_http_request_is_not_a_gap(self):
        for payload in (self.request.replace(PROBE.encode(), b"different_probe_01234567"),
                        self.request.replace(b"10.0.2.2:18080", b"10.0.2.3:18080"),
                        self.request.replace(b"HTTP/1.1", b"HTTP/invalid")):
            with self.subTest(payload=payload):
                self.recording["pcap"] = self.save("capture.pcap", pcap(payload))
                self.expect("inconclusive")

    def test_unknown_packet_prevents_a_partial_success(self):
        good = pcap(self.request)
        bad_frame = bytes(12) + b"\x81\x00" + bytes(46)
        data = good + struct.pack("<IIII", 1792029602, 1000, len(bad_frame), len(bad_frame)) + bad_frame
        self.recording["pcap"] = self.save("capture.pcap", data)
        self.expect("inconclusive")

    def test_bad_json_and_incomplete_schema(self):
        for data in (b"{", b"[]", b'{"schema":"network-probe/v1","schema":"other"}', b'{}'):
            with self.subTest(data=data):
                self.evaluate()
                (self.root / "proof.json").write_bytes(data)
                result = CHECK.evaluate(self.root / "proof.json", self.root / "recording.json")
                self.assertEqual(result["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
