# Public roadmap

PyBLE is developed in public. This roadmap communicates direction rather than
promising dates; accepted work is tracked through GitHub issues and milestones.

The detailed [firmware v0.6.1 and v0.7.0 proposal](planning/firmware-v0.6.1-v0.7.0-roadmap.md)
records the post-v0.6.0 contract-hardening and Reliable Projects candidates.
The v0.6.1 hardening scope is approved for specification-first implementation;
v0.7.0 remains non-normative and requires separate maintainer approval.

## Available now

- iPad external beta through TestFlight
- PBLE/1 editing, run/stop, console, and file workflows over BLE
- Offline Blockly with beginner GPIO and NeoPixel examples
- The current qualified firmware v0.6.0 covers five exact profiles: four ESP
  Web Serial installers and the verified Pico 2 W UF2/manual-BOOTSEL path. All
  five exact-byte hardware, recovery, PBLE/1, iPadOS, and Android rows passed
  for that immutable release.
- MIT-licensed app, agent firmware, protocol, website, tests, and release tools

## Near term

- Qualify the app 0.2.0 beta train, starting at globally monotonic build 5,
  across the retained iPad/Android and five-profile hardware test scope
- Complete source-selected firmware v0.6.1 contract hardening, deterministic
  builds, and fresh resource, recovery, and physical qualification across the
  same atomic five-profile scope before publication
- Expand user-facing setup, recovery, and board-specific wiring guidance
- Open and document the Android beta distribution path
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
