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
- A RUN reservation is not yet execution. If an accepted STOP or SOFT_REBOOT arrives after the RUN response but before supervisor pickup, the supervisor MUST consume the reserved request as cancelled, MUST NOT compile or execute its file/source or emit `RUN_STATE(running)`, and MUST emit the terminal `RUN_STATE(idle)`. Supervisor pickup MUST publish the executing marker before its final cancellation check; that store is the linearization cut. Control accepted before the store sets cancellation intent which the final check consumes, while control accepted after the store observes execution and takes the P3 post-RSP interrupt path. There MUST be no check-then-publish gap in which an accepted control command neither cancels nor interrupts the source.
- After a SOFT_REBOOT response is successfully handed to BLE, the agent enters a closing state. Global command admission MUST run before every handler until reset: every valid non-SOFT_REBOOT command which normally has a response returns `EBUSY`, including unknown opcodes, while `FILE_PUT_DATA` and `CONSOLE_INPUT` are dropped because those commands have no response. No rejected handler may execute or mutate runtime, filesystem, label, autorun, console, or runner state. A duplicate SOFT_REBOOT also returns `EBUSY` without moving the deadline. The supervisor may consume the already-cancelled reservation and recover its terminal state, but MUST NOT start new user work or pump filesystem work while closing.

## P3. STOP (FROZEN)

- STOP handler: `RSP{OK}` always (idempotent while idle), but its control effect is command-local and provisional until response encoding and `send_message` both succeed. Only after that handoff may the agent commit the stop/cancel intent and decide between P2 cancellation and the executing-run interrupt path. Any dispatch, encode, or send exception MUST discard the staged action without changing the runner, VM, or reboot state; a response that was not handed off never stops or cancels user code. A later command can never inherit the staged action.
- A reserved-but-not-picked-up RUN follows the P2 cancellation path and does not need a VM interrupt. For an executing RUN, only after the RSP has been handed to the BLE TX path, arm `0x03` in the agent console tee and enqueue the native `os.dupterm_notify(None)` call with `micropython.schedule` → upstream converts the interrupt char into a main-thread `KeyboardInterrupt` at the next VM back-edge (`extmod/os_dupterm.c`, `py/scheduler.c`). The handler MUST NOT call `os.dupterm_notify` inline from the synchronous BTstack IRQ: an inline pending exception unwinds inside the protected BLE IRQ callback before the RSP and upstream disables that IRQ handler. Arming `0x03` and enqueueing its notify are transactional: if scheduler admission raises (including a full queue), the console MUST clear the armed byte before the agent invokes the injected non-returning hardware-reset fail-safe. Thus an already-acknowledged STOP either lands as `KeyboardInterrupt` or stops the program by reset; it never silently continues and never leaves a latent interrupt.
- Upstream `mp_os_dupterm_tx_strn()` catches every exception which escapes a
  Python dupterm `write()` call and deactivates that dupterm slot. Therefore a
  STOP `KeyboardInterrupt` which lands while the running program is printing
  MUST NOT escape the console tee's `write()` frame into that upstream catch.
  The tee tracks whether its armed `0x03` was consumed. If that exact in-flight
  STOP lands inside `write()`, the tee consumes it locally, re-arms `0x03`,
  enqueues one retry trampoline, and immediately returns the full write count.
  The pinned scheduler checks a pending exception before callbacks, runs at
  most one Python queue item per pending checkpoint, and holds the scheduler
  `LOCKED` while that callback runs. The frozen `write()` bytecode has exactly
  two pending checkpoints after retry admission and no third before
  `RETURN_VALUE`: checkpoint 1 runs the trampoline, which enqueues native
  `os.dupterm_notify` while the scheduler lock prevents it from running
  recursively; checkpoint 2 runs that native callable, consumes `0x03`, and
  sets the pending `KeyboardInterrupt` only after its exception check has
  already passed. `write()` then returns and upstream removes its NLR catch;
  the next outer VM check raises into the runner, which performs ordinary clean
  teardown and publishes `RUN_STATE(idle)` on the same connection. Pinned
  `mpy-cross` disassembly plus a deterministic checkpoint/NLR oracle MUST gate
  this ordering. A
  `KeyboardInterrupt` without the consumed-STOP marker MUST propagate
  unchanged. Terminal transition clears both the marker and any armed byte.
  Initial trampoline admission failure, or native-notify admission failure
  inside the locked trampoline, MUST clear both before invoking the injected
  non-returning hardware-reset fail-safe. This print-flood recovery
  does not move the original response-before-effect cut or weaken the
  `<500 ms` STOP/terminal gate.
