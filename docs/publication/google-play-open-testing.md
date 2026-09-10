# PyBLE Google Play open-testing submission packet

Prepared **2026-09-10** for candidate **`0.2.0 (8)`**, package
**`dev.pyble.pyble`**. The owner reports that open testing is enabled. This
packet prepares the app information and release handoff; it does not claim
that Play Console has received, approved or published a release.

Build `8` is a proposed fresh identity after locally retained builds `5`, `6`
and `7`. Confirm it exceeds every version code already used in Play Console,
including discarded uploads, before finalizing the bundle. If not, select the
next unused code and update every candidate reference here before building.

## Files to use

| Material | File |
| --- | --- |
| Store app name | [`title.txt`](google-play/en-US/title.txt) |
| Short description | [`short-description.txt`](google-play/en-US/short-description.txt) |
| Full description | [`full-description.txt`](google-play/en-US/full-description.txt) |
| Release notes, including Console language tags | [`release-notes.txt`](google-play/en-US/release-notes.txt) |
| Concise reviewer instructions | [`app-access.txt`](google-play/en-US/app-access.txt) |
| Detailed reviewer setup and review flow | [Reviewer guide](google-play-reviewer-guide.md) |
| Tester onboarding, scenarios, feedback template and exit criteria | [Tester guide](google-play-tester-guide.md) |
| Invitation draft, to complete after the track is live | [`tester-invitation.txt`](google-play/en-US/tester-invitation.txt) |
| Data safety and permission assessment | [Data safety worksheet](google-play-data-safety.md) |
| Icon, feature graphic and screenshot preparation/provenance | [Asset guide](google-play-assets.md) |
| Built AAB/APK, hashes, signer and completed validation | [Build 8 artifact handoff](../testing/google-play/0.2.0-build-8.md) |

Text files contain the field content only. Paste the release-note language
tags as provided; omit filenames/headings. The other files are maintainer
guidance, not text to paste wholesale into the listing.

The invitation is a separate draft message, not a Play listing field. Replace
its opt-in placeholder, confirm the installed version and send it only after
the release is actually available. Preparing this file does not send it.

## Store settings

| Field | Prepared value or required decision |
| --- | --- |
| Existing app | Use the existing `dev.pyble.pyble` Play Console app; do not create another package. |
| App/game | **App** |
| Display name | **PyBLE: MicroPython over BLE** |
| Default language | **English (United States), en-US** |
| Category | Proposed **Tools**, reflecting the general-purpose MicroPython IDE. Education is an alternative if the owner chooses that positioning. |
| Tags | Choose only available Console tags matching programming/development and the actual feature set; do not fabricate tags or use unrelated discovery terms. |
| Price | **Free**; no in-app products or subscriptions. |
| Website | `https://pyble.dev` |
| Support website | `https://pyble.dev/support` |
| Support email | `viwat.v@chula.ac.th` — already public in the project's site configuration. |
| Public phone | Optional; leave blank unless the owner chooses a maintained public number. |
| Privacy policy | `https://pyble.dev/privacy` |
| Developer identity/address/verification | Keep the verified account's real legal/contact information. Repository branding does not establish what is verified in Console. |

