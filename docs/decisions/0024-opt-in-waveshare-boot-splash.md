# ADR-0024 — Add an opt-in exact-board PyBLE boot splash

- Status: **Accepted**
- Date: 2026-08-01
- Amended by: [ADR-0029](0029-enable-waveshare-splash-after-erased-install.md)

## Context

The Waveshare ESP32-S3-LCD-1.47B has a built-in 172 × 320 ST7789V3 panel.
After ADR-0023, the shared ESP32-S3 image already contains an inert generic
display runtime and the app contains an explicit exact-board example. A small
boot screen can make a deliberately configured board feel complete, show that
its PyBLE agent is reachable, and give a second device a durable path to the
current app distribution channel.

The same `esp32-s3-n16r8` image is also valid for generic N16R8 hardware.
GPIO45 and GPIO46 are ESP32-S3 strapping pins, the panel is write-only, and the
flash/PSRAM tuple is not a board identity. Inferring this board from its chip,
memory, MAC, label, or display traffic would therefore be unsafe. Rendering
before BLE is actually available could also turn a cosmetic feature into a
misleading or blocking boot path. A direct TestFlight QR would make firmware
bytes depend on Apple's current invitation URL.

## Decision

PyBLE will add an exact-board companion module named
`pyble_waveshare_lcd147b` to the existing ESP32-S3 image.

1. **No board inference or new provisioning profile is added.** The module is
   frozen only into `esp32-s3`; classic ESP32 and ESP32-C3 do not contain it.
   Importing it performs no GPIO, SPI, framebuffer, display, sleep, task, or
   NVS-write operation. The generic image remains electrically inert unless a
   user explicitly enables or invokes this exact-board feature.

   "Frozen" also governs resolution, not just manifest membership. During the
   automatic boot transaction, the common frozen `_boot.py` saves the exact
   contents of `sys.path`, temporarily replaces them in place with only
   `.frozen`, imports the companion, runs its complete guarded hook (including
   lazy driver/version imports), and restores the saved contents in `finally`.
   A mutable VFS or `/lib` lookalike therefore cannot replace the automatic
   companion or one of its dependencies. On classic ESP32 and ESP32-C3 the
   frozen-only lookup finds no companion and fails open; it never falls back to
   a same-named user file.

2. **Boot display has an exact-profile factory state and a persistent choice.**
   As amended by ADR-0029, a missing NVS key enables the splash after a fresh
   erased exact-board install; only the pinned NVS-not-found error receives
   that treatment. The public API is
   `boot_splash_enabled()`, `enable_boot_splash()`,
   `disable_boot_splash()`, and `show_boot_splash()`. Enable/disable stores the
   exact integer `1`/`0` at NVS `pyble/lcd147splash` and commits before
   reporting success. Stored `0` disables, stored `1` enables, and other
   readable values or other NVS failures disable. Disable also makes the known
   active-high backlight low on a
   best-effort basis. No PBLE/1 opcode, capability, board catalog, MAC rule, or
   app connection gate is introduced.

   The first three calls return a Boolean/`None`/`None` respectively.
   `show_boot_splash()` returns true only after a final immediate BLE-ready
   check and retained backlight assertion; it returns false when that final
   check fails, while display faults clean up and propagate to an explicit
   caller.

3. **BLE readiness precedes an automatic splash.** After
   `pble_ble.init_agent()`, the common frozen boot imports the companion when
   available. It first checks the effective setting. Only an enabled board calls
   the native bounded readiness helper, which succeeds only after NimBLE has
   accepted advertising or a connection is already active. The boot wait is
   at most 1,500 ms and releases the MicroPython GIL. Timeout, advertising
   failure, missing module, NVS failure, allocation failure, or display failure
   silently skips the splash and continues the normal runner, filesystem,
   console, and autorun lifecycle.

   Failure to allocate the readiness Event Group is nonfatal: BLE still starts,
   readiness remains false, and every readiness wait returns false.

   The frozen-only `sys.path` transaction encloses the readiness wait and draw,
   and restores the original path contents on success, timeout, import fault,
   readiness fault, display fault, cleanup fault, or process-control exception.
   It runs before either MicroPython worker is created, so the bounded GIL-
   releasing wait cannot expose the temporary import path to concurrent user
   Python. Normal user imports and `boot.py` see the exact original path.

4. **The frame is deterministic, private, and offline.** It uses the documented
   exact-board wiring: SPI 1 at 40 MHz, mode 0, SCLK GPIO40, MOSI GPIO45, CS
   GPIO42, D/C GPIO41, reset GPIO39, active-high backlight GPIO46, geometry
   172 × 320, offset `(34, 0)`, BGR order, and inversion. The frame identifies
   PyBLE, shows the dynamic frozen `pyble.__version__`, states `BLE READY`, and
   displays `pyble.dev/app`. It contains no MAC, device ID, label, BLE address,
   owner data, or telemetry-derived value.

   `BLE READY` is a boot snapshot, not a live-link indicator: it means actual
   advertising/connection readiness was observed again immediately before the
   panel was lit. A later disconnect or reset does not rewrite retained GRAM.

