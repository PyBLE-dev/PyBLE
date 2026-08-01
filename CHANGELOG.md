# Changelog

Notable public changes to PyBLE are recorded here. App and firmware versions
are released independently from this monorepo.

## Unreleased

- Established `PyBLE-dev/PyBLE` as the canonical public monorepo.
- Added public contributor, security, architecture, protocol, and validation
  documentation.

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