- The deferred `KeyboardInterrupt` may land anywhere from the P2 executing-marker cut through terminal transition/publication, including after user `exec` returns. Runner terminalization and the supervisor's escaped-interrupt recovery MUST be idempotent: they clear the reservation/executing/stop bookkeeping, leave the RSM non-RUNNING, and publish exactly one terminal `RUN_STATE(idle)`. Terminal publication has explicit `transitioned/unpublished` and `published` phases. The emitter commits `published` at its actual send/record cut: a `KeyboardInterrupt` before that commit leaves `unpublished` and recovery retries, while an interrupt after the commit observes `published` and MUST NOT emit IDLE again. An interrupt during that post-exec cut MUST NOT escape into a blind swallow, lose or duplicate the terminal event, strand `RUNNING` with no pending request, or make later RUN commands permanently `EBUSY`.
- The supervisor pins `micropython.kbd_intr(3)` at start. Known limitation (same class as ESP32): user code calling `kbd_intr(-1)` defeats STOP.
- `tee.readinto` returns 1 byte or `None` — never 0 and never raises (EOF/raise deactivates dupterm; `extmod/os_dupterm.c`).

## P4. SOFT_REBOOT (FROZEN)

`machine.soft_reset()` is unusable from `_boot.py` on rp2 (the port's `main.c` falls to the REPL with the agent dead). Port semantics: stage SOFT_REBOOT without mutating run/reboot state, hand `RSP{OK}` to BLE, then commit cancellation of a reserved RUN per P2 or stop executing user code through P3's scheduler-deferred `0x03` path. Dispatch/encode/send failure discards the staged SOFT_REBOOT and leaves the run, VM, deadline, and reset alarm unchanged. While one successfully acknowledged reboot is pending, every duplicate SOFT_REBOOT returns `EBUSY`, does not re-arm anything, and does not move the original deadline.

The successful response commit fixes one deadline at `now + 250 ms` and arms an rp2 `machine.Timer` one-shot for the same interval with `hard=True`; its allocation-free callback invokes the injected **`machine.reset()`** directly. This hardware-alarm path, not cooperative polling or the VM interrupt, is the reset guarantee: user `kbd_intr(-1)`, a tight loop, a full GET pump, or a supervisor exception cannot starve or lose it. Timer-admission failure invokes the non-returning reset fail-safe immediately. The supervisor retains a deadline fallback, checks it without first starting new runner/filesystem work, and services it from `finally`; any other exception while closing invokes reset rather than allowing the outer fault-rebuild path to discard the deadline. P3 scheduler-admission failure likewise resets immediately after clearing the armed byte. A cancelled-run terminal interrupt cannot strand the reset. Observable behavior matches ESP32: link drops, board returns advertising with a fresh VM. (Recorded deviation: hard reset — peripherals and USB re-enumerate.)

## P5. Persistence (FROZEN — no NVS on rp2)

`/pyble_conf.json` on the LFS2 vfs: `{"label": str ≤24 UTF-8 bytes, "autorun": 0|1}`. The top-level reserved `pyble` prefix in the workspace jail shields it from PBLE/1 clients. Survives soft/hard reset; a filesystem reformat wipes it (accepted; identity is not stored there).

## P6. Ingest bounds (FROZEN)

Reassembled RX message cap **4096 bytes** (covers RUN source ≤ 2048 + headers); oversize → drop + `RSP ERANGE` with best-effort opcode/id echo (the ESP32-HIL-verified ERANGE-on-oversize behavior). Per-handler bounds: path ≤ 128, RUN source ≤ 2048, label ≤ 24 UTF-8 bytes.

## P7. Transport bindings (FROZEN)

`gatts_set_buffer(rx_handle, ≥247, False)` immediately after service registration (the default attribute buffer is ~20 bytes — **silent truncation** otherwise; hardware-verified 2026-08-11: the app's 71-byte HELLO arrived as 19 bytes without it). `ble.config(mtu=247)` after `active(True)` to pin the ceiling. Module-local **numeric IRQ constants** (modbluetooth exports no `_IRQ_*` names; hardware-verified AttributeError without them). Contingency: if HIL shows write-without-response merge/loss, escalate to `append=True` + a blob reframer — not default.

## P8. Console & pacing (FROZEN method and refill horizon)

One `io.IOBase` object serving three roles: stdout tee (gated on the run-active flag — the main-thread equivalent of the ESP32 worker-origin gate) emitting `CONSOLE_DATA` `[stream:u8][bytes ≤200]` chunks; a 256-byte stdin ring (drop-on-overflow) for `CONSOLE_INPUT`; and the `0x03` STOP channel (P3). BTstack queues congested notifies on the heap rather than dropping (the inverse of the ESP32 mbuf-starve loss mode): emission uses the bounded token bucket below; a dead link degrades to drop-and-continue, never a wedge.

The portable token bucket has exact capacity `TX_CAPACITY = 2048` bytes and
exact refill rate `TX_REFILL_PER_MS = 20` bytes per millisecond. Its
source-derived maximum empty-to-full refill horizon is therefore frozen as:

```text
TX_BUDGET_MS = ceil(TX_CAPACITY / TX_REFILL_PER_MS)
             = (2048 + 20 - 1) // 20
             = 103 ms
```

`TX_BUDGET_MS` and the release-evidence field `console_tx_budget_ms` mean only
that refill horizon. They are not a blocking Notify timeout, per-chunk sleep,
or promise to retain every flood byte. The runtime MUST define all three
positive integer constants and MUST derive `TX_BUDGET_MS` with the exact
ceiling formula above. The OI bench MUST import that runtime value, verify the
same formula, record exactly `103`, and expose no operator-selectable pacing
number. The native ESP `PBLE_CONSOLE_TX_BUDGET_MS = 250` wait budget is a
different mechanism and MUST NOT enter Pico evidence. This closes OI-P3's
numeric-definition item without recording a HIL pass; STOP/flood behavior and
the complete GP2 matrix remain release-blocking.

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

The OI reset samples use a bounded operator power-disconnect seam because Pico
2 W exposes no host-controlled reset edge in this setup. The service-filtered
scanner MUST be active before the disconnect prompt. After the operator
confirms all Pico power is disconnected and `assert_reset()` returns, the
harness MUST establish the common bounded consecutive quiet window from
[§5.3.2](../specs.md#532-frozen-qualification-workload), discarding every
pre-confirmation callback while keeping the scanner active. A callback queued
before confirmation but delivered afterward restarts the 1,000 ms window; it
does not fail the sample by itself. The runner MUST obtain a full callback-free
window within 15,000 ms, so a Pico that remains powered and advertising cannot
pass. Only after that interval may the harness prompt for power reconnection.
After the operator confirms reconnection, the watcher atomically establishes
the post-release epoch and numeric start boundary. Thus an advertisement seen
while the operator was reaching for either cable action can neither pass the
power-off proof nor become the measured post-reconnection advertisement.

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
window/chunk, and `console_tx_budget_ms: 103`, the source-bound P8 empty-to-full
refill horizon; ESP/NimBLE DLE/PHY/serial link-settlement keys are forbidden.
Any other or operator-supplied value fails the observation.

The release artifact is `rpi-pico2-w/firmware.uf2`. Release metadata binds its
exact byte size/SHA-256 and the raw `firmware.bin` size/SHA-256 used for static
resource evidence. The browser must verify the UF2 bytes before offering a
download and must create the download from those verified in-memory bytes.
There is no ESP Web Tools manifest, chip family, offset, partition component
map, or Web Serial fallback for this profile.

The UF2/raw-image identity check accepts exactly the pinned RP2350 Arm stream
emitted by the build: its first 512-byte record is the RP2 ignore-block
extension (`flags = 0x0000a000`, family `0xe48bff57`, address `0x10ffff00`,
256-byte payload, block number `0`, total `2`) and carries the little-endian
extension tag `0x9957e304` in the four bytes immediately after that payload;
the rest of the record before the end magic is zero. Every following record
is one sequential 256-byte RP2350 Arm payload (`flags = 0x00002000`, family
`0xe48bff59`) at `0x10000000 + 256 * block_number`, with zero padding outside
the payload. Validation reconstructs those Arm payloads and requires an exact
raw `firmware.bin` prefix followed only by zero image padding. Any missing,
duplicate, reordered, differently tagged, nonzero-padded, or additional UF2
record fails closed. Baseline HIL MUST use this same release validator shape;
it must not reject the required extension tag as stray payload padding.

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
- **OI-P3** — CLOSED for the source-derived `103 ms` refill-horizon
  definition; GP2 still validates the resulting console-flood/STOP behavior on
  the final candidate.
- **OI-P4** — NeoPixel claim withheld until the upstream package + `machine.bitstream` primitive are validated on rp2 (FR-LIB rule).
- **OI-P5** — core1 fs-worker increment (restores transfer-during-run concurrency).
