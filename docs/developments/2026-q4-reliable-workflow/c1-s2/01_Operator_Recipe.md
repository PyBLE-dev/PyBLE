<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# C1-S2 — scoped recovery operator recipe

| Field | Record |
|---|---|
| Status | Prepared 31 October 2026; candidate execution/reproduction and final results remain pending |
| Applies to | Bounded current-text candidate `0.3.0+9`, PYB-006.2; no full project/Blocks recovery claim |
| Source | [Normative contract](../../../specifications/App/current-draft-recovery.md), [S1 inventory/cost model](../c1-s1/04_Validation_Inventory_and_Operator_Recipe.md) |
| Result owner | Actual operator records name, date, immutable candidate/artifacts and raw-evidence location; no absent owner is invented |
| Public result | [Execution record](00_Execution_Record.md); private device IDs, source captures and raw screenshots stay in ignored local evidence |

## Setup and artifact binding

| Prerequisite | Required record / check |
|---|---|
| Source and app | Exact source SHA, clean/dirty state, `pubspec` version/build, platform build command, retained artifact SHA-256 and installed identity; do not identify a candidate solely by a branch name |
| Devices | Actual Android model/API and iPad model/iPadOS; available application installation/signing route; accessible persistent storage |
| Current access | Both Lenovo and iPad are connected. The Android normal-entry candidate runs locally; signed iPad profile builds install and launch through `devicectl`. The Flutter debug/JIT route remains a separate limitation, not a blocker for profile-mode physical execution |
| User data | Preserve existing store installations and their data. Use a separate qualification identity/container when running test applications; never uninstall or clear app data to manufacture a passing recovery result |
| Board-backed steps | Exact supported board profile, firmware identity, harmless setup and explicit destination; reserve a disposable user file that cannot affect startup or the PyBLE agent |
| Evidence | Ignored local folder with commands, timestamps, outcome logs and artifact hashes; publish only reviewed redacted results, not device identifiers or user source |
| Connectivity | Keep network/BLE unavailable during local startup/Restore checks; connect deliberately only for the later target-consent steps |

A remembered September installation is not this candidate's evidence. An
emulator, recording connection or unit fake cannot replace required physical
observations. Do not flash a different firmware merely to exercise this
app-only storage feature; use a recorded applicable baseline and the selected
affected matrix.

## Automated checks

Run commands from `app/` with the repository's pinned Flutter toolchain. Preserve
exit codes and the exact integrated SHA. Component runs aid diagnosis; the
integrated suite is authoritative for the combined candidate.

```sh
flutter pub get --enforce-lockfile
flutter analyze
flutter test test/data/draft_repository_test.dart
flutter test test/unit/draft_recovery_test.dart test/unit/editor_document_test.dart
flutter test test/unit/recovery_board_races_test.dart
flutter test test/widget/recovery_gate_test.dart test/widget/recovery_panel_test.dart
flutter test
```

From the repository root, run the applicable source/document/dependency gates:

```sh
tools/ci/no_leak.sh
tools/ci/import_boundary.sh
tools/ci/locale_parity.sh
tools/ci/spdx_lint.sh
python3 tools/ci/docs_links.py
```

Use the existing Drift schema fixture/export tests to verify schema v1. A future
schema bump needs explicit forward migration and old/new fixtures; never invent
a persisted pre-recovery release. Local full/corrupt/I/O fault injection is
storage evidence, distinct from a board PBLE `ENOSPC` response. Child-process
SIGKILL tests demonstrate host database behavior, not iPad/Android OS lifecycle.

## Physical current-text workflow

Run the following on **each** required physical candidate. Record actual
pass/fail/not_run/blocked and the observed state; repeat affected rows after a
source/artifact change. Retain the original failure before any repair/rerun.

