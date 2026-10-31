<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Bounded recovery — platform engineering observations

| Field | Record |
|---|---|
| Date / operator | 31 October 2026, Asia/Bangkok; automated operator on the maintainer's Mac |
| Source | App source candidate `0.3.0+9`; final bounded source `90311f3` (including storage preflight fix `8657e5a`); earlier source snapshots identified below |
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

## Final bounded candidates and iPad native execution

| Evidence | Result |
|---|---|
| Final ordinary suite | 972 tests pass; full analysis clean after the metadata byte/count preflight fix |
| Final Android production-entry APK | `artifacts/pyble-0.3.0-9-recovery-final.apk`; SHA-256 `957982f5acec969f8003d04b2d6444eecbba9af26b7392d760badb5be5d6bd0e`; installed on Lenovo, version `0.3.0 (9)` |
| Final runtime source | Copied `lib/` is byte-identical to `90311f3`; only copied native bundle/application identities differ. Final source manifests retained |
| iPad route | Signed **profile** mode launches through `devicectl` using current device settings; this bypasses the unavailable Flutter debug/JIT route |
| iPad seed | All seed assertions and repository close completed; bounded test receipt says `phase=seed`, `passed=true`, `platform=ios`, completion `2026-10-31T04:06:31.192251Z` |
| iPad process boundary | Seed process 5826 killed with `devicectl device process terminate --kill`; subsequent process enumeration confirms it absent |
| iPad verify | Final bounded candidate installed into the same isolated container and launched separately; all exact-text, dirty/unbound, explicit Restore and declined-board-write assertions completed; receipt `passed=true` at `2026-10-31T04:08:45.983001Z` |
| iPad database integrity | Seed/verify closed files both SHA-256 `d3c028da3b7439503b9a6f54e5ab2520d60f9a4a7ca7af59a62b0d3b841587b6` |
| Retained iPad profile archives | Seed with receipt: SHA-256 `6d707ede856b1cd8de9c4ccd383b60b5ba86fe52c2d302d5c83e16edddc10514`; verify: `9588a9e94a9eb484b9408a8e86f61e0c12c8fadcc5147caf970f72f3411bcb87` |

Receipts are written only after assertions and store close, are removed before
rerunning that phase, and contain bounded test metadata rather than user source.
The seed preceded the final corrupt-metadata bound; verify used the new bound
against that same valid v1 store. This proves compatible valid-state reopening.
These native profile harness checks do not claim the full iPad production UI or
physical BLE board scenarios have passed.

## Five-board discovery observation

The owner reported all five boards connected. A fresh Lenovo scan in the final
qualification app shows `PyBLE-DA86`, `PyBLE-3DCB`, `PyBLE-5646` and `PyBLE-C81A`.
The [historical hardware record](../../../testing/tutorial-five-board-screenshot-provenance-2026-08-28.md)
associates the absent `8C9E` label with classic ESP32, and `3DCB` with Pico 2 W.
Names are contextual labels, not new identity or authorization evidence.

Source inspection found no four-result limit: the adapter filters by PBLE
service UUID, the accumulator retains distinct OS device IDs and the list
renders the complete hit count. Both ESP/Pico agents resume advertising after
disconnection. An active connection elsewhere or absent firmware advertising
can explain a missing board, but neither cause has yet been established for
`8C9E`. USB enumeration of its CP2102 adapter alone does not prove agent health.
No board was reset, flashed or sent a command during this diagnosis.

## Remaining release evidence

Complete the iPad production interaction matrix, remaining Android interaction/interruption rows,
explicit harmless physical board Save/Run/Files destination consent, applicable
Blocks handoff checks and the selected release matrix. Preserve candidate
provenance and report every unrun row. Participant follow-up and the unfinished
M-01/SG0 pilot work remain separate from engineering recovery evidence.
