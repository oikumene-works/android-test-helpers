# Android test helpers

Two small command-line helpers extracted from practical Android app testing.
They keep evidence and its limits visible without starting or managing a test
environment. Python 3.10 or newer and its standard library are enough for the
offline examples and network analysis. Device capture also requires ADB.
The checked host environment is Linux; other hosts are not validated.

| Helper | Why it exists | Guide |
| --- | --- | --- |
| [`capture_phase.py`](tools/capture_phase.py) | Save a named phase's screenshot, UI tree, settings, input notes and cleanup results together. | [Capture a phase](docs/capture.md) |
| [`check_network_coverage.py`](tools/check_network_coverage.py) | Compare independent receipts for one successful HTTP connection with its packet recording. | [Check one connection](docs/network-coverage.md) |

Capture has two optional UI methods: a no-idle Java fallback for a constantly
changing screen, and a separate instrumentation helper that requests
preservation of accessibility services. Their source and offline builders are
included. **The default UI dump and the no-idle fallback can interrupt
accessibility services.** Read the capture guide before selecting a method.

## Try it without a device

From this checkout:

```sh
python3 -B examples/run_synthetic.py --output ./example-output
python3 -B tools/check_network_coverage.py \
  --proof example-output/network/observed/proof.json \
  --recording example-output/network/observed/recording.json
python3 -B -m unittest discover -s tools/tests -p 'test_*.py' -v
```

The first command creates a new directory and refuses to overwrite it. It uses
a local fake ADB and invented receipts; it does not contact a phone, emulator,
ADB server or network endpoint. The second command reports `observed` with
`evidence_kind: synthetic`. This demonstrates interpretation of fixture data,
not a working connection. See [examples and cleanup](examples/README.md).

## Use in a real test

Select and prepare your own device, app, connection and evidence directory.
The helpers neither grant access nor provide device isolation. Capture writes
temporary device files and removes its own files when it can verify cleanup;
the network checker only reads local files. Neither helper judges whether the
app works correctly. A complete capture and an observed connection answer
different, limited questions.

Use an [exact Git revision](docs/versions.md) throughout a test. Build optional
device helpers from that revision, record their hashes, and keep private test
output outside the source checkout. There is no package installer or automatic
update mechanism.

## Evidence, authorship and maintenance

Codex implemented the helpers, ran the recorded checks and device experiments,
interpreted their evidence, and prepared this publication package. The human
operator directed and bounded the work, supplied test devices and made the
recorded manual setup and viewing actions. Those actions do not constitute
independent verification of Codex's results. [Validation](docs/validation.md)
separates synthetic tests, emulator integration and physical-device prototype
evidence. Raw device records are private and are not bundled here.

Maintenance follows our own use: checked improvements and documented limits,
with outside contributions considered when time permits. There is no response
time, feature roadmap or broad compatibility promise. See
[maintenance and contributions](MAINTENANCE.md).

The package uses the [MIT license](LICENSE); [provenance](docs/provenance.md)
describes the imported source, dependencies and review limits.
