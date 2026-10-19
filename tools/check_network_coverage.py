#!/usr/bin/env python3
"""Read-only comparison of one HTTP probe and a finalized Ethernet PCAP.

No networking, process launching or environment discovery. Receipt statements
are supplied by the operator; hashes check consistency, not their authenticity.
"""
import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import struct
import sys

LIMIT = 64 * 1024 * 1024
LABELS = {"observed": "havaittu", "verified_gap": "varmennettu katve",
          "inconclusive": "tarkistus jäi epäselväksi"}


class Unclear(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Unclear(reason)


def read_file(path, limit=LIMIT):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, f"File exceeds the {limit}-byte limit: {path}")
    return data


def object_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique,
                       parse_constant=lambda v: (_ for _ in ()).throw(Unclear(f"Invalid number: {v}")))
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def timestamp(value):
    require(isinstance(value, str), "Timestamp must be an ISO 8601 string")
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(value.utcoffset() is not None, "Timestamp lacks timezone")
    return value.timestamp()


def nonempty(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"Missing {name}")
    return value


def artifact(base, ref):
    require(isinstance(ref, dict), "Missing artifact reference")
    name = nonempty(ref["file"], "artifact filename")
    require(Path(name).name == name and name not in (".", ".."),
            "Artifacts must be sibling files, without path traversal")
    data = read_file(base / name)
    require(hashlib.sha256(data).hexdigest() == ref["sha256"], f"Hash mismatch: {name}")
    return data


def http_body(raw):
    header, separator, body = raw.partition(b"\r\n\r\n")
    require(separator, "Client response lacks a complete HTTP header")
    lines = header.split(b"\r\n")
    require(re.fullmatch(rb"HTTP/1\.[01] 200 [^\r\n]+", lines[0]),
            "Client response is not HTTP 200")
    headers = {}
    for line in lines[1:]:
        key, sep, value = line.partition(b":")
        require(sep and key.lower() not in headers, "Invalid/duplicate response header")
        headers[key.lower()] = value.strip()
    require(b"transfer-encoding" not in headers, "Chunked/encoded transfer is unsupported")
    require(headers.get(b"content-encoding", b"identity") == b"identity",
            "Encoded response is unsupported")
    require(headers.get(b"content-length") == str(len(body)).encode(),
            "Client response body is incomplete or has extra bytes")
    return body


def packets(data):
    """Classic PCAP, Ethernet, microsecond or nanosecond timestamps."""
    magics = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
              b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
    require(len(data) >= 24 and data[:4] in magics, "Missing/unsupported PCAP header")
    endian, scale = magics[data[:4]]
    major, minor, zone, sigfigs, snaplen, link = struct.unpack(endian + "HHiIII", data[4:24])
    require((major, minor, zone, sigfigs, link) == (2, 4, 0, 0, 1) and 54 <= snaplen <= LIMIT,
            "Unsupported PCAP version, clock metadata, snap length or link type")
    pos = 24
    count = 0
    while pos < len(data):
        require(pos + 16 <= len(data), "Truncated PCAP record header")
        sec, fraction, size, original = struct.unpack(endian + "IIII", data[pos:pos + 16])
        pos += 16
        require(fraction < scale and 14 <= size == original <= snaplen,
                "Invalid timestamp, truncated packet or invalid packet length")
        require(pos + size <= len(data), "Truncated PCAP packet")
        count += 1
        yield count, sec + fraction / scale, data[pos:pos + size]
        pos += size


