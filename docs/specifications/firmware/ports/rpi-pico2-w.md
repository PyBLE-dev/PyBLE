# PyBLE — rpi-pico2-w port (Raspberry Pi Pico 2 W: RP2350 + CYW43439)

Status: **P1–P9 FROZEN for the F-25/F-26/F-27/X-13 stories (`[docs]` 2026-08-11)**; P10 gates and P11 open items are living, and every result remains **PENDING**. Derived per [firmware/specs.md §1.1](../specs.md); [ADR-0030](../../../decisions/0030-pico2w-portable-python-agent-first.md) records the portable-Python-first deviation, while [ADR-0033](../../../decisions/0033-qualify-v060-as-five-profile-heterogeneous-release.md) defines the heterogeneous v0.6.0 release admission. Cited upstream facts refer to the pinned MicroPython v1.28.0 submodule.

## P1. Identity & caps (FROZEN)

- `chip` token: **`rpi-pico2-w`** (protocol.md §7 open identifier; ADR-0021 — no protocol amendment needed, additive under §9).
- `device_id`: derived from **`machine.unique_id()`** (8-byte flash ID), last two bytes uppercase hex — NEVER from `ble.config('mac')` (BTstack falls back to a per-boot random static address if the controller reports all-zeros; `extmod/btstack/modbluetooth_btstack.c`). Advertised name `PyBLE-XXXX` / label-else-default unchanged (FR-BLE-5 twin).
- caps: the frozen §7 short tokens, HELLO RSP leads with `[status:u8]`; `chunk = mtu − 18`; `put_window = 4` (initial; raise only on HIL evidence); `has_identify = 0` and `IDENTIFY` → `EUNSUPPORTED` this increment (spec-legal per protocol.md §4); `SET_IDENTIFY_LED` payloads are validated per frozen §4 (`ERANGE`/`EBADREQ`) but not persisted while `has_identify = 0`; `auto_run` served from the persisted flag; `agent_version` single-sourced from `versions.lock` via a build-generated frozen `_version.py` (BLD-12 equivalent).

## P2. Execution model (FROZEN — the port's central design)

