<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE 0.3.0 (9) — prepared app release packet

Prepared 31 October 2026. This is candidate copy for the existing Google Play
open-testing and TestFlight channels. It does not announce availability, a
submission, or store delivery. Engineering admission is accepted for the frozen
artifacts; final PR checks and merge precede publishing. The [readiness record](../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md)
owns the artifact and gate states. Confirm that build 9 is unused in each
account before uploading; a consumed number requires a new source version
contract and rebuilt artifacts, not a renamed file.

## Google Play release notes

```text
PyBLE can keep one current Python draft locally and offer Restore or Discard after restart. Local recovery status is separate from board saving. Recovered text needs current-destination confirmation before board Save, Run or Upload. Landscape editing stays usable above the keyboard. Blocks workspaces and multi-file projects are not included in draft recovery. Board workflows require a compatible MicroPython board running the PyBLE agent.
```

## TestFlight — What to Test

```text
Test local recovery of the current Python text draft in PyBLE 0.3.0 (9).

Use a compatible, separately provisioned MicroPython board running the PyBLE agent. Keep test hardware free of hazardous loads. About identifies the installed app version; record the board profile and agent version with feedback.

1. Edit a disposable Python draft, choose Save recovery copy, and wait for Saved locally. Close the app process and reopen it without deleting or reinstalling the app. Check the exact text and filename in the recovery preview.
2. Restore while disconnected. Recovery should preserve the text without connecting to or writing to a board. Cancel a Discard confirmation, then confirm Discard using only disposable content; check the next launch.
3. Deliberately connect to a board. Check the current destination and separate Save/Run effects before confirming. Cancel a confirmation and verify that no unwanted board action occurs.
4. Copy generated Python from Blocks into Editor, save its recovery copy, and restart. Only the generated text is covered; the Blocks workspace, graph revisions and companion files are not restored by this local slot.
5. Exercise New, Board Open, Files Upload, disconnect/reconnect, portrait/landscape, larger text, an external keyboard and VoiceOver where available. On iPad, hide and reopen the docked keyboard through its input palette, then check that console Expand remains reachable and dismisses it. Report any lost text, stale destination, inaccessible control or inaccurate success message.

There is one recovery slot and no draft history. Wait for Saved locally before expecting an edit to survive termination. Storage failure can leave current edits only in memory; follow the displayed guidance. App removal or clearing app storage removes local recovery data. A draft that existed only in memory in an older version cannot be recovered by upgrading.

Include app version/build, tablet/OS, exact board profile and agent version, numbered steps, expected and actual behavior, and whether the event followed an app restart or board switch. Omit private source, device identifiers, credentials and personal data from public reports.
```

Keep the existing maintained contact/review information and hardware-access
instructions in the account. Verify them against the current form rather than
inventing reviewer access, audience declarations, privacy attestation or a
store review result. No tester invitation is sent by preparing this packet.

## Installed store baseline before delivery

| Platform | Existing production/store identity | Release implication |
|---|---|---|
| iPad | PyBLE `0.2.0 (6)` | Preserve this installed-store baseline for the eventual TestFlight upgrade receipt; the local Preview `0.3.0 (9)` is separate evidence |
| Lenovo Android | `dev.pyble.pyble` `0.2.0`, versionCode `8`; installing and initiating package `com.android.vending`, with the Play certificate recorded in readiness | Preserve this Play-signed app and its data; the isolated qualifier `0.3.0 (9)` is separate evidence and the upload-key APK is not a compatible replacement for the Play-signed install |

These installed baselines do not reveal whether a newer build number has
already been uploaded to either account. Confirm account history before
submission and record store-delivered About identity after actual delivery.

## Artifact and channel handoff

| Step | Required result |
|---|---|
| Candidate | Final accepted source/app tree, locked dependencies, exact signed artifact hashes, full `0.3.0 (9)` identity and retained checks |
| Android package | `dev.pyble.pyble`, production flavor, normal `lib/main.dart`; existing owner upload signer, AAB validation and native alignment checks |
| iOS package | `dev.pyble.pyble`, normal `lib/main.dart`, distribution export and successful `tools/validate_ios_ipa.sh` |
| Admission | Accepted recovery evidence, required app/profile matrix, packaging/provenance review and no unresolved release-blocking defect |
| Account checks | Unused build numbers; current upload/signing identity, account role, declarations, review contact and hardware instructions |
| Submit | Upload only admitted artifacts; record processing and review outcomes independently on Play and App Store Connect |
| Verify delivery | Record actual track/group availability, then store-delivered installation/upgrade, About identity and a scoped launch/workflow check |
| Public copy | Update release availability only after observing it; preserve each platform's actual status |

The isolated development applications used for engineering tests have different
application identities. Their successful installation does not prove an upgrade
of `dev.pyble.pyble`, store processing, or store delivery. A distribution export
also does not establish successful execution on the physical tablet.

The [dependency review](../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md#dependency-review-scope)
records the current website audit separately from the frozen mobile artifact:
no high/critical findings, with moderate web-tooling findings still open for
maintenance. It does not claim that every dependency is vulnerability-free.

## Privacy and recovery scope

Candidate 0.3.0 adds an app-private local database containing one current text
draft and bounded recovery metadata. See the dated addendum in the
[Data safety assessment](google-play-data-safety.md#31-october-2026--candidate-030-local-recovery-addendum).
The slot has no app-managed cloud synchronization. OS backup behavior remains
subject to platform and user settings. Board files and exported copies have
their own retention boundaries; Discard does not delete them.

## Official submission references checked 31 October 2026

- Google requires new app/update submissions to target API 36 or higher under
  the current mobile-app rule: [target API requirements](https://support.google.com/googleplay/android-developer/answer/11926878).
- Apps targeting Android 15 and higher must support 16 KiB pages on 64-bit
  devices: [Android page-size guidance](https://developer.android.com/guide/practices/page-sizes).
- Apple accepts uploads through its supported tools with the appropriate
  account role; processing must finish before the build appears in App Store
  Connect: [upload builds](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/).

These public requirements do not reveal this application's private account
history or satisfy its project-specific hardware and release gates.
