# Source provenance and license scope

Codex reviewed the source files, retained implementation records and dependency
use on 19 October 2026, then prepared this account. The initial import contains
ten byte-identical source/test files from the maintainer's local Android
app-testing workspace. Their baseline hashes are in
[`imported-sources.sha256`](imported-sources.sha256). The source workspace had
no Git history; this repository starts a new history rather than reconstructing
one. Private reports, device identifiers, screenshots and recordings are not
part of the import.

## Origin of the code

| Files | Recorded origin |
| --- | --- |
| `tools/capture_phase.py`, capture tests and fake ADB | Codex implementation and local checks, 12 October 2026; no-idle extension on 17 October and preserving-method integration on 19 October. |
| `tools/build_ui_dump.py`, `tools/ui-dump/NoIdleDump.java` | Codex implementation for the 17 October no-idle experiment, using the platform's legacy UI Automator API. |
| `tools/build_ui_preserve.py`, `tools/ui-preserve/` | Codex implementation from the 19 October preserving-method prototype and integration. Java and manifest bytes are unchanged from the prototype. |
| `tools/check_network_coverage.py`, network tests | Codex implementation and synthetic checks for the 15 October connection-visibility experiment. |
| English guides, synthetic example runner and its test | Codex publication preparation on 19 October, based on the above files, recorded results and operator decisions. |

The operator requested and bounded the work, selected the publication and
maintenance direction, supplied the physical test device and performed the
manual actions described in [validation](validation.md). Codex performed the
implementation, execution, analysis and drafting. No independent human code
review or test verification is claimed.

The `fdroid-*` temporary-path prefixes, package names and prototype labels
inside the imported code are retained to preserve the checked implementation.
They do not imply F-Droid affiliation. This collection is independently
maintained.

## External references and dependencies

The review found no vendored third-party implementation, copied license header
or bundled runtime in these files. The Java code calls Android platform APIs;
the Python code imports only the standard library. This is a source review
finding, not an exhaustive proof of originality or legal rights.

The preserving method was informed by Android's public
[`UiAutomation` API documentation](https://developer.android.com/reference/android/app/UiAutomation#FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
and inspection of pinned Android 16 source, including
[`UiAutomation.java`](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r1/core/java/android/app/UiAutomation.java)
and
[`Instrumentation.java`](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r1/core/java/android/app/Instrumentation.java).
Those references explain platform behavior; their implementation files are
not included here. The inspected framework files carry their own Apache 2.0
notices. AOSP has multiple licenses, so its general license preference is not
a substitute for checking any file copied in a future change. See
[AOSP license guidance](https://source.android.com/docs/setup/contribute/licenses).

| Dependency | How used | Redistribution in this repository |
| --- | --- | --- |
| Python and standard library | Execute scripts, parse files and run checks. | None; use your installed distribution and its license. |
| Android platform-tools / ADB | Explicit command-line connection for device capture. | None; provided by the caller. |
| Android SDK platform and build-tools | Compile the optional sources; platform jars are classpath/library inputs. | No SDK, platform jar, tool binary, generated JAR or APK is shipped. |
| JDK | `javac` and `keytool` for local builds. | None; use your chosen distribution and its terms. |

The builders package this collection's compiled helper classes and manifest.
They do not copy the platform jars into the output. The temporary APK signing
identity is for a bounded local test and is removed by the builder; it is not
a public release key. Build and test outputs remain outside the public tree.

## License

The package's [MIT license](../LICENSE) follows the
[published MIT license text](https://opensource.org/license/mit). It permits
reuse and modification, including commercial use, while requiring retention
of the copyright and permission notice. It includes the standard warranty
disclaimer. This is the proposed license for this repository's own code,
tests, examples and documentation; it does not relicense external tools,
platforms or private test evidence.

The collective notice names `android-test-helpers contributors`. It is not a
claim that the operator personally wrote Codex's implementation. Before any
future third-party code import, inspect its origin and terms and preserve its
notices. The initial package contains no third-party license file because no
third-party implementation is redistributed.

To verify the unmodified initial import from the repository root:

```sh
sha256sum -c docs/imported-sources.sha256
```

After later source changes, this historical import manifest is expected to
differ; use the selected Git commit to identify the new version.