5. **The QR is a fixed reviewed artifact.** Its payload is exactly
   `https://pyble.dev/app`: a stable first-party landing page that may link to
   the current approved app channel. It is QR Model 2, Version 2, byte mode,
   error correction M, mask 2, a 25 × 25 module matrix, five pixels per module,
   and the required four-module white quiet zone. The resulting 165 × 165
   square is rendered at `(3, 52)`. Runtime firmware contains only the reviewed
   25-row bit matrix; it has no QR dependency, network access, redirect lookup,
   or dynamic encoder.

6. **Display ownership is bounded.** The splash builds one existing RGB565
   framebuffer and transfers exactly one complete frame while the backlight
   remains off, then deinitializes the driver and collects garbage to release
   SPI and framebuffer immediately. It rechecks readiness with zero wait and
   asserts the exact-board backlight high only when that check succeeds,
   leaving
   the controller's retained pixels visible without a delay or background
   task. User code remains free to construct `pyble_st7789.ST7789` and take
   over the same pins. A failed path leaves CS high, backlight low, and any
   constructed SPI/framebuffer released on a best-effort basis.

   The serialized frozen-Python transaction is deliberate. A second startup
   display task would add concurrent SPI/pin ownership and another lifecycle to
   cancel or join. Instead, the native BLE host establishes readiness while the
   main VM performs at most one bounded frozen call; no display task survives
   the call, and the ordinary runner/filesystem workers start only after path,
   SPI, and framebuffer ownership have been restored/released.

7. **The landing route is part of the feature.** `https://pyble.dev/app` is a
   canonical, static, no-trailing-slash page with an ordinary link to the
   approved TestFlight invitation, a visible fallback URL, and links to
   firmware setup and support. Its deployment MUST preserve the already-active
   `/flash` release. The direct invitation remains the website specification's
   source of truth; changing app channels does not require reflashing boards.

8. **Tests and exact-board HIL are release gates.** Red host tests precede the
   implementation and prove default electrical inertness, exact NVS behavior,
   actual-advertising readiness, timeout and soft-reset races, fixed QR bytes,
   frame layout, safe cleanup, manifest cardinality, and unchanged generic boot
   order. Exact-board HIL must prove disabled and enabled boots, BLE
   connectivity while the splash is visible, QR scanning to the exact HTTPS
   payload, dynamic version text, resource release, and subsequent ordinary
   TFT-driver reuse. Visual confirmation is an explicit operator observation;
   it cannot be manufactured by a host fake.

   The combined runner gives each required human observation its own bounded
   deadline, distinct from every BLE/device-operation deadline. The operator
   may spend at most 900 seconds confirming one retained splash (including the
   real QR scan) or the live TFT pattern. That wait does not consume the
   residual BLE/reconnect/RUN budget. The runner keeps a bounded device reserve
   for STOP or link closure, rechecks the same connected/live state after the
   callback, and on timeout or refusal admits no evidence and performs the
   existing disable-and-darken cleanup. Timeout-driven cancellation of the
   cancellable prompt is a qualification failure, not an operator-originated
   process-control exception.

   Host boot tests also place same-named modules in the simulated VFS and prove
   that the S3 executes only the frozen companion/dependencies, classic/C3
   execute neither copy, and the original `sys.path` contents are restored
   exactly after success and every injected import/readiness/render failure.

   Every enabled `_boot.py` execution, including a MicroPython soft reset,
   renders once. An already advertising or connected native agent satisfies
   readiness immediately; a NimBLE reset must re-establish real availability.

## Consequences

- A generic N16R8 ESP32-S3 receives no display-pin output unless somebody has
  explicitly selected this exact-board behavior.
- Editable VFS files cannot replace or activate the automatic splash path; they
  remain ordinary user code outside the frozen boot transaction.
- The app-distribution destination can evolve behind a stable PyBLE-owned URL.
- Enabled boards perform one bounded boot-time display transfer, but the BLE
  control plane has priority and failures never prevent recovery.
- The persistent splash is branding/identity UX for one named physical board,
  not a user-code routing profile or a new claim about every S3 module.

## Evidence boundary

- Board documentation: <https://www.waveshare.com/wiki/ESP32-S3-LCD-1.47B>
- QR destination: <https://pyble.dev/app>
- QR matrix SHA-256 (25 unsigned 32-bit big-endian rows):
  `6b00240151e36ff2fdbb1d556d6f3b0dd75f8fcce13683ea21033e8149687875`
- The schematic and controller sources recorded by ADR-0023 remain the
  electrical/display evidence inputs. Vendor demo source remains excluded.

<!-- SPDX-License-Identifier: MIT -->