| Step | Operator action | Required oracle / evidence |
|---|---|---|
| P01 | Launch the recorded candidate with network/BLE unavailable | Storage choice/error resolves before any connection workflow; no permission/scan/board operation is required for recovery |
| P02 | Reach Editor through the normal existing workflow; enter a disposable named draft containing whitespace, Unicode comments and punctuation | Accepted text stays exact locally; board normalization is a separate explicit board-action behavior |
| P03 | Invoke **Save recovery copy** and wait for its completion | Saved-local status appears only after the matching transaction; board dirty state remains independently truthful |
| P04 | Terminate the app process using platform tooling; relaunch the same app/container without clearing data | Recovery preview shows the last acknowledged exact draft, filename and checkpoint; no implicit board/network action |
| P05 | Use Back/dismiss and return to recovery | Decision remains unresolved and durable copy remains intact; an empty Editor never overwrites it |
| P06 | Explicitly Restore while disconnected | Exact text visible locally; `dirty=true`, no active historical board target; copy/export only on explicit user action |
| P07 | Edit again; exercise normal idle/continuous editing and a pause/relaunch | Local pending/saving/saved states are truthful. A last uncommitted edit may be absent; the previous complete acknowledged checkpoint must remain recoverable |
| P08 | Relaunch and cancel Discard confirmation; then confirm Discard | Cancel retains copy/prompt; success commits an empty slot before installing a fresh buffer; next launch has no prompt for that empty untitled slot |
| P09 | Exercise a deliberately empty **named** file through checkpoint/relaunch | Empty named document remains recoverable; it is not confused with a confirmed empty untitled slot |
| P10 | Restore a draft, connect deliberately to a harmless recorded board and request Save/Run | Consent shows the actual current destination and write/run effect. Cancel sends no write/run; recovery itself never listed/probed or wrote a board |
| P11 | Request Files Upload after moving the current directory; change document/session/target while consent is pending where the harness permits | Actual `cwd/name` destination is shown; stale consent cannot authorize another target/session/revision |
| P12 | Confirm a harmless board action, then check dirty/local-copy state; reconnect to another session and act again | Only matching completion binds/clears board dirty. Recovered text still requires explicit current-session consent; no automatic upload/run |
| P13 | Try New, Board Open and Blocks-to-Editor over meaningful pending/dirty text | Captured-epoch confirmation protects current text; failed local replacement keeps it and offers Cancel or explicit volatile fallback |
| P14 | Copy generated Python from Blocks into Editor and checkpoint/relaunch | The text can recover; workspace graph/revisions/sidecars are not represented as restored by the local text slot |
| P15 | Check recovery choice/error/local panel with 2× text, keyboard and screen reader | Controls scroll/remain reachable, focus/semantics announce correctly, no technical filename/path/source is translated |

### P15 keyboard regression continuation

The 31 October device findings refine P15's existing reachability requirement.
Run the affected cases on the recorded repaired candidate; preserve each
original failure and do not substitute a mocked dismissal request for an
observed keyboard/viewport transition.

| Case | Operator action | Required oracle |
|---|---|---|
| P15-K1 | In landscape Editor, open the software keyboard, edit harmless text and expand the compact console strip | Navigation and console controls remain reachable; the keyboard actually dismisses, the console expands, and text/selection and buffered output are retained |
| P15-K2 | In landscape Blocks, edit a native Blockly field with its keyboard open and expand the console | The native keyboard dismisses, the console expands, and field text/workspace state remain intact; Flutter-only focus tests do not establish this result |
| P15-K3 | On iPad, hide the keyboard and reopen it through the keyboard palette; repeat with Editor and a native Blocks field | The visible docked keyboard leaves controls reachable above it; content is reduced by the observed overlap once and Expand can actually be tapped. Hiding the full keyboard accounts for any remaining input palette; zero keyboard occlusion is expected only after editing ends and the guide returns to its safe-area baseline |

Platform-controlled interruption before/during/after checkpoint should preserve
whole permitted old/new content. If a required phase cannot be deterministically
hit on a device, record that limitation and its host fault-test evidence; do not
claim the physical phase passed from timing alone. Use the existing safe HIL
procedures for any affected BLE/profile matrix rows.

