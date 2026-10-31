<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# iPad recovery and app compatibility acceptance

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | Normal-app recovery and affected workflow observations for PYB-006.2 / PYB-008.1; app-only compatibility rows Q01/Q03/Q05/Q07/Q09 |
| Outcome | Exact offline restoration, current-board consent and normal Blocks-generated text recovery observed; final keyboard repair and all five app-only iPad board rows pass within the recorded scope below |
| Current runtime | `bef67bded9e5b83437e3eb0e2ec4be6a4cfd1a64`, app tree `60b3a68b693551af5d83076547c502f69838e052`; PR #41 |
| Candidate | PyBLE Preview `0.3.0 (9)`, normal `lib/main.dart`, signed profile mode, isolated `dev.pyble.recoveryqualification` identity |
| Physical platform | iPad Air 13-inch (M4), model `iPad16,10`, iPadOS `26.6.2`, wired to the maintainer's Mac |
| Operator | Automated engineering run through native XCTest; no independent human review, participant observation or audible VoiceOver evaluation claimed |
| Prior results | [Platform observations](02_Platform_Qualification.md); storage seed/kill/verify is distinct from this normal-app interaction evidence |

## Installed artifacts and continuity

| Runtime | Private archive SHA-256 | Observations |
|---|---|---|
| Merged PR #40 `6f5b3ea` | `c91bc6f7e14f421a528668bd3723e3f965d55f79f11ea90fec707a8fb15a4d1a` | Initial installed identity and five-board discovery; superseded for layout qualification |
| Landscape repair `e54a78a` | `ddf611e85065db05c1622faef59c6eddc5b821dfd1a2702ec0cbb66d093e5a0b` | Unicode lifecycle/offline recovery, current-target consent, empty named draft and classic ESP32 workflow |
| Native dismissal `01a7ac8` | `3a2775d1648fe3a188b89f30912af0b7f771ec08b8c0e3b9f4d0c3d49d33510b` | Blocks-to-Editor recovery and C3 workflow; input-palette geometry defect reproduced |
| Native keyboard guide `bef67bd` | `7d39100283fb2cd9189d448881b788ad5eadfdf813a0e5f36ff9a2850fa6c471` | Clean profile build; exact Dart/AppDelegate source manifest matches the runtime; compiled guide channel present and diagnostic instrumentation absent |

Archives, source manifests, native accessibility trees, screenshots and
`.xcresult` bundles are retained under ignored
`local/recovery-completion/ipad/`; the original baseline archive is under
`local/recovery-implementation/ipad-preview-0309/`. Only bundle/display identity
differs from the normal application. Signature verification and installation
pass. Installs reuse the same Preview container without clearing its data.

The existing TestFlight `dev.pyble.pyble` installation remains `0.2.0 (6)`.
Preview acceptance does not establish a TestFlight-delivered upgrade. Before
these runs, a private backup of Preview application support passed SQLite
`integrity_check` and contained zero draft rows and zero content bytes. No
storage reset established that initial state.

## Recovery observations

