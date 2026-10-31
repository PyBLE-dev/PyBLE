<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Bounded recovery — platform engineering observations

| Field | Record |
|---|---|
| Date / operator | 31 October 2026, Asia/Bangkok; automated operator on the maintainer's Mac |
| Source | App source candidate `0.3.0+9`; integrated source `4479ff6a02e04d1b8e28a01cd70dfa702e8fb218` |
| Scope | Local storage, explicit offline recovery and platform builds; partial evidence toward DR-T02/03/07/13/14 |
| Acceptance | Engineering observations only; full physical board consent, interruption/interaction matrix and release qualification remain pending |
| Raw evidence | Ignored `local/recovery-implementation/`: commands/results, source manifests, screenshots/UI dumps, retained checkpoint and APK; raw captures are not committed |
| Review | [Execution record](00_Execution_Record.md), [operator recipe](01_Operator_Recipe.md), [draft PR #40](https://github.com/PyBLE-dev/PyBLE/pull/40) |

## Isolation and artifact identity

The installed store applications were preserved. Qualification used copied app
sources and a separate application identity. Android used
`dev.pyble.recoveryqualification.integrationtest`; iOS used
`dev.pyble.recoveryqualification`. These are engineering identities, not new
production packages or store submissions. Only the ignored copied projects had
bundle/application IDs and the Android namespace changed.

The Android production-entry build uses `lib/main.dart` and the integration
flavor/debug signing. All Dart runtime source matches integrated `4479ff6`
except two subsequently removed redundant imports in `app/shell.dart` and
`blocks/blocks_document.dart`; the exact build source manifest is retained.
Neither that relationship nor the passing checks establish release-signature
or whole store-binary equivalence.

| Artifact / record | Identity |
|---|---|
| Retained Android production-entry APK | `artifacts/pyble-0.3.0-9-recovery-qualification.apk` beneath the ignored evidence directory |
| APK SHA-256 | `1492d55e1cb9583afcbe1c0c083365ad16044722fe267814751ac0d90b9155c4` |
| Android version / SDKs | `0.3.0 (9)`; min SDK 24, target/compile SDK 36 |
| Earlier verify-harness APK hash at execution | `da234794379dc4b3ed249481a304d9891b4eda61020b802b111a57f7b56bbcab`; that build output was subsequently replaced by the retained production-entry APK |
| Seed/verify closed database SHA-256 | `a2e9027dbc29cd743b28bdcaf49e90d876c2a35b37b94253304c45fa0b2f3ac4`; identical after separate-process verify |
| Build toolchain | Flutter 3.44.1, Dart 3.12.1, macOS 27.0.1 on Apple Silicon |

## Lenovo TB-J616X — Android 12 / API 31

| Step | Actual execution and result |
|---|---|
| Availability | Device reconnected by the owner and recognized by ADB/Flutter over USB |
| Seed | Real platform Application Support database received exact Unicode text, filename, origin context and committed generation; native integration harness passed |
| Process boundary | Seed app retained with `flutter drive --keep-app-running`; exact isolated package then force-stopped through ADB. Default Flutter drive cleanup uninstalls the app, so an initial non-retained attempt was excluded from restart evidence |
| Verify | Verify-phase APK installed over the same isolated package/container and launched separately; exact text restored dirty/unbound and declined board Save sent no PUT through the recording seam; harness passed |
| Integrity | Closed database hash after verify equals the seed checkpoint hash |
| Production entry | Normal `lib/main.dart` candidate launched with an explicitly seeded disposable `pyble.sqlite`; startup displayed filename, real checkpoint time, exact Unicode text and Restore/Copy/Discard controls |
| Explicit Restore | Restore selected through the native UI; app displayed Disconnected, Saved locally and the exact current-text preview. No board was selected or connected |
| Relaunch | Package force-stopped, absence of its process checked, then launched afresh. After startup settled, Restore/Copy/Discard were offered again; no implicit restoration |
| Large text | System font scale temporarily set to 2.0; startup preview, source and all actions remained visible/reachable in landscape. Screenshot reviewed. Original font scale restored in a `finally` block |
| Clipboard | No Copy action was invoked during the native UI observation; source was not copied automatically |

The harness uses a recording connection. It proves native local storage and
cancellation behavior, not physical PBLE/1 traffic. The production-entry
observations prove the visible disconnected recovery path; no claim of a
connected board overwrite/run test or packet capture is made. Keyboard and
screen-reader regressions have automated coverage; full physical assistive
technology and P01–P15 coverage are still outstanding.

## iPad16,10 — iPadOS 26.6.2

| Step | Actual execution and result |
|---|---|
| Discovery | Initially wireless, then connected over USB by the owner and listed by Flutter/devicectl |
| Release compile | `flutter build ios --release --no-codesign` succeeded in the isolated copied project |
| Signed harness compile | `flutter build ios --debug --target integration_test/draft_recovery_device_qualification.dart --dart-define=PYBLE_RECOVERY_TEST_PHASE=seed` succeeded using an available development identity |
| Installation | Direct `devicectl` installation of the signed isolated harness succeeded; the existing TestFlight application was preserved |
| Launch | Both wireless and USB Flutter attempts reported that Developer Mode must be enabled; no successful harness or production-UI execution is claimed |
| Next action | Owner enables Settings → Privacy & Security → Developer Mode, restarts/confirms if required, unlocks and reconnects; then execute seed → terminate → verify and P01–P15 as applicable |

A signed build is build evidence. It does not establish successful installation,
execution, offline restoration, TestFlight availability or physical BLE behavior.
Any further install/launch result must be recorded separately.

## Remaining release evidence

Complete iPad execution, the remaining Android interaction/interruption rows,
explicit harmless physical board Save/Run/Files destination consent, applicable
Blocks handoff checks and the selected release matrix. Preserve candidate
provenance and report every unrun row. Participant follow-up and the unfinished
M-01/SG0 pilot work remain separate from engineering recovery evidence.