- **Single-threaded agent on core0.** A supervisor loop frozen in the overlay `_boot.py` owns the main thread and replaces the local REPL; core1 is left to user `_thread` code.
- **The supervisor activates the builtin USB device itself** (`machine.USBDevice().active(True)`, best-effort) before entering its loop: rp2's `main.c` calls `mp_usbd_init()` only *after* `_boot.py` returns, which the supervisor never does — without this the board runs BLE-only with no USB CDC console (hardware-observed 2026-08-11 on the first flashed image).
- BLE events are **BTstack SYNC events**: the whole BTstack run loop executes inside a scheduler node; the Python irq handler runs synchronously inside it and MUST return quickly; the entire irq dispatch is wrapped in `try/except` (an uncaught raise permanently disables the handler — `extmod/modbluetooth.c`).
- **Fast ops answered inline** in scheduled context: HELLO, DEVICE_INFO, RUN (validate → reserve → RSP only), STOP, SOFT_REBOOT, CONSOLE_INPUT, SET_LABEL, SET_AUTORUN, SET_IDENTIFY_LED, IDENTIFY, FILE_LIST/STAT/DELETE/MKDIR/RENAME. **Mailboxed to the supervisor:** RUN execution, FILE_GET streaming, FILE_PUT windows.
- Transfers during an active RUN return `EBUSY` (legal §8; the ESP32 port's concurrent fs-worker behavior is restored only by a future core1 increment — OI-P5).

## P3. STOP (FROZEN)

- STOP handler: `RSP{OK}` always (idempotent while idle), then arm `0x03` in the agent console tee and call `os.dupterm_notify(None)` → upstream converts the interrupt char into a main-thread `KeyboardInterrupt` at the next VM back-edge (`extmod/os_dupterm.c`, `py/scheduler.c`). The supervisor catches it → `RUN_STATE(idle)` (stopped ≠ done/error — the `pble_runner.c` twin).
- The supervisor pins `micropython.kbd_intr(3)` at start. Known limitation (same class as ESP32): user code calling `kbd_intr(-1)` defeats STOP.
- `tee.readinto` returns 1 byte or `None` — never 0 and never raises (EOF/raise deactivates dupterm; `extmod/os_dupterm.c`).

## P4. SOFT_REBOOT (FROZEN)

`machine.soft_reset()` is unusable from `_boot.py` on rp2 (the port's `main.c` falls to the REPL with the agent dead). Port semantics: `RSP{OK}`, then stop user code (the `0x03` path), then **`machine.reset()`** scheduled from the supervisor after a bounded TX-flush delay. Observable behavior matches ESP32: link drops, board returns advertising with a fresh VM. (Recorded deviation: hard reset — peripherals and USB re-enumerate.)

## P5. Persistence (FROZEN — no NVS on rp2)

`/pyble_conf.json` on the LFS2 vfs: `{"label": str ≤24 UTF-8 bytes, "autorun": 0|1}`. The top-level reserved `pyble` prefix in the workspace jail shields it from PBLE/1 clients. Survives soft/hard reset; a filesystem reformat wipes it (accepted; identity is not stored there).

## P6. Ingest bounds (FROZEN)

Reassembled RX message cap **4096 bytes** (covers RUN source ≤ 2048 + headers); oversize → drop + `RSP ERANGE` with best-effort opcode/id echo (the ESP32-HIL-verified ERANGE-on-oversize behavior). Per-handler bounds: path ≤ 128, RUN source ≤ 2048, label ≤ 24 UTF-8 bytes.

## P7. Transport bindings (FROZEN)

`gatts_set_buffer(rx_handle, ≥247, False)` immediately after service registration (the default attribute buffer is ~20 bytes — **silent truncation** otherwise; hardware-verified 2026-08-11: the app's 71-byte HELLO arrived as 19 bytes without it). `ble.config(mtu=247)` after `active(True)` to pin the ceiling. Module-local **numeric IRQ constants** (modbluetooth exports no `_IRQ_*` names; hardware-verified AttributeError without them). Contingency: if HIL shows write-without-response merge/loss, escalate to `append=True` + a blob reframer — not default.

## P8. Console & pacing (FROZEN method; numeric tuning still open)

One `io.IOBase` object serving three roles: stdout tee (gated on the run-active flag — the main-thread equivalent of the ESP32 worker-origin gate) emitting `CONSOLE_DATA` `[stream:u8][bytes ≤200]` chunks; a 256-byte stdin ring (drop-on-overflow) for `CONSOLE_INPUT`; and the `0x03` STOP channel (P3). BTstack queues congested notifies on the heap rather than dropping (the inverse of the ESP32 mbuf-starve loss mode): emission uses a token-bucket budget whose constants are HIL-tuned; a dead link degrades to drop-and-continue, never a wedge (the `PBLE_CONSOLE_TX_BUDGET_MS` twin).

The current portable implementation exposes byte-capacity and bytes-per-ms
token-bucket constants, not an authoritative millisecond budget. The `250 ms`
native ESP constant and the `250` value used by host fixtures therefore MUST
NOT be copied into Pico release evidence as though the Pico runtime reported
it. Before a Pico baseline fragment is admissible, one positive pacing value
and its units MUST be frozen here, represented by an exact runtime-source
constant, and consumed by the OI bench without an operator-selectable numeric
override. Until that amendment lands, OI-P3 remains release-blocking and a
merely positive `console_tx_budget_ms` supplied on the command line is not
qualification evidence.

## P9. Build & provisioning contract (RP2-BLD, FROZEN)

Board `PYBLE_RPI_PICO2_W`; overlay `firmware/board_overlays/rpi-pico2-w/` (five files: `mpconfigboard.cmake`, `mpconfigvariant.cmake`, `mpconfigboard.h`, `manifest.py`, `_boot.py`); `build_rp2.sh` with the same `--plan`/fail-clean contract as `build.sh`; pinned **ARM GNU 14.2.Rel1** via `versions.lock [arm_gnu_toolchain]` (verify-or-fail, never a silent substitution — BLD-4 equivalent; the unpinned Homebrew arm-none-eabi-gcc on PATH must never be selected); BUILD dir outside the submodule; artifacts `firmware.uf2` (primary), `firmware.elf`, `firmware.bin`, provenance JSON (`port: "rp2"`); hard image-size gate **≤ 1,572,864 bytes**; flash = `picotool load -v -x`; BOOTSEL re-entry = `picotool reboot -f -u` or BLE RUN of `machine.bootloader()`.

The installer default `firmware/.arm-gnu/` is a gitignored, pinned third-party
compiler tree. Authored-source gates MUST prune that exact root, as they do
`firmware/.esp-idf`, while similarly named authored paths remain in scope.

**Release-history ruling (recorded 2026-08-11):** the published v0.4.2 ESP32
bytes and their evidence remain immutable. `[targets_rp2]` and
`[arm_gnu_toolchain]` are additive, section-scoped inputs; they do not
retroactively qualify Pico or change a historical release. Any later combined
source candidate requires its own versioned artifacts and fresh target-specific
evidence before publication.

The first combined source identity is **agent version `0.6.0`**. The existing
`0.5.1` source identity predates this port and MUST NOT be reused for different
bytes. ADR-0033 selects Pico for the v0.6.0 candidate without qualifying it.
Its profile may enter a finalized public selector only after P10 (including
GP2), the schema-3 resource row, verified-UF2 install/recovery, and the common
five-profile exact-byte gates pass.

## P10. Gates (per PRD §1B.7 sub-gate allowance; G0–G4 untouched)

- **GP0 build/boot:** image builds under the pinned toolchain, passes the size gate, boots advertising. *Verify: build.*
- **GP1 parity:** host unit + shared conformance corpus green for every grown module. *Verify: unit/conformance.*
- **GP2 HIL:** the complete matrix is green on one physical Pico 2 W against
  the final hash-locked candidate. It includes the common PBLE/1 behavior,
  STOP/console-flood, safe boot, reconnect, filesystem, resume, 20 × 16 KiB
  reliability, and OI workload; the RP2-specific image-budget/GC/BTstack
  observations; both physical iPad and physical Android app workflows; a
  browser-verified exact UF2 download and manual BOOTSEL copy; and an
  interrupted/failed-copy recovery using the same verified UF2. *Verify:
  HIL/size/app/provisioning.* "Hardware-tested"/supported flips ONLY when GP2
  and the common v0.6.0 release gates pass. Until then the profile remains a
  visibly pending candidate, never an active qualified selector.

### P10.1 v0.6.0 release evidence (FROZEN by ADR-0033)

Pico's schema-3 resource row uses `resource_kind = "rp2"`. Its immutable
build facts are raw `firmware.bin` byte length, the exact 1,572,864-byte image
limit, and their non-negative headroom. Its 16 runtime heap snapshots contain
exactly `gc_free_bytes` and `gc_allocated_bytes`; ESP-IDF heap keys are
forbidden. Transport evidence records BTstack, negotiated ATT MTU, advertised
window/chunk, and the source-bound console pacing budget after P8/OI-P3 freezes
it; ESP/NimBLE DLE/PHY/serial link-settlement keys are forbidden. An arbitrary
positive operator-supplied value cannot satisfy this field.

The release artifact is `rpi-pico2-w/firmware.uf2`. Release metadata binds its
exact byte size/SHA-256 and the raw `firmware.bin` size/SHA-256 used for static
resource evidence. The browser must verify the UF2 bytes before offering a
download and must create the download from those verified in-memory bytes.
There is no ESP Web Tools manifest, chip family, offset, partition component
map, or Web Serial fallback for this profile.

The pending V5 Pico gate summary is JSON `null`. Finalization may replace it
only with a validator-derived `passed` summary that binds GP0, GP1, complete
GP2, the final candidate UF2/raw-image hashes, both app platforms, manual
BOOTSEL install, and recovery. This section records no such pass.

## Bench evidence (2026-08-11, pre-GP2)

Recorded from the physical Pico 2 W + the unchanged iPad app (build 0.1.0):
connect + HELLO (`chip=rpi-pico2-w`, MTU negotiated) ✓; editor RUN of
`print("Hi")` with console output and terminal RUN_STATE ✓; real GPIO actuation
✓ — `Pin("LED", Pin.OUT)` blink observed on the onboard CYW43 `WL_GPIO0` LED,
ten cycles, then `done` on the console. USB CDC + BLE concurrently served by
the supervisor. The remaining GP2 matrix (file ops over BLE, windowed
PUT/resume goodput, STOP latency, print-flood, re-advertise, fail-safe,
autorun) is pending a bench central without the stale-bond obstruction; the
port status stays **in progress**.

Board reality note: the Pico 2 W onboard LED has **no integer GPIO** — it is
`Pin("LED")` (CYW43 `WL_GPIO0`, upstream `pins.csv: LED,EXT_GPIO0`). A numeric
GPIO choice in the app's Blocks examples drives a bare header pin on this
board. Closed same-day by app story **A-38** (FR-BLOCKS-1B, named pins in the
Blocks GPIO surfaces): the Blink example with the named pin `LED` was
hardware-verified on this board through the real iPad app — materialized
`Pin("LED", Pin.OUT)`, uploaded, ran, LED blinked. The app remains
board-agnostic (CON-7: the name is user-entered, never suggested).

## P11. Open items

- **OI-P1** — native-BTstack module retirement (ADR-0030).
- **OI-P2** — `ble.config('mac')` boot-stability probe (spec footnote only; identity already derives from `unique_id`).
- **OI-P3** — console pacing constants (HIL-tuned at F-27).
- **OI-P4** — NeoPixel claim withheld until the upstream package + `machine.bitstream` primitive are validated on rp2 (FR-LIB rule).
- **OI-P5** — core1 fs-worker increment (restores transfer-during-run concurrency).