## Additional isolated platform-storage harness

`app/integration_test/draft_recovery_device_qualification.dart` provides `seed` and `verify`
phases using the actual platform Application Support store and a recording board
seam. The phase is selected with `PYBLE_RECOVERY_TEST_PHASE=seed` or `verify`.
The qualification database is `qualification-current-draft.sqlite`, separate
from the production slot. Build/launch seed, actually terminate its process,
then build/launch verify using the same isolated application identity/container.
Record that transition and artifact identities. A successful single-process
rerun does not prove process restart. The harness verifies local storage and
cancellation with a fake board; it does not prove physical BLE behavior or the
production recovery UI, and does not replace P01–P15.

## Failure, storage and rollback boundaries

| Condition | Required handling |
|---|---|
| Read/commit timeout | After ten seconds expose Retry / Continue without recovery. Late completion cannot hydrate newer live text; do not reopen/delete storage under an active task |
| Full/permission/I/O failure | Retain live text and previous committed copy; report failed local protection and offer Retry. Export/copy only by explicit user action |
| Corrupt or unsupported store | Preserve `pyble.sqlite` and companions; offer bounded choices without reset/downgrade. Retrying must not silently overwrite either current or recovered text |
| Upgrade from volatile release | First persistence schema starts empty; no promise to recover a pre-upgrade in-memory draft |
| Downgrade | Do not write an unsupported newer schema. Retain data for a compatible app; do not delete the database as a rollback procedure |
| App removal/data clearing | Outside the guarantee. Do not use it as a recovery or acceptance step on user data |

Production storage uses the platform `getApplicationSupportDirectory()` path.
The Android manifest currently sets no app-specific `allowBackup`, custom
`fullBackupContent` or `dataExtractionRules` override. The iOS source currently
sets no app-managed backup exclusion or alternate data-protection attribute for
this database. OS backup/restore behavior therefore follows platform/user/device
policy; it is not a PyBLE backup guarantee and has not been qualified here.
PyBLE adds no app-managed remote synchronization or source telemetry. Record any
packaged settings that differ from this source before admitting a candidate.

## Recording and admission

| Evidence row | Required content |
|---|---|
| Automated | Integrated SHA, command/toolchain, exit code and result log; counts not summed across overlapping suites |
| Physical | Platform/device redacted identity, exact installed app/firmware, procedure step, expected/observed result, timestamp, operator and raw-evidence reference |
| Limitation | Exact unrun/failed scenario, concrete access/artifact/setup gap and next action; no inferred pass |
| Admission | DR-T01–14 and applicable release matrix accounted for; required failures resolved; qualified artifact identity and review recorded before publication |
| Follow-up | Participant/retention evidence remains under the S1 pilot protocol; no fake cohort, activation or named human sign-off |

Two representative recovery runs do not qualify five firmware profiles or award
PyBLE Ready. This recipe is complete as a prepared instruction set; execution,
correction from actual observations and second-operator reproduction remain
separate evidence obligations under PYB-009.

The manual harness is deliberately separate from the single CI Android smoke
entry point. Use `--keep-app-running` with `flutter drive` for the seed phase:
its default cleanup uninstalls the app and removes its private data. Force-stop
that exact isolated package before the verify phase, retain both artifacts, and
verify the second installation preserves the same data container. Never run a
qualification harness over a user's installed store app.

For iOS where Flutter's debug launch is unavailable, a signed profile build of
this same harness can launch through `devicectl`. Copy the phase's result JSON
from app-private Application Support and require `passed=true`; its receipt is
written only after every assertion and repository close. Kill and verify absence
of the seed process before installing/launching verify into the same container.
This is native harness evidence, not a substitute for production UI/physical BLE
checks. See the [actual platform report](02_Platform_Qualification.md).
