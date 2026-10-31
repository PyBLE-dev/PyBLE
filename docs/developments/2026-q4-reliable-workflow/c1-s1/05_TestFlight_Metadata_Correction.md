<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# C1-S1 — TestFlight app-level metadata correction

| Field | Record |
|---|---|
| Discovered | 25 September 2026, during C1-S1-T01 |
| Backlog | PYB-002.1, newly identified residual copy discrepancy; the earlier Android correction remains complete |
| State | Done for PYB-002.1 on 31 October: English (U.S.) app description saved, exactly reloaded and independently verified in the public response |
| Action owner | User-authorized App Store Connect operation through the owner-authenticated browser; original S1 preparation used no store access |
| Evidence | [Channel ledger](01_Channel_and_Artifact_Ledger.md), public TestFlight response and retained body hash; [physical iPad verification](07_iPad_Channel_Verification.md) |

The 25 September public invitation's description presented the older ESP-family/agent-0.4.0 scope. A capability-defined app description should explain how to select the correct tested setup without implying that every current board/profile works with an unidentified TestFlight build. The historical [build-5 handoff](../../../testing/testflight/0.2.0-build-5.md) remains unchanged.

The later device retry establishes that the observed native TestFlight offer and installed beta are `0.2.0 (6)`, with a successful launch and TestFlight signing origin. Its source/archive mapping remains unknown. Installed metadata reports `MinimumOSVersion = 18.0` while the build notes describe an iOS/iPadOS 15 rebuild; reconcile that difference with archive and store eligibility before publishing an older-OS support claim. This discovery does not change the public description or the historical build-5 handoff.

## Historical prepared description for the recorded 0.2.0 baseline

The following is app-level copy for review against the actual offered build. It is not a build-specific “What to Test” entry and does not announce a new binary, production release or completed compatibility matrix.

```text
PyBLE (Python over Bluetooth Low Energy) is a free, open-source, tablet-first MicroPython IDE. It connects over BLE to a compatible board running the PBLE/1 PyBLE agent, so you can edit and transfer Python files, run and stop programs, inspect console output, manage board files, and use offline Blocks.

A Bluetooth-capable board running stock MicroPython is not automatically compatible. Before starting, check https://pyble.dev/flash for exact board and firmware requirements, and follow the compatibility instructions for the TestFlight build you install. Initial firmware installation or recovery may require a computer and USB cable. After provisioning, the normal development workflow uses BLE.

This is a TestFlight beta. See https://pyble.dev/learn for setup and first-program guidance, https://pyble.dev/support for help, and https://pyble.dev/privacy for the privacy policy. Use harmless test programs and back up important work. Local editor drafts in the current working-loop implementation do not survive an app restart; saving to the board is a separate explicit action.

PyBLE is MIT-licensed and developed in public at https://github.com/PyBLE-dev/PyBLE. The app has no required account, advertising, analytics, subscriptions or purchases. Optional public GitHub example import requires Internet access; the normal board workflow uses BLE.
```

## Original owner handoff and completion criteria

| Action | Required evidence / boundary |
|---|---|
| Identify the offered TestFlight build | Observed build is `0.2.0 (6)` on 25 September; retain unknown archive/source mapping and recheck the offer before changing build-specific compatibility or test instructions |
| Reconcile minimum OS | Check installed variant metadata (18), build notes (15), archive and actual store eligibility; avoid promising support on an untested older OS |
| Check the app-level description | Confirm the offered build supports the described core features; adjust a claim if its actual artifact differs |
| Apply the metadata through App Store Connect | Record the actual field, locale, saved/submitted state and date; avoid touching unrelated listing fields or version history |
| Keep build-specific notes separate | Use notes tied to the selected artifact; do not paste the old build-5 notes into a different build or assert untested five-profile compatibility |
| Verify the public invitation | Retrieve the public page again and verify the corrected description when Apple exposes it; retain a dated response hash and pending processing state if applicable |
| Close PYB-002.1 | Both the actual metadata update and public verification must be evidenced; preparing this packet alone does not complete the correction |

