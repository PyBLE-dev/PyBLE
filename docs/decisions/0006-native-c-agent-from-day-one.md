# ADR 0006 — Native-C agent from day one

**Status:** Accepted (2026-07-01). Supersedes the "frozen-Python first" stance of [ADR-less] firmware.md §2 / firmware TDD Decision D1. **Closes OI-3.**

## Context

The PyBLE agent (Layer 3) can be realized two ways behind the same **PBLE/1** wire contract:

- **Frozen-Python** `.py` modules baked into the firmware (`pyble_*.py`), using MicroPython's `bluetooth`/`vfs`/`_thread` APIs.
- A **native `USER_C_MODULE`** (`pble_*.c`) compiled into the firmware image.

The prior design (firmware.md §2, TDD §2.1 **D1**) chose *frozen-Python first, then port hot paths to C where HIL footprint forced it* — with the frozen→native transition point left open as **OI-3**.

On 2026-07-01 the frozen-Python path was proven end-to-end on real hardware (ESP32-S3): the firmware builds via the pinned ESP-IDF, boots MicroPython v1.28.0, runs the frozen `pyble_proto` (`crc32("123456789") == 0xcbf43926`), and brings up the `pyble_ble` NimBLE peripheral (advertises + discoverable over BLE). That de-risked the wire and the toolchain.

The project owner has directed that **the agent be built as native C from day one**, not frozen-first.

## Decision

**The PyBLE agent base is a native MicroPython `USER_C_MODULE` (C) from v1.0.** The agent is implemented as `pble_*.c` sources under `firmware/user_c_modules/pyble/`, compiled into the firmware image via `USER_C_MODULES` (wired into `firmware/scripts/build.sh`). The first module, `pble_proto.c`, is **byte-identical** to `pyble_proto.py` and shares the one PBLE/1 conformance corpus.

Unchanged by this ADR: the **PBLE/1 wire contract**, the **four-layer model**, the **chip-agnostic Layer-3 rule**, the **module boundaries** (`pble_ble` / `pble_proto` / `pble_runner` / `pble_fs` / `pble_console` / `pble_info`), and the **clean-room / no-leak** rule — the native C is authored fresh against `protocol.md`, never ported from any proprietary source.

Any frozen `.py` module that already exists (`pyble_proto.py`, `pyble_ble.py`) is now a **scaffold**, retired as each native module reaches parity. Migration order: `pble_proto` → `pble_ble` → `pble_fs` → `pble_runner`/`pble_console`/`pble_info`.

## Consequences

**Positive**
- Native throughput and flash/RAM headroom from the start — most valuable on **ESP32-C3**, the footprint-binding target (prd §10.4).
- Deterministic per-packet timing (CRC32, framing, fragmentation, file chunking are C loops, not bytecode).
- The agent base matches a native firmware discipline; no mid-project frozen→native migration to schedule.

**Costs / mitigations**
- C iterates slower and is less host-testable than Python. **Mitigation:** TDD leans on the **shared PBLE/1 conformance corpus** as the oracle, a **C host-test harness** (to author, firmware-test-author), and **on-device/HIL** verification. `pble_proto.c` byte-matches `pyble_proto.py`, so the existing corpus applies unchanged.
- Cross-compile + hardware are needed to fully verify; host gates cover what they can (no-leak, SPDX, build-plan), HIL covers the rest.

**Process**
- Spec-first (this ADR + firmware.md §2 + TDD §2.1) lands before code, per SDD.
- **OI-3 is closed:** the transition point is day one.
- The firmware sprint plan and agent-spec team ownership (`pble_*.c` owners) are updated to reflect the native base.

## Related

- Supersedes the frozen-first half of `docs/specifications/firmware.md#2-agent-base-native-vs-frozen` and `docs/specifications/firmware/TDD.md` §2.1 (D1).
- Wire, IP boundary, and layering: [architecture.md](../specifications/architecture.md), [protocol.md](../specifications/protocol.md).
