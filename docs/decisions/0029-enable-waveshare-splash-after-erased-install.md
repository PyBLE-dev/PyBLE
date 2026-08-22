# ADR-0029 — Enable the exact Waveshare splash after an erased install

- Status: **Accepted**
- Date: 2026-08-03

## Context

The browser installer performs a full-chip erase before writing firmware. That
also erases NVS, including `pyble/lcd147splash`. ADR-0024 defined a missing key
as disabled, so a successful fresh installation of the exact
`waveshare-esp32-s3-lcd-147b` image left its integrated TFT blank. This is the
opposite of the exact-board installer's promise: its bounded boot frame should
confirm that PyBLE is ready and expose the app QR immediately.

The lean `esp32-s3-n16r8` image freezes no display driver, companion, board
pins, or splash hook and is unaffected.

## Decision

1. On the exact `waveshare-esp32-s3-lcd-147b` image, the pinned
   `ESP_ERR_NVS_NOT_FOUND` result for an absent `pyble/lcd147splash` value means
   **enabled**. A freshly erased installation therefore shows the QR splash on
   its first successful BLE-ready boot. Other NVS failures remain disabled.
2. Stored integer `0` remains an explicit persistent disable. Stored integer
   `1` remains an explicit persistent enable. Other readable integer values
   remain disabled.
3. `disable_boot_splash()` continues to commit `0` before blanking the
   backlight. A reboot or update that preserves NVS respects that choice. A
   full-chip erase intentionally restores the exact profile's factory state.
4. Import remains electrically inert. Only the exact-board boot wrapper calls
   the companion, after native BLE initialization, and all failures remain
   fail-open to the normal agent lifecycle.
5. Generic ESP32-S3, classic ESP32, and ESP32-C3 images remain unchanged and
   contain no Waveshare display code or pins.
6. The web installer describes the splash as enabled after a fresh erased
   installation and does not require a hidden post-flash opt-in step.

## Consequences

- Fresh exact-board installations have an immediately visible result and a
  scannable app QR.
- Users retain a persistent opt-out.
- This is exact-profile presentation policy, not hardware detection, a PBLE/1
  capability, or a generalized routing profile.
- Any retained pre-split `v0.5.0` engineering-candidate bytes remain immutable
  and unqualified; the behavior begins only in a later independently qualified
  firmware release.