The [operator recipe](01_Operator_Recipe.md) and
[normative evidence matrix](../../../specifications/App/current-draft-recovery.md#7-required-evidence-before-acceptance)
remain authoritative. A receipt marked partial below contributes only its
completed assertions; its later failure is retained separately.

| Procedure | Actual result and receipt |
|---|---|
| P01/P04/P06: offline startup and Restore | `offline-restore-radio-target`: terminate the same app/container, explicitly verify Wi-Fi and Bluetooth off, relaunch, inspect exact filename/source, Restore into the disconnected local panel. No connection is required. Original radios restored |
| P02/P03: exact named checkpoint | `classic-unicode-checkpoint`: `/q0309i_e54a/recovery.py`, exact `# café λ` followed by `print(271828)`; native text-value assertion and **Saved locally** after manual checkpoint |
| P05: unresolved decision | Discard Cancel preserves the exact preview. In `classic-discard-loop`, backgrounding to Settings and returning preserves the unresolved recovery prompt |
| P07: editing/lifecycle | Real native typing and multiple acknowledged checkpoints survive process termination/relaunch. On final `bef67bd`, `settled-native-input` injects the complete `print(424242` batch after the full keyboard is visibly settled, obtains exact `print(424242)`, checkpoints and restores it after termination without a board write. Continuous-edit debounce behavior remains covered by automated tests; no unacknowledged final keystroke is promised durable |
| P08: explicit Discard | `classic-discard-loop` completes Cancel, confirmed Discard and terminate/relaunch assertions: the next launch shows Scan without a recovery prompt. Its later folder-tap failure does not erase these observations |
| P09: empty named draft | `classic-readback-empty`: deliberately created `empty.py` checkpoints and returns as a named empty recovery copy; distinct from an empty untitled slot |
| P10: actual Save/Run target | `classic-target-cancel`: both current destination `/recovery.py` and distinct write/write-and-run effects are shown; Cancel retains the draft. The board is deliberately connected after Restore |
| P11/P12: Files destination and completion | `classic-upload-run`: move to the owned folder, cancel Upload, confirm its actual folder/file target, then explicitly confirm Run and observe `271828` with Finished. Real clear/Open readback verifies the Unicode source. Session/epoch mutation races remain covered by automated tests |
| P13: replacement guards | `blocks-handoff-recovery` cancels Blocks handoff over Unicode before later confirming. `c3-replacement-finite` and its resume cancel Editor New and board Open over the meaningful generated draft; source remains exact |
| P14 / DR-T12: generated text | `blocks-handoff-recovery`: ordinary Hello example generates exact `print('Hello, PyBLE!')` plus trailing newline, guarded adoption into `blocks.py`, acknowledged checkpoint and actual process termination/relaunch recover that exact text. The next process's Blocks surface offers a new example; no workspace graph restoration is inferred |
| P15 / DR-T13 | Widget/localization/semantics and 2× text coverage is recorded in source validation. Physical native keyboard checks are below. Native XCTest accessibility labels/values are observed; this is not a claim of audible VoiceOver speech or a complete human gesture evaluation |

The offline panel intentionally previews restored text before connection; the
normal Editor shell appears after an explicit board connection. An early final
candidate helper incorrectly expected an Editor text field while still on that
panel. The panel held the exact recovered text; the corrected connected check
passed. That selector error is not a restoration failure.

## Keyboard defects and physical regression

Three separately tested repairs address measured failures: landscape overflow,
native WebView keyboard dismissal, and the iPad input-palette transition.
In the last case UIKit reported an off-screen end frame after **Hide keyboard →
Keyboard → Show Keyboard**, while `keyboardLayoutGuide` reported the actual
498-point occlusion. Private logging established that mismatch; its instrumented
binary is excluded from acceptance and distribution.

The final native guide observer supplies the missing geometry, and Flutter uses
the larger valid platform/native inset without summing them. A remaining input
palette is a real occlusion; hiding the full keyboard does not imply zero inset.
Ending editing returns to ordinary safe-area layout.

| Final `bef67bd` receipt | Actual observation |
|---|---|
| `guide-editor-connected` | Existing exact generated checkpoint restores; C3 Ready; the normal Editor receives native focus |
| `guide-editor-palette` | Full keyboard shown, hidden and shown again through the native palette. Editor text-field height remains 218 points with the full keyboard; console Expand occupies y=478…526 above it. Expand is hittable, hides the actual native keyboard, restores the 555-point normal Editor viewport and preserves exact text. Screenshots and accessibility frames agree |
| `guide-blocks-palette` | Native Blocks field repeats Hide → Show Keyboard; Expand remains hittable, dismisses the keyboard, and retains exact `Hello, PyBLE!`. Cancel closes the field without changing its block; returning to Editor retains the exact generated text |

The final source has 984 passing ordinary tests, including guide geometry,
observer lifecycle and stale-generation coverage. iOS profile compilation and
repository analysis/source gates pass. Automated coverage does not replace the
physical input-palette sequence above.

## App-only board matrix

Immutable program verification identifies the selected firmware: classic ESP32 uses
published `c8f549ee`; S3, Waveshare S3, C3 and Pico use retained observer
`96497b9`. Exact component hashes and the source-impact assessment are in the
[execution record](00_Execution_Record.md) and
[release readiness](06_Release_Readiness.md). No firmware was reflashed for this
app qualification. Identical relevant runtime/build-driver source does not make
the two firmware artifacts byte-identical.

| Row | Physical profile / suffix | Installed app | Result / receipt |
|---|---|---|---|
| Q01 | `esp32-4mb` / 8C9E | `e54a78a` | Pass: ordinary discovery/Ready, named Unicode edit/save, stdout/Finished, tight-loop Run/Stop→Idle, exact clear/Open readback, disconnect/reconnect continuity and recovery/current-target cases. Receipts `classic-*`; helper failures retained below |
| Q03 | `esp32-s3-n16r8` / 5646 | `bef67bd` | Pass: ordinary Ready; owned finite source Save/Run→`424242`/Finished; tight-loop Run/Stop→Idle; true clear/Open exact readback of both files; disconnect/reconnect continuity; acknowledged `loop.py` checkpoint, terminate/relaunch and exact Restore. Receipts `matrix-5646*`; initial failed attempts retained |
| Q05 | `waveshare-esp32-s3-lcd-147b` / DA86 | `bef67bd` | Pass: all common finite-output/Stop/readback/reconnect checks and named checkpoint/relaunch/Restore in one `matrix-da86` run |
| Q07 | `esp32-c3-4mb` / C81A | `01a7ac8` | Pass: ordinary Ready, owned `blocks.py` upload/Hello stdout/Finished, genuine clear/Open readback, tight-loop and print-flood Stop→Idle, connection remains usable, reconnect continuity and subsequent bounded Hello run. `c3-replacement-finite-resume`, completed `c3-readback-stops` assertions, `c3-stop-flood-now`, `c3-final-matrix` |
| Q09 | `rpi-pico2-w` / 3DCB | `bef67bd` | Pass after retained initial disconnect: `matrix-3dcb-retry` completes finite-output/Stop, true clear/Open readback, reconnect continuity and exact named checkpoint/relaunch/Restore |

Earlier rows retain their actual installed identities. Later native/layout
changes do not alter transport, storage or Stop behavior, but final keyboard
checks are separately required. These UI Stop observations establish neither a
fresh C3 firmware qualification nor a sub-500-ms wire-level timing result.

## Retained failures and cleanup

| Observation | Classification / disposition |
|---|---|
| XCTest Touch ID authorization timeout | Owner completed the prompt; normal-app native automation subsequently runs. Resolved operator-access dependency |
| Newly installed helper launch denied while offline | Developer-certificate verification occurred before the test body. Retry entered offline mode within one running helper, verified both radios and passed; original radios restored |
| Native helper folder/file selector and terminated-app screenshot errors | Corrected using observed controls and device-screen capture; exact retries retained. No passing result inferred from preparation |
| C3 flood stdout prefix assertion | Existing Hello output preceded flood output in the same console label. Stop immediately returned Idle; retry cleared the console first and passed the intended stdout/Stop/readback/reconnect/bounded-run checks |
| Rapid synthetic typing and initial file-row attempts on S3 | One batched XCTest `print(424242` input produced `print(24242)` and failed the exact oracle before Save. Waiting for the visible keyboard and observing automatic `print()` insertion before injecting digits produced exact text; this is a controlled retry, not a code fix. Source review found no digit-normalization rule; the suspected platform/controller feedback timing was not proven. A further final-candidate control injects the original whole batch after the keyboard is fully visible and settled and passes exact text plus checkpoint/relaunch/Restore (`settled-native-input`); the failure is not reproduced under that controlled focus condition. Two initial file-Open assertions also timed out; explicit retries obtained exact source after a genuine empty Editor, and their failures remain retained |
| Early typing before async New-file GET completed | The editor epoch guard retained the newly typed buffer; no stale GET replaced it. A disposable classic `/untitled.py` was consequently written by the explicit Save/Run; this exact owned file was backed up and removed during coordinated cleanup |
| Initial Pico connection | Reached Ready, then disconnected before folder creation. A continuation incorrectly assumed the old connected layout and selected the Waveshare scan row; its Name-field assertion failed before any write. Waveshare cleanup had already finished. The corrected retry explicitly disconnected, rescanned, checked Pico Ready and passed the complete row; no firmware or transport fix is claimed |
| iPad input-palette geometry | Product defect reproduced with measured native frames; final repair and physical results above |

Only disposable qualification files/folders are written. The classic fixtures
and their CRC-verified backups/cleanup are recorded with the
[Android continuation](05_Android_Acceptance.md); pre-existing root entries are
preserved. The S3, Waveshare and Pico follow-up fixtures have likewise been CRC-verified,
backed up and removed with unrelated root entries unchanged. C3 fixtures remain
tracked privately for cleanup after the final Android continuation. Raw captures, binaries, database backups and helper
sources remain ignored. No user project or original store installation is reset.

This report establishes only its recorded observations. Final admission,
production package identity and channel delivery are tracked in
[release readiness](06_Release_Readiness.md); independent pilot and Ready-program
obligations remain separate.
