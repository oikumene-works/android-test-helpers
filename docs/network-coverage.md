# Check the recording of one HTTP connection

[`check_network_coverage.py`](../tools/check_network_coverage.py) answers a
narrow question: does a finished packet recording show the same connection
that independent client and server receipts say succeeded? It was written
after a recording failed to establish visibility of an app's traffic. Codex
implemented the checker, performed its recorded experiments and wrote this
guide. It does not capture packets, make requests or start an environment.

Python 3.10+ and its standard library are sufficient. Inputs are local files;
the checker prints JSON to stdout. Start with the device-free
[synthetic examples](../examples/README.md):

```sh
python3 -B examples/run_synthetic.py --output ./example-output
python3 -B tools/check_network_coverage.py \
  --proof example-output/network/observed/proof.json \
  --recording example-output/network/observed/recording.json
```

## Interpret the result

| Exit / `status` | Meaning |
| --- | --- |
| `0` / `observed` | Independent receipts agree on success, and TCP endpoints and times identify that connection in the recording. |
| `1` / `verified_gap` | Independent receipts agree on success, but the valid, finalized, correctly scoped recording is empty. |
| `2` / `inconclusive` | Missing evidence, contradictions or format limits prevent classification. Read `reasons`. Argument errors also return 2, with stderr. |

`connection_packets` identifies packets in the timed TCP connection.
`matching_packets` and `request_header_observed` separately describe visibility
of the exact HTTP request header. A connection can be observed without that
header. Packet counts are not request counts; capture points can record
duplicates. Machine-readable `status` is English; the existing `label` field
contains Finnish display text and is retained for compatibility.

An empty file alone never proves a gap. Even an empty PCAP needs a valid
24-byte header and independently recorded readiness, time bounds, successful
closure and zero drops. A zero-byte, truncated or still-open capture is
inconclusive, as is a capture of a different connection or HTTP request.

## Scope and limits

The supported input is classic PCAP 2.4, Ethernet link type 1, with one direct
IPv4/TCP/HTTP connection at a server-side capture point after any emulator
address translation. Both byte orders and microsecond/nanosecond timestamps
are parsed; the actual experiment used little-endian microsecond PCAP.
The declared filter must be exactly `ipv4 tcp port PORT`, and all packets must
belong to the receipt's timed TCP connection. Mixed captures are inconclusive.
Do not remove packets afterward to make a classification pass.

There is no PCAPNG, Linux cooked capture, TCP reassembly, TLS decryption,
fragment reassembly or general traffic analysis. Split candidate HTTP request
headers, unknown protocols, truncated packets and conflicting timestamps
remain inconclusive. Responses must be HTTP 200 with `Content-Length` and the
body below; chunked or compressed responses are unsupported. Artifact files
are limited to 64 MiB each; the two top-level JSON files to 1 MiB each.

This check does not establish HTTPS, proxy, VPN, IPv6 or whole-app coverage.
Your probe must exercise the route you intend to assess. If that route is
outside this version's supported scope, record that limit rather than treating
a direct HTTP example as its substitute.

## Input receipts

The generator creates complete examples in `example-output/network/observed/`.
Use them to understand the format, not as evidence of a real test. Each artifact
reference is an object with `file` and `sha256`; the file must be a sibling of
the JSON document that references it, with no directory components. Inputs
are trusted local evidence, not a sandbox for hostile files or symlinks.

| File / schema | Required content |
| --- | --- |
| `proof.json`, `network-probe/v1` | Matching `run_id`, unique `probe_id` (16–128 letters/digits/underscores/hyphens), `evidence_kind` (`live_emulator` or `synthetic`); verified route; request; server receipt reference; client result. |
| `route` object in proof | `verified: true`, `transport: direct-ipv4-http`, description and an evidence file reference. |
| `request` object in proof | `method: GET`, `ipv4`, integer `port`, `host` as `IP:PORT`, and `path` as `/coverage/PROBE_ID`. |
| `client` object in proof | `source: android-shell-nc`, `exit_code: 0`, host-measured `started_at`/`finished_at`, and raw HTTP `response` reference. |
| Server receipt, `network-server-receipt/v1` | Same run/probe IDs and method/host/path, `status: 200`, `received_at`, `local_ipv4`/`local_port`, `peer_ipv4`/`peer_port`, `response_nonce` and `response_body_sha256`. |
| `recording.json`, `network-recording/v1` | Same IDs and evidence kind, capture `point`, exact `filter`, server-side `destination_ipv4`/`destination_port`, `started_at`/`ended_at`, `clock: host-utc`, `ready: true`, `closed_cleanly: true`, `dropped_packets: 0`, and `pcap` reference. |

Timestamps are ISO 8601 with timezones. The client's command and the server's
receipt must fit inside the recording interval. The recorded experiment used
the same host clock for these boundaries and packet timestamps, not the
Android screen clock.

Generate a random 32-character lowercase hexadecimal `response_nonce` on the
server only after the request arrives. Return exactly this ASCII body,
including the final newline:

```text
Network coverage check
Probe: PROBE_ID
Receipt: SERVER_NONCE
```

The checker compares the independently saved client response with the server
receipt and its body hash. The client's zero exit code, or traffic in the PCAP
being assessed, is insufficient on its own.

The caller establishes provenance and route evidence. Hashes detect changes
relative to the receipts, not fabricated receipts. The helper cannot verify
your `route.verified`, readiness, clock or closure statements. Write them only
after actual checks. Keep unknowns explicit and never relabel live evidence
as synthetic or vice versa to change a result.

## Use with an authorized experiment

1. Verify the selected device, actual route, allowed destination, capture point
   and test boundaries. Prepare one unique request and independent receipts.
2. Start the scoped recording and verify readiness before sending the request.
3. Preserve the client response and server receipt. Close the recording,
   inspect drops and record boundaries, filter, point and artifact hashes.
4. Run the command with those two JSON paths and read the reasons and limits.

The repository intentionally provides no server, capture runner, proxy setup
or device launcher. The previous experiment used `adb shell -T` to send the
request; an `adb exec-out` attempt did not deliver stdin and was inconclusive.
Treat that as a recorded constraint, not a generic connectivity guarantee.

## Cleanup

The checker does not modify its inputs or create temporary resources. Any
stdout file you create by redirection is yours to retain or remove. The caller
stops the recorder/server and cleans up the environment used to produce real
evidence. Keep raw captures and receipts private until individually reviewed.
The example guide explains removal of its entirely synthetic output.
