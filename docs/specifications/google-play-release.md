<!-- SPDX-License-Identifier: MIT -->

# Google Play open-testing preparation

Status: historical candidate preparation, 10 September 2026; publication status
updated 25 September 2026. This contract supplements
the [app distribution requirements](App/specs.md#9-build-versioning--distribution--bld)
and [ADR-0044](../decisions/0044-start-app-v020-beta-train-at-build-5.md).

At preparation time, the owner reported that the open-testing track was
available for the existing Play application. That preparation alone did not
establish a submitted or approved release.

## Published status — 25 September 2026

The owner confirms that PyBLE **0.2.0** is now published on Google Play for
Android **open testing**. The official
[listing](https://play.google.com/store/apps/details?id=dev.pyble.pyble)
identifies SciLabPro and describes open testing for this version. The
[publication review](../testing/website/android-open-testing-2026-09-25.md)
records the primary-source check.

Current README and website copy MUST reflect this live open-testing status,
as specified by [website §3.1](website.md#31-app-beta-distribution). Google Play
determines account, country, device, and testing availability. Do not infer a
production-track release, worldwide availability, or the installed artifact's
exact version code/source from the public version alone. Keep the official
listing as the public link; no signed-in opt-in workflow is asserted verified.

The preparation, artifact identities, and remaining historical checklists
below retain their original scope. Publication does not retroactively certify
unrecorded Console decisions, hardware evidence, or later source changes.

## Candidate identity

The 10 September candidate is **0.2.0 (8)**, owned by `app/pubspec.yaml`, for
production package `dev.pyble.pyble`. Build 5 remains a historical handoff;
retained local builds 6 and 7 must not be relabelled or replaced. The automated app-version
contract must bind build 8 to base version 0.2.0, PBLE/1 HELLO, and the existing
GitHub User-Agent. If Play Console has already consumed code 8 or higher,
increase this declaration and the version contract before rebuilding.

## App and submission contract

- About must expose the full app privacy policy offline, with the public
  policy URL and contact. Opening and leaving it must preserve the IDE and
  connection state. All UI copy must follow the existing localization and
  accessibility requirements.
- The app remains free, account-free, and BLE-first. This preparation adds no
  analytics, advertising SDK, remote execution, demo transport, or new network
  workflow. App features must remain at iOS/Android source parity.
- The Android bundle must use the production entry point and the existing
  upload key through BLD-12, with target API at least 36. Record its source
  commit, app-tree identity, version, SHA-256, signer, SDKs and native ABIs.
  Check the AAB signature, bundle structure, and 16 KiB native alignment.
  No signing material or generated binary belongs in Git.
- Store listing copy must describe implemented capabilities and the need for
  a compatible, separately provisioned board. Use the qualified firmware
  available on `pyble.dev/flash`; engineering v0.6.1 evidence must not be
  presented as published firmware qualification.
- Graphics must use the existing original PyBLE identity. Screenshots must
  be authentic and record device, source and build provenance. Historical
  captures, debug builds and emulators must be identified accurately; they
  cannot establish release-binary or physical BLE validation.
- The submission packet must supply English listing text, release notes,
  suggested app-content declarations with evidence and owner decisions,
  hardware-aware review instructions, tester setup, feedback guidance, test
  cases, artifact handoff, and the remaining Console steps. Official policy
  references must include their verification date.
- No data-collection exemption, all-transfers-encrypted answer, IARC rating,
  country selection, age declaration, reviewer hardware access, Play prelaunch
  result or store approval may be inferred from an account-free app. Record
  outstanding decisions explicitly.

## Verification and handoff

Run the focused privacy and version tests red before implementation, then the
app analyzer, ordinary tests, golden tests and repository source gates. Record
any stale golden requiring a reviewed update. Physical release-candidate BLE
checks and iOS distribution parity remain separate release gates; an emulator
or historical engineering report does not close them.

At the preparation handoff, the public website's testing status was to remain
unchanged until open testing became available. The dated publication status
above now governs current public copy. Console declarations, reviewer
arrangements, upload, review submission and rollout remain explicit handoff
steps. This preparation does not authorize sending tester messages or
publishing a production release.

## Official references

Verified 10 September 2026:

- [Open testing](https://support.google.com/googleplay/android-developer/answer/9845334)
- [Target API levels](https://support.google.com/googleplay/android-developer/answer/11926878)
- [User Data policy](https://support.google.com/googleplay/android-developer/answer/10144311)
- [Data safety](https://support.google.com/googleplay/android-developer/answer/10787469)
- [16 KiB page sizes](https://developer.android.com/guide/practices/page-sizes)
