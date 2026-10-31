<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# App 0.3.0 (9) — release readiness and channel handoff

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | App-only bounded current-text recovery; existing Play open-testing and TestFlight channels |
| Runtime source | Recovery baseline plus landscape-keyboard repair at `e54a78acf32e7ea26166a60d66573fdf9e697ad4` |
| Build checkout | Release worktree `e8aeddd8ddbda85293dcca72ad524823bd5ae66a`; app tree `d0f2a464e9886c8451a0cb046123973095f246c6`, verified identical to the runtime baseline |
| State | Production Android and iOS rebuilt cleanly with the keyboard-layout repair; packaging and the bounded Android 16 KiB runtime smoke pass. Physical acceptance and final release admission remain outstanding |
| Local evidence | Ignored `local/recovery-completion/release/candidate-e54a78a/`: build/check logs, source/artifact manifests, runtime evidence and retained signed binaries |
| Public copy | [Prepared release packet](../../../publication/app-0.3.0-build-9-release-packet.md); no submission or availability claim |

## Gate selection

This increment changes the app, not the firmware bytes. The
[qualification inventory](../c1-s1/04_Validation_Inventory_and_Operator_Recipe.md#1-evidence-and-gate-selection)
requires affected app workflows on the five existing exact profiles and both
platforms for that compatibility claim. An unchanged firmware is a named input
with its own historical qualification limits. This work does not require or
claim a new firmware release, fresh firmware OI-1 qualification or a Ready badge.

| Gate | Required evidence | Current disposition |
|---|---|---|
| M-02 recovery acceptance | All DR-T01–14 required evidence, including representative physical generated-text recovery and both platform offline/current-board-consent records | Reconcile against the [execution record](00_Execution_Record.md) and actual device reports; installation/scan alone is insufficient |
| App regression | Accepted source contract, red/green history, locked dependencies, ordinary tests, pinned goldens, platform builds and repository gates | PR #40/post-merge CI passed historically; the keyboard repair records 974 ordinary Flutter tests, 25 shell widget tests and clean analysis/source gates. Integrated-candidate CI and final physical acceptance remain separate |
| Five-profile app compatibility | Q01–Q10 below with exact app/firmware identity, actual observations and retained failures | Final complete candidate-bound matrix not yet established |
| Production packaging | Android upload signer/AAB/APK/native alignment; iOS distribution export/IPA validation; capability parity | Android and iOS checks below pass for the repaired source and exact retained artifacts |
| Release review | Frozen artifact identity, resolved mandatory failures, supported scope, privacy/dependency review and recorded acceptance | Not yet admitted |
| M-05 channel delivery | Actual upload/processing/review/availability, followed by store-delivered installed identity and upgrade/launch checks | No upload or new channel delivery established by this preparation |

Pilot participation and useful-return evidence remain separate from maintenance
release admission. A second operator is required for the optional reproduction
claim, not for an unrelated app release. Neither distinction waives mandatory
physical or packaging evidence.

## Required app compatibility rows

| iPad row | Android row | Exact profile | App checks |
|---|---|---|---|
| Q01 | Q02 | `esp32-4mb` | Common workflow plus affected recovery |
| Q03 | Q04 | `esp32-s3-n16r8` | Common workflow plus affected recovery; do not infer the profile from the `esp32-s3` chip string alone |
| Q05 | Q06 | `waveshare-esp32-s3-lcd-147b` | Common workflow plus affected recovery; keep its exact-board/image identity distinct from generic S3 |
| Q07 | Q08 | `esp32-c3-4mb` | Common workflow plus affected recovery and real-UI tight-loop/print-flood Stop; see scope below |
| Q09 | Q10 | `rpi-pico2-w` | Common workflow plus affected recovery on each physical platform; no new full GP2 qualification inferred |

Each common row includes ordinary service-filtered discovery/HELLO, editing and
saving a harmless file, Run/stdout/terminal state, Stop, exact file readback,
disconnect/reconnect and workspace continuity. Retain the selected candidate's
affected lifecycle/recovery scenarios. Record the actual result of every row;
a scan result or one platform cannot stand in for another row.

The [C3 contract](../../../specifications/firmware/ports/esp32-c3-4mb.md#c3-g5--real-app-hil-on-both-platforms-frozen)
and inventory require tight-loop and print-flood Stop through the real UI on
both platforms. The full C3-G5 firmware qualification also requires the C3-G2
wire oracle: exactly one matching `RSP{OK}` before `RUN_STATE(idle)` in less
than 500 ms from complete STOP submission, a usable connection and a subsequent
bounded run. UI observations alone cannot prove that latency or a complete
C3-G5 pass.

The contract's dated status clarification scopes those frozen qualification
gates to a fresh automated-qualified C3/candidate claim. Under the inventory's
app-only scope, this storage/layout increment does not automatically require a
new firmware qualification or fresh wire-latency capture. Impact review found
`app/lib/ble/` and `app/lib/pble/` unchanged between `8dde8d6` and the repaired
runtime baseline; the Run controller's Stop implementation is also unchanged.
Keep fresh UI workload results, existing firmware provenance and any timing
claim distinct. No artifact-bound v0.6.1 timing receipt was established by this
preparation; the historical v0.6.0 qualification and incomplete published
v0.6.1 automated HIL retain their original limits. No new timing pass or arbitrary
repetition count is inferred.

## Prepared Android production artifacts

Both builds use normal `lib/main.dart`, production flavor and the established
owner upload key. Secret values were obtained from the existing local secret
manager and never written into source or logs.

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `PyBLE-0.3.0-build-9-production-release.aab` | `6fe609a2ebfb925bbffe2662d64a24b4b9bfdb8b5b39ee3fde6077f3cf8fba73` | 64,413,036 |
| `PyBLE-0.3.0-build-9-production-release.apk` | `71b99f8312c298693e6a8ed1aaa9fc4dc960ac6371504fdfec81152873f67ef8` | 66,439,954 |

| Check | Actual result |
|---|---|
| Package and version | `dev.pyble.pyble`, `0.3.0`, version code `9` |
| SDKs / ABIs | Minimum 24, target/compile 36; `arm64-v8a`, `armeabi-v7a`, `x86_64` |
| Signing | AAB JAR verification and APK signature verification pass; certificate SHA-256 matches the retained owner certificate `DCA95C5060CDF4936F19FD8C3212A871C223E2BA3FB67B6226179AFFDA62DD57` |
| Bundle | Official bundletool 1.18.3 validation passes; tool digest checked against the retained verified digest; configuration declares `PAGE_ALIGNMENT_16K` |
| Native libraries | All 12 packaged shared objects have every ELF LOAD alignment at least 16 KiB, including `libsqlite3.so` and `libdartjni.so` on all three ABIs |
| APK alignment | `zipalign -c -P 16 -v 4` passes |
| Permissions | Expected BLE, legacy location, Internet and AndroidX signature permission; no new authored platform permission |
| Runtime page-size check | Production APK launched on the official API 36 Google APIs 16 KiB arm64 emulator; kernel `PAGE_SIZE=16384`, About `Version 0.3.0 (9)`, bundled native SQLite mapped from the APK, and existing schema v1 reopened successfully; installed APK bytes match the recorded artifact hash |

The 16 KiB runtime observation also force-stopped and relaunched the same
installed package without data clearing. The normal disconnected screen
returned without a fatal exception or native-library load error. The database
created by the earlier `6f5b3ea` production candidate and its WAL reopened with
`integrity_check=ok`
and the expected `projects`, `project_files` and `settings` tables. This is a
native packaging/startup smoke, not a physical BLE row or the full recovery
acceptance matrix. The SQLite database's own page size is independent of the
operating-system memory page size. The emulator uses Google APIs 16 KiB arm64
API 36 image revision 7; its fingerprint and private UI captures are recorded
with the candidate manifest.

The first local invocation incorrectly used `--no-pub` after fresh `pub get`,
leaving the integration-test plugin in a generated Android registrant. Its
failed log is retained. Repeating the canonical CI production commands,
which allow Flutter to regenerate release plugin metadata, built both artifacts
successfully without a source change.

A later incremental rebuild after the keyboard repair regenerated AOT inputs
but reused stale Gradle merged/stripped native libraries. Comparing packaged
`libapp.so` against current build inputs exposed the mismatch; those artifacts
were rejected and retained under `rejected-stale-gradle-e54a78a/`. Running
`flutter clean` and both canonical production commands rebuilt the current
artifacts above. Their packaged AOT libraries match current stripped outputs
on all three ABIs. The earlier `6f5b3ea` artifacts remain historical evidence
under `artifacts-6f5b3ea/`; they are not the repaired release candidate.

The APK uses the upload certificate, whereas Google Play can deliver its own
app-signing certificate. Do not uninstall an existing user's Play app or clear
its data merely to install this locally signed APK. Store upgrade acceptance
must use the actual delivered package.

## Prepared iOS distribution artifact

| Field / check | Actual result |
|---|---|
| IPA | `PyBLE-0.3.0-build-9-app-store.ipa`, 23,784,757 bytes |
| SHA-256 | `14146b8951e4cd3298d27eb20e2036c80bbcd1b05bba42c98bf1abbd53b5eba6` |
| Identity | `dev.pyble.pyble`, `0.3.0 (9)`, normal `lib/main.dart` |
| Build / deployment floor | Xcode 27.2 / iOS SDK 27.2; app and compiled deployment floor at least iOS 15.0 |
| Export | App Store Connect distribution export; automatic signing with build-number management disabled; export destination only, no upload |
| Provisioning | Production App Store profile; debugging disabled, no development-device list, beta reporting enabled; valid through 17 May 2027 |
| Validation | `tools/validate_ios_ipa.sh` passes code-signature, compiled minimum OS, embedded-asset mode/classification and Xcode `swinfo` checks; only the three expected unsigned resource-bundle records are excluded |

The archive and exported IPA are retained privately. A distribution package
with no development-device list is not the separately installed development
Preview app. Its local validation does not establish App Store processing,
TestFlight availability, or store-installed upgrade behavior.

## Android WebView diagnostic boundary

An earlier isolated debug-build Blocks startup timeout is retained in the
private Android evidence. The first profile-build captures showed loading;
they did not establish an expired watchdog. On the Lenovo with Google WebView
155.0.8059.43, three separate controls passed: a native inline HTML/JavaScript
bridge, a native WebView with the exact production Blockly assets/CSP, and a
minimal Flutter profile app using the same pinned WebView plugins and asset
path. The exact-asset controls observed `onPageStarted`, then `hostReady`, and
confirmed that `window.pybleBlocks.configureHost` exists. The selected provider
was installed/enabled and not stopped or suspended at inspection time.

The current isolated profile candidate subsequently reached the real Blocks
workspace. These observations distinguish the retained debug failure from a
completed profile-candidate failure; they do not identify the original cause
or prove DR-T12 by themselves. The inline control exposed a possible callback
ordering hazard, but neither exact-asset control reproduced it, so no runtime
change or claimed fix followed. The physical report must separately record
actual generated-text handoff, recovery and cold relaunch. Diagnostic fixture
sources, APK hashes and callback logs remain under ignored
`local/recovery-completion/{native-webview-smoke,flutter-webview-smoke,android}/`.
The production artifacts above remain bound to `e54a78a`.

## Distribution access and remaining account work

The owner Android upload identity is locally usable and matches the historical
certificate. A valid Apple distribution identity and cached production App
Store provisioning profile are available. Signing access alone does not prove
an authenticated store session, role, account version history or review status.

No dedicated Play/App Store Connect connector or configured command-line store
credential was found in the standard locations inspected. Account access and
whether build 9 has already been consumed remain **unverified**. This is not a
claim that the owner has no access through the respective web consoles.

After the candidate is admitted, the authorized distribution operator must
verify the exact package, unused build numbers and current declarations, upload
the retained artifacts, resolve processing/review findings, and record actual
availability and installed-store results separately. The prepared packet and
artifact records make those steps concrete; they do not substitute for them.
