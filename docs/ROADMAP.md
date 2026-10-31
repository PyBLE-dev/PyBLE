# Public roadmap

PyBLE is developed in public. This roadmap communicates direction rather than
promising dates; accepted work is tracked through GitHub issues and milestones.

The detailed [firmware v0.6.1 and v0.7.0 proposal](planning/firmware-v0.6.1-v0.7.0-roadmap.md)
records the post-v0.6.0 contract-hardening and Reliable Projects candidates.
The v0.6.1 hardening implementation has been published on owner confirmation;
v0.7.0 remains non-normative and requires separate maintainer approval.

## Available now

- iPad external beta through TestFlight
- Android PyBLE 0.2.0 published for
  [Google Play open testing](https://play.google.com/store/apps/details?id=dev.pyble.pyble),
  subject to Play's account, country, device, and testing availability
- PBLE/1 editing, run/stop, console, and file workflows over BLE
- Offline Blockly with beginner GPIO and NeoPixel examples
- The published firmware v0.6.1 covers five exact profiles: four ESP
  Web Serial installers and the verified Pico 2 W UF2/manual-BOOTSEL path.
  Publication follows the owner's qualification confirmation, recorded in the
  [owner confirmation](https://pyble.dev/firmware-v0.6.1-owner-confirmation.md).
  Incomplete automated evidence is preserved unchanged; the qualified v0.6.0
  release remains a separate historical baseline. The original qualification
  tracker [#24](https://github.com/PyBLE-dev/PyBLE/issues/24) was closed as
  superseded on 2026-09-13; its incomplete checklist is not marked completed.
- Guided [tutorials](https://pyble.dev/learn) with reviewed Lenovo captures,
  the [firmware functional reference](https://pyble.dev/features), and the
  separate [official example collection](https://github.com/PyBLE-dev/examples)
- MIT-licensed app, agent firmware, protocol, website, tests, and release tools

## Near term

- Complete the [C1-S1 remaining evidence](developments/2026-q4-reliable-workflow/c1-s1/00_Execution_Record.md):
  confirmed pilot ownership/setup, actual capacity and five real baseline
  observations. Existing Play 0.2.0 (8) and TestFlight 0.2.0 (6) installations
  and launches are verified on connected tablets; fresh enrollment/reinstallation
  was not exercised. The pilot kit, recovery design and validation inventory
  are prepared; this does not complete the Sprint or board qualification.
- Validate and qualify the implemented [bounded current-text recovery candidate](developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md)
  against the [contract](specifications/App/current-draft-recovery.md). Source
  candidate `0.3.0+9` supplies atomic local checkpoints and offline recovery;
  full A-24 and Blocks graph persistence remain separate scope. The original
  45–72 hour estimate remains a forecast, not measured effort.
- Correct the [stale public TestFlight description](developments/2026-q4-reliable-workflow/c1-s1/05_TestFlight_Metadata_Correction.md)
  through the distribution owner; replacement copy is prepared, not published.
- Prepare the next app `0.3.0+9` candidate while retaining the published 0.2.0 channel baseline. The
  [Android publication review](testing/website/android-open-testing-2026-09-25.md)
  records live open-testing availability. The
  [prepared build-8 handoff](testing/google-play/0.2.0-build-8.md) remains a
  source-specific historical record. The [current Android installation check](developments/2026-q4-reliable-workflow/c1-s1/06_Android_Channel_Verification.md)
  matches 38 retained code/asset entries to that AAB; this supports its historical
  source mapping, not complete binary equivalence or validation of subsequent
  source changes. The [iPad check](developments/2026-q4-reliable-workflow/c1-s1/07_iPad_Channel_Verification.md)
  records TestFlight build 6 with source mapping unresolved; distribution-owner
  review is needed for conflicting minimum-OS metadata before making a support
  claim.
- Review the proposed v0.7.0 Reliable Projects scope before implementation.
- Expand user-facing setup, recovery, and board-specific wiring guidance
- Gather Android open-testing feedback and improve installation and recovery
  guidance
- Convert remaining pre-public planning references into focused GitHub issues
- Improve automated app-to-board integration coverage

## Toward 1.0

- Stabilize public app and firmware release processes
- Publish a reusable PBLE/1 conformance kit for new board ports
- Define the maintainer process and evidence template for non-ESP32 ports
- Complete accessibility, localization, privacy, and security review
- Establish compatibility and deprecation guarantees for PBLE/1

## Future ports

PyBLE is not limited to ESP32. A proposed port should demonstrate:

1. supported MicroPython execution;
2. BLE GATT peripheral capability;
3. a maintained PBLE/1 agent integration;
4. sufficient flash, RAM, and runtime isolation;
5. build and protocol-conformance results;
6. transfer recovery and filesystem-safety behavior; and
7. repeatable HIL evidence on an exact board profile.

Open an issue before substantial porting work so the compatibility contract and
validation plan can be agreed first.