def tcp(frame):
    kind = int.from_bytes(frame[12:14], "big")
    if kind == 0x0806:
        require(len(frame) >= 42, "Truncated ARP frame")
        return None
    if kind == 0x86DD:
        require(len(frame) >= 54 and frame[14] >> 4 == 6, "Invalid IPv6 frame")
        require(len(frame) >= 54 + int.from_bytes(frame[18:20], "big"), "Truncated IPv6 frame")
        return None  # The probe is explicitly direct IPv4, without a tunnel.
    require(kind == 0x0800, f"Unsupported EtherType 0x{kind:04x}")
    ip = frame[14:]
    require(len(ip) >= 20 and ip[0] >> 4 == 4, "Invalid IPv4 header")
    ihl, total = (ip[0] & 15) * 4, int.from_bytes(ip[2:4], "big")
    require(20 <= ihl <= total <= len(ip), "Invalid/truncated IPv4 packet")
    require(int.from_bytes(ip[6:8], "big") & 0x3FFF == 0, "IPv4 fragments are unsupported")
    if ip[9] in (1, 17):
        return None
    require(ip[9] == 6, "Unsupported IPv4 transport protocol")
    segment = ip[ihl:total]
    require(len(segment) >= 20, "Truncated TCP header")
    thl = (segment[12] >> 4) * 4
    require(20 <= thl <= len(segment), "Invalid TCP header length")
    sport, dport = struct.unpack("!HH", segment[:4])
    return {"src": str(ipaddress.IPv4Address(ip[12:16])),
            "dst": str(ipaddress.IPv4Address(ip[16:20])),
            "sport": sport, "dport": dport, "payload": segment[thl:]}