Google's listing limits are 30 characters for name, 80 for short description
and 4,000 for full description; the contact email is required. The listing is
shared across tracks, so review its effect on existing testers too.
[Create and set up your app](https://support.google.com/googleplay/android-developer/answer/9859152?hl=en).

Only the English UI locale is currently implemented. This packet provides
English metadata and does not advertise translated app interfaces. The full
description prominently states that the connected IDE requires a compatible
physical board and initial computer-based firmware setup.

## Open-testing settings

These are prepared defaults pending the owner's country/audience choices and
the account's live Console availability:

| Setting | Prepared value |
| --- | --- |
| Track | **Testing → Open testing** |
| Suggested release name | **`0.2.0 (8) - open testing`** |
| Countries/regions | **All available countries/regions**, after checking distribution availability and audience obligations for those countries. |
| Tester count | **Unlimited** |
| Feedback channel | **`viwat.v@chula.ac.th`**; public support URL is an alternative. |
| Proposed target age groups | **13–15, 16–17, 18 and over**, only if these are the genuine designed audiences. |
| Opt-in link | Copy the actual link from the published open-test track. No verified live link is available in this packet. |
| Listing URL | `https://play.google.com/store/apps/details?id=dev.pyble.pyble` — existing package address, not proof of open-test availability. |

Google allows unlimited open-test participants; a numeric cap must be at least
1,000. The feedback channel appears on the opt-in page. Internal-test members
must leave that track before receiving open-test builds. Publish/review status
controls when the opt-in page becomes available.
[Testing-track setup](https://support.google.com/googleplay/android-developer/answer/9845334?hl=en).

Audience is a product decision, separate from the IARC content rating. Do not
check all ages simply to maximize reach or claim a rating before completing
the questionnaire. Child-status rules vary by country; Google asks developers
targeting users under 21 to assess applicable local obligations. The Data
safety worksheet records the audience-dependent Families/BLE review.
[Audience guidance](https://support.google.com/googleplay/android-developer/answer/9867159?hl=en).

## App content declarations

These values follow the audited app source. The owner must attest that they
also describe the exact artifact and all relevant live behavior. Console may
show additional declarations based on its current dashboard or the selected
countries/category.

| Form | Prepared answer or action |
| --- | --- |
| Privacy policy | Use `https://pyble.dev/privacy`; verify live access without login and matching in-app full policy. |
| Ads | **No**; no advertising UI or ad SDK is present. |
| App access | **Some functionality needs special access**: the connected IDE needs external BLE hardware. Use the reviewer instructions; no login credentials exist. |
| Content rating | Complete the IARC questionnaire; no resulting rating is preselected or claimed. Use the factual worksheet below. |
| Target audience/content | Owner confirmation of proposed 13–15, 16–17, 18+ and corresponding country obligations. |
| Data safety | Review and attest the complete five-type recommendation in the dedicated worksheet, including its clearly marked provider-policy inferences. **Do not copy a blanket "no data collected" answer from internal testing.** |
| Advertising ID | **No** in the audited source; check the merged release manifest and SDK inventory. |
| Account creation/deletion | **No account creation**; account-deletion requirement is not triggered by a nonexistent account. Board-file deletion is a separate workflow. |
| Financial features | **No financial features**. |
| Health apps | **No health features**. |
| Government app | **No**. |
| News app | **No**. |
| Foreground service / background location / all-files access / VPN / accessibility service / photo-video permissions | None declared in the audited main manifest; answer only if the final bundle or Console actually triggers a declaration, after inspecting it. |

App content is where Google collects privacy, ads, access, rating and other
policy declarations. Complete every applicable "Needs attention" item before
sending the release for review.
[Prepare your app for review](https://support.google.com/googleplay/android-developer/answer/9859455?hl=en).

### Content-rating worksheet

Use a maintained contact email (`viwat.v@chula.ac.th`) and the questionnaire
category matching an ordinary utility/IDE, such as its other-app category if
offered. Answer the actual questions, which can change with earlier answers.

| Factual question area | App facts to use |
| --- | --- |
| Violence, sexual content, profanity, horror, drugs, gambling in authored content | None in the reviewed bundled app/examples. |
| Real-money or simulated gambling, betting, prizes, purchases | No implemented feature. |
| User-to-user communication, chat, social network | No implemented in-app feature. BLE console is communication with the user's microcontroller. |
| Sharing current physical location with other users | No implemented feature; legacy Android BLE permission does not mean the app derives/shares location. |
| User-created/downloaded content | **Present**: users edit arbitrary Python and can import arbitrary public GitHub `.py` content. Disclose it wherever the question's scope includes this behavior. |
| Unrestricted web browsing | No general web browser; importer is restricted to public GitHub API requests, and bundled Blockly runs locally. |
| Content filtering of imported source | No promise that arbitrary public repository content is age-filtered or curated. The official examples default does not prevent choosing another public repository. |

Retain the returned rating certificate and review whether the questionnaire's
downloaded-content questions introduce further requirements. No "Everyone,"
"PEGI 3," "Teacher Approved" or similar label is asserted by this packet.

## Build and technical handoff

The signed candidate has been built. Use the
[artifact handoff](../testing/google-play/0.2.0-build-8.md) for its verified
source, filenames, SHA-256 values, signer and test results; the steps below
also document how to prepare a replacement if Console requires another code.

Use the **production release App Bundle**, package `dev.pyble.pyble`. The
`.integrationtest` flavor, debug APKs and CI's temporary signing key are not
upload artifacts. The current pinned Flutter toolchain resolves minimum API
24 and target/compile API 36; verify these in the resulting bundle.

Since 2026-08-31, Google requires API 36 or newer for new phone/tablet apps and
updates. Do not rely on the lower existing-app availability threshold.
[Target API requirements](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en).

1. Confirm version code `8` is unused and higher than all prior uploads. Update
   source identity if another code is needed; do not label different bytes as
   the same already distributed build.
2. Use the existing owner-controlled upload key and secure local signing
   configuration. The release Gradle contract reads
   `PYBLE_ANDROID_KEYSTORE_PATH`, `PYBLE_ANDROID_KEYSTORE_PASSWORD`,
   `PYBLE_ANDROID_KEY_ALIAS` and `PYBLE_ANDROID_KEY_PASSWORD`. Keep their
   values and the keystore outside Git and logs. Do not create a replacement
   identity when the established key is needed.
3. Run the app checks in [`app/README.md`](../../app/README.md), the Android
   integration gate and appropriate release validation; retain logs outside
   Git. Run `tools/ci/no_leak.sh` before any later commit and use DCO sign-off.
4. Build from the approved source using the pinned toolchain and locked
   dependencies:

   ```sh
   cd app
   flutter pub get --enforce-lockfile
   flutter build appbundle --release --flavor production --target lib/main.dart
   ```

5. Verify AAB signature, established upload certificate, package, version,
   minimum/target SDK, native ABIs, merged permissions and bundletool
   validation. Confirm the upload certificate against Console → App integrity;
   it differs from Google's app-signing certificate used for delivered APKs.
6. Check both native ELF segment alignment and generated APK ZIP alignment for
   16 KB devices; run a compatible emulator/device smoke test. Flutter embeds
   native libraries, so a Dart-only feature set is not an exemption.
   [Android 16 KB compatibility](https://developer.android.com/guide/practices/page-sizes).
7. Perform physical Android BLE acceptance against the exact final bundle and
   firmware, plus fresh-install and Play-upgrade checks. An upload-key-signed
   local APK may not update a Google app-signing-key-installed copy; test the
   store upgrade through Play rather than interpreting this expected signing
   difference as an app regression.

The earlier Android build-4 handoff records this upload-certificate SHA-256:

```text
DC:A9:5C:50:60:CD:F4:93:6F:19:FD:8C:32:12:A8:71:C2:23:E2:BA:3F:B6:7B:62:26:17:9A:FF:DA:62:DD:57
```

Historical source:
`build/google-play-0.1.0-build-4:docs/testing/google-play/0.1.0-build-4.md`.
It is a useful continuity check, not confirmation of the current Console
certificate or proof that the old bundle was published.

Record the final filename, size, SHA-256, source commit/diff identity, signing
certificate, version name/code, SDKs, ABIs and test results in the ignored
handoff directory. Retain native debug symbols/mapping outputs if generated;
upload applicable symbols through Console to make crash reports actionable.

## Visual assets

Use the [asset guide](google-play-assets.md) for actual files, provenance and
remaining captures. Required listing materials include a 512×512 PNG icon, a
1024×500 JPEG or opaque PNG feature graphic, and at least two screenshots
across supported device types. Screenshots must be 320–3840 pixels per side,
with the longer dimension no more than twice the shorter. Google allows up to
eight per device type. Follow the separate tablet-specific and promotion
recommendations in the live Console. [Preview asset specifications](https://support.google.com/googleplay/android-developer/answer/9866151?hl=en).

Show the actual Android app. A useful set covers editor/console, Files,
Blocks, GitHub review, Connect and privacy. Only publish captures with reviewed
state and privacy; do not use iPad screenshots, test-fake boards or UI goldens.
The asset guide identifies authentic historical tablet captures whose depicted
surfaces remain representative of the current UI. Preserve that provenance;
they are listing illustrations, not this candidate's hardware evidence. A
feature graphic may use the canonical brand artwork; it must not imply awards,
rank or a production release. Promotional video is optional.

## Review and rollout checklist

Perform the preparation below before the final upload/review decision:

- [ ] Owner confirms final unused version code and candidate identity.
- [x] Exact signed production AAB, checksums, signature and technical checks
  are recorded and tied to current source.
- [ ] Physical BLE smoke, fresh install, upgrade and Android 16/layout checks
  are recorded; failures affecting core operation are fixed.
- [ ] Main listing, free price, category/tags and maintained contact completed.
- [x] Icon, feature graphic and ten phone/tablet screenshots validated and
  reviewed; historical core-feature captures retain their original provenance.
- [x] Full privacy policy available in-app and at the live URL.
- [ ] Data safety's recommended categories, purposes and sharing choices
  reviewed and attested, including conservative GitHub policy inferences.
- [ ] Owner confirms target ages and countries; relevant Families/BLE review
  complete.
- [ ] All Console App content forms completed truthfully and IARC rating
  certificate retained.
- [ ] Reviewer has an agreed workable path to a compatible physical board;
  instructions reference the production app and no imaginary demo account.

Then perform the Console handoff:

1. Select the existing app and inspect App integrity, Policy status, developer
   verification and the currently used version codes.
2. Open **Testing → Open testing**, configure countries, testers and feedback,
   and create the named release. Add the exact approved production AAB.
3. Paste [`release-notes.txt`](google-play/en-US/release-notes.txt). Google
   permits 500 Unicode characters per language, and the internal release name
   is not user-facing. [Release preparation](https://support.google.com/googleplay/android-developer/answer/9859348?hl=en).
4. Inspect generated device support, App Bundle Explorer, integrity findings,
   permission declarations, policy errors and pre-launch reports. Automated
   crawling cannot establish BLE-board operation; attach retained hardware
   evidence where review requests it.
5. Review the full change list and submit for review/rollout to **Open
   testing**. Record the actual submission and publishing state; do not infer
   approval from an accepted upload. Use managed publishing if available and
   appropriate for the account's release flow.
6. After the release is actually available, copy and test the open-test opt-in
   link using a non-internal tester account in a selected country. Verify that
   the installed About screen shows the intended build.
7. Share the tester guide and verified link, then update the website's invited
   internal-testing copy, QR destination, relevant website specification and
   tests in a separate verified publication change. Current website wording
   must not be switched before the open track is live.
8. Monitor Android vitals, pre-launch results, private Play feedback and the
   support inbox. Apply the tester guide's exit criteria before expanding to
   production. This packet does not designate version `1.0.0` or a production
   release; retain the project's cross-platform release/parity requirements.

## Remaining owner and Console information

The following items require the owner or live Console state; preparation does
not fabricate their answers:

- actual highest uploaded version code and registered upload certificate;
- physical release-candidate BLE and Play-delivered upgrade evidence;
- confirmed countries, target ages and any verification/account declarations;
- owner-attested Data safety form/export and generated IARC ratings;
- reviewer hardware arrangement;
- actual open-test opt-in URL, submission/review/availability status;
- screenshots of account-only settings and any support-case outcome.

The source packet, metadata files and reproducible assets can be reviewed
before these account-only fields are finalized. Keep private Console records,
signing material, raw screenshots and builds in the ignored local publication
workspace.
