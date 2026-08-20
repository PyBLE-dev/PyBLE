# Changelog

Notable public changes to PyBLE are recorded here. App and firmware versions
are released independently from this monorepo.

## Unreleased

- Established `PyBLE-dev/PyBLE` as the canonical public monorepo.
- Added public contributor, security, architecture, protocol, and validation
  documentation.

### App and website source

- Added fail-closed Android upload signing and signed App Bundle CI contracts,
  plus the invited Google Play internal-test link and QR alongside TestFlight
  on `pyble.dev`.
- Added an independent `/privacy` policy and stable `/app` landing page.
- Extended every Blocks GPIO surface to accept explicit bounded MicroPython
  pin names such as `LED` while preserving numeric GPIOs, offline operation,
  and the app's board-neutral architecture.
- Patched the remediable website PostCSS/Nanoid dependency chain and bounded
  the remaining build-only `image-size` advisory behind a static-deploy and
  no-metadata-image-route contract until an upstream fix exists.

### Firmware 0.6.0 source integration

- Abandoned the unpublished local `firmware-v0.6.0` candidate at `719b211…`
  after the C3 stateless-PHY/post-OI receipt and fixed performance-contract
  amendments. Version 0.6.0 and its atomic five-profile scope are retained for
  a source-era-routed replacement; all candidate/HIL gates restart before any
  tag is pushed or release is published.
- Added the `rpi-pico2-w` portable frozen-Python agent port, its isolated RP2
  build plane, and pinned Arm GNU toolchain input alongside the four existing
  ESP build variants.
- Recorded successful pre-GP2 Pico 2 W BLE/app operation and physical onboard
  LED actuation as engineering evidence. Pico remains absent from public
  release metadata and the web installer until its complete GP2 matrix passes.
- Reserved a new source identity instead of reusing the earlier `0.5.1`
  Waveshare/ESP candidate version; all publishable artifacts require fresh
  version-bound build, provenance, resource, recovery, and HIL evidence.

### Firmware 0.5.1 source candidate — 2026-08-03

- Defined the independently selected `waveshare-esp32-s3-lcd-147b`
  provisioning profile for the exact ESP32-S3-LCD-1.47B B-version board with
  16 MiB flash and 8 MiB Octal PSRAM.
- Specified its exact-board-only ST7789 MicroPython runtime, bounded boot
  companion, app QR, persistent splash opt-out, and dedicated display/HIL
  qualification contract. An erased exact-board installation defaults the
  splash on; stored `0` remains an explicit opt-out.
- Kept `esp32-s3-n16r8` lean and board-neutral: its image contract contains no
  Waveshare pin map, TFT driver, companion, QR, splash hook, or display-only
  readiness seam.
- Expanded the candidate source/build contract to four variants over the three
  initial ESP32-family targets. No new exact bytes or public profile are
  qualified by this documentation change; reproducible builds, license audit,
  and independent final-candidate HIL remain required for all three candidate
  release profiles, while ESP32-C3 remains deferred.

## Firmware 0.4.2 — 2026-07-31

- Published the exact hardware-tested beta for `esp32-4mb` and
  `esp32-s3-n16r8`; ESP32-C3 remains unavailable.
- Validated production Chrome installation, deliberate interruption,
  interrupted-flash recovery, and reset on real hardware for both exact
  profiles.
- Bound the public release to its annotated source tag, immutable metadata,
  binary hashes, and post-release production-browser attestation.
- The complete release qualification remains pending across the app, PBLE/1,
  resource, and remaining firmware matrices.

## App 0.1.0-beta — 2026-07-30

- Opened the iPad app for external testing through TestFlight.
- Added BLE discovery, PBLE/1 connection, code editing, run/stop, live console,
  and wireless file management.
- Added the offline Blockly workspace, beginner examples, GPIO and NeoPixel
  blocks, exact sidecar reopening, and bounded Python-to-block conversion.
- Added adaptive portrait and landscape layouts, About and license surfaces,
  and the production launcher icon.

## Firmware 0.4.1 — 2026-07-30

- Qualified browser-installable images for `esp32-4mb` and
  `esp32-s3-n16r8`.
- Added the native PBLE/1 BLE agent, filesystem bridge, run/stop engine,
  console streaming, transfer recovery, device identity, and standard
  MicroPython NeoPixel support.
- Added release-integrity, license, qualification, and browser-installer
  validation gates.

The pre-publication development history is intentionally archived outside this
repository. Public development starts from the audited source snapshot.
Firmware 0.4.1 therefore remains a legacy pre-publication release; its source
is present here, but its original commit identifier is not part of the public
history. The next firmware release will rebuild and requalify from a public
commit.
