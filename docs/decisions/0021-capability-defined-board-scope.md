# ADR-0021 — Define board scope by MicroPython and Bluetooth capability

- Status: **Accepted**
- Date: 2026-07-29

## Context

PyBLE began with classic ESP32, ESP32-S3, and ESP32-C3 because they provide a
practical, testable first firmware family: upstream MicroPython, a BLE
peripheral stack, accessible toolchains, and inexpensive hardware. Early
product copy consequently described PyBLE as an IDE for generic ESP32 boards.

That wording confuses the first reference implementation with the product
boundary. The app discovers a PBLE/1 service rather than a silicon vendor, and
PBLE/1 carries MicroPython IDE operations without requiring ESP-IDF. Limiting
the platform permanently to one microcontroller family would work against the
open protocol and community-port architecture.

At the same time, Bluetooth hardware and a MicroPython port do not by
themselves make a board work today. A target also needs a compatible BLE
peripheral/GATT stack, enough resources for the protected agent and user
workspace, a maintained PyBLE agent port, and hardware validation. Public copy
must not turn a platform vision into a false compatibility promise.

## Decision

PyBLE's platform scope is **all microcontroller boards that can run MicroPython
and provide Bluetooth Low Energy connectivity capable of hosting a conforming
PBLE/1 agent**.

1. **Capability defines eligibility.** Silicon vendor, CPU architecture, and
   commercial board identity do not define the product boundary. A target is
   hardware-eligible when it can run a supported upstream MicroPython port,
   operate as a BLE GATT peripheral for PBLE/1, and provide sufficient flash,
   RAM, execution isolation, and filesystem support for the agent contract.
2. **A port defines actual support.** Eligibility is not a claim of immediate
   compatibility. A board is supported only when a versioned PyBLE agent port
   or firmware image exists for its target and passes protocol conformance,
   build, recovery, resource, and hardware-in-the-loop gates.
3. **ESP32 is the initial reference family.** The v1 firmware and browser
   flasher initially target classic ESP32, ESP32-S3, and ESP32-C3. These remain
   named wherever current artifacts, tests, pin guidance, or release gates are
   discussed, but they are not PyBLE's permanent scope.
4. **The portable seams remain vendor-neutral.** The Flutter app scans for the
   PyBLE service UUID and capability-negotiates features; it must not gate on a
   known chip list. PBLE/1's `chip` field is a port-defined ASCII identifier,
   not a closed enum. Firmware keeps target differences below the agent
   contract in a target adapter or board overlay.
5. **BLE remains the transport contract.** “Bluetooth connectivity” means a
   Bluetooth Low Energy implementation capable of the PBLE/1 GATT service.
   Bluetooth Classic alone does not satisfy the current protocol.
6. **Public communication separates three layers.** Product vision describes
   the broad MicroPython-plus-BLE platform. Compatibility guidance names the
   requirements for a port. Download and beta copy lists only targets with
   currently validated artifacts.

## Consequences

- PyBLE can grow across MicroPython ports and microcontroller vendors without
  changing the app's product identity or replacing PBLE/1.
- New targets require an explicit port, conformance corpus results, resource
  budgets, provisioning instructions, and HIL evidence; adding a name to a
  marketing list is not support.
- ESP32-specific build scripts, NimBLE/ESP-IDF details, pin references, and
  release artifacts remain correct as v1 implementation documentation.
- Website, app About copy, manifests, store metadata, and repository summaries
  must present the broad scope and the current ESP32 target set separately.
- A future target may use a different MicroPython port, BLE host, build system,
  provisioning tool, or target adapter while preserving the PBLE/1 wire and
  the four-layer control-plane boundary.

<!-- SPDX-License-Identifier: MIT -->
