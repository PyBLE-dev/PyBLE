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
| Review | [Execution record](00_Execution_Record.md), [operator recipe](01_Operator_Recipe.md), [merged PR #40](https://github.com/PyBLE-dev/PyBLE/pull/40) |

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
| Launch | Wireless and USB Flutter debug attempts reported that Developer Mode must be enabled; subsequent signed profile harness execution succeeded as recorded below |
| Next action | Complete production UI/board P01–P15 as applicable. Profile seed → terminate → verify has passed using current settings; Developer Mode remains an optional prerequisite for the separate debug/JIT route |

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
disconnection. The live classic ESP32 was subsequently identified through its CP2102 ROM
interface: ESP32-D0WD revision 1.0, base MAC ending `8C:9C` (Bluetooth suffix
`8C9E`). A 115200-baud read of the first 256 KiB matches the retained c8f549ee
0.6.1 install prefix at offset 0x1000. The initial 460800-baud attempt had a
framing error; no flash write occurred. Exact complete-image equivalence is
not inferred from a prefix.

A 45-second controlled startup trace then captured:
`PyBLE workspace recovery is required; reconnect by USB.`, followed by the
MicroPython 1.28.0 / PyBLE 0.6.1 banner and REPL. This confirms the workspace
mount/refusal path, which deliberately withholds BLE agent startup. It explains
the absent fifth advertisement. Short early captures missed the later message;
the guard scans the complete 2 MiB workspace before refusing it.

Retained September qualification records for the same board contain an
intentional invalid-media fixture and a failed acquisition before its planned
recovery. Its fixture hash is preserved separately; this history alone does not
prove current contents. The fresh complete current workspace backup exactly matched that refusal fixture. The verified original owner backup
and its valid LFS2 workspace remain intact, with identical partition geometry.
ROM reads and startup tracing involved controlled resets. The verified valid pre-test workspace was then restored only to its original region, and the next scan shows all five boards. See the [recovery report](03_Classic_ESP32_Workspace_Recovery.md) for backups, hashes, offline inventory and the verified write.

## Remaining release evidence

Complete the iPad production interaction matrix, remaining Android interaction/interruption rows,
explicit harmless physical board Save/Run/Files destination consent, applicable
Blocks handoff checks and the selected release matrix. Preserve candidate
provenance and report every unrun row. Participant follow-up and the unfinished
M-01/SG0 pilot work remain separate from engineering recovery evidence.

## Lenovo production workflow on recovered classic ESP32

The final production entry connected to `8C9E` and showed **Ready**, runtime
`esp32` and agent **0.6.1**. The initial Editor was empty. A disposable
`print(123)` draft was entered, explicitly checkpointed and shown **Saved
locally**. The app was force-stopped and relaunched; startup preview offered the
exact text before any connection. Explicit Restore displayed it while
Disconnected. Only then was the classic board selected again.

Board Save displayed the exact `/untitled.py` destination and explained that
upload does not run code. Cancel dismissed that choice. A subsequent explicitly
confirmed upload succeeded and cleared board-dirty state while local status
remained separate. Run requested separate upload-and-run consent for the same
current destination. On confirmation the board console returned `123` and
**Finished**, and the connection returned Ready. Files refresh showed the
10-byte test file. The transfer stayed on the selected physical board; this is
an observed happy path, not a physical board-swap race test.

Raw UI XML records under the ignored evidence directory include
`lenovo-live-relaunch-prompt.xml`, `lenovo-live-restored-offline.xml`,
`lenovo-real-save-consent.xml`, `lenovo-real-run-consent.xml` and
`lenovo-print-run-result.xml`. The automated recording seams remain the evidence
for exact zero-verb cancellation/race assertions; no radio packet capture was
claimed for the physical cancellation.

Afterward only the created 10-byte `/untitled.py` test file was explicitly
deleted, with its exact-name confirmation. Existing directories were preserved.
New then committed the empty local slot; the disposable Editor text was cleared
and its saved-local status retained. A fresh launch after that tombstone showed no stale recovery prompt or test text, and the final disconnected scan again showed all five boards.

The iPad's isolated harness was terminated and removed after its receipts,
checkpoint files and signed archives were retained. The original TestFlight
application remained installed and was brought forward without terminating it.
The separate Lenovo production-entry candidate remains available for review;
its test draft and board test file were cleared as described above.

## Post-merge iPad normal-app deployment — 31 October

After PR #40 merged at `6f5b3ea`, the normal `lib/main.dart` entry point was built
in signed profile mode and installed under the isolated
`dev.pyble.recoveryqualification` identity with the display name **PyBLE Preview**.
This replaces the earlier test-only harness route with the normal candidate UI;
the existing TestFlight installation remains a separate app.

| Evidence | Observation |
|---|---|
| Source | All 100 copied `lib/` files, pubspec and lockfile match merged source; only the isolated native application identity and display name differ |
| Artifact | Retained `ipad-preview-0309/PyBLE-Preview-0.3.0-9-profile.app.zip` beneath ignored `local/recovery-implementation/`; SHA-256 `c91bc6f7e14f421a528668bd3723e3f965d55f79f11ea90fec707a8fb15a4d1a` |
| Build and signature | Normal `lib/main.dart`, `0.3.0 (9)`, profile mode; no qualification-phase Dart define; strict code-signature verification passes |
| Installed apps | PyBLE Preview `0.3.0 (9)` and original PyBLE TestFlight `0.2.0 (6)` both present |
| Launch and discovery | Normal disconnected scan UI launches and displays `5646`, `C81A`, `DA86`, `8C9E` and `3DCB` |
| Evidence scope at deployment | Installation/launch/discovery only; no board connection or write performed during this deployment checkpoint |
| Raw receipt | `ipad-preview-0309/deployment-observation.json`, source manifest, installed-app metadata and captures retained privately |

This observation explains the two iPad icons and versions. It supplies no new
TestFlight availability claim and does not by itself satisfy the normal-app
recovery/board-consent scenarios in DR-T14.
