# Validation and its limits

Codex performed the checks and experiments summarized below and wrote this
summary from the retained local records. The operator directed and bounded
the work; where recorded, the operator viewed the stopped emulator and
released cleanup, and enabled the phone's synthetic accessibility service
manually. These actions are not independent verification of the results.

## Reproducible checks included here

```sh
python3 -B -m unittest discover -s tools/tests -p 'test_*.py' -v
```

The imported suite has 41 capture tests and 16 network tests. Capture tests
invoke the real CLI with a local fake ADB. They cover explicit connection
selection, preserved older evidence, malformed PNG/XML, missing context,
locale fallback, method selection, helper identity, locking, timeouts,
interruption and uncertain cleanup. Network tests cover all three outcomes,
independent receipt mismatches, corruption, timing, wrong connections and
unsupported formats. A further public-example test covers all seven example
outcomes, synthetic labels, temporary fake-device cleanup, repeatable network
bytes and refusal to replace existing output.

The 57 imported tests passed in the new checkout on Linux with Python 3.14.7
on 19 October 2026. The added example test also passed. These checks do not
launch an emulator or contact a phone or network. They do not establish
Android runtime behavior, other host compatibility or a Python-version matrix.

On 20 October 2026, Codex corrected the interpretation of an unset clock
preference. The CLI regression checks cover a successful `null` response,
explicit `12`/`24` preferences, empty and unexpected output, and a failed read
that nevertheless prints `null`. Only the valid default/explicit cases may
complete. An unrelated missing setting remains partial. Codex also replayed
the retained clock command's successful `null` response locally; the original
capture was not changed. This is interpretation and synthetic CLI validation,
not a new phone or emulator run. All 62 local tests passed on Linux with
Python 3.14.7 after this change.

## Previously recorded device evidence

The initial publication preserves the helper source bytes from the local
experiments. Private raw device records remain with the maintainer; this
summary does not make them independently reproducible public evidence.

| Date / experiment | What Codex observed | Boundary |
| --- | --- | --- |
| 12 October 2026, stock capture | AOSP Android 16 / API 36 settings capture; explicit 24-hour format produced complete output, default `null` format stayed partial. Artifacts, locale/focus and cleanup checked. | Earlier capture version; not a claim about all Android releases. |
| 17 October 2026, no-idle extension | AOSP API 36 stock dump worked on a stopped synthetic screen; on a continuously updating screen, stock failed and the no-idle fallback returned a usable tree. | No-idle helper source is unchanged; this was not a physical-phone test. |
| 19 October 2026, preserving prototype | AOSP API 36 and Samsung Galaxy A36 / Android 16: stock capture restarted the synthetic service; preserving capture retained the same service instance, fresh trees and received events during an open connection. | Prototype evidence on one synthetic service; not the later Python integration on that phone. |
| 19 October 2026, preserving integration | AOSP API 36: three complete captures and an intentionally timed-out partial capture; all four cleaned up. Same service instance, 36 received events, maximum observed interval 267 ms. | Full CLI integration on emulator only. Event delivery was not proved lossless. |
| 15 October 2026, network checker | One direct HTTP connection over the emulator's Wi-Fi route was observed in a server-side capture. Separate server receipt and Android raw response agreed. An earlier failed stdin attempt was inconclusive. | No real verified gap was produced. No HTTPS, proxy, VPN, IPv6 or whole-app coverage claim. |

The prototype and integration environments and temporary installations were
cleaned up in their original runs. Publication preparation did not reopen
them. It added device-free examples and reran appropriate local checks.

The preserving method on GrapheneOS, arbitrary accessibility services and broad
device/version coverage are unverified. No new AutoScroller test was performed
with the preserving method. A declared minSdk is not a passed compatibility
range. Screenshot, tree and context times differ because capture is sequential.
Report these limits alongside any use of the results.
