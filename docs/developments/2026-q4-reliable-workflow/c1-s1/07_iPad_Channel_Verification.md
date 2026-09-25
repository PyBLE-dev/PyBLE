<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# C1-S1 — physical iPad TestFlight verification

| Field | Record |
|---|---|
| Observed | 25 September 2026, approximately 10:42–10:48 UTC / 17:42–17:48 Asia/Bangkok |
| Task / story | C1-S1-T03; iPad portion of PYB-001.2 |
| Result | **Done for verification of the current TestFlight installation**; fresh enrollment and a new installation/update were not performed |
| Device / OS | Physical `iPad16,10`; iPadOS `26.6.2`, build `23G90`; live device queries and screen captures succeeded |
| Installed app | `dev.pyble.pyble`, version `0.2.0`, build `6` |
| Distribution proof | Installed-app metadata reports `SignerIdentity = TestFlight Beta Distribution`, `beta-reports-active = true`, `get-task-allow = false`; the native TestFlight page offers the same version/build with **Open** |
| Launch | Successful nonterminating activation before and after the TestFlight inspection; captured PyBLE's disconnected screen with **No board connected** |
| Source mapping | Unresolved; no installed binary was matched to an immutable uploaded archive or source revision |
| Evidence author | Codex, direct device queries and inspection; no independent human review or usability participant is implied |
| Related | [Channel ledger](01_Channel_and_Artifact_Ledger.md), [execution record](00_Execution_Record.md), [TestFlight metadata correction](05_TestFlight_Metadata_Correction.md), [Sprint backlog](../06_Sprint_Backlogs.md) |

This retry supersedes the earlier locked-device result for current iPad access
and installed identity. T03 asks to verify the current TestFlight installation;
the installed beta and its functioning launch satisfy that bounded task without
reinstalling an already working app. The combined PYB-001.2 story still needs its
Android evidence and explicitly retains any unperformed enrollment/install
criteria. Neither this check nor a completed task qualifies BLE, draft recovery,
the firmware matrix, or the five-participant pilot.

## Observations and acceptance assessment

| Check | Observed evidence | Assessment / boundary |
|---|---|---|
| Live device access | Exact PyBLE query, device details and native screenshot commands succeeded | Earlier unlock/access blocker cleared |
| Installed identity | CoreDevice and the independent installation-proxy query both report `0.2.0 (6)` | Build is observed on the device; source `pubspec.yaml` was not used to infer it |
| Existing beta access | The public invitation opened on the iPad, then its actual `itms-beta` link opened PyBLE in the native TestFlight app | Existing account can access this beta; no fresh-account eligibility or country-wide availability claim |
| Currently offered build | TestFlight shows `0.2.0`, **Build 6**, **Open**, 62 days until expiration, and 21.6 MB; release date is 27 August 2026 | No Update or Install action was offered on the observed page; the relative expiry is only a dated observation |
| TestFlight origin | Exact installed-app lookup: `TestFlight Beta Distribution`; beta reporting enabled; debugger entitlement disabled | Stronger evidence than an Open button or a matching version alone |
| Foreground launch | Two successful `devicectl` launch results and screenshots of PyBLE's disconnected screen | Launch smoke passed; About was not opened and its text is not claimed as evidence |
| Safe existing state | No uninstall, clear-data, replacement build, test runner, board connection, run, or STOP action | Existing data was not deliberately modified; draft contents and persistence were not assessed |
| Historical/source mapping | Historical build-5 handoff differs from installed build 6; no archive comparison performed | Distribution owner must bind the observed beta to retained build/archive/source evidence |
| Installation floor | Installed-app metadata reports `MinimumOSVersion = 18.0`; TestFlight build notes describe an iOS/iPadOS 15 rebuild | Reconcile the delivered variant, archive and store eligibility before claiming tested support on iPadOS 15–17 |

CoreDevice reports `builtByDeveloper = true` and `containerAccessible = true`
for this app. Those booleans are **not** used to classify its signing origin:
the scoped installation-proxy response identifies TestFlight Beta Distribution.
Equally, the displayed **Open** action alone would not have established origin.

The installed `MinimumOSVersion` is a fact about the metadata returned for this
device. It does not establish the universal minimum of all delivered variants,
prove an App Store Connect configuration error, or demonstrate compatibility on
an older OS. The distribution owner owns this follow-up alongside source
mapping. Current-device launch passed on iPadOS 26.6.2 despite this unresolved
cross-version question. The stale public description remains tracked in the
[metadata correction packet](05_TestFlight_Metadata_Correction.md).

## Reproducible inspection procedure