This residual task does not block preparation of the persistence contract or otherwise qualified maintenance work. No paid feature, app allowlist, new protocol behavior or PyBLE Ready claim is introduced.

## 31 October 2026 public-page recheck

A fresh HTTPS GET of the [public TestFlight invitation](https://testflight.apple.com/join/yU4e8s6d)
at 11:46 UTC returned HTTP 200 and still showed the old three-ESP-profile and
agent-`0.4.0` description. PYB-002.1 remained unresolved at that checkpoint. The public
page does not establish a currently offered build, archive/source identity or
eligibility for a particular device.

Raw response and receipt: ignored
`local/recovery-completion/public-channel-recheck/testflight.html` and
`testflight-receipt.json`; response SHA-256
`78b9fb6bf3ff04ce12dfdf0e2a24ae694d0fda50cc1b8a468ae5d01c8277fdfb`.
No metadata was changed during that early recheck. The later completion below
supersedes its pending status and updates the old draft-durability sentence for
the actual `0.3.0 (9)` offer; the original proposal remains historical.


## 31 October published description and closure

The user authorized test details and external-testing setup for `0.3.0 (9)`.
Through the authenticated App Store Connect browser, the English (U.S.) Beta
App Description was saved and exactly verified after reload. The original
717-character description remains privately backed up. The saved replacement
is 1,523 characters with SHA-256
`6153fd0834440d4c47eec30743d3b0dd8988519e9bfd1fad9da377c5a06ff27a`:

```text
PyBLE (Python over Bluetooth Low Energy) is a free, open-source, tablet-first MicroPython IDE. It connects over BLE to a compatible board running the PBLE/1 PyBLE agent, so you can edit and transfer Python files, run and stop programs, inspect console output, manage board files, and use offline Blocks.

A Bluetooth-capable board running stock MicroPython is not automatically compatible. Before starting, check https://pyble.dev/flash for exact board and firmware requirements, and follow the compatibility instructions for the TestFlight build you install. Initial firmware installation or recovery may require a computer and USB cable. After provisioning, the normal development workflow uses BLE.

This is a TestFlight beta. See https://pyble.dev/learn for setup and first-program guidance, https://pyble.dev/support for help, and https://pyble.dev/privacy for the privacy policy. Use harmless test programs and back up important work. In PyBLE 0.3.0, one current Python text draft can be saved locally and offered for Restore or Discard after restart. Wait for Saved locally before closing the app; saving to the board remains a separate explicit action. Local recovery does not include Blocks workspaces, multiple-file projects or draft history.

PyBLE is MIT-licensed and developed in public at https://github.com/PyBLE-dev/PyBLE. The app has no required account, advertising, analytics, subscriptions or purchases. Optional public GitHub example import requires Internet access; the normal board workflow uses BLE.
```

An independent fresh GET of the [public invitation](https://testflight.apple.com/join/yU4e8s6d)
at `2026-10-31T14:52:55Z` returned HTTP 200. Its rendered description, normalized
only for whitespace, exactly matched the saved replacement. The old agent
`0.4.0` and ESP-only opening were absent; the version-specific recovery copy
was visible. Public HTML SHA-256 is
`eb23bd0b6a80d208797fe85e37673bfa989cbef7c7bfc069d9540cce6a628c45`.
The search/browser extraction still returned an older cached rendering; that
is distinct from the fresh direct response and is not a failed publication.

Private evidence is retained under `local/recovery-completion/ipad/`:
`testflight-beta-description.txt`, `asc-description-verify` captures and
`public-testflight-description-recheck/20261031T145255Z.{html,json}`.
The actual field save/reload and public verification complete **PYB-002.1**.
The separately saved build-specific test details are recorded in the
[release packet](../../../publication/app-0.3.0-build-9-release-packet.md#testflight--what-to-test).

Description publication does not establish external-group build-9 approval,
universal eligibility or fresh firmware qualification. The build-6 archive
mapping/minimum-OS discrepancy remains historical and unresolved; this copy
makes no new older-OS support claim. Internal-account build-9 installation and
smoke evidence are recorded in the [delivery continuation](../c1-s2/06_Release_Readiness.md#31-october-testflight-delivery-and-published-metadata).
