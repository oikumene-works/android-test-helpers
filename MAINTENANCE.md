# Maintenance and contributions

This collection follows the maintainer's own Android testing needs. Checked
improvements are published when useful in that work. Known limitations stay in
the relevant guide. Outside issues and contributions may be considered when
time permits; there are no response deadlines, support commitments, promised
features or general Android compatibility guarantees.

Keep changes small and related to an observed need. The collection is not a
device farm, test runner, installation manager or monitoring service. A new
format, capture route or platform needs its own evidence before it is described
as supported. Adding a dependency also requires recording its source and license.

## Reporting an observation

Include the helper revision, host and Android versions, selected capture
method, the command with private values removed, expected and actual behavior,
and the relevant status or error. Share the smallest useful reproduction.
Screenshots, UI trees and raw command output may contain private information;
inspect and redact copies before sharing. Do not post keys or credentials.

State who performed the work and how. Separate synthetic results, device
observations and interpretation. If Codex or another tool performed execution,
analysis or drafting, describe its actual contribution. Human direction or
approval alone is not independent verification.

## Before proposing a change

Run the relevant existing tests and the full local suite before release:

```sh
python3 -B -m unittest discover -s tools/tests -p 'test_*.py' -v
```

These checks use fake ADB and synthetic files only. If behavior changes on a
device, say which device behavior has and has not been checked. A passing
synthetic suite does not replace the necessary device evidence. Preserve old
failed attempts and explain changed output or interpretation in the guide.
Keep one source of development in this repository and consume fixed revisions
as described in [versions](docs/versions.md).

Contribute only material you may share under this repository's MIT license;
preserve third-party notices and identify any external source. Publication and
acceptance remain the maintainer's decision.

The operator selected this bounded maintenance model. Codex drafted this text
from that decision and the existing working practice.