def evaluate(proof_path, recording_path):
    result = {"schema": "network-coverage-result/v1", "status": "inconclusive",
              "label": LABELS["inconclusive"], "reasons": [],
              "limits": ["One identified direct IPv4 HTTP probe at one recording point and time.",
                         "Does not establish HTTPS, proxy or whole-application coverage.",
                         "Receipt provenance and route verification remain the caller's responsibility."]}
    try:
        proof_path, recording_path = Path(proof_path), Path(recording_path)
        p = object_json(read_file(proof_path, 1024 * 1024))
        c = object_json(read_file(recording_path, 1024 * 1024))
        require(p["schema"] == "network-probe/v1" and c["schema"] == "network-recording/v1",
                "Unsupported receipt schema")
        for key in ("run_id", "probe_id", "evidence_kind"):
            nonempty(p[key], key)
            require(p[key] == c[key], f"Probe/recording {key} mismatch")
        require(p["evidence_kind"] in ("live_emulator", "synthetic"), "Unknown evidence kind")
        require(re.fullmatch(r"[A-Za-z0-9_-]{16,128}", p["probe_id"]), "Invalid unique probe ID")
        result.update(run_id=p["run_id"], probe_id=p["probe_id"], evidence_kind=p["evidence_kind"])
        route = p["route"]
        require(route["verified"] is True and route["transport"] == "direct-ipv4-http",
                "Route unverified or unsupported")
        nonempty(route["description"], "route description")
        require(artifact(proof_path.parent, route["evidence"]).strip(), "Empty route evidence")
        req = p["request"]
        require(req["method"] == "GET" and req["path"] == "/coverage/" + p["probe_id"],
                "Request is not the identified probe")
        require(type(req["port"]) is int and 1 <= req["port"] <= 65535, "Invalid port")
        require(req["host"] == str(ipaddress.IPv4Address(req["ipv4"])) + ":" + str(req["port"]),
                "Host header and direct IPv4 destination disagree")
        server = object_json(artifact(proof_path.parent, p["server_receipt"]))
        require(server["schema"] == "network-server-receipt/v1", "Wrong server receipt schema")
        for key in ("run_id", "probe_id"):
            require(server[key] == p[key], f"Server {key} mismatch")
        for key in ("method", "host", "path"):
            require(server[key] == req[key], f"Server {key} mismatch")
        require(server["status"] == 200, "Server did not return success")
        for key in ("local_ipv4", "peer_ipv4"):
            require(str(ipaddress.IPv4Address(server[key])) == server[key], "Invalid server endpoint address")
        for key in ("local_port", "peer_port"):
            require(type(server[key]) is int and 1 <= server[key] <= 65535, "Invalid server endpoint port")
        nonce = server["response_nonce"]
        require(isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce), "Invalid server nonce")
        client = p["client"]
        require(client["source"] == "android-shell-nc" and type(client["exit_code"]) is int
                and client["exit_code"] == 0, "Client did not complete successfully")
        body = http_body(artifact(proof_path.parent, client["response"]))
        expected = f"Network coverage check\nProbe: {p['probe_id']}\nReceipt: {nonce}\n".encode("ascii")
        require(body == expected and hashlib.sha256(body).hexdigest() == server["response_body_sha256"],
                "Client response does not match the independent server receipt")
        begin, finish = timestamp(client["started_at"]), timestamp(client["finished_at"])
        received = timestamp(server["received_at"])
        start, end = timestamp(c["started_at"]), timestamp(c["ended_at"])
        require(start <= begin <= received <= finish <= end and begin < finish,
                "Recording does not bracket the independently timed probe")
        require(c["clock"] == "host-utc" and c["ready"] is True and c["closed_cleanly"] is True,
                "Recorder clock/readiness/finalization is unverified")
        require(type(c["dropped_packets"]) is int and c["dropped_packets"] == 0,
                "Recorder reported drops or lacks drop accounting")
        nonempty(c["point"], "recording point")
        require(c["filter"] == f"ipv4 tcp port {req['port']}", "Capture filter is unknown or mismatched")
        require(c["destination_ipv4"] == server["local_ipv4"] and c["destination_port"] == req["port"]
                == server["local_port"], "Recording endpoint does not match the server-side route")
        data = artifact(recording_path.parent, c["pcap"])
        matches, connection_packets, incomplete, count = [], [], [], 0
        wanted = f"GET {req['path']} HTTP/1.1\r\n".encode("ascii")
        for number, at, frame in packets(data):
            count += 1
            require(start - 0.001 <= at <= end + 0.001, "Packet timestamp is outside recorder interval")
            packet = tcp(frame)
            require(packet is not None and req["port"] in (packet["sport"], packet["dport"]),
                    "Packet contradicts the declared IPv4 TCP port filter")
            endpoints = (packet["src"], packet["sport"], packet["dst"], packet["dport"])
            forward = (server["peer_ipv4"], server["peer_port"], server["local_ipv4"], server["local_port"])
            reverse = (forward[2], forward[3], forward[0], forward[1])
            require(endpoints in (forward, reverse), "Capture contains a different TCP connection")
            if begin <= at <= finish:
                connection_packets.append(number)
            if (packet["dst"], packet["dport"]) != (c["destination_ipv4"], req["port"]):
                continue
            payload = packet["payload"]
            if not payload:
                continue
            header, sep, rest = payload.partition(b"\r\n\r\n")
            if not sep or not header.startswith(b"GET "):
                incomplete.append(number)
                continue
            lines = header.split(b"\r\n")
            require(not rest and all(b":" in line for line in lines[1:]),
                    "Unsupported request body or malformed HTTP request headers")
            hosts = [line[5:].strip() for line in lines[1:] if line.lower().startswith(b"host:")]
            require(lines[0] + b"\r\n" == wanted and hosts == [req["host"].encode("ascii")],
                    "Capture contains a different or malformed HTTP request")
            require(begin <= at <= finish, "Matching request is outside the client interval")
            matches.append({"packet": number, "at_epoch": at,
                            "source": f"{packet['src']}:{packet['sport']}",
                            "destination": f"{packet['dst']}:{packet['dport']}"})
        result.update(packet_count=count, matching_packets=matches, connection_packets=connection_packets,
                      request_header_observed=bool(matches), recording_point=c["point"],
                      route=route["description"], capture_sha256=c["pcap"]["sha256"])
        # Never let a partial parse turn absence into a confirmed gap.
        require(not incomplete, "Candidate HTTP headers span packets or are unsupported; TCP reassembly is not implemented")
        require(not count or connection_packets, "TCP packets fall outside the independently timed connection")
        status = "observed" if connection_packets else "verified_gap"
        result.update(status=status, label=LABELS[status], reasons=[
            "Independent server receipt and Android response agree on the unique probe and server nonce.",
            "Finalized capture with zero reported drops brackets the probe on the same host clock.",
            ("The exact request, Host header and server-side TCP connection occur in the capture." if matches else
             "TCP endpoints and time identify the connection; HTTP request-header visibility is not established.")
            if connection_packets else
            "The finalized valid capture is empty although the independent receipts prove the connection occurred."])
    except (Unclear, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, struct.error) as error:
        result["reasons"] = [f"{type(error).__name__}: {error}"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--recording", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(args.proof, args.recording)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"observed": 0, "verified_gap": 1, "inconclusive": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
