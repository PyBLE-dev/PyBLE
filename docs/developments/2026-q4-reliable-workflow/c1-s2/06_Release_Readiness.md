<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# App 0.3.0 (9) — release readiness and channel handoff

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | App-only bounded current-text recovery; existing Play open-testing and TestFlight channels |
| Runtime source | Recovery baseline plus landscape layout, native keyboard dismissal and iPad palette-geometry repairs at `bef67bded9e5b83437e3eb0e2ec4be6a4cfd1a64` |
| Build checkout | Release worktree `c6e685dd3ebe718ed89fcfe58e441331eb174648`; app tree `60b3a68b693551af5d83076547c502f69838e052`, verified identical to the runtime baseline |
| State | M-02 and app-only M-04 engineering admission accepted on 31 October for the frozen artifacts below. Final PR required CI and merge precede publishing; M-05 delivery remains pending |
| Local evidence | Ignored `local/recovery-completion/release/candidate-bef67bd/`: build/check logs, source/artifact manifests, runtime evidence and retained signed binaries |
| Public copy | [Prepared release packet](../../../publication/app-0.3.0-build-9-release-packet.md); no submission or availability claim |

A post-freeze comment correction clarifies Android's asset/file-access adapter
semantics. It changes no executable behavior or loading path; the retained
artifacts remain bound to the frozen runtime and app tree above.

## Gate selection

