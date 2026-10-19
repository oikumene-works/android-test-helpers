# Synthetic examples

Codex wrote these examples from the helpers' existing local test fixtures.
They generate invented evidence and run the actual Python command-line
helpers against it. No real ADB, phone, emulator, HTTP server, packet recorder,
SDK or network access is used. Python 3.10+ on Linux is sufficient.

From the repository root, choose a new output directory:

```sh
python3 -B examples/run_synthetic.py --output ./example-output
```

The parent must exist. Repeating the command with the same output path returns
2 and leaves it intact. Use another name for a second run. Each invocation
finishes after producing four fake captures and three network classifications:

| Directory | Expected result | Demonstrates |
| --- | --- | --- |
| `capture/stock` | `complete`, exit 0 | Ordinary capture and context. |
| `capture/no-idle` | `complete`, exit 0 | Failed stock evidence retained alongside a successful fallback. |
| `capture/preserve` | `complete`, exit 0 | Preserving path selection and cleanup against fake ADB. |
| `capture/missing-notes` | `partial`, exit 1 | Missing caller notes stay visible even with valid artifacts. |
| `network/observed` | `observed`, exit 0 | Matching receipts and a request in a synthetic PCAP. |
| `network/verified_gap` | `verified_gap`, exit 1 | Consistent success receipts and a valid empty PCAP. |
| `network/inconclusive` | `inconclusive`, exit 2 | Recorder readiness is false. |

The generator itself returns 0 when all seven expected outcomes occur, including
the deliberately partial and inconclusive cases. Inspect `results.json` and
the referenced capture `metadata.json` files. Each synthetic screenshot is a
one-pixel image, not an Android screen. Fake JAR/APK bytes are never executed;
the temporary fake device, executable and placeholder files are removed.
Saved command paths refer to that now-removed fake environment.

For a single network classification, run:

```sh
python3 -B tools/check_network_coverage.py \
  --proof example-output/network/observed/proof.json \
  --recording example-output/network/observed/recording.json
```

Substitute `verified_gap` or `inconclusive` in both paths for the other cases.
The JSON retains `evidence_kind: synthetic`. Even a `verified_gap` here proves
only that the classifier handles invented receipts as designed; it is not a
measured blind spot. The PCAP has synthetic framing and zero IP/TCP checksums;
it is not a captured live packet. The checker does not validate those checksums.

Network files are byte-repeatable. Capture timestamps, UUIDs and temporary
paths intentionally vary; their expected outcomes are repeatable. Run the
[test suite](../docs/validation.md) for corruption, timeout, interrupted cleanup
and other failure cases.

## Cleanup

Only the output directory is retained. After inspecting it, remove that exact
directory through your file manager, or, if you used the path above from the
repository root:

```sh
rm -r -- ./example-output
```

No device uninstall, ADB shutdown or network cleanup is needed for these examples.
Generated files are ignored by Git at that default path. Outputs elsewhere
remain your responsibility. Do not substitute these files for real test evidence.
