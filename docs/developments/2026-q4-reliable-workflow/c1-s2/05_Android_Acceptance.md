<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Android recovery acceptance continuation

| Field | Record |
|---|---|
| Date / operator | 31 October 2026; automated operator on the maintainer's Mac |
| State | Completed Android continuation within the physical scope and limitations recorded below |
| Physical device | Lenovo TB-J616X; Android 12 / API 31; landscape 2000 × 1200 pixels at 240 dpi |
| App | `0.3.0 (9)`, normal `lib/main.dart`; isolated qualification application identity preserves the installed store app and its data |
| Final runtime source | `01a7ac8acab32e926c185c8567f9b8dca08d3d68`; Android worktree runtime is byte-equivalent. The native package name alone is changed for the isolated identity |
| Final profile APK SHA-256 | `afc50a741a07344047d3069c9d4a36c1111869b3286e67b0a9f8d4a61a408e89`; also verified against the installed `base.apk` |
| Final arm64 AOT SHA-256 | `2ddb34eb36169466b5aa5aa32515e007354389f1ebdd276c0fdd40638e6e47a4` |
| Final native DEX SHA-256 | `1b62aceb530a2d361980b18d009188994cf7c92118d22842af3a6293757b61bb` |
| Original debug APK | Source equivalent to `6f5b3ea`; SHA-256 `957982f5acec969f8003d04b2d6444eecbba9af26b7392d760badb5be5d6bd0e`; original failures retained |
| Earlier profile APK | Runtime equivalent to `e54a78a`; SHA-256 `5b93b0c68bfc7bfa06a3a887ab70192a4d47c4786cf82e5428005ef94b199861` |
| Governing evidence | [Recovery contract](../../../specifications/App/current-draft-recovery.md#7-required-evidence-before-acceptance), [operator recipe](01_Operator_Recipe.md), [execution record](00_Execution_Record.md), [release matrix](../c1-s1/04_Release_Qualification_Matrix.md) |
| Private evidence | Ignored `local/recovery-completion/android/`: exact artifact/source manifests, native assertions, fresh UI XML/screenshots, logs, initial isolated-data backup and installed-artifact hash |

Both profile candidates were built from the normal application entry point.
The final candidate was built after `flutter clean`, with the new Dart keyboard
helper and native activity handler included. It is a qualification package;
these observations do not independently establish Play delivery or production
signing. The release record owns that separate packaging evidence.

## Recovery and replacement observations

The initial isolated Editor was empty. Its private data was backed up before
qualification, and the store app was not replaced or cleared. Only disposable
text and uniquely named board fixtures were used. No firmware was flashed by
this Android workflow.

| Recipe | Result / physical oracle | Evidence prefix |
|---|---|---|
| P01 | Pass on final candidate: actual Bluetooth state OFF and Wi-Fi disabled; startup presents the exact checkpoint before any connection workflow | `nativefix-all-offline-relaunch`, `nativefix-offline-bluetooth-confirmed` |
| P02 | Pass: named `recovery.py` retains Unicode `✓`, punctuation, blank lines and final newline; native entry was asserted exactly before normal key-event editing | `nativefix-typing-seed`, `nativefix-continuous-expected` |
| P03 | Pass: explicit recovery save acknowledges the matching text; Saved locally and board Unsaved changes remain distinct | `profile-saved-local`, `nativefix-continuous-saved` |
| P04 | Pass: actual force-stop/relaunch reproduces exact named text and checkpoint, including the generated Blocks text | `nativefix-typed-offline-relaunch`, `nativefix-generated-relaunch` |
| P05 | Pass: Back leaves the unresolved recovery decision; relaunch presents the same complete generated checkpoint | `nativefix-recovery-before-back`, `nativefix-recovery-after-back` |
| P06 | Pass on final candidate: explicit Restore shows exact text in the disconnected local panel; connecting remains a separate action | `controlled-3dcb-local-restore` |
| P07 | Pass for ordinary edit/lifecycle behavior: repeated normal key events, idle acknowledged checkpoint, backgrounding, force-stop and exact recovery | `nativefix-continuous-*`, `nativefix-all-offline-relaunch` |
| P08 | Pass on final candidate: Cancel retains the exact copy; confirmed Discard commits the empty slot and another process launch has no recovery prompt | `controlled-3dcb-discard-*`, `controlled-3dcb-empty-slot` |
| P09 | Pass on earlier profile: deliberately empty named `acceptance_1730.py` survives checkpoint/process relaunch as a recoverable document | `profile-empty-named-saved`, `profile-empty-named-prompt` |
| P10 | Pass on earlier profile: Save and Run show their current destination and distinct write-only/write-and-run effects; Cancel preserves the document. Confirmed upload and subsequent Run produced `67891` | `profile-save-consent-dialog`, `profile-run-consent-dialog`, `profile-named-upload-consent`, `profile-hello-output-complete` |
| P11 | Pass for physical moved-directory destination: Upload names the actual current directory; cancellation and confirmed upload were exercised | `profile-upload-cwd-consent`, `controlled-3dcb-cwd-upload-consent` |
| P12 | Pass on final candidate: matching confirmed upload clears board dirty; a new connection session requires current-target consent again, which was cancelled | `controlled-3dcb-upload-ack`, `controlled-3dcb-new-session-consent` |
| P13 | Pass on final candidate: Editor New, Board Open and Blocks handoff each protect meaningful pending Unicode text. Cancel retains it exactly; confirmed Blocks replacement installs the generated text | `nativefix-new-*`, `nativefix-board-open-*`, `nativefix-block-handoff-*` |
| P14 / DR-T12 | Pass on final candidate: normal Hello example → Open in Editor → guarded replacement → Save recovery copy → Disconnect → force-stop/relaunch recovers exactly `print('Hello, PyBLE!')\n` as text | `nativefix-generated-checkpoint`, `nativefix-generated-relaunch` |
| P15 | Verified physical scope: 2× recovery controls, Editor/Blocks keyboard layout, and native accessibility focus/labels with TalkBack active. Audible pronunciation and complete gesture navigation were not observed | `nativefix-named-2x-*`, `nativefix-blocks-ime-*`, `talkback-probe-*` |

The generated-text recovery observation does not claim restoration of a Blocks
workspace, revision history or companion files. The UI explicitly states that
the local slot contains one current text draft.

The retained earlier-profile observations cover unchanged storage, target-guard
and transport code. The final runtime changes keyboard dismissal; its affected
Editor/native-WebView behavior and Blocks handoff were repeated on the final
installed artifact. This is an impact assessment, not a claim that every earlier
observation was rerun on identical bytes.

Deterministic transaction-phase interruption, storage failure/volatile fallback
and stale-consent races remain covered by the automated fault/controller tests.
The normal device UI does not provide a reliable way to force those internal
phases. Their physical execution is not inferred from a successful ordinary
restart. Error-panel localization/layout coverage also remains part of the
host widget/semantics/golden evidence.

## Physical app-only matrix

Every passing core row covers edit, explicit Save, Run, observed stdout, Stop,
clearing the Editor before opening the saved board file, exact readback, explicit
disconnect/reconnect, and another readback. Program bytes and private action
receipts are retained with each row. A Ready scan result alone is not counted.

| Row | Exact profile / board alias | App candidate | Result | Raw prefix |
|---|---|---|---|---|
| Q02 | `esp32-4mb` / 8C9E | Final | Pass | `q8c9e` |
| Q04 | `esp32-s3-n16r8` / 5646 | Final | Pass | `q5646` |
| Q06 | `waveshare-esp32-s3-lcd-147b` / DA86 | Final | Pass | `qda86` |
| Q08 | `esp32-c3-4mb` / C81A | Earlier profile; unchanged transport/run code | Pass, including both required real-UI Stop cases | `profile-c3-*`, `profile-tight-*`, `profile-flood-*` |
| Q10 | `rpi-pico2-w` / 3DCB | Final | Pass after an explicitly retained Android-133 connection failure and retry | `q3dcb` |

C3 ran both `while True:\n    pass\n` and
`while True:\n    print(24680)\n`. The recorded UI changed from Running to
Ready/Console Idle after Stop and remained connected. During the print flood,
UIAutomator could not obtain an idle hierarchy; a direct live screenshot records
Running and repeated output before the captured toolbar Stop action. The settled
hierarchy then records Ready/Idle. No fresh wire-level latency bound or complete
firmware C3 qualification is claimed.

The [execution record](00_Execution_Record.md) owns the fresh immutable-program
bindings and app-only scope decision. Classic ESP32 is bound to the published
baseline; the two S3 boards, C3 and Pico 2 W are bound to the verified observer
baseline `96497b9`. Their common HELLO version `0.6.1` is not treated as evidence
of identical firmware bytes or of the published five-profile firmware gate.

## Defects resolved and evidence limits

| Finding | Original observation | Final observation |
|---|---|---|
| Landscape keyboard overflow | Original debug candidate hid the Editor and overflowed Files/navigation while IME was visible | Editor and navigation remain visible; console collapses honestly and expands after keyboard dismissal |
| Native WebView keyboard remained open | Earlier profile: Blocks HTML field → Expand console retained the IME despite the successful semantic button action | Final profile: same action retains the field/workspace, expands console, and changes Android `mInputShown` from true to false |
| Initial debug Blocks startup failure | Original debug retries and device/provider restart reached the startup watchdog; browser-side diagnostics alone did not establish a JS/CSP cause | Clean profile application initializes, loads/edits the example and completes real handoff/relaunch. Exact-assets native and pinned-plugin diagnostic apps also initialize. No speculative CSP/bootstrap change was made |

Initial helper attempts that reused a stale hierarchy, replaced populated rich
Editor text unreliably, or encountered an unrelated Android crash dialog were
retained and excluded. Accepted readbacks first clear the Editor, and named-file
input waits for the adopted Editor filename. The initial TalkBack gesture
attempt is also excluded because service/interaction state was not controlled.
A post-probe interval failed the following test's expected UI precondition and
was excluded from target/discard acceptance; that complete sequence subsequently
passed in a fresh uninterrupted run. No cause is inferred for those intervals.

The later isolated accessibility probe used
`FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`. For Restore, Copy text and Discard
recovery copy, it verified an exact visible/enabled native button, accepted
accessibility-focus action, matching focus event and focused node. TalkBack
remained bound before and after the probes. This verifies native focus and label
exposure, not audible speech or complete screen-reader usability. Recorded
accessibility-service, touch-exploration and font settings were restored in a
`finally` step. Original radio settings were restored after offline checks.
All board connections were explicitly released; temporary diagnostic apps,
device helper files and the debugging forward were removed. The isolated
qualification app/data and private evidence remain available for review. An
exact ownership manifest records the disposable board fixtures for coordinated
cleanup without touching other files.
