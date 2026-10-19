# Use one checked source revision

This repository is the development source. Consume an exact commit for each
test instead of copying helpers into app projects or pulling changes during a
run. Codex prepared and locally checked this procedure for the initial package.
It uses ordinary Git; there is no new updater, release service or framework.

## Prepare a fixed checkout

In a source checkout that contains the desired commit, set `HELPERS_REVISION`
to its full commit ID. `HELPERS_CHECKOUT` must name a new absolute directory
reserved for test dependencies, outside tracked source and evidence directories.
Choose the revision from a reviewed record;
a hash identifies bytes but is not proof that a revision is trustworthy.

```sh
git worktree add --detach \
  "${HELPERS_CHECKOUT:?set a new absolute checkout directory}" \
  "${HELPERS_REVISION:?set the reviewed full commit ID}"
git -C "$HELPERS_CHECKOUT" rev-parse HEAD
git -C "$HELPERS_CHECKOUT" status --short
```

Check that HEAD is the intended commit and status is empty. Run helpers using
that directory's absolute path, for example:

```sh
python3 -B "$HELPERS_CHECKOUT/tools/capture_phase.py" --help
python3 -B "$HELPERS_CHECKOUT/tools/check_network_coverage.py" --help
```

For a real capture, supply the current test's arguments from the
[capture guide](capture.md). Build its optional JAR/APK from this checkout too.
Do not edit a fixed checkout or change its revision while a test references it.
Detached HEAD prevents accidental branch movement, not file editing; check
the working tree again when recording the test's result.

## Record identity with the test

In your private test record, retain the full Git commit, clean-tree result,
selected helper path/method, and JAR/APK hashes if applicable. Capture records
the optional artifact's hash itself; the preserving builder also records
source hashes and signing verification in `.build.json`. There is no claim
that a newly rebuilt APK is byte-reproducible: each build creates a temporary
signing identity. Use the same built APK throughout that run.

Store outputs outside the checkout. Once the test is closed and no live
operation depends on the files, remove the worktree with:

```sh
git worktree remove "$HELPERS_CHECKOUT"
```

Git refuses removal if the checkout has changes; inspect them rather than
forcing deletion. Keep the commit and your evidence records available.

## Moving an existing local consumer

For the first adoption, compare the old helper bytes with the selected
revision, including both Java sources, the manifest and builders. Record any
differences before switching. Existing private reports keep their old evidence
and version references; do not rewrite historical results as tests of a new
revision.

Between active runs, point the consumer's invocation at the fixed checkout.
If old command paths must remain usable, symlink those entry points to the
same checkout, including their adjacent Java source directories. Resolve each
link and run device-free CLI/examples from the resulting paths. Keep one
rollback copy only for the transition; mark it archived and do not develop it.
Do not maintain a second editable source tree or silently update consumers.

Subsequent improvements happen here. Check the change, record its new revision
and validation scope, and deliberately select it for the next test. Git commit
identity and artifact hashes keep public code, local use and evidence tied
together without promising compatibility beyond the recorded checks.
