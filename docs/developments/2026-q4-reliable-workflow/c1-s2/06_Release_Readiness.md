<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# App 0.3.0 (9) — release readiness and channel handoff

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | App-only bounded current-text recovery; existing Play open-testing and TestFlight channels, with subsequent explicit owner authorization to promote the same accepted Android build to production |
| Runtime source | Recovery baseline plus landscape layout, native keyboard dismissal and iPad palette-geometry repairs at `bef67bded9e5b83437e3eb0e2ec4be6a4cfd1a64` |
| Build checkout | Release worktree `c6e685dd3ebe718ed89fcfe58e441331eb174648`; app tree `60b3a68b693551af5d83076547c502f69838e052`, verified identical to the runtime baseline |
| State | M-02 and app-only M-04 engineering admission accepted on 31 October for the frozen artifacts below. [PR #41](https://github.com/PyBLE-dev/PyBLE/pull/41) merged at `247e58a` after all 36 final-head checks passed; M-05 is partial: internal-account TestFlight delivery verified; external build 9 is submitted and Waiting for Review; Google Play open-testing build 9 is submitted with Changes in review; production promotion is blocked on the audience/Bluetooth requirement below; approval and delivery remain pending |
| Local evidence | Ignored `local/recovery-completion/release/candidate-bef67bd/`: build/check logs, source/artifact manifests, runtime evidence and retained signed binaries |
| Public copy | [Release packet](../../../publication/app-0.3.0-build-9-release-packet.md); build-9 test details saved and app description publicly verified; TestFlight delivery observed for the existing internal account only |

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
| App regression | Accepted source contract, red/green history, locked dependencies, ordinary tests, pinned goldens, platform builds and repository gates | Accepted runtime evidence: 984 ordinary Flutter tests, including 28 shell widget tests, six iOS guide/platform-control tests and one platform-fallback test; 36 frozen-runtime CI checks; pinned goldens and clean analysis/source gates. Final head `34dd89e` passed all 36 integration checks and merged as `247e58a`; the [merge receipt](00_Execution_Record.md#pr-41-final-integration-receipt) records workflow links and exact repository-tree equality |
| Five-profile app compatibility | Q01–Q10 below with exact app/firmware identity, actual observations and retained failures | Accepted Q01–Q10 on the exact named firmware inputs below, with source-impact mapping for earlier unaffected rows and final affected keyboard/recovery reruns on both tablets; retained failures remain visible in the device reports |
| Production packaging | Android upload signer/AAB/APK/native alignment; iOS distribution export/IPA validation; capability parity | Android and iOS checks below pass for the repaired source and exact retained artifacts |
| Release review | Frozen artifact identity, resolved mandatory failures, supported scope, privacy/dependency review and recorded acceptance | Accepted app-only M-04 engineering admission for `bef67bd` and the hashes below, with the Lenovo OEM precondition and historical firmware limits retained |
| M-05 channel delivery | Actual upload/processing/review/availability, followed by store-delivered installed identity and upgrade/launch checks | Apple upload accepted at `14:03:25 UTC`; later internal-account TestFlight `0.3.0 (9)` offer/Open, production About and bounded device smoke pass. The update transaction was not observed. External build 9 is submitted and Waiting for Review; Google Play open-testing build 9 is submitted with Changes in review; its approval and delivery remain pending |

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
| Initial export | App Store Connect distribution export; automatic signing with build-number management disabled; export destination only. The subsequent archive-upload receipt is recorded below |
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

## Distribution access and account verification

The owner Android upload identity is locally usable and matches the historical
certificate. A valid Apple distribution identity and cached production App
Store provisioning profile are available. Signing access alone does not prove
an authenticated store session, role, account version history or review status.

A read-only check of the Lenovo production package found `dev.pyble.pyble`
version `0.2.0`, versionCode `8`, with installing and initiating package
`com.android.vending` and its
last update on 17 September. Its verified signing certificate SHA-256 is
`e3c1334dc7aad1ae20fe043b52c2d5638584a67a66e6a5255a87bf89f56f06d0`, distinct
from the owner upload certificate above. The production app was not replaced.
This installed baseline alone did not establish account upload history. The later
authenticated Console check and accepted build-9 submission below now establish
that separate account state; the installed app still remains build 8.

No dedicated Play/App Store Connect connector or configured standalone
command-line store credential was found in the standard locations inspected.
The initial inspection found one configured production Apple-account reference
in Xcode and cached provisioning metadata for the candidate signing team.
Those local records did not establish a live session, role or unused build
number. The later successful upload below verifies that this existing account
could upload the unchanged `0.3.0 (9)` archive without a build-number conflict.
Initial read-only browser discovery did not establish an authenticated console session;
that observation does not imply that the owner lacks web-console access.

A read-only GitHub audit found zero repository Actions secrets and zero
repository environments. The only authored active workflow is
`.github/workflows/ci.yml`, which validates/builds but has no store-publishing
job; the tracked tree has no Fastlane configuration. Organization-secret
listing returned HTTP 403, so inherited organization credentials were not
proven absent. No existing repository workflow consumes a Play or App Store
publisher credential. This inspection found no configured CI upload route;
it does not infer that the owner lacks credentials elsewhere.

An initial Lenovo Chrome preflight reached Google Play Console but required
owner verification and selection of the actual PyBLE publishing account. The
owner subsequently authenticated; the correct app's account history and live
tracks were inspected before the accepted build-9 upload and review submission
recorded below. Account names, email addresses and unrelated account details
remain private.

The qualified AAB was staged at
`/sdcard/Download/PyBLE-0.3.0-build-9-bb041a9a-20261031.aab`.
Device-side verification confirmed 64,439,893 bytes and SHA-256
`bb041a9adcba7e84ece9800c418e69d7fa62274c2a170a929a37797a02784429`,
matching the admitted artifact above. The private staging receipt is
`local/recovery-completion/android/play-console/aab-device-preparation.json`,
SHA-256 `f23f53d2e3e1a1ef808dfc8c0124b2489325e9158819cb6948b40ef913751405`.
After submission was durably verified, that uniquely named device copy was
removed only after another size/hash check; the retained host artifact is
unchanged. `staged-download-cleanup.json` records the verified removal.

Engineering admission and PR #41 integration are complete. Both stores have
accepted build `9`; neither upload should be repeated. Internal-account
TestFlight delivery is verified. Apple external testing remains Waiting for
Review and Google Play open testing remains Changes in review at the dated
checks below. Review submission alone does not establish approval or delivery.

## 31 October App Store Connect upload receipt

The existing configured Xcode account uploaded `dev.pyble.pyble` version
`0.3.0`, build `9`, after PR #41 merged. The upload command exited zero at
`2026-10-31T14:03:25Z`. Xcode reported “Uploaded package is processing.” and
“Upload succeeded.” Automatic build-number changes were disabled; the upload
reported no build-number conflict. Apple has accepted and consumed build `9`;
do not repeat that upload. A replacement Apple binary requires an explicit
next-build contract and rebuilt artifacts. This establishes accepted upload and
the start of server processing only.

| Observation | Recorded result |
|---|---|
| Submitted transport IPA | `PyBLE-0.3.0-build-9-submitted.ipa`, 23,795,921 bytes; SHA-256 `2235ebcb46362871b5722ca9416b62fe109ce5fd42a4f235f1b3e87841ca5de3` |
| Admitted archive input | `PyBLE-0.3.0-build-9.xcarchive.zip`, the complete archive including dSYMs; SHA-256 `0e52d142ee14009a947422a6ded5ffa25ad70ad2297dae6735db802f5a6310dd` |
| Re-export identity | Xcode re-exported and re-signed the archive for transport, so the submitted IPA differs from the prepared `54552bbb…` export above. All five Mach-O executables match outside their code-signature regions; resources, `Info.plist` and provisioning profile match. Differences are signatures, `CodeResources` and regenerated Symbols entries |
| Submitted-package checks | `tools/validate_ios_ipa.sh` and deep/strict code-signature verification pass on the actual retained transport IPA |
| Server upload receipt | Version `0.3.0`, build `9`, platform `IOS`; uploaded at `2026-10-31T14:03:24Z`; state `PROCESSING`, with empty errors and warnings in that receipt |
| Processing completion / TestFlight availability at upload | Not established by this initial receipt; later internal-account delivery is recorded below |
| TestFlight snapshot | At approximately `14:04–14:05 UTC`, the connected iPad's actual TestFlight detail for PyBLE offered version `0.2.0`, build `6`, with an Open button and build-6 notes; no `0.3.0` availability was observed in that snapshot |
| Installed-app provenance limit | The separate device query found the same bundle/build and marked it developer-accessible. The TestFlight channel view and device query are distinct evidence; neither is reconstructed as a new store-install receipt |
| Installation / data | No update, uninstall or app-data clearing was performed during that channel check |
| Delivery evidence still needed at upload | Processing result, tester/group availability, then channel-installation identity and scoped launch/workflow observations; later results are recorded below |

The submitted IPA, command/validation logs, selected server responses and
code-equivalence comparisons remain under ignored
`local/recovery-completion/release/candidate-bef67bd/store-upload/20261031T140128Z/`.
The `selected-server-receipts.json` SHA-256 is
`c92ec28f87a42bfee8c2bb7b2e2b0afacb2b284472ed26bea5f649ee416afaba`;
`submitted-code-equivalence.json` is
`24db92bf0f8256859a29d0db5fc041e4b718a1988bb2974e456a7c8296f0c0ee`.
The opaque server delivery identifier and account metadata remain private.
A later read-only command-line status request required separate authenticated
credentials and yielded no newer processing state; no credential was extracted.
The initial iPad Safari App Store Connect check reached Apple's sign-in page,
without an authenticated browser session. Its private capture is
`local/recovery-completion/ipad/asc-session-after-upload.{log,xcresult}`.
The owner subsequently authenticated that browser; the actual saved metadata
and delivery observations below supersede this initial access limitation.

The timestamped TestFlight captures are retained privately as
`local/recovery-completion/ipad/testflight-pyble-after-upload.{log,xcresult}`.
This initial upload snapshot is preserved as history. It alone establishes no
Play submission or completed TestFlight delivery; later observations follow.


## 31 October TestFlight delivery and published metadata

At approximately `14:29 UTC`, a fresh device query found production bundle
`dev.pyble.pyble` version `0.3.0`, build `9`. The actual TestFlight detail for the
existing internal account repeatedly offered `0.3.0 (9)` with Open. Opening it
from TestFlight launched the production app; About reported `Version 0.3.0 (9)`.
This later observation supersedes the `14:04–14:05 UTC` build-6 snapshot without
changing that historical result.

| Check | Actual result and boundary |
|---|---|
| Delivery scope | Existing updated installation verified through the internal account's TestFlight offer/Open, installed identity and normal production-app launch; no universal or external-group availability inferred |
| Bounded device smoke | Production About `0.3.0 (9)`, all five known boards visible, C3 connection to Ready with agent `0.6.1`, explicit disconnect, then cold relaunch and About `0.3.0 (9)` pass |
| Update transaction | The exact update transaction was not observed. Automatic Updates had previously been enabled; the observations are consistent with that mechanism, but no manually exercised build-6-to-9 installation gesture is claimed |
| Data and firmware boundary | No sideload, manual installation, uninstall, data clearing, text replacement, board file write or Run was performed in this delivery smoke. It does not repeat or extend the full HIL matrix |
| Google Play | The `14:34 UTC` Lenovo snapshot still found Play `0.2.0 (8)`. The later accepted open-testing submission is recorded below; the final Play listing/install check still offers no update and remains build 8 |
| External testing | Build `0.3.0 (9)` assigned to existing `PyBLE external` group, submitted and verified after reload as Waiting for Review at `15:03:35 UTC` and again at `15:23:25 UTC`; approval and external availability are not yet established |
| Build-specific test details | English (U.S.) What to Test for `0.3.0 (9)` saved and exactly read back after reload: 2,242 characters; SHA-256 `01d14e5a7c0bfd50ad77c9d0f4d4571ba7be058e064d430c81d7f6c3f0d7507b`; exact published copy is in the [release packet](../../../publication/app-0.3.0-build-9-release-packet.md#testflight--what-to-test) |
| App-level public description | English (U.S.) Beta App Description saved, reloaded and exactly verified: 1,523 characters; fresh public HTTP response also matches. [PYB-002.1 correction](../c1-s1/05_TestFlight_Metadata_Correction.md#31-october-published-description-and-closure) is complete; historical build-6 provenance/minimum-OS questions remain separate |

The consolidated private delivery receipt is
`local/recovery-completion/ipad/testflight-build9-delivery-receipt.json`, SHA-256
`b95919ae0598e8620f8e451efd113b71f33f1e33591d730f443f7465f80b5cc5`.
The same directory retains `post-processing-installed-identity.json`,
`testflight-processing-followup.{log,xcresult}`,
`asc-build9-save-notes.{log,xcresult}`, `build9-what-to-test.txt`,
`asc-description-verify` captures and the original/replacement description.
Account identifiers and raw UI captures remain private. M-05 is partial: this
internal-account delivery and metadata result do not establish external-test
approval, Google Play delivery, participant outcomes or a Ready award.

## 31 October external-testing submission

The user-authorized App Store Connect action assigned `0.3.0 (9)` to the
existing **PyBLE external** group and submitted it for beta review. At
`2026-10-31T15:03:35Z`, a reload preserved the group assignment and the iOS
Builds page displayed **Waiting for Review**. This is a successful external
submission, not Apple approval or verified external-tester availability.

Automatically notify testers was unchecked and asserted off immediately before
submission. No new testers were invited, and no explicit Notify Testers action
was issued. Existing review contacts and the sign-in requirement were retained.
Review Notes were saved and exactly reloaded: 987 characters, SHA-256
`140d744c27e3930b253cc43a1355a49311ba3b32db9f6626347132f52e532ca3`;
the [release packet](../../../publication/app-0.3.0-build-9-release-packet.md#app-store-connect-review-notes)
contains the exact saved text.

The private receipt is
`local/recovery-completion/ipad/testflight-external-submission-receipt.json`,
SHA-256 `2a5ee9a0282ee6100496173a024491f39d0b3fb8c644fc4f009945260a9b9252`.
The same directory retains `asc-build9-submit-review` and
`asc-build9-review-verify` passing captures, `asc-review-notes-save` passing
save/reload evidence and `build9-review-notes.txt`. Await Apple's actual review
outcome and observe external availability before changing that claim. M-05
remains partial; internal-account delivery is verified and Google Play delivery
is still separate pending work.

A fresh authenticated-page reload at `2026-10-31T15:23:25Z` again verified
`0.3.0 (9)` as **Waiting for Review** in the same external group's Builds tab.
This read-only recheck made no store change. Its private receipt is
`local/recovery-completion/ipad/testflight-external-status-recheck.json`, SHA-256
`83b72cac5668f32304c70b39a8ec6d43ce1ae73056c89c476b6671924103ea97`.

## 31 October Google Play open-testing submission

After owner authentication, the actual PyBLE Console showed existing build
`8 (0.2.0)` live in both production and open testing. The pre-upload bundle
history contained codes `8`, `4` and `2`; code `9` was available at that check.
Google then accepted the admitted AAB as `dev.pyble.pyble`, version `0.3.0`,
versionCode `9`. Build `9` is now consumed; do not repeat its upload. A replacement
binary requires an explicit next-build contract and rebuilt artifacts.

| Observation | Recorded result |
|---|---|
| Accepted artifact | 64,439,893-byte AAB; SHA-256 `bb041a9adcba7e84ece9800c418e69d7fa62274c2a170a929a37797a02784429`, matching the frozen admitted artifact |
| Saved draft and validation | Open-testing release `9 (0.3.0)` saved; preview showed Ready to launch with no observed validation error, warning or required declaration prompt |
| Release notes | Exact prepared English (U.S.) text accepted and read back: 441 characters, SHA-256 `b199632c5a7442305e9dd622a47684780c2725948aee7c0a8f233281ab3a7e20`; the [release packet](../../../publication/app-0.3.0-build-9-release-packet.md#google-play-release-notes) preserves it |
| Submitted scope | Exactly one prepared change: Open testing `9 (0.3.0)`, Start full rollout, requesting 100% of the existing 178-country/region open-testing track. This is not production promotion |
| Submission receipt | Send 1 change for review and its confirmation completed; receipt recorded at `2026-10-31T15:22:21Z` |
| Durable current state | Fresh Console page and native semantic readback at `2026-10-31T15:23:55Z`: **Changes in review**, only the open-testing build-9 change |
| Review progress | Automated common-issue checks were running; content review follows automatically. No review completion or duration is promised |
| Publishing and production | Managed publishing remains off, unchanged; production `8 (0.2.0)` remains unchanged. The requested open-testing rollout has not been observed live |
| Actual Play delivery check | The enrolled Lenovo beta tester's Play listing offers Open and Uninstall, with no Update and `0.2.0` notes. Installed `dev.pyble.pyble` remains `0.2.0`, versionCode `8`, installed by `com.android.vending`. No upgrade or production-app data change was performed |

The private consolidated receipt is
`local/recovery-completion/android/play-console/release-preparation.json`,
SHA-256 `dff88fa5974a99cee0840825f802133236a381339440db88e2fb03b6b68c11d4`.
Its one-unsent-change fields describe preparation before submission; the later
submission and durable review fields supersede that phase. The same directory
retains validation, final submitted-state and actual Play-listing captures.
The uniquely staged Downloads AAB was removed after hash/size verification;
`staged-download-cleanup.json` has SHA-256
`ffb6465b4255e2416363e3d275cacfa3b2ce847b509b47befb2482233ddf357c`.
No store approval, live build-9 rollout or Android installation of the update
has been observed. PYB-014.1 submission is complete for the selected channels;
PYB-014.2 and M-05 remain partial until the remaining delivery evidence exists.

## 31 October Android production scope decision

After the open-testing submission above, the user explicitly requested Android
production release of `0.3.0 (9)`. This is the separate production decision
required by [PYB-014.1](../05_Product_Backlog_and_Stories.md#35-release-and-channel-verification).
It extends the selected track scope to production using the same accepted AAB
from the Play artifact library; it does not authorize a new binary or another
build-9 upload. The frozen source, signed artifact hash, packaging checks and
app-only M-04 engineering admission remain unchanged. The earlier
`15:23:55 UTC` open-testing receipt and production-build-8 baseline remain dated
history.

The production draft uses accepted build `9` from the artifact library. Its
preview passed and requested a full rollout to the existing 178 countries and
regions. The final Restart review confirmation was **not confirmed**; production
build `9` has not been submitted for review or observed live. The earlier
open-testing review remains separate.

The actual maintained target-audience settings include ages **9–12, 13–15,
16–17 and 18+**, with a Families commitment last updated on 7 August. Console
showed no required actions, ten completed App content declarations and no
policy issues. Those automated/account views do not resolve the specific
implementation requirement found during source review.

For an audience including children, the current [Google Play Families policy](https://support.google.com/googleplay/android-developer/answer/9893335?hl=en)
requires Companion Device Manager (CDM) when requesting Bluetooth, with an
exception only for apps targeting OS versions that cannot support CDM.
[Android documents CDM from API 26](https://developer.android.com/develop/connectivity/bluetooth/companion-device-pairing).
This candidate supports API 24 and later and targets API 36, including the tested
API-31 Lenovo; the incompatible-OS-only exception does not apply. The frozen
[scan adapter](../../../../app/lib/ble/fbp_ble_adapter.dart) invokes
`FlutterBluePlus.startScan`. The [locked](../../../../app/pubspec.lock)
`flutter_blue_plus_android 7.0.4` path requests `BLUETOOTH_SCAN` directly and calls
`BluetoothLeScanner.startScan`; the reviewed path does not use CDM.

This is a pre-existing Android package/audience issue, also relevant to the
ongoing open-testing review and existing production baseline; it is not a
requirement unique to production promotion. The previously submitted open-testing
review has not been changed while the owner clarifies the audience. Its accepted
submission does not establish policy clearance.

The newly requested production promotion is therefore **blocked by the saved
audience and the Bluetooth implementation mismatch**, not by a Google validation
error. The owner's actual intended audience must be established before choosing an
accurate audience correction or a separately specified and qualified
implementation change. No audience declaration has been changed to bypass
this decision. The broader Data safety worksheet remains a conservative
proposal, not a newly attested declaration or an additional established
production blocker. Existing scoped M-02/app-only M-04 engineering results stay
valid; they do not establish current Families compliance or unconditional
production admission.

The production preparation and unchanged App content observations are retained
in `local/recovery-completion/android/play-console-production/production-release-preparation.json`,
SHA-256 `c8504d5dbf278c8c2d7544e084979afcc181928bdb58be5458b2f8582ed32e86`.
Its hold was recorded at `2026-10-31T15:37:16Z` with the final confirmation still
open and unconfirmed. The [Data safety assessment](../../../publication/google-play-data-safety.md#31-october-2026--actual-console-inspection-and-audience-hold)
records the observed saved answers without adopting or reattesting them.

The immutable source/policy audit is retained privately as
`local/recovery-completion/android/play-console-production/policy-review/families-bluetooth-review.json`,
SHA-256 `44f6a9ffefc12b7be4a60a1f0ef91ed791072f303eb934c3c0d0efbb4fa7c8a0`.
It binds the frozen source, admitted AAB, supported API range, locked plugin and
saved audience evidence; the same directory retains the reviewed policy page.

The iPad's final observed external state remains Waiting for Review at
`15:23:25 UTC`; its verified internal-account delivery is separate. No further
iPad operation is required to document that snapshot.
