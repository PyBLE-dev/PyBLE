# ADR-0032 — Qualify the generic ESP32-C3 4 MB profile on reference hardware

- Status: **Accepted**
- Date: 2026-08-12
- Builds on: [ADR-0021](0021-capability-defined-board-scope.md)
- Qualification contract:
  [firmware/ports/esp32-c3-4mb.md](../specifications/firmware/ports/esp32-c3-4mb.md)

## Context

PyBLE already builds the generic `esp32-c3` firmware variant for IDF target
`esp32c3`, but `esp32-c3-4mb` remains deliberately unavailable because no
matching physical profile has completed its independent engineering and
release gates. A build, a family-level chip probe, or evidence from classic
ESP32 or ESP32-S3 cannot qualify C3. This matters especially on C3: its
single-core scheduler and no-PSRAM memory budget make it the binding footprint
and control-plane responsiveness target.

The newly available reference hardware is a dual-Type-C development carrier
containing an **ESP32-C3-MINI-1-N4** module (physical marking reported as
`C3N4`). Espressif's
[module datasheet](https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.html)
specifies the N4 member with 4 MiB Quad-SPI flash and an embedded chip revision
of v0.4. The carrier is sold as an
[ESP32-C3 Dual Type-C DevKitM-1](https://shop.controllerstech.com/products/esp32-c3-dual-type-c-wifi-bluetooth-ble-5-0-devkitm-1-core-development-board).
It has no PSRAM in the qualification configuration. Those facts match the
existing generic profile's revision-v0.3-or-newer, 4 MiB, no-PSRAM boundary.

Matching that memory/silicon boundary does not turn the carrier into a PyBLE
board product. Its dual USB connectors and its operator-reported onboard
NeoPixel wiring are carrier details. PBLE/1 and the app still discover the
generic `esp32-c3` target and never route behavior by carrier name.

The C3 path has a stress failure mode that a quiet smoke test would miss: even
when the runner interrupt remains reachable under `while True: pass`,
`while True: print("x")` can fill the notification path until the STOP response
times out. Qualification therefore has to prove control-plane priority under
console flood, not merely prove that the runner interrupt works. This context
defines the required regression; it is not a passing qualification result.

## Decision

1. **Use this module as the reference hardware for the existing generic
   profile.** The exact engineering reference is ESP32-C3-MINI-1-N4, embedded
   chip revision v0.4, 4 MiB flash, and no PSRAM. Before any destructive write,
   qualification records an operator inspection of the module marking and
   independent tool/runtime probes of the connected device. A family string or
   carrier product listing alone is insufficient.

2. **Do not add an exact-board firmware variant.** Qualification uses build
   variant `esp32-c3`, IDF target `esp32c3`, provisioning profile
   `esp32-c3-4mb`, and PBLE/1 `chip = "esp32-c3"`. It retains the existing
   `firmware/board_overlays/esp32-c3/` overlay. There is no carrier detector,
   routing profile, new capability, UUID, advertising prefix, app allowlist,
   or carrier-specific frozen module. Like every maintained ESP and RP2
   target, it obtains its agent version only from
   `firmware/versions.lock [pyble].agent_version`; the combined source identity
   is currently `0.6.0`, and no board-local version override is permitted.

3. **Freeze a complete engineering matrix before implementation.** The
   derived C3 contract freezes independently verifiable gates for exact
   identity and clean/reproducible build; generic BLE/HELLO/INFO smoke; file
   and source RUN plus authoritative STOP; complete filesystem, reliability,
   and dropped-link resume; a C3-only OI-1 engineering baseline; real iPad and
   Android app HIL; and an explicitly selected reference-carrier NeoPixel
   observation. Every gate starts **pending**. This ADR records no successful
   test and changes no current support status.

4. **Reserve control-plane capacity under bulk console output.** On the C3
   reference path, `CONSOLE_DATA` is bulk traffic and MUST leave enough
   notification capacity for the one-fragment STOP response and terminal idle
   event. Pending STOP control traffic pre-empts the next console message at a
   complete-message boundary; fragments within either message remain
   contiguous and never interleave. Under both `while True: pass` and
   `while True: print("x")`, the host-observed STOP sequence is
   `RSP{OK}` followed by `RUN_STATE(idle)`, with the terminal idle event less
   than 500 ms after the STOP command is submitted. Console completeness under
   deliberate overload is subordinate to that bounded control-plane behavior;
   malformed frames, a lost control event, or a wedged link are never allowed.

5. **Keep GPIO8 strictly reference-carrier evidence.** The operator may
   confirm this particular connected carrier's onboard NeoPixel is wired to
   GPIO8, explicitly enter GPIO8 and pixel count 1 in the ordinary generic
   NeoPixel example, and observe a bounded colour/off sequence. PyBLE never
   supplies, suggests, persists, or infers GPIO8. The observation is neither a
   property of `esp32-c3`, a generic `esp32-c3-4mb` pin promise, an Identify LED
   default, nor permission for boot firmware to drive the pin.

6. **Separate engineering qualification from release admission.** Completing
   the focused matrix may establish that the generic profile works on the
   named reference hardware and may provide a retained OI-1 baseline. It does
   not add C3 to the current three-profile pre-v1 policy, public firmware
   bundle, browser installer, website compatibility copy, README, changelog,
   or release ledger. Public admission requires a later spec-first release
   scope/schema amendment, candidate-bound thresholds, fresh final-candidate
   HIL, reproducibility and license gates, browser install/recovery, and the
   ordinary release approval path.

## Consequences

- C3 can be evaluated honestly against its real single-core/no-PSRAM
  constraint without proliferating a carrier-specific image.
- The same app and PBLE/1 contract used by classic ESP32 and ESP32-S3 remains
  the cross-target proof; target or carrier conditionals are a failure.
- The console path gains a small, testable control-priority invariant. Its
  implementation may apply backpressure or discard bounded bulk output during
  a deliberate flood, but it cannot spend the capacity needed to acknowledge
  and finish STOP or corrupt PBLE/1 reassembly through fragment interleaving.
- OI-1 obtains a C3-only engineering baseline before a future release policy
  admits C3. Measurements from another profile never fill the C3 row.
- GPIO8 remains an operator-owned wiring fact rather than product routing
  metadata.

<!-- SPDX-License-Identifier: MIT -->
