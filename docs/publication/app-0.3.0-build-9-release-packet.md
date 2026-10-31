<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE 0.3.0 (9) — prepared app release packet

Recorded 31 October 2026 for the existing Google Play open-testing and
TestFlight channels. Engineering admission and [PR #41 integration](../developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md#pr-41-final-integration-receipt)
are complete. Apple accepted build `9`; later internal-account TestFlight
`0.3.0 (9)` offer/Open, production About and bounded physical smoke pass
([delivery record](../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md#31-october-testflight-delivery-and-published-metadata)).
The exact update transaction was not observed. Build 9 is assigned to the
existing PyBLE external group and submitted; the reloaded iOS Builds page
reports **Waiting for Review** ([submission receipt](../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md#31-october-external-testing-submission)).
This is not approval or an all-tester availability claim.
Apple build `9` is consumed: do not repeat its upload. A replacement binary
requires an explicit next-build contract and rebuilt artifacts. Google Play
submission remains pending: the Lenovo browser reached Console, but owner
verification is required to select the PyBLE publishing account. Check its
account history before uploading build `9`. A consumed number requires rebuilt
artifacts, not a renamed file.

## Google Play release notes

```text
PyBLE can keep one current Python draft locally and offer Restore or Discard after restart. Local recovery status is separate from board saving. Recovered text needs current-destination confirmation before board Save, Run or Upload. Landscape editing stays usable above the keyboard. Blocks workspaces and multi-file projects are not included in draft recovery. Board workflows require a compatible MicroPython board running the PyBLE agent.
```

## TestFlight — What to Test

English (U.S.), saved and exactly verified after reload on 31 October: 2,242
characters, SHA-256 `01d14e5a7c0bfd50ad77c9d0f4d4571ba7be058e064d430c81d7f6c3f0d7507b`.

```text
Test local recovery of the current Python text draft in PyBLE 0.3.0 (9). Open About and confirm Version 0.3.0 (9).

Use a compatible, separately provisioned MicroPython board running the PyBLE agent. Keep test hardware free of hazardous loads. About identifies the installed app version; record the board profile and agent version with feedback.

1. Edit a disposable Python draft, choose Save recovery copy, and wait for Saved locally. Close the app process and reopen it without deleting or reinstalling the app. Check the exact text and filename in the recovery preview.
2. Restore while disconnected. Recovery should preserve the text without connecting to or writing to a board. Cancel a Discard confirmation, then confirm Discard using only disposable content; check the next launch.
3. Deliberately connect to a board. Check the current destination and separate Save/Run effects before confirming. Cancel a confirmation and verify that no unwanted board action occurs.
4. In Blocks, choose Open in editor to adopt generated Python into Editor. Save its recovery copy and restart. Only the generated text is covered; the Blocks workspace, graph revisions and companion files are not restored by this local slot.
5. Exercise New, Board Open, Files Upload, disconnect/reconnect, portrait/landscape, larger text, an external keyboard and VoiceOver where available. On iPad, hide and reopen the docked keyboard through its input palette, then check that console Expand remains reachable and dismisses it. Report any lost text, stale destination, inaccessible control or inaccurate success message.

There is one recovery slot and no draft history. Wait for Saved locally before expecting an edit to survive termination. Storage failure can leave current edits only in memory; follow the displayed guidance. App removal or clearing app storage removes local recovery data. A draft that existed only in memory in an older version cannot be recovered by upgrading.

Include app version/build, tablet/OS, exact board profile and agent version, numbered steps, expected and actual behavior, and whether the event followed an app restart or board switch. Omit private source, device identifiers, credentials and personal data from public reports.
```

Keep the existing maintained contact/review information and hardware-access
instructions in the account. Verify them against the current form rather than
inventing reviewer access, audience declarations, privacy attestation or a
store review result. No tester invitation is sent by preparing this packet.

## App Store Connect review notes

Saved and exactly verified after reload on 31 October: 987 characters,
SHA-256 `140d744c27e3930b253cc43a1355a49311ba3b32db9f6626347132f52e532ca3`.
Existing review contacts and the sign-in requirement were retained. External
submission used the existing PyBLE external group with automatic tester
notification unchecked; no new testers were invited and no explicit Notify
Testers action was issued.

```text
PyBLE needs no sign-in or demo account. Startup, BLE scanning and About can be inspected without a board. File transfer, Run/Stop and board file management require a nearby compatible MicroPython board running the PBLE/1 PyBLE agent; stock MicroPython alone is not sufficient. Exact board profiles, firmware installation and first-program guidance are at https://pyble.dev/flash and https://pyble.dev/learn. After provisioning, select a board in the app and wait for Ready.

PyBLE 0.3.0 (9) adds explicit local recovery of one Python text draft. In a working session, choose Save recovery copy and wait for Saved locally before closing the app. On restart, Restore or Discard is a local action; board Save/Run/Upload requires current-target confirmation for recovered text. Blocks workspaces and multi-file projects are not restored. The build-specific What to Test provides the test sequence. Please use the maintained review contact if hardware access or setup clarification is needed.
```

## Historical baseline and current channel observations

| Platform | Existing production/store identity | Release implication |
|---|---|---|
| iPad | Historical `14:04–14:05 UTC` TestFlight snapshot offered `0.2.0 (6)`; later internal-account TestFlight offers `0.3.0 (9)` with Open, and production About/device smoke pass | Existing updated installation verified; exact update transaction unobserved. No manual update gesture or external-group availability inferred; local Preview remains separate evidence |
| Lenovo Android | `dev.pyble.pyble` `0.2.0`, versionCode `8`; installing and initiating package `com.android.vending`, with the Play certificate recorded in readiness | Preserve this Play-signed app and its data; the isolated qualifier `0.3.0 (9)` is separate evidence and the upload-key APK is not a compatible replacement for the Play-signed install |

These baseline observations do not reveal full account upload history. Apple
has accepted the recorded build-9 upload; confirm Google Play history
before submission. Record store-delivered About identity after actual delivery.

## Artifact and channel handoff

| Step | Required result |
|---|---|
| Candidate | Final accepted source/app tree, locked dependencies, exact signed artifact hashes, full `0.3.0 (9)` identity and retained checks |
| Android package | `dev.pyble.pyble`, production flavor, normal `lib/main.dart`; existing owner upload signer, AAB validation and native alignment checks |
| iOS package | `dev.pyble.pyble`, normal `lib/main.dart`, distribution export and successful `tools/validate_ios_ipa.sh` |
| Admission | Accepted recovery evidence, required app/profile matrix, packaging/provenance review and no unresolved release-blocking defect |
| Account checks | Apple accepted build 9; do not repeat it. Complete the owner verification in Lenovo Chrome, select the actual PyBLE publishing account, then verify Google Play build-9 availability, upload/signing identity, declarations and review instructions |
| Submit | Internal-account Apple delivery is verified; external build 9 is assigned/submitted and Waiting for Review. Upload the admitted Android artifact only after its independent account checks; retain each platform outcome |
| Verify delivery | Retain the completed internal-account iPad installation/About/smoke evidence and its transaction limit; verify external-group and Google Play outcomes separately |
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