This increment changes the app, not the firmware bytes. The
[qualification inventory](../c1-s1/04_Validation_Inventory_and_Operator_Recipe.md#1-evidence-and-gate-selection)
requires affected app workflows on the five existing exact profiles and both
platforms for that compatibility claim. An unchanged firmware is a named input
with its own historical qualification limits. This work does not require or
claim a new firmware release, fresh firmware OI-1 qualification or a Ready badge.

| Gate | Required evidence | Current disposition |
|---|---|---|
| M-02 recovery acceptance | All DR-T01–14 required evidence, including representative physical generated-text recovery and both platform offline/current-board-consent records | Accepted: mandatory DR-T01–14 evidence is reconciled in the [execution record](00_Execution_Record.md) and its iPad/Android reports, including final normal-candidate generated-text recovery, offline restore and current-target Cancel checks |
| App regression | Accepted source contract, red/green history, locked dependencies, ordinary tests, pinned goldens, platform builds and repository gates | Accepted runtime evidence: 984 ordinary Flutter tests, including 28 shell widget tests, six iOS guide/platform-control tests and one platform-fallback test; 36 Android runtime CI checks; pinned goldens and clean analysis/source gates. The final documentation/rebase head must still pass required PR CI before merge and publishing |
| Five-profile app compatibility | Q01–Q10 below with exact app/firmware identity, actual observations and retained failures | Accepted Q01–Q10 on the exact named firmware inputs below, with source-impact mapping for earlier unaffected rows and final affected keyboard/recovery reruns on both tablets; retained failures remain visible in the device reports |
| Production packaging | Android upload signer/AAB/APK/native alignment; iOS distribution export/IPA validation; capability parity | Android and iOS checks below pass for the repaired source and exact retained artifacts |
| Release review | Frozen artifact identity, resolved mandatory failures, supported scope, privacy/dependency review and recorded acceptance | Accepted app-only M-04 engineering admission for `bef67bd` and the hashes below, with the Lenovo OEM precondition and historical firmware limits retained |
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

The selected unchanged firmware inputs are the published `c8f549ee` reference
for classic ESP32 and the retained `96497b9` observer reference for generic S3,
Waveshare S3, C3 and Pico 2 W. Current immutable image checks and exact hashes
are recorded with the [execution evidence](00_Execution_Record.md). Runtime and
build-driver source review found no differences between those references, but
the artifact bytes differ. This is an app-only matrix on those named inputs;
it must not be relabeled as five current published-image passes or a fresh
firmware qualification. No firmware update is part of this release preparation.

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
| `PyBLE-0.3.0-build-9-production-release.aab` | `bb041a9adcba7e84ece9800c418e69d7fa62274c2a170a929a37797a02784429` | 64,439,893 |
| `PyBLE-0.3.0-build-9-production-release.apk` | `92dd447ea9ee48ee00225825cbf89cb58807f3ba4d5f74d6e54d791874dd8979` | 66,456,338 |

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
created by the earlier `6f5b3ea` production candidate, subsequently reused by
`e54a78a` and `01a7ac8`, and its WAL reopened with
`integrity_check=ok` and the expected `projects`, `project_files` and `settings` tables. This is a
native packaging/startup smoke, not a physical BLE row or the full recovery
acceptance matrix. The SQLite database's own page size is independent of the
operating-system memory page size. The emulator uses Google APIs 16 KiB arm64
API 36 image revision 7; its fingerprint and private UI captures are recorded
with the candidate manifest.

The first final smoke attempt stopped at the emulator-only ADB root request,
before package installation. Its failed attempt is retained. The completed
rerun verified the reconnected emulator identity and root user before the
installation and runtime checks; no physical-device settings were changed.

The first local invocation incorrectly used `--no-pub` after fresh `pub get`,
leaving the integration-test plugin in a generated Android registrant. Its
failed log is retained. Repeating the canonical CI production commands,
which allow Flutter to regenerate release plugin metadata, built both artifacts
successfully without a source change.

A later incremental rebuild after the keyboard repair regenerated AOT inputs
but reused stale Gradle merged/stripped native libraries. Comparing packaged
`libapp.so` against current build inputs exposed the mismatch; those artifacts
were rejected and retained under `rejected-stale-gradle-e54a78a/`. Running
`flutter clean` and both canonical production commands resolved that mismatch.
The native-dismissal and subsequent iPad palette-geometry repairs each used a clean build; its packaged AOT
libraries match current stripped outputs and the AAB on all three ABIs. The
`6f5b3ea` artifacts under `artifacts-6f5b3ea/` and pre-native-fix `e54a78a`
artifacts under `candidate-e54a78a/`, and pre-guide `01a7ac8` artifacts under
`candidate-01a7ac8/` remain historical evidence. The latter package is superseded
by the iPad reachability defect described below.

The earlier `01a7ac8` build encountered an OpenJDK 17 AArch64 JIT internal
error in a long-lived Gradle daemon. Its failed log and crash receipt are kept
under `failed-jvm-01a7ac8/`. A fresh-daemon clean retry built the recorded APK,
AAB and IPA without a source change; all artifact checks were repeated. The
new `bef67bd` clean build completed without that failure.

The APK uses the upload certificate, whereas Google Play can deliver its own
app-signing certificate. Do not uninstall an existing user's Play app or clear
its data merely to install this locally signed APK. Store upgrade acceptance
must use the actual delivered package.

## Prepared iOS distribution artifact

| Field / check | Actual result |
|---|---|
| IPA | `PyBLE-0.3.0-build-9-app-store.ipa`, 23,795,805 bytes |
| SHA-256 | `54552bbb0cadf5f33c0bebd4e869623ea17308cd73281680c986daa6509e2c3d` |
| Identity | `dev.pyble.pyble`, `0.3.0 (9)`, normal `lib/main.dart` |
| Build / deployment floor | Xcode 27.2 / iOS SDK 27.2; app and compiled deployment floor at least iOS 15.0 |
| Export | App Store Connect distribution export; automatic signing with build-number management disabled; export destination only, no upload |
| Provisioning | Production App Store profile; debugging disabled, no development-device list, beta reporting enabled; valid through 17 May 2027 |
| Validation | `tools/validate_ios_ipa.sh` passes code-signature, compiled minimum OS, embedded-asset mode/classification and Xcode `swinfo` checks; only the three expected unsigned resource-bundle records are excluded |

The archive (including dSYMs), exported IPA and Android R8 mapping are retained
privately outside the temporary build worktree. A distribution package
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

The earlier isolated profile candidate subsequently reached the real Blocks
workspace. Those observations did not establish the cause of the retained
debug failure or prove DR-T12 by themselves. A later final-candidate profile
failure was reproduced and isolated separately below. The inline control exposed a possible callback
ordering hazard, but neither exact-asset control reproduced it, so no startup-protocol
change or claimed startup fix followed. The physical report must separately record
actual generated-text handoff, recovery and cold relaunch. Diagnostic fixture
sources, APK hashes and callback logs remain under ignored
`local/recovery-completion/{native-webview-smoke,flutter-webview-smoke,android}/`.
A separate physical finding established that console Expand did not dismiss
an Android keyboard owned by a native Blockly field. The final candidate adds
a narrow current-window dismissal request on Android and iOS while retaining
layout based on actual insets. The Android rerun observed IME visibility change
from shown to hidden, an expanded console and retained field text. The final iPad
report also passes reachable Expand/dismissal in both Editor and Blocks. The production artifacts
above include this repair and the later iPad geometry fallback; the diagnostic controls
did not change the Blocks startup protocol.

## Final Android renderer suppression control

The final `bef67bd` isolated qualifier profile subsequently timed out on Blocks
startup, including Retry and a startup with no active UI-automation polling.
The failure is retained; earlier profile success does not erase it. An ignored
instrumented copy of the actual host completed controller setup and asset-load
submission by 412 ms. At 3 and 9 seconds the native URL was the bundled asset,
but bounded JavaScript readiness probes timed out. No page-start, page-finished
or bridge callback arrived; the 15-second watchdog fired at generation zero.
This observed failure preceded the startup gate, so no host-readiness protocol
change was justified.

Android retained the qualifier's renderer service as pending with no process or
binder. Its ActivityManager explicitly suppressed service startup. The device's
DuraSpeed service was enabled and listed the isolated qualifier package in its
suppression set. The actual production package `dev.pyble.pyble` was absent from
that set and was not changed. A plain native Activity loading the exact bundled
assets under the same qualifier APK/UID also failed before any page/bridge
callback, establishing that Flutter and the Blocks startup gate were not
necessary for this failure.

The ordinary qualifier App info → Battery screen initially selected
**Optimized**. A scoped, reversible control selected **Unrestricted** for that
qualifier alone. The same native APK/UID then emitted page-start at 594 ms,
`hostReady` at 801 ms, page-finished at 809 ms, and successful document/API
readiness probes at 3 and 9 seconds. DuraSpeed remained globally enabled and
its global configuration was unchanged. No provider replacement, global
optimization disable, hidden allowlist mutation, firmware change or app-data
reset was used. This native control alone was not final app acceptance: a later
normal-APK shell launch still produced a retained watchdog failure. Both the
older and final normal profile APKs subsequently opened a valid empty workspace
through the actual launcher. A helper initially misclassified that ready empty
state because it waited for enabled Preview code before any blocks existed;
the raw hierarchy instead showed Visual block workspace, Browse examples and
Add blocks to generate Python, with no startup error. This oracle correction
does not erase the separate real watchdog failures.

The final normal `945e9746` qualifier then passed Hello example generation,
native-field keyboard Expand/dismissal with content retained, guarded Editor
handoff, a local generated-text checkpoint, offline cold relaunch/Restore with
both radios off, and current-C3 Save Cancel and Run Cancel. A first post-radio
C3 service-discovery timeout was retained; explicit reconnect succeeded before
the two Cancel checks. The board was explicitly disconnected afterward.
No startup source change or extra artifact rebuild followed these controls.

After these observations, the qualifier's original **Optimized** battery mode
was restored through the same ordinary Settings screen. Fresh native hierarchy
and screenshot receipts show only Optimized checked. The qualifier was removed
from the device-idle allowlist; the global DuraSpeed configuration is byte-for-
byte identical to its baseline and remains enabled. The production package
remains absent from the DuraSpeed suppression/explicit allowlist observations
and its settings were untouched. The final acceptance therefore records the
observed Unrestricted/actual-launcher qualification precondition and restoration,
rather than promising operation while the OS suppresses renderer startup.

Raw callback logs, the failed attempts and normal APK identities are retained
under ignored `local/recovery-completion/android/`. OEM policy, checked-radio
screenshots and the restoration recipe are under
`local/recovery-completion/blockly-startup-diagnostic/`. This is an explicit
device precondition for the isolated qualification container, not a claim of
unconditional operation while Android suppresses its WebView renderer.

## iPad keyboard palette regression

On the native-dismissal candidate `01a7ac8`, opening the docked keyboard through
its input palette could leave console Expand underneath the keyboard and
unreachable. This affected both the Flutter Editor and native Blockly input;
it did not establish a failure of the dismissal handler, which could not be
invoked. A normal initial keyboard focus produced a correct 498-point inset.
After Hide → palette Show Keyboard, however, the local keyboard notifications
reported end frame `[0,1024,1366,498]`, outside the current 1366×1024 view, while
`UIKeyboardLayoutGuide` correctly reported `[0,526,1366,498]`. The engine
registrar, current view controller and window were all present. Ignored native
console/XCTest receipts preserve this measured mismatch.

The final repair observes that current engine view's public layout guide and
uses the maximum of native overlap and Flutter's bottom inset. It preserves
real 70.5/81.5-point palette occlusion, treats a hidden safe-area-only guide as
zero, and restores ordinary safe-area padding. It does not add both insets or
change Flutter/Blockly upstream code. Generation checks, post-frame attachment,
background reset and explicit post-metrics snapshots avoid stale callbacks and
a measured-window-size race. The editor and Blocks host retain their identity.

Signed red `4882049` and green `c6e685d` correspond to integrated red `bd36731`
and runtime `bef67bd`. The complete ordinary suite passes 984 tests; six guide
regressions cover the actual fallback, Blocks dismissal/host retention,
maximum/padding behavior, resize ordering, stale callbacks/lifecycle and the
unchanged Android path. Native iOS profile compilation and static/source gates
pass. Final physical iPad palette reopening and reachable Expand/dismissal
passed in both Editor and Blocks on `bef67bd`; the iPad report linked from the [execution record](00_Execution_Record.md)
retains the original failures and measured diagnostic alongside the successful
reruns. These physical observations, not the IPA export alone, satisfy the
affected keyboard acceptance.

## Dependency review scope

On 31 October, GitHub's 19 open Dependabot entries mapped to 12 advisory
families in the website's npm manifests. Current main already contains fixes
for 11 families; the braces advisory was withdrawn. A fresh
`npm audit --audit-level=high --json` exited successfully with no high or
critical findings. It reports 15 moderate affected dependency nodes from two
roots: minimatch in development lint tooling and Satori in vinext image tooling.
No authored affected SVG, cache or TLS invocation was found. Production serves
static output, and these website dependencies are outside the frozen app
artifact. The moderate findings remain separate web maintenance; this review
does not claim that every dependency is vulnerability-free. No alerts were
dismissed and no dependencies were changed.

The retained audit completed at `2026-10-31T12:54:17.290202+00:00` against lockfile
SHA-256 `2c7b0c6c652a078eefada990f4a018ae4650355bfb703858c581b5cf430e5483`.
Its advisory mapping, audit JSON and summary remain under ignored
`local/recovery-completion/dependency-audit/`.

## Distribution access and remaining account work

The owner Android upload identity is locally usable and matches the historical
certificate. A valid Apple distribution identity and cached production App
Store provisioning profile are available. Signing access alone does not prove
an authenticated store session, role, account version history or review status.

No dedicated Play/App Store Connect connector or configured standalone
command-line store credential was found in the standard locations inspected.
However, Xcode preferences contain one configured production Apple-account
reference, and its cached provisioning metadata includes the candidate signing
team. The existing Xcode account may therefore support an archive upload after
admission without a separate App Store Connect API key. Account metadata alone
does not verify a live session, App Store Connect role or whether build 9 has
already been consumed; these remain **unverified**. Read-only browser discovery
did not establish an authenticated console session. This is not a claim that
the owner lacks web-console access or that Xcode has no potential upload route.

A read-only GitHub audit found zero repository Actions secrets and zero
repository environments. The only authored active workflow is
`.github/workflows/ci.yml`, which validates/builds but has no store-publishing
job; the tracked tree has no Fastlane configuration. Organization-secret
listing returned HTTP 403, so inherited organization credentials were not
proven absent. No existing repository workflow consumes a Play or App Store
publisher credential. This inspection found no configured CI upload route;
it does not infer that the owner lacks credentials elsewhere.

Engineering admission is complete for the frozen artifacts. After the final
required PR checks and merge, the authorized distribution operator must verify
the exact package, unused build numbers and current declarations, upload the
retained artifacts, resolve processing/review findings, and record actual
availability and installed-store results separately. The existing Xcode account
is a concrete route to attempt, with server authentication and receipts retained.
The prepared packet and artifact records do not substitute for channel delivery.
