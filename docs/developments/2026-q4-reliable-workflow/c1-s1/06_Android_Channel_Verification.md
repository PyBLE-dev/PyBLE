<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# C1-S1 — physical Android channel verification

| Field | Observed result |
|---|---|
| Date | 25 September 2026, UTC / Asia/Bangkok |
| Task | C1-S1-T02; Android part of PYB-001.2 |
| Device | Physical Lenovo TB-J616X, Android 12; connected and unlocked |
| Channel | Google Play, existing beta membership; listing explicitly describes open testing |
| Installed application | `dev.pyble.pyble`, version `0.2.0`, version code `8` |
| Result | **Done for the existing-installation verification scope:** official channel, installed identity, launch and About checked; payload-to-historical-artifact mapping established below |
| Evidence author | Codex, through ADB and the actual device UI; no independent participant or second-operator attestation |
| Related records | [Channel ledger](01_Channel_and_Artifact_Ledger.md), [execution record](00_Execution_Record.md), [historical build-8 handoff](../../../testing/google-play/0.2.0-build-8.md) |

This retry supersedes the earlier “no connected Android device” finding. An
existing, working Play installation was present. There was no Update or Install
action offered, so no fresh enrollment, fresh installation or upgrade event was
performed. The ledger's existing-app/update branch permits this nondestructive
verification; it does not require uninstalling a user's app to manufacture a
fresh-install result. The separate [iPad result](07_iPad_Channel_Verification.md) completes the other
platform portion of PYB-001.2; both reports retain their evidence limits.

## Actual channel and launch observations

