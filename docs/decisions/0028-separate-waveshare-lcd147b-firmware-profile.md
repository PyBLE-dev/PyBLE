# ADR-0028 — Separate the Waveshare LCD board from the lean ESP32-S3 image

- Status: **Accepted**
- Date: 2026-08-03
- Supersedes: the shared-image packaging decisions in ADR-0023 and ADR-0024
- Amended by: [ADR-0029](0029-enable-waveshare-splash-after-erased-install.md)

## Context

ADR-0023 introduced a clean-room `pyble_st7789` user runtime and ADR-0024
introduced an opt-in boot splash for the Waveshare ESP32-S3-LCD-1.47B. Their
first implementation froze the driver and exact-board companion into the
otherwise generic `esp32-s3-n16r8` image because that board has the same
ESP32-S3, 16 MiB flash, and 8 MiB Octal-PSRAM topology.

Matching memory does not make board peripherals interchangeable. ESP32-S3
boards vary widely, and each display, sensor, storage device, or other onboard
peripheral can require a different driver and wiring. Accumulating those
drivers in one memory-profile image would make every generic S3 user carry
irrelevant frozen code, board-specific boot machinery, and future maintenance
risk. It would also make the image name conceal a material runtime difference.

PyBLE already distinguishes destructive provisioning images from PBLE/1
runtime discovery. A separate exact-board image is therefore compatible with
the capability-defined product model as long as it is an explicit installer
choice rather than a board detector, GPIO-routing service, protocol
capability, or app connection allowlist.

## Decision

PyBLE will build the Waveshare ESP32-S3-LCD-1.47B as the separate prospective
provisioning image profile `waveshare-esp32-s3-lcd-147b`. It becomes a public
release profile only after its reproducibility, licensing, exact-byte HIL, and
activation gates pass.

1. **The generic S3 image is lean and board-neutral.**
   `esp32-s3-n16r8` retains the common PyBLE agent, upstream MicroPython
   runtime, and standard frozen NeoPixel module. It does not freeze
   `pyble_st7789` or `pyble_waveshare_lcd147b`, does not contain the splash QR
   or board pin constants, does not run an optional display hook, and compiles
   out the splash-only native readiness Event Group and `wait_ready` API.

2. **The exact-board image owns all display additions.**
   `waveshare-esp32-s3-lcd-147b` alone freezes the clean-room
   `pyble_st7789` runtime, the exact-board companion, the splash-capable boot
   wrapper, and the bounded native BLE-readiness seam defined by ADR-0024. It
   retains the documented ESP32-S3-LCD-1.47B **B-version** wiring and the
   factory-enabled-after-erase, persistently disableable setting from
   ADR-0029. The similarly named non-B board and other
   ESP32-S3 boards are not covered.

3. **Target identity and provisioning identity remain distinct.**
   Both S3 images use IDF target `esp32s3`, ESP Web Tools family `ESP32-S3`,
   merged-image offset `0`, and the 16 MiB flash / 8 MiB Octal-PSRAM topology.
   PBLE/1 `DEVICE_INFO` continues to report the target as `esp32-s3`; no wire
   byte, capability bit, BLE identifier, automatic board detection, or app
   connection gate is added. The exact profile ID exists only in build,
   release, installer, support, and qualification evidence.

4. **Build variants are first-class and extensible.**
   Build tooling distinguishes a build variant from its underlying IDF target.
   The maintained matrix is `esp32`, `esp32-s3`,
   `waveshare-esp32-s3-lcd-147b`, and `esp32-c3`, with independent retained
   MicroPython source/build roots. This permits future explicitly requested
   board images without adding their drivers to a chip-family image.

5. **The split v0.5 source contract defines three prospective profiles.**
   Their exact order is `esp32-4mb`, `esp32-s3-n16r8`, then
   `waveshare-esp32-s3-lcd-147b`; `esp32-c3-4mb` remains deferred. The two S3
   manifests intentionally use the same chip family and offsets but reference
   different firmware bytes. A future qualified installer requires separate,
   explicit compatibility consent and never aliases the exact-board action to
   the generic S3 manifest. This source contract does not assert that a v0.5
   public bundle or exact-byte qualification currently exists.

6. **Qualification follows the bytes.**
   The exact three profiles receive independent application-image, heap, boot,
   transfer, browser-install, interrupted-flash-recovery, and physical
   power-cycle evidence. The Waveshare profile additionally passes the
   existing exclusive TFT/splash/QR/driver-reuse gate. One S3 image or board
   cannot stand in for the other. The OI-1 policy becomes schema 2 with three
   threshold rows, `release.json` becomes schema 3 for the three-profile
   bundle, and the embedded HIL report becomes `PYBLE_HIL_RECORDS_V4` schema 4.
   V4 retains ADR-0024's private null-to-derived exact-board summary, now bound
   to the exact-board profile bytes.

7. **Published history is not reinterpreted.**
   The public v0.4.2 selector and bundle retain their exact historical
   two-profile, release-schema-2, HIL-V2 contract. The pre-split v0.5
   engineering baseline and candidate evidence are invalid for the new bytes;
   the split requires a new source-commit baseline, independently derived
   thresholds, reproducible builds, candidate, and complete HIL matrix.

8. **The app surface remains explicit.**
   The TFT Blocks API, Python-to-Blocks subset, and manually selected
   `waveshare-esp32-s3-lcd-147b` example remain unchanged and cost no board
   firmware space. Their copy states that the frozen runtime is supplied only
   by the exact-board image, unless a user separately installs a compatible
   module. They do not inspect `DEVICE_INFO`, select firmware, fill a GPIO, or
   claim a display automatically.

## Compatibility rules

- The lean `esp32-s3-n16r8` image may run common PyBLE workloads on a matching
  N16R8 board, including the Waveshare board, but makes no bundled TFT or boot
  splash promise.
- The `waveshare-esp32-s3-lcd-147b` image is scoped only to the exact B-version
  board even though ESP Web Tools can verify only the chip family. It becomes
  publicly supported only after all release gates pass; users must then affirm
  the exact model and memory topology before flash.
- Changing between profiles through a future qualified public installer is a
  destructive full-chip installation. The exact image's erased NVS state enables its
  splash; a stale NVS splash setting must never make the lean
  image drive display pins because that image contains no splash path.
- Adding another ESP32-S3 variation requires its own named build/profile,
  bounded dependency set, compatibility copy, reproducibility evidence, and
  HIL gates. It does not broaden either existing S3 image.

## Consequences

- Generic ESP32-S3 firmware remains small and understandable as more boards
  are added.
- The exact board receives the complete display experience without implying
  that memory topology identifies peripherals.
- Release, license, website, and HIL matrices gain one profile and one build
  variant; this additional work is the cost of truthful independent binaries.
- The clean-room driver and splash behavior from ADR-0023/0024 remain intact,
  but their earlier shared-S3 packaging statements are superseded.

<!-- SPDX-License-Identifier: MIT -->