| Step | Operation | Result |
|---|---|---|
| 1 | Query the live device and exact `dev.pyble.pyble` bundle, including default apps | One matching app; `0.2.0 (6)` |
| 2 | Activate PyBLE without `--terminate-existing`; capture its screen | Successful launch and disconnected-screen smoke |
| 3 | Query only `com.apple.TestFlight` | Installed TestFlight `4.3.1 (681.1)` |
| 4 | Open `https://testflight.apple.com/join/yU4e8s6d` on the iPad | Public PyBLE beta invitation rendered |
| 5 | Open the invitation's actual `itms-beta://testflight.apple.com/join/yU4e8s6d` link; allow the page to finish loading; capture it | Native TestFlight offered build 6 with Open |
| 6 | Perform read-only `instproxy_lookup` for only `dev.pyble.pyble` through installed libimobiledevice | Installed signer and beta entitlements established; metadata preserved privately |
| 7 | Activate PyBLE again without termination, capture the screen, and repeat exact installed identity query | Successful smoke; installed version/build unchanged |

Representative commands, with device identifiers and raw output paths replaced:

```sh
xcrun devicectl device info details --device '<paired-iPad>' \
  --json-output '<private-evidence>/device-details.json'
xcrun devicectl device info apps --device '<paired-iPad>' \
  --include-default-apps --bundle-id dev.pyble.pyble \
  --json-output '<private-evidence>/pyble-apps.json'
xcrun devicectl device process launch --device '<paired-iPad>' \
  --json-output '<private-evidence>/pyble-launch.json' dev.pyble.pyble
xcrun devicectl device capture screenshot --device '<paired-iPad>' \
  --destination '<private-evidence>/pyble-launch.png'
xcrun devicectl device process openURL --device '<paired-iPad>' \
  'https://testflight.apple.com/join/yU4e8s6d'
xcrun devicectl device process openURL --device '<paired-iPad>' \
  'itms-beta://testflight.apple.com/join/yU4e8s6d'
```

Tool versions were Xcode `27.0` (`27A266a`), CoreDevice CLI `642.16`,
libimobiledevice `1.4.0`, and libplist `2.7.0`. The local read-only metadata
probe starts the standard installation-proxy service and calls
`instproxy_lookup` with the sole application ID `dev.pyble.pyble`; it neither
browses unrelated apps nor calls install/uninstall APIs. Its fresh, small C
source is retained with the raw evidence. Only selected nonpersonal fields
are published here.

The legacy `idevicescreenshot` command failed because its screenshot service
was unavailable; native `devicectl device capture screenshot` then succeeded.
One later launch attempt put device options after the positional app argument
and returned CLI usage error `64`; the corrected command succeeded. These are
inspection-tool failures, not observed PyBLE launch failures. Initial captures
during transitions/loading were not used as final UI evidence.

## Retained evidence

Raw logs, plist/JSON responses, helper source and screenshots remain in the main
workspace's ignored `local/c1-s1/2026-09-25-retry/ipad/`. They contain private
device/account context and are excluded from Git. The hashes below identify
captures, not signed app binaries or a source revision.

| Capture | SHA-256 | Purpose |
|---|---|---|
| `device-details.json` | `1b5311b7ae5d5c7d362477c06c9c7d5973bbffc43204717d975c79a1c9af1d9b` | Live model/OS and available developer services |
| `pyble-apps.json` | `e05fec8dd09a57d1ad3af88180b18cb9b692c273c344a7f86830b731508763a7` | Exact initial installed identity |
| `pyble-launch.json` | `3be33583b4da503617630396123fa191668332946be5e1ad2643ca9050385bd7` | Successful initial activation |
| `pyble-launch.png` | `a3c4501b6a8a097f86a581e48c0098d6899c9d3a0b2f995a85e0b5534c12e7ee` | Initial disconnected-screen smoke |
| `testflight-apps.json` | `3025a8cf7f77741a321c5ff7167e3cce2eb214a5d53f325ff394d972bcec2900` | Exact TestFlight app query |
| `testflight-app-settled.png` | `cc5d640c8e9ffe3f32873dcdb11bf2f8ee9ba83b20c1d0967477c6f3fe11ed53` | Loaded native PyBLE beta page and offered build |
| `pyble-installation-proxy.plist` | `442009f522d4641aad8698d730ca9b72e90cc6fbb12bc9410499c124322199d1` | Exact installed signer, beta entitlements, version and minimum OS metadata |
| `app_lookup.c` | `f0fae980df75eafc22dc595ca3dbecd1d18281461dab17932fd0f9951de9e53c` | Read-only, single-bundle metadata probe source |
| `pyble-final-launch.json` | `30c488910697ab53e74e38a8782b6a9ff7145d4cd5f99e8483e00fb0ad7079bb` | Successful activation after TestFlight inspection |
| `pyble-final-v2.png` | `1dc640507bdd80b3542534b4bca919d554d343c4d970f2206ea994cd5cabab72` | Final disconnected-screen smoke |
| `pyble-apps-final.json` | `aeac713c535d4ccf21cc7cf06b7ee8fbd43afd5c3241e673048e623463288572` | Installed identity unchanged after channel inspection |
