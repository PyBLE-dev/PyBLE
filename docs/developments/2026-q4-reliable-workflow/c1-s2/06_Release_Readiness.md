<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# App 0.3.0 (9) — release readiness and channel handoff

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | App-only bounded current-text recovery; existing Play open-testing and TestFlight channels |
| Source | Merged PR #40 at `6f5b3ea73a70342331fb49d0685938ce2a4cae11`; app tree `b12fe3621f1d100a3b3724d15ee0dea3b359acfe` |
| State | Production Android and iOS packaging verified for this source; physical acceptance and final release admission remain outstanding. The physical-device follow-up identified a keyboard-layout issue being repaired separately, so these pre-fix artifacts are provisional and must be rebuilt after that change |
| Local evidence | Ignored `local/recovery-completion/release/`: build/check logs, artifact manifest and retained signed binaries |
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
| App regression | Accepted source contract, red/green history, locked dependencies, ordinary tests, pinned goldens, platform builds and repository gates | PR #40 and its post-merge CI passed; 972 ordinary Flutter tests recorded; rerun affected checks for any further code change |
| Five-profile app compatibility | Q01–Q10 below with exact app/firmware identity, actual observations and retained failures | Final complete candidate-bound matrix not yet established |
| Production packaging | Android upload signer/AAB/APK/native alignment; iOS distribution export/IPA validation; capability parity | Android and iOS checks below pass for the recorded source; affected checks must follow a repaired candidate |
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
| Q07 | Q08 | `esp32-c3-4mb` | Common workflow plus affected recovery and the real-app C3-G5 behavior |
| Q09 | Q10 | `rpi-pico2-w` | Common workflow plus affected recovery on each physical platform; no new full GP2 qualification inferred |

Each common row includes ordinary service-filtered discovery/HELLO, editing and
saving a harmless file, Run/stdout/terminal state, Stop, exact file readback,
disconnect/reconnect and workspace continuity. Retain the selected candidate's
affected lifecycle/recovery scenarios. Record the actual result of every row;
a scan result or one platform cannot stand in for another row.

[C3-G5](../../../specifications/firmware/ports/esp32-c3-4mb.md#c3-g5--real-app-hil-on-both-platforms-frozen)
requires Stop through the real UI against both a tight loop and print flood.
Its C3-G2 oracle is exactly one matching `RSP{OK}` before `RUN_STATE(idle)` in
less than 500 ms from complete STOP submission, a usable connection, and a
subsequent bounded run. UI responsiveness alone cannot establish that wire
latency. There is no new arbitrary repetition count added by this app increment.

## Prepared Android production artifacts

Both builds use normal `lib/main.dart`, production flavor and the established
owner upload key. Secret values were obtained from the existing local secret
manager and never written into source or logs.

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `PyBLE-0.3.0-build-9-production-release.aab` | `fcf4692dbf7655f53a50a0687eedb81d9cf63bc601721552f622246d5cca0330` | 64,414,627 |
| `PyBLE-0.3.0-build-9-production-release.apk` | `8656549a8480ae7ebfe9b6023220fa35c9b967fb07ca0a754a0ec24cd63e3e13` | 66,439,954 |

| Check | Actual result |
|---|---|
| Package and version | `dev.pyble.pyble`, `0.3.0`, version code `9` |
| SDKs / ABIs | Minimum 24, target/compile 36; `arm64-v8a`, `armeabi-v7a`, `x86_64` |
| Signing | AAB JAR verification and APK signature verification pass; certificate SHA-256 matches the retained owner certificate `DCA95C5060CDF4936F19FD8C3212A871C223E2BA3FB67B6226179AFFDA62DD57` |
| Bundle | Official bundletool 1.18.3 validation passes; tool digest checked against the retained verified digest; configuration declares `PAGE_ALIGNMENT_16K` |
| Native libraries | All 12 packaged shared objects have every ELF LOAD alignment at least 16 KiB, including `libsqlite3.so` and `libdartjni.so` on all three ABIs |
| APK alignment | `zipalign -c -P 16 -v 4` passes |
| Permissions | Expected BLE, legacy location, Internet and AndroidX signature permission; no new authored platform permission |
| Runtime page-size check | Production APK launched on the official API 36 Google APIs 16 KiB arm64 emulator; kernel `PAGE_SIZE=16384`, About `Version 0.3.0 (9)`, bundled native SQLite mapped from the APK, and fresh schema v1 created successfully |

The 16 KiB runtime observation also force-stopped and relaunched the same
installed package without data clearing. The normal disconnected screen
returned; the retained fresh database and WAL reopened with `integrity_check=ok`
and the expected `projects`, `project_files` and `settings` tables. This is a
native packaging/startup smoke, not a physical BLE row or the full recovery
acceptance matrix. The SQLite database's own page size is independent of the
operating-system memory page size.

The first local invocation incorrectly used `--no-pub` after fresh `pub get`,
leaving the integration-test plugin in a generated Android registrant. Its
failed log is retained. Repeating the canonical CI production commands,
which allow Flutter to regenerate release plugin metadata, built both artifacts
successfully without a source change.

The APK uses the upload certificate, whereas Google Play can deliver its own
app-signing certificate. Do not uninstall an existing user's Play app or clear
its data merely to install this locally signed APK. Store upgrade acceptance
must use the actual delivered package.

## Prepared iOS distribution artifact

| Field / check | Actual result |
|---|---|
| IPA | `PyBLE-0.3.0-build-9-app-store.ipa`, 23,782,489 bytes |
| SHA-256 | `73ad7cda10c402a7f25316efc5e30f9c80bbd030e23c2bfc32313fd79c41c2ab` |
| Identity | `dev.pyble.pyble`, `0.3.0 (9)`, normal `lib/main.dart` |
| Build / deployment floor | Xcode 27.2 / iOS SDK 27.2; app and compiled deployment floor at least iOS 15.0 |
| Export | App Store Connect distribution export; automatic signing with build-number management disabled; export destination only, no upload |
| Provisioning | Production App Store profile; debugging disabled, no development-device list, beta reporting enabled; valid through 17 May 2027 |
| Validation | `tools/validate_ios_ipa.sh` passes code-signature, compiled minimum OS, embedded-asset mode/classification and Xcode `swinfo` checks; only the three expected unsigned resource-bundle records are excluded |

The archive and exported IPA are retained privately. A distribution package
with no development-device list is not the separately installed development
Preview app. Its local validation does not establish App Store processing,
TestFlight availability, or store-installed upgrade behavior.

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
