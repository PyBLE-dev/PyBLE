# ADR 0030 — The rpi-pico2-w port ships the portable frozen-Python agent first; native BTstack C follows at parity

**Status:** Accepted (2026-08-11). Scopes a **recorded deviation** from [ADR-0006](0006-native-c-agent-from-day-one.md) for the `rpi-pico2-w` target only — it does not supersede ADR-0006 for the ESP32-family reference ports. Builds on [ADR-0021](0021-capability-defined-board-scope.md) (capability-defined board scope). The port's derived requirements live in [firmware/ports/rpi-pico2-w.md](../specifications/firmware/ports/rpi-pico2-w.md).

## Context

ADR-0006's native base is realized as `pble_*.c` owning **NimBLE under FreeRTOS**, with NVS/`esp_mac`/`esp_timer` dependencies in every module except the platform-clean `pble_proto.c`. The pinned MicroPython v1.28.0 `rp2` port builds `RPI_PICO2_W` BLE over **BTstack on bare-metal pico-sdk** — no NimBLE, no FreeRTOS, no NVS. The native modules cannot be recompiled for rp2; a native rp2 agent is a second implementation, not a rebuild.

Meanwhile the repo already holds ADR-0006-sanctioned portable scaffolds (`firmware/pyble/pyble_ble.py`, a 321-line transport over MicroPython's portable `bluetooth` API; `pyble_proto.py`, the full §3/§4 frame codec sharing the conformance corpus). They are portable to rp2 **by construction**, because `bluetooth` runs over BTstack there. This was validated on the physical Pico 2 W on 2026-08-11: the scaffold transport advertised, negotiated MTU with CoreBluetooth, and completed the frozen HELLO exchange against the unchanged iPad app (`chip = "rpi-pico2-w"`), after two scaffold defects were found and fixed on hardware (the nonexistent `bluetooth._IRQ_*` attribute reads, and the missing `gatts_set_buffer` call that truncated inbound writes to ~20 bytes).

## Decision

**The first Pico 2 W increment grows the `firmware/pyble/` scaffolds to full PBLE/1 parity and freezes them into a `PYBLE_RPI_PICO2_W` image** (Layer-2 overlay `firmware/board_overlays/rpi-pico2-w/`, frozen manifest, frozen `_boot.py` auto-start). The agent remains **embedded in the image and never a user-deletable vfs file** — the embedded-control-plane rule is NOT deviated. The image speaks the identical frozen PBLE/1 wire; the app needs no change (ADR-0021: `chip` is open metadata).

## Recorded deviation (SDD honesty)

Native-from-day-one is deviated **for this target only**. Acceptance criteria are carried, not dropped. Retirement condition: each frozen module retires when its native BTstack `pble_*.c` twin reaches parity on the shared PBLE/1 conformance corpus — tracked as port open item **OI-P1** in the port spec.

## Unchanged

The PBLE/1 wire (protocol.md §2–§10), the four-layer model, the module boundaries, the workspace jail, clean-room/no-leak, cold-boot safety, the ESP32-family native agent and its candidate evidence, and every §1A.3 rejection.

## Alternatives considered

- **Native BTstack C now.** Rejected: the slowest path to first conformance evidence; all implementation risk lands before any hardware validation of the platform. The Python-first route already proved the transport on hardware in one bench day.
- **Stay ESP32-only.** Rejected: contradicts ADR-0021's capability-defined scope, which explicitly rejects a chip allowlist.
- **Wait for upstream NimBLE-on-rp2.** Rejected: no basis in the pinned tree; BTstack is the rp2 port's stack.

## Consequences

**Positive.** Fastest conforming second family; proves the portability claim with running hardware; the shared conformance corpus becomes genuinely two-implementation.

**Costs / mitigations.** Python-agent throughput and heap on RP2350 are unmeasured — mitigated by the port's own derived resource gates (GP2 in the port spec) before any support or public claim, per hardware.md §1.3; announcement surfaces keep the port invisible until GP2 (the external-beta message matrix freeze is untouched).

**Process.** Spec-first: this ADR + the port spec + the hardware.md/firmware.md amendments land as `[docs]` before any `[red]` test; then red → green per story (F-25..F-27, X-13).

## Related

- Deviates (scoped): [ADR-0006](0006-native-c-agent-from-day-one.md). Builds on: [ADR-0021](0021-capability-defined-board-scope.md).
- Ratifies: [firmware/ports/rpi-pico2-w.md](../specifications/firmware/ports/rpi-pico2-w.md) (P1–P11), the firmware.md §2 scoped-deviation note, §4.1 ports-in-progress table, §6 rp2 build bullet, and hardware.md §1.3.
