# Capture one Android test phase

[`capture_phase.py`](../tools/capture_phase.py) reduces repeated evidence
collection: one call stores a screenshot, Android's UI hierarchy, device and
app context, supplied language/input notes and cleanup results. Codex wrote
the helper and this guide from its recorded tests. It does not navigate, type,
install apps, change settings or decide whether the application passed a test.

## Choose the UI method first

| Method | When useful | Device effect and limits |
| --- | --- | --- |
| Default stock dump | An ordinary settled screen where a service interruption is acceptable. | Uses `uiautomator dump`; can suppress accessibility services. No additional APK. |
| `--ui-fallback-jar` | A changing screen prevents the stock dump from reaching idle. | Starts with stock, then at most one no-idle invocation after a completed but unusable dump. Both methods can suppress services. |
| `--ui-preserve-apk` | An accessibility service must remain active during capture. | Uses a separately installed debug instrumentation helper, with the preserving flag from its first connection. Never falls back to either method above. Owner user 0 only. |

The options are mutually exclusive. Android documents that UiAutomation
suppresses accessibility services by default and provides
[`FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`](https://developer.android.com/reference/android/app/UiAutomation#FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
to request continued operation. This is not a guarantee that every service or
event remains unaffected. See the [actual validation scope](validation.md).

## Requirements and preparation

Use Python 3.10+, a Linux host and an explicitly selected ADB executable,
server host/port and device serial. Establish the authorized ADB connection
before capture and use a client compatible with that server. ADB can start a
missing server or replace a mismatched version; supplying a server address is
not an isolation mechanism. In an isolated test, invoke the helper inside
that test's existing environment.

The app must already be installed and its intended screen open. Wait for it
to settle when possible. Choose an existing absolute evidence directory
outside this checkout. Screenshots, UI text and raw system dumps can contain
private data. There is no automatic redaction.

Fill these variables from the current test: `CAPTURE_ADB` (absolute executable),
`CAPTURE_ADB_HOST`, `CAPTURE_ADB_PORT`, `CAPTURE_DEVICE`, `CAPTURE_PACKAGE`,
`CAPTURE_EVIDENCE_DIR` (absolute directory), `CAPTURE_LANGUAGE` (observed UI
language) and `CAPTURE_INPUT` (input method and relevant intended input).
The variables are shell conveniences, not stored configuration.

From the selected checkout:

```sh
python3 -B tools/capture_phase.py \
  --adb "${CAPTURE_ADB:?set the current ADB executable}" \
  --server-host "${CAPTURE_ADB_HOST:?set the current server host}" \
  --server-port "${CAPTURE_ADB_PORT:?set the current server port}" \
  --serial "${CAPTURE_DEVICE:?set the selected device serial}" \
  --package "${CAPTURE_PACKAGE:?set the app package ID}" \
  --phase TC03-after-save \
  --output "${CAPTURE_EVIDENCE_DIR:?set the evidence directory}" \
  --app-language-note "${CAPTURE_LANGUAGE:?record the observed UI language}" \
  --input-note "${CAPTURE_INPUT:?record input method and intended input}"
```

Use a phase name that describes the actual step. If language or input context
is unknown, omit that note option: the result remains explicitly partial.
The helper records your notes without verifying them. Locale settings do not
establish what language appeared on screen or whether intended input arrived.

`--timeout` is seconds **per ADB command**, default 15, not a total deadline.
The usual stock path uses 24 commands; the preserving path uses 30. Locale
fallback adds one, and no-idle fallback adds further commands. No host command
is automatically retried. Set a separate overall test and cleanup budget.

## Read the output

Each call prints a new timestamped evidence directory, created with mode
`0700`. Repeated phase names never reuse earlier directories. It contains:

- `screenshot.png`, if captured, and the selected tree file named in
  `metadata.json` at `captures.ui_tree.file`;
- `metadata.json`, with per-command times, results, raw-output filenames,
  supplied notes, method attempts and cleanup status;
- raw stdout and stderr, including failed attempts and partial files.

The selected tree can be `ui_tree.xml`, `ui_fallback_tree.xml` or
`ui_preserve_tree.xml`. Always read its filename from metadata. Context includes
model, Android release/API, package path, locale settings, display size/density,
font scale, input method/state, window focus and clock settings.

| Exit / status | Meaning |
| --- | --- |
| `0` / `complete` | Both artifacts pass structural checks, context and notes are present, and owned temporary-file cleanup is verified. |
| `1` / `partial` | At least one artifact passes, but another artifact, context, note or cleanup check is incomplete. |
| `2` / `failed` | Neither artifact passes. Invalid arguments or local storage errors also return 2; inspect stderr. |
| `130` | Interrupted; inspect any saved metadata and cleanup state. |

`Needs review` summarizes incomplete fields. A `null` time format or empty
setting is retained as missing, not guessed. If `persist.sys.locale` is empty,
the helper tries `am get-config` and preserves Android resource qualifiers
such as `en-rUS` without presenting them as normalized language tags. Unknown
formats remain incomplete. Window focus uses the full `dumpsys window` output.

`complete` describes evidence collection, not application correctness. PNG
checks cover framing and CRCs, not decoded pixels; XML checks cover parsing
and hierarchy nodes. Inspect the actual image and tree. They and the metadata
are collected sequentially, not atomically; an animation or counter can change
between them. Package paths do not prove APK provenance or foreground identity.

## Build and use the no-idle fallback

Use an already installed JDK providing `javac --release 8`, an Android SDK
platform containing `android.jar`, `uiautomator.jar` and
`optional/android.test.base.jar`, and build-tools providing `d8`.
The recorded build used platform 36 and build-tools 36.0.0. No SDK is bundled
or downloaded. Set the three variables to absolute paths; the output must be
new and its parent directory must exist.

```sh
python3 -B tools/build_ui_dump.py \
  --platform "${CAPTURE_PLATFORM:?set installed SDK platform directory}" \
  --build-tools "${CAPTURE_BUILD_TOOLS:?set installed build-tools directory}" \
  --output "${CAPTURE_UI_JAR:?set a new absolute JAR path}"
```

Add `--ui-fallback-jar "$CAPTURE_UI_JAR"` to the capture command. The JAR is
only pushed if stock finishes but fails to produce a usable tree. Stock
timeout or signal termination skips fallback because remote completion is
unknown. The Java invocation makes up to three attempts, 300 ms apart, only
while no output file exists; it does not retry an existing invalid XML file.

This uses the legacy UI Automator API and its Java runner directly. The shell
wrapper changed the output base during the API 36 experiment. It does not
require root. It removes idle waiting in its own process; it does not freeze
the screen and can still interrupt accessibility services. Failed stock
evidence and both method attempts are preserved.

## Build and use the preserving method

This needs a JDK (`javac`, `keytool`), an installed Android SDK platform and
build-tools (`d8`, `aapt2`, `zipalign`, `apksigner`). The builder produces a
new signed APK and `.build.json` receipt, without downloading dependencies.
Its temporary signing key and build directory are removed on normal completion;
the receipt records verification and removal. A hard host/process failure can
leave temporary build material to inspect. Each build uses a new signing key:
keep the same APK for the whole test, not a rebuilt replacement.

```sh
python3 -B tools/build_ui_preserve.py \
  --platform "${CAPTURE_PLATFORM:?set installed SDK platform directory}" \
  --build-tools "${CAPTURE_BUILD_TOOLS:?set installed build-tools directory}" \
  --output "${CAPTURE_UI_APK:?set a new absolute APK path}"
```

The package is `qa.capture.preserve`, separate from the app under test.
The manifest has minSdk 24, targetSdk 36, debugging enabled, backup disabled
and no requested permissions. The minimum SDK is not a compatibility claim.

During your test setup, check that no unrelated installation of this package
exists. Install the newly built APK only on the selected test device, through
the same explicit ADB connection. Do not use replacement installation to
overwrite an unknown package. For a fresh test installation:

```sh
"$CAPTURE_ADB" -H "$CAPTURE_ADB_HOST" -P "$CAPTURE_ADB_PORT" \
  -s "$CAPTURE_DEVICE" install --user 0 "$CAPTURE_UI_APK"
```

Add `--ui-preserve-apk "$CAPTURE_UI_APK"` to the capture command. Capture
itself never installs the helper or changes accessibility settings. It checks
user 0, a single installed APK and its hash against your local file, then
acquires a lock inside the helper's private directory. A busy or uncertain
lock is not overridden. It requires successful instrumentation status, a
fresh capture ID, the preserving connection flag and the requested active
package in the returned tree. Any error stays on this path; no stock fallback
is attempted. The serializer bounds tree depth and node count; it does not
promise the same attributes or coverage as the stock dumper.

## Cleanup and interruption

Stock and fallback use an owned UUID directory under `/data/local/tmp/`.
The helper removes its XML, optional JAR and empty directory. A timed-out or
interrupted remote writer leaves cleanup `unverified` even if removal succeeds.

For preserving capture, only after acquiring its lock does the helper
force-stop **its own package**, check that its process is gone, remove its
tree file, verify absence and release the lock. If stopping cannot be verified,
the file and lock remain for inspection. It never force-stops the app under
test. The installed helper APK is retained between captures.

Treat `cleanup.status: unverified` or an abandoned `in_progress` record as
unfinished cleanup. Inspect the recorded commands and exact owned paths in
the current test environment. Do not remove another capture's lock or claim
that elapsed time proves a remote process stopped.

At the end of your test, uninstall the helper installation you prepared:

```sh
"$CAPTURE_ADB" -H "$CAPTURE_ADB_HOST" -P "$CAPTURE_ADB_PORT" \
  -s "$CAPTURE_DEVICE" uninstall qa.capture.preserve
```

Verify package absence through the same connection. Remove your host JAR/APK
and temporary build output when no longer needed; retain hashes and useful
receipts with private evidence. Evidence directories are intentionally not
deleted by capture. Device/emulator shutdown and the rest of test cleanup
remain the caller's responsibility.
