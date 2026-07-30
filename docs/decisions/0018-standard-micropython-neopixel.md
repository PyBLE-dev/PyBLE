# ADR 0018 — PyBLE exposes the standard MicroPython NeoPixel API end to end

**Status:** Accepted (2026-07-28). Extends
[ADR-0015](0015-generic-micropython-gpio-blocks.md),
[ADR-0016](0016-offline-beginner-blockly-examples.md), and
[ADR-0017](0017-blocks-sidecar-and-bounded-python-import.md). It does not add a
PBLE/1 operation, board profile, pin catalog, or agent-mediated hardware path.

## Context

MicroPython's pinned ESP32 port normally freezes the MIT `neopixel` package,
whose `NeoPixel` class drives WS2812-compatible addressable LEDs through the
standard `machine.bitstream` primitive. PyBLE's lean classic-ESP32 and
ESP32-S3 manifests replaced the upstream board manifest but failed to require
that standard package; the ESP32-C3 overlay inherited it transitively. The
result is inconsistent firmware and an `ImportError` on boards whose onboard
status LED is an addressable RGB pixel.

Digital `machine.Pin.value()` blocks cannot drive a WS2812 data stream. A
special board-specific "onboard LED" block would hide this distinction and
would be wrong for generic boards whose LED pin, pixel count, colour order, or
presence differs.

## Decision

**Every PyBLE ESP32-family firmware image freezes upstream MicroPython's
standard `neopixel` package, and Blocks wraps only its public API with explicit
user-supplied hardware values.**

1. **Firmware uses upstream unchanged.** Each `esp32`, `esp32-s3`, and
   `esp32-c3` build resolves exactly one standard `neopixel.py` from the pinned
   MicroPython/micropython-lib tree. PyBLE adds no copied driver, upstream patch,
   PBLE/1 capability, or agent GPIO abstraction. `from neopixel import
   NeoPixel` must work offline in file/source runs and after soft reboot.

2. **No board assumption.** Firmware and app store no NeoPixel GPIO, pixel
   count, colour, named onboard component, or chip/board mapping. The program
   supplies them. GPIO 48 is therefore a valid user choice for a board whose
   documentation assigns its RGB LED there, but it is never a PyBLE default.

3. **Five composable Blocks types.** A localized **NeoPixel** toolbox category
   contains:

   | Type | Shape | Standard MicroPython generation |
   |---|---|---|
   | `pyble_neopixel_create` | output `NeoPixel`; required `PIN: Pin`, required `PIXELS: Number` | `NeoPixel(pin, pixels)` |
   | `pyble_neopixel_rgb` | output `NeoPixelColor`; required `RED/GREEN/BLUE: Number` | `(red, green, blue)` |
   | `pyble_neopixel_set_pixel` | statement; required `STRIP: NeoPixel`, `INDEX: Number`, `COLOR: NeoPixelColor` | `strip[index] = color` |
   | `pyble_neopixel_fill` | statement; required `STRIP: NeoPixel`, `COLOR: NeoPixelColor` | `strip.fill(color)` |
   | `pyble_neopixel_write` | statement; required `STRIP: NeoPixel` | `strip.write()` |

   The constructor reuses ADR-0015's explicit `Pin` value; its `PIXELS` is a
   positive safe integer literal with no shadow/default. RGB, index, and
   receiver inputs must be connected and single-line; numeric expressions
   remain composable and the standard runtime owns their dynamic range/type
   errors. The generator reserves `NeoPixel` and owns exactly one
   `from neopixel import NeoPixel` definition. `Pin` import ownership remains
   with `pyble_gpio_pin`.

4. **Buffer mutation stays explicit.** Set-pixel and fill change only the
   NeoPixel buffer. `write()` is a separate visible block because that is when
   the standard driver transmits. Off is RGB `(0, 0, 0)` plus set/fill and
   write; blink composes those operations with standard loops and the existing
   Time block. There is no hidden auto-write, implicit delay, brightness
   transform, or monolithic blink helper. RGBW and non-default timing are
   outside this increment.

5. **The bounded reverse converter expands with the generated subset.**
   ADR-0017 additionally admits the exact unaliased, use-dependent import
   `from neopixel import NeoPixel`, `NeoPixel(Pin(...), positive_count)`,
   three-item RGB tuples, NeoPixel index assignment, `.fill(rgb)`, and
   `.write()`. Receivers must be definitely bound NeoPixel variables on every
   reachable control-flow path and loop iteration. Loop backedges are validated
   to a conservative fixed point, and a possibly-zero-iteration `while` exit
   intersects the entry and body-exit bindings. Malformed arity, unsupported
   RGBW/timing/keyword forms, invalid literal counts, and non-NeoPixel receivers
   fail the complete conversion. There is no partial or raw-code fallback.

6. **A generic seventh example is a versioned catalog amendment.** Catalog
   version 2 adds `blink-neopixel` after `blink-led`. It creates one pixel,
   sets index zero to a dim RGB value and off, explicitly writes after each
   buffer change, and uses finite repeats/delays. Its GPIO role is disconnected
   in the shipped JSON and must be entered by the user before preview/copy.
   The example never names an S3 board, assumes an onboard LED, stores GPIO 48,
   or runs automatically.

7. **Tests are the executable boundary.** Red tests precede implementation and
   prove resolved manifest parity, no copied driver/profile/default, fresh
   three-chip builds, runtime import, block shapes/imports/calls/name safety,
   invalid-workspace retention, catalog v2 materialization/generation, bounded
   Python conversion, sidecar exact reopen, localization/offline policy, and
   real iPadOS/Android WebView generation. Hardware colour tests use an explicit
   operator-supplied GPIO, remain dim and bounded, and turn the pixel off in
   `finally`.

## Consequences

PyBLE again matches the standard MicroPython ESP32 user-code surface and can
generate portable, inspectable addressable-LED programs. Users must still know
their board's GPIO and pixel topology; that is the honest tradeoff for generic
ESP32 support. The frozen driver adds a small flash cost to the two lean images,
recorded by the existing footprint/build gates, and no new Flutter dependency.

## Related

- [Firmware requirements](../specifications/Firmware/specs.md)
- [App requirements §4.10](../specifications/App/specs.md)
- [App TDD §4.6](../specifications/App/TDD.md)
- [Hardware support](../specifications/hardware.md)
- [Public roadmap](../ROADMAP.md)
