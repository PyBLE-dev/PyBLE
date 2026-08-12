# ADR-0023 — Freeze an explicit ST7789 user-runtime and Blocky surface

- Status: **Accepted**
- Date: 2026-08-01

## Context

The Waveshare ESP32-S3-LCD-1.47B is an ESP32-S3R8 board with 16 MiB external
flash, 8 MiB Octal PSRAM, and a write-only 172 × 320 ST7789V3 panel. Its memory
topology exactly matches PyBLE's existing `esp32-s3-n16r8` provisioning image.
The panel itself is routed to GPIO45 (MOSI), GPIO40 (SCLK), GPIO42 (CS), GPIO41
(D/C), GPIO39 (reset), and GPIO46 (active-high backlight), with an X RAM offset
of 34 and Y offset of 0.

Upstream MicroPython provides `machine.SPI`, `machine.Pin`, and `framebuf`, but
the pinned runtime does not provide an ST7789 driver. Generating display code
without freezing its runtime would therefore recreate the prior missing-module
failure. Conversely, making the board a connection profile or hiding its pins
inside the agent would violate PyBLE's capability-defined, user-code hardware
boundary.

The official Waveshare demo archive has no package-wide MIT-compatible licence.
It may corroborate electrical facts, but its source and initialization code are
not inputs to PyBLE. The implementation must be authored clean-room from the
board schematic, LCD/controller command documentation, and real-hardware tests.

## Decision

PyBLE will freeze a fresh MIT `pyble_st7789` user-runtime in the ESP32-S3 image
and expose the same explicit surface in Blocky.

1. **The existing provisioning profile remains authoritative.** The board uses
   `esp32-s3-n16r8`; no board-routing profile, PBLE/1 opcode, capability bit,
   app chip allowlist, automatic board selection, or connection gate is added.

2. **The display library is outside the agent control plane.** Importing
   `pyble_st7789` performs no GPIO, SPI, allocation, or display I/O. User code
   explicitly constructs `ST7789` with an SPI bus ID, baud rate, polarity,
   phase, explicit `Pin` objects, visible width/height and RAM offsets, colour
   order, inversion, and bounded internal transfers. Construction configures
   `machine.SPI` and is the first permitted hardware side effect. The generic
   library contains no Waveshare pin constants.

3. **The v0.5.0 API is deliberately bounded.** It exports `ST7789` and
   `rgb565`. The generated constructor subset is the exact positional call
   `ST7789(spi_id, baudrate, polarity, phase, sck, mosi, cs, dc, reset,
   backlight, width, height, x_offset, y_offset, bgr, inversion)`, where every
   hardware signal is an explicit `Pin`. `ST7789` owns one RGB565 framebuffer
   and exposes `fill`, `pixel`,
   `line`, `rect`, `fill_rect`, `text`, explicit `show`, explicit Boolean
   `backlight`, and `deinit`. `show` transmits in bounded chunks and restores
   framebuffer byte order even if SPI raises. A failed transfer forces the
   backlight low and CS high but retains the driver-owned SPI and framebuffer
   so the same display object can retry a complete frame; only constructor
   failure or explicit `deinit()` releases those resources. Construction
   leaves the backlight off. Rotation and PWM brightness are not claimed in
   this increment.

4. **Blocky remains explicit and inspectable.** A localized **TFT Display**
   category provides eight composable types: ST7789 construction, RGB565
   colour, fill, pixel, outline/filled rectangle, text, show, and backlight.
   Generation uses only `machine.Pin`, `machine.SPI`, and the frozen
   `pyble_st7789` API. Required inputs have no board defaults, generator failure
   retains the workspace, imports are exact-once/use-dependent, and the bounded
   Python-to-Blocks converter admits the same subset all-or-nothing.

5. **The board example is guidance, not detection.** Catalog version 3 adds
   one manually selected example named for the exact
   `ESP32-S3-LCD-1.47B`. Its six GPIO roles are disconnected in the shipped
   workspace and must be entered before preview or copy. Localized wiring copy
   states the documented B-board values and warns that the non-B board differs.
   Panel geometry, offset, MicroPython SPI bus ID **1**, mode 0, conservative
   40 MHz clock, BGR order, and inversion are visible ordinary block values.
   Exact-board HIL proved `machine.SPI(1)` with SCLK GPIO40 and MOSI GPIO45;
   `machine.SPI(2)` resets this ESP32-S3 port and therefore MUST NOT appear in
   the named-board example or its HIL workload. This qualification does not
   constrain the generic driver's explicit `spi_id` input. Loading never runs,
   saves, or writes the board.

6. **Tests are the executable boundary.** Red tests precede implementation and
   cover manifest resolution, source/licence provenance, zero import side
   effects, pre-output scalar and real-`machine.Pin` validation, exact ordered
   panel command/data sequencing, colour conversion, clipping, byte-order
   restoration, chunk bounds, retry-safe transfer cleanup, partial-constructor
   cleanup, every block shape/generator, catalog role materialization, Python
   round-trip, localization, and absence of board gates/default GPIO values.
   HIL on the connected exact board must
   prove 16 MiB flash and 8 MiB PSRAM, runtime import after reboot, a bounded
   172 × 320 colour/text/corner pattern, active-high backlight off/on, and PBLE/1
   responsiveness while refreshing the panel.

## Consequences

- Any N16R8 ESP32-S3 board may use the generic module by supplying its own
  documented ST7789 wiring; merely having the module does not claim a display.
- The S3 image grows and uses about 110 KiB for a 172 × 320 RGB565 framebuffer
  only after construction. Existing build/resource gates measure the change.
- The exact Waveshare example is approachable without turning PyBLE into a
  board catalog or silently driving strapping pins during boot.
- Unsupported rotations, touch, SD, IMU, and battery behaviour remain outside
  this increment and are not implied by TFT support.

## Evidence boundary

- Board documentation: <https://www.waveshare.com/wiki/ESP32-S3-LCD-1.47B>
- Official schematic: <https://files.waveshare.com/wiki/ESP32-S3-LCD-1.47B/ESP32-S3-LCD-1.47B_schematic_diagram.pdf>
- LCD module datasheet: <https://files.waveshare.com/wiki/ESP32-C6-LCD-1.47/1.47inch_LCD_Datasheet.pdf>
- Local schematic verification SHA-256:
  `43738d1480ef9c983bca3e7f1f7ad852c288a1bd00f1621f9ac3e6974e7539fd`

<!-- SPDX-License-Identifier: MIT -->
