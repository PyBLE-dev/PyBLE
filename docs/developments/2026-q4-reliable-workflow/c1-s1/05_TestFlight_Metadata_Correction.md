<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# C1-S1 — TestFlight app-level metadata correction

| Field | Record |
|---|---|
| Discovered | 25 September 2026, during C1-S1-T01 |
| Backlog | PYB-002.1, newly identified residual copy discrepancy; the earlier Android correction remains complete |
| State | Replacement copy prepared; App Store Connect change and public verification pending |
| Action owner | Project maintainer / App Store Connect owner; store access not used in this execution |
| Evidence | [Channel ledger](01_Channel_and_Artifact_Ledger.md), public TestFlight response and retained body hash |

The live public invitation's description still presents the older ESP-family/agent-0.4.0 scope. A capability-defined app description should explain how to select the correct tested setup without implying that every current board/profile works with an unidentified TestFlight build. The historical [build-5 handoff](../../../testing/testflight/0.2.0-build-5.md) remains unchanged.

## Prepared Beta App Description

The following is app-level copy for review against the actual offered build. It is not a build-specific “What to Test” entry and does not announce a new binary, production release or completed compatibility matrix.

```text
PyBLE (Python over Bluetooth Low Energy) is a free, open-source, tablet-first MicroPython IDE. It connects over BLE to a compatible board running the PBLE/1 PyBLE agent, so you can edit and transfer Python files, run and stop programs, inspect console output, manage board files, and use offline Blocks.

A Bluetooth-capable board running stock MicroPython is not automatically compatible. Before starting, check https://pyble.dev/flash for exact board and firmware requirements, and follow the compatibility instructions for the TestFlight build you install. Initial firmware installation or recovery may require a computer and USB cable. After provisioning, the normal development workflow uses BLE.

This is a TestFlight beta. See https://pyble.dev/learn for setup and first-program guidance, https://pyble.dev/support for help, and https://pyble.dev/privacy for the privacy policy. Use harmless test programs and back up important work. Local editor drafts in the current working-loop implementation do not survive an app restart; saving to the board is a separate explicit action.

PyBLE is MIT-licensed and developed in public at https://github.com/PyBLE-dev/PyBLE. The app has no required account, advertising, analytics, subscriptions or purchases. Optional public GitHub example import requires Internet access; the normal board workflow uses BLE.
```

## Owner handoff and completion criteria

| Action | Required evidence / boundary |
|---|---|
| Identify the offered TestFlight build | Record actual version/build and source mapping or unknowns before changing build-specific compatibility or test instructions |
| Check the app-level description | Confirm the offered build supports the described core features; adjust a claim if its actual artifact differs |
| Apply the metadata through App Store Connect | Record the actual field, locale, saved/submitted state and date; avoid touching unrelated listing fields or version history |
| Keep build-specific notes separate | Use notes tied to the selected artifact; do not paste the old build-5 notes into a different build or assert untested five-profile compatibility |
| Verify the public invitation | Retrieve the public page again and verify the corrected description when Apple exposes it; retain a dated response hash and pending processing state if applicable |
| Close PYB-002.1 | Both the actual metadata update and public verification must be evidenced; preparing this packet alone does not complete the correction |

This residual task does not block preparation of the persistence contract or otherwise qualified maintenance work. No paid feature, app allowlist, new protocol behavior or PyBLE Ready claim is introduced.