| Check | Actual evidence | Interpretation |
|---|---|---|
| Official listing | Opened `market://details?id=dev.pyble.pyble` explicitly in `com.android.vending`; the corresponding public listing is [Google Play](https://play.google.com/store/apps/details?id=dev.pyble.pyble) | The actual device's Play Store was used, not third-party indexing or a sideload |
| App identity | Listing displayed PyBLE: MicroPython IDE (Beta), publisher SciLabPro | Correct product listing |
| Testing state | Play showed existing beta-tester membership and said future updates would include beta versions; its update notes stated open testing for PyBLE 0.2.0 | This account/device can access the installed beta; no new opt-in was exercised |
| Available action | Open; no Update or Install action observed | Already installed/current for the offer shown to this account/device; not a global rollout claim |
| Installation source | Android package metadata reported `installerPackageName=com.android.vending`; exact package was installed, enabled, not hidden or suspended | Consistent with the observed Play-managed installation |
| Recorded installation dates | Device package metadata: first installed 22 August 2026; last updated 17 September 2026 | Historical package timestamps, not events performed during this retry |
| Play → app | Tapped Open in the actual listing; PyBLE's disconnected home screen rendered | Successful nondestructive launch from the channel |
| About | Opened About PyBLE; UI displayed `Version 0.2.0 (8)` | UI and package-manager version/build agree |
| Return | Returned from About to the app; did not initiate a BLE scan or board connection | About navigation completed without modifying editor or board content |

No country, new-account or age eligibility test was performed. There was no
invitation prompt for this already-enrolled account. That observation does not
prove every account/country can enroll. No uninstall, clear-data, force-stop,
local build installation, rating, store submission or account-setting change
occurred.

## Installed artifact and source provenance

The device supplied a base APK and an `arm64-v8a` configuration split. Both were
copied read-only into the ignored evidence directory and verified with Android
SDK `apksigner`. Their package version code is `8`; the base reports version
name `0.2.0`. Both signatures verify under the same delivered-app signer.

| Artifact / field | Actual value |
|---|---|
| Installed base APK | `1,221,421` bytes; SHA-256 `d34417d31d8c8d08fa52458f34657b5b1961cdcacb6b239bf78b8bfafa738e6a` |
| Installed `config.arm64_v8a` APK | `19,714,340` bytes; SHA-256 `f211bc7be13509a4084f4596dda010e0c39e73fb6ad8bdceefc717c6f14b748a` |
| Delivered-app signer certificate | SHA-256 `e3c1334dc7aad1ae20fe043b52c2d5638584a67a66e6a5255a87bf89f56f06d0` |
| Retained historical AAB | Rehashed during this retry: SHA-256 `ee2439589e2c2195ef4c861b524f871b0e5168e84fbea60a1cd379319c6eb5d7`, matching the 10 September handoff |
| Historical source binding | Commit `768fafe45beee7731d1a38480cc0463a2f5680cd`; app tree `27fd1a264a576e68126c38f966db328559660249`, as recorded in that handoff |
| Compiled Dart application | Installed `lib/arm64-v8a/libapp.so` SHA-256 `77108c759dc7f1668f4a1a787663629062dd6bea0db824a0eda145f17982db9a`; byte-identical to the historical AAB entry |
| Android DEX code | Installed `classes.dex` SHA-256 `6baa7d569a6ba4507f4acc52af0a98abd858ae6a3c14dabff8e1c61df73f2f4c`; byte-identical to historical `base/dex/classes.dex` |
| Compared payload set | **38/38 identical:** 35 Flutter asset files, two native libraries (`libapp.so` and `libflutter.so`) and one DEX file; none of these installed payloads lacked a historical AAB counterpart |

The comparison hashes the uncompressed ZIP-entry bytes. Installed asset/native
paths map to the AAB's `base/` paths; `classes.dex` maps to
`base/dex/classes.dex`. This establishes a concrete payload link to the retained
build-8 artifact and its recorded source, stronger than matching a version
label alone.

It is not a whole-artifact equality or a reproducible-build result. Play creates
and signs delivery splits, so their digests differ from the upload AAB and local
APK. Android manifests, resource tables and signing records are outside the
38-payload comparison. The delivered base/split manifests report minimum SDK
`29` and the base targets SDK `36`; the historical AAB handoff reports minimum
SDK `24`. This device-specific observation does not redefine the product's
universal OS requirement or explain the manifest transformation. Console upload
history, country targeting and the signer certificate shown in Console were
not inspected.

## Repeatable read-only procedure

Use the selected connected device, keep personal device/account identifiers out
of published logs, and retain complete outputs privately.

```sh
adb -s '<device>' shell dumpsys package dev.pyble.pyble
adb -s '<device>' shell am start \
  -a android.intent.action.VIEW \
  -d 'market://details?id=dev.pyble.pyble' \
  -p com.android.vending
adb -s '<device>' shell uiautomator dump /sdcard/pyble-c1-ui.xml
adb -s '<device>' exec-out cat /sdcard/pyble-c1-ui.xml
adb -s '<device>' exec-out screencap -p
adb -s '<device>' shell pm path dev.pyble.pyble
adb -s '<device>' pull '<returned-apk-path>' '<private-evidence-apk>'
apksigner verify --print-certs '<private-evidence-apk>'
aapt dump badging '<private-evidence-apk>'
```

Capture the channel UI before using its Open action; then inspect About and
capture the displayed identity. Resolve each returned APK separately. Compare
only like-for-like uncompressed payload entries against the rehashed historical
AAB. The temporary device UI XML was removed after the private capture; device
coordinates and serials are intentionally omitted from this reusable procedure.

## Retained evidence

Raw UI XML/screenshots, package output, APKs, certificate checks and comparison
details remain under the main workspace's ignored
`local/c1-s1/2026-09-25-retry/android/`. They are not committed. Account/device
identifiers are excluded from this report. These hashes identify the actual
private captures, which may contain metadata beyond the selected public fields.

| Capture | SHA-256 | What it establishes |
|---|---|---|
| `play-listing-first.xml` | `4ef1211ff53b935d28781d5b74fcc18c014cc734e7d6f1b06607c111c4b31934` | Actual listing, beta membership, open-testing notes and Open action |
| `play-listing.png` | `cac6d520c23637e256ed09d7086b717b6fb406c034d5db50aa2c368d6096d9b3` | Retained device screenshot of the listing |
| `app-open.xml` | `993a74964fcef3b2b57b5d50590345918d97660c3f2fd988a91fe9c4832a7ff1` | App rendered after Play's Open action |
| `app-about.xml` | `66142bb0ad9271a347ef5fbf6221872914f54e512b3dbf622561bf2a3d687266` | About identity `0.2.0 (8)` |
| `app-about.png` | `f9a07e3f092c45758a03351c755978c3cc1135f09969c07dbfdc94bea4904ad7` | Retained device screenshot of About |
| `package-dump.txt` | `fbc9d1689ca2dc590f69846e5a7dc15b862ccded5785808cbd25fa4876d57b4e` | Initial installed package/build and installer metadata |
| `package-dump-after.txt` | `2d20c4416aeced749a679d4eeb5342bf039926065aabb549ff3ba53162709639` | Package observation after the UI check |
| `payload-comparison.json` | `d6535850c912c974ba4804f90818a7c9c561682c035614181f12fc7afd533476` | All 38 entry-by-entry comparisons and artifact digest |
| `installed-00-signer.txt`, `installed-01-signer.txt` | `ad8012fcd96316866cfc8ff7a772d3e84933a2ebf15392dca54896704a9ec03f` each | Successful signature verification and identical signer output |

The result closes Android device access and installed-channel verification for
C1-S1-T02. It does not qualify BLE behavior, firmware/profile compatibility,
draft persistence, first-install or upgrade behavior, or participant usability.
No pilot activation, human observation or PyBLE Ready reproduction is inferred.
