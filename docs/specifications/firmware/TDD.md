# PyBLE Agent Firmware — Technical Design Document (TDD)

Status: **DRAFT** · Owner: project maintainer · Last updated: 2026-07-30

> **Frozen at G0 (2026-07-01, `[docs]`):** the source-tree layout ([§10.5](#105-source-layout-frozen)), which realizes the frozen NFR-MAINT-2 six-module design and the [specs.md](specs.md) §5.1/§5.6/§6/§8 freeze. Design narrative elsewhere in this doc remains DRAFT and is pinned per-story by its `[red]` tests ([§4](#4-module-design)).
>
> **Frozen pre-v1 resource-qualification design (2026-07-30, `[docs]`):**
> [§8.5](#85-meeting-the-nfr-fp-gates) and
> [§14.3](#143-build-size-and-hil-gates) freeze the two-profile measurement,
> policy, and HIL V2 design before the dependent `[red]` tests. Numeric
> thresholds remain pending measured baseline evidence.

## 0. Naming note (acronym clash)

In **this** document, **TDD = Technical Design Document** — the engineering design of the PyBLE agent firmware. The project's *development methodology* is also abbreviated "TDD", meaning **Test-Driven Development** (`red → green → refactor`), defined in [PRD §1B](../prd.md). Where this document says "TDD" it means *this design document*; where it discusses the methodology it spells out "Test-Driven Development". [§14](#14-test-design) is where the two meet: the Technical Design is exercised through Test-Driven Development.

## 1. Purpose & scope

### 1.1 Purpose

This document specifies **how the initial ESP32-family v1 PyBLE agent port** is
engineered to satisfy the requirements in [specs.md](specs.md) (the firmware
requirements specification). specs.md owns *what/why* (requirement IDs `FR-*`,
`NFR-*`, `CON-*`, `IF-*`, `BLD-*`, `SEC-*`); this document owns *how* (modules,
data structures, tasks, state machines, build pipeline) and traces every design
element back to those IDs ([§15](#15-traceability)). It is not a mandate that
future MicroPython ports use ESP-IDF, NimBLE, FreeRTOS, NVS, or the same binary
layout.

### 1.2 Scope

The design covers **Layers 1–3** of the four-layer model
([firmware.md §1](../firmware.md#1-four-layer-rule),
[specs.md §1.2](specs.md)) for the initial ESP32 port: the consumed upstream
MicroPython submodule (Layer 1), the per-chip board overlay (Layer 2), and the
PyBLE agent modules `pyble_ble` / `pyble_proto` / `pyble_runner` / `pyble_fs` /
`pyble_console` / `pyble_info` plus the `pyble_agent` dispatch surface (Layer
3). Layer 4 (the user workspace) is served, not designed here. The Flutter app
([app.md](../app.md)) is out of scope except where the firmware shares an
in-memory fake transport with the Dart `pble` client for conformance tests
([§14](#14-test-design)).

### 1.3 Relationship to other documents

- [specs.md](specs.md) — the requirements this design satisfies; the authority on *what*.
- [PRD §10](../prd.md) — apex firmware requirement set; specs.md and this TDD both flow from it.
- [firmware.md](../firmware.md) — the firmware overview (four-layer rule, module table, native-vs-frozen decision, build, footprint); this TDD is the detailed design beneath it.
- [protocol.md (PBLE/1)](../protocol.md) — **owns** the wire format. This document maps the wire format to in-firmware structures and **never redefines** frame bytes, opcodes, UUIDs, or status codes; it cites the relevant `§`.
- [hardware.md](../hardware.md) — **owns** chip facts; cited, never restated.
- [`firmware/versions.lock`](../../../firmware/versions.lock), [`firmware/upstream/README.md`](../../../firmware/upstream/README.md) — the single version pin and the clean-submodule rule that the build design ([§10](#10-build-system-design)) implements.

## 2. Design goals & key decisions

The decisions below are the load-bearing choices the rest of the design rests on. Each cites the requirement(s) it serves.

### 2.1 Native-C agent from day one

**Decision (D1, revised 2026-07-01 — see [ADR-0006](../../decisions/0006-native-c-agent-from-day-one.md)):** implement the agent as a **native `USER_C_MODULE`** (C) from v1.0 — the `pble_*.c` sources under `firmware/user_c_modules/pyble/`, compiled into the firmware image via `USER_C_MODULES`. It uses the ESP-IDF NimBLE, VFS, and FreeRTOS APIs behind the unchanged PBLE/1 contract. Any interim frozen `.py` module is a scaffold, retired as each native module reaches parity; `pble_proto.c` is **byte-identical** to `pyble_proto.py` and shares its conformance corpus. — *(firmware.md [§2](../firmware.md#2-agent-base-native-vs-frozen); serves NFR-MAINT-3, NFR-FP-C3; **closes OI-3** — the transition point is day one.)*

Rationale: native C gives throughput + RAM/flash headroom from the start (most acutely on ESP32-C3, the footprint constraint, [§8](#8-memory--footprint-design)) and deterministic per-packet timing, matching the project's decision to own the agent base in C. TDD leans on the **shared PBLE/1 conformance corpus** plus a C host harness and on-device/HIL verification rather than CPython host runs. The module boundaries ([§4](#4-module-design)) still isolate each module behind the wire so it can be built and verified independently.

### 2.2 Chip-agnostic Layer 3

**Decision (D2):** within the initial ESP32 port, the shared agent code
contains **zero** `esp32`/`esp32-s3`/`esp32-c3` conditionals. Everything
chip-specific (pins, flash size, USB, PSRAM, NimBLE config) lives in the
Layer-2 board overlay; the agent reads any chip-varying value at runtime from
MicroPython (`sys.platform`, `os.uname()`, `gc.mem_free()`, `machine`) or from
a single overlay-provided constants module. Cross-vendor BLE, scheduler,
storage, identity, clock, build, and provisioning differences belong behind a
future target-adapter implementation, not in this ESP32 chip overlay. —
*(satisfies NFR-MAINT-1, CON-4; supports BLD-4.)*

### 2.3 Static allocation strategy (C3-driven)

**Decision (D3):** all large, long-lived buffers (reassembly buffer, file I/O buffer, TX notification staging) are **allocated once at boot** and reused, never per-message. Per-message Python object churn on the hot path is minimized to keep the GC quiet and keep a predictable heap floor on the ESP32-C3 ([§8](#8-memory--footprint-design)). — *(serves NFR-FP-HEAP, NFR-FP-C3, NFR-REL-1.)*

### 2.4 BLE/agent task vs runner task separation

**Decision (D4):** the agent runs on a **BLE/agent task** (the asyncio event loop servicing NimBLE + PBLE/1 dispatch). User code runs on a **separate runner task** spawned via `_thread`. The link, `STOP`, and all control-plane commands remain serviceable no matter what user code does — including `while True: pass`. — *(satisfies FR-RUN-3, FR-BLE-11, NFR-SAFE-2; see [§5](#5-concurrency--task-model).)*

### 2.5 Never edit upstream; overlay copied in at build prep

**Decision (D5):** Layer 1 is a pinned submodule that is **never** modified. The board overlay is **copied into** the upstream `ports/esp32/boards/` tree at build prep, the agent ships as `USER_C_MODULES` / frozen manifest, and the submodule tree stays pristine; the default patch count is zero. — *(satisfies CON-1, CON-2, CON-4, CON-12, BLD-15; implemented in [§10](#10-build-system-design).)*

### 2.6 Wire format is referenced, never redefined

**Decision (D6):** `pyble_proto` and `pyble_ble` treat [protocol.md §3](../protocol.md#3-framing)/[§4](../protocol.md#4-opcodes)/[§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) as the single source of truth; opcode/status/UUID numbers live in **one** generated constants table mirrored from protocol.md, so a protocol freeze updates exactly one file. — *(satisfies IF-PROTO, FR-PROTO-2; manages OI-4.)*

### 2.7 Device config is per-device UX state, not a routing profile

**Decision (D7):** the **device label** and the **single optional identify-LED** (one GPIO number + active level) are persisted in a tiny **NVS-backed device-config store** ([§4.8](#48-device-config-store--label--identify-led-nvs)) that the agent owns purely for its own screenless-identity UX. This store is **not** a routing/pin profile, **not** a board-capability map, and **never** maps hardware for user code; the identify blink is cosmetic only. `device_id`/`label`/identify config are for recognition and display, and the agent **never** branches trust or gates access on MAC/`device_id`/`label`. — *(satisfies CON-13, FR-IDENT-6, SEC-11; upholds — and does not weaken — the [PRD §1A.3](../prd.md) rejection of routing/pin profiles and MAC gating.)*

### 2.8 Cross-platform target-adapter boundary

**Decision (D8):** PBLE/1, the protected control plane, workspace jail,
capability negotiation, and conformance corpus are portable. This TDD's
ESP-IDF NimBLE, FreeRTOS scheduling/interrupt delivery, MicroPython VFS,
`esp32.NVS`, BLE-MAC identity, timer, build, binary-layout, and ESP Web Tools
details are the initial ESP32 target adapter. A future MicroPython + BLE port
MUST supply equivalent BLE peripheral, runner/STOP, filesystem, persistent
config, stable non-personal identity, timer, build, artifact, provisioning, and
HIL behavior behind Layer 2; it need not reproduce these concrete APIs. —
*(implements ADR-0021; serves NFR-MAINT-1 and the PRD §1A.4 portability
boundary.)*

## 3. Architecture overview

### 3.1 The four layers

```text
+--------------------------------------------------------------+
| Layer 4  USER WORKSPACE  (served, not part of the agent)     |
|          /main.py  /lib/*.py  /data/*  /project.json         |
+--------------------------------------------------------------+
| Layer 3  PYBLE AGENT  (control plane — this design)          |
|   pyble_agent  (boot + dispatch surface)                     |
|   pyble_ble  pyble_proto  pyble_runner                       |
|   pyble_fs   pyble_console pyble_info                        |
+--------------------------------------------------------------+
| Layer 2  TARGET ADAPTER / BOARD OVERLAY (v1: esp32/-s3/-c3) |
|          pins, flash, USB, PSRAM, NimBLE config, manifest    |
+--------------------------------------------------------------+
| Layer 1  UPSTREAM MICROPYTHON  (pinned submodule, pristine)  |
|          VM, bluetooth(NimBLE), vfs/LittleFS, _thread, asyncio|
+--------------------------------------------------------------+
```

### 3.2 Component diagram (Layer 3)

```text
              BLE (GATT: RX write / TX notify / INFO read)
                              |
        +---------------------v-----------------------+
        |                pyble_ble                    |   NimBLE peripheral:
        |  advertise(PyBLE-XXXX) · GATT svc · MTU     |   adv, MTU, fragment/
        |  fragment/reassemble (protocol §3.2)        |   reassemble
        +-----------+--------------------+------------+
            RX msgs |                    ^ TX msgs (notify)
                    v                    |
        +-----------+--------------------+------------+
        |               pyble_proto                   |   frame codec, CRC32,
        |  decode/encode frame · CRC32 · ID correlate |   ID match, dispatch
        |  dispatch table (OPCODE -> handler)         |   table
        +--+-------+---------+----------+---------+---+
           |       |         |          |         |
           v       v         v          v         v
      pyble_info pyble_fs pyble_runner pyble_console pyble_agent
       (HELLO/   (list/   (RUN/STOP/   (stdout/      (boot, mode
        DEVICE_  stat/get/ SOFT_REBOOT/ stderr tee,   FSM, wiring,
        INFO,    put/del/  RUN_STATE,   stdin feed,   single-writer
        caps)    mkdir/rn) runner task) CONSOLE_*)    serialization)
                    |          |            |
                    v          v            v
            vfs/LittleFS   _thread/asyncio  TX queue (back to pyble_ble)
            (fs_root jail)  user code task
```

### 3.3 Data flow app↔agent over RX/TX

1. App writes PBLE/1 fragments to **RX**; `pyble_ble` reassembles per [protocol.md §3.2](../protocol.md#3-framing) into a complete §3.1 message in the static reassembly buffer.
2. `pyble_proto` validates CRC32, decodes the frame, and dispatches by `OPCODE` to a handler (`pyble_fs` / `pyble_runner` / `pyble_console` / `pyble_info`), or returns an error status if CRC/structure/version is bad.
3. The handler executes (file op, run, etc.) under the single-writer serialization owned by `pyble_agent`.
4. Responses (`RSP`) and asynchronous events (`EVT`: `RUN_STATE`, `CONSOLE_DATA`, `FILE_PUT_ACK`, `FILE_GET_*`) are encoded by `pyble_proto` and handed to `pyble_ble`, which fragments and **Notifies** them on **TX**.
5. **INFO** characteristic reads are answered directly by `pyble_ble` from a `DEVICE_INFO`-equivalent payload prepared by `pyble_info`, with no subscription required.

### 3.4 Module-to-layer mapping

All six functional modules plus `pyble_agent` are **Layer 3**. They depend downward only on Layer-1 MicroPython APIs and a single Layer-2 constants module (D2). No Layer-3 module imports another chip-specific symbol directly. — *(NFR-MAINT-1, NFR-MAINT-2.)*

## 4. Module design

Each module is single-responsibility (NFR-MAINT-2). API sketches are illustrative Python signatures, not the frozen interface; the frozen interface is whatever the `[red]` tests pin down per [§14](#14-test-design).

### 4.1 `pyble_ble` — BLE peripheral & transport

**Responsibility:** own the NimBLE peripheral: advertising, the single GATT service (RX/TX/INFO), MTU negotiation, and PBLE/1 fragmentation/reassembly. It is the only module that touches `bluetooth`.

**Public interface (sketch):**

```python
class BleLink:
    def start(self, info_payload: bytes) -> None      # init NimBLE, register svc, advertise
    def set_info_payload(self, payload: bytes) -> None # update INFO characteristic (FR-BLE-4)
    def set_adv_name(self, name: str) -> None          # update advertised name pre-connect (FR-BLE-12)
    def send_message(self, msg: bytes) -> None         # fragment + notify on TX (FR-BLE-10)
    def on_message(self, cb) -> None                   # register reassembled-message callback
    def mtu(self) -> int                               # negotiated MTU (FR-BLE-7/8)
    def on_connect(self, cb) -> None
    def on_disconnect(self, cb) -> None
```

**Key data structures / state:** the GATT table (Service/RX/TX/INFO UUIDs from the [protocol.md §2](../protocol.md#2-ble-transport-gatt) constants mirror); a single **reassembly buffer** (static, sized `max_message`, see [§7.3](#73-buffer-sizing)); a fragment-index tracker (`FIRST`/`LAST`/`index mod 64`); negotiated MTU; connection handle; the **advertised name** — the device label when set, else `PyBLE-` + `device_id` (the last two BLE-MAC bytes in uppercase hex), used for the name only, never for access control ([§4.8](#48-device-config-store--label--identify-led-nvs), CON-7/SEC-7/SEC-11).

**Advertised-name assembly:** at boot the name is `PyBLE-` + `device_id`; when `SET_LABEL` sets a non-empty label, `pyble_ble.set_adv_name(label)` updates the advertisement so the label shows in the scan list pre-connect; clearing the label restores `PyBLE-` + `device_id` (FR-BLE-12). Length bounding/validation happens in the device-config store before the value reaches the air ([§4.8](#48-device-config-store--label--identify-led-nvs), SEC-10).

**Dependencies:** Layer-1 `bluetooth`; the protocol constants mirror (UUIDs, frag-header bits); the device-config store ([§4.8](#48-device-config-store--label--identify-led-nvs)) for the label/`device_id` feeding the advertised name. Calls up into `pyble_proto` via the `on_message` callback.

**Frozen-vs-native plan:** frozen first. Reassembly, the per-fragment copy loop, and TX fragmentation are prime **native** candidates (D1) since they run per packet.

**Satisfies:** FR-BLE-1…12, IF-BLE, CON-5 (NimBLE only), SEC-5 (advertisement contents).

### 4.2 `pyble_proto` — protocol engine

**Responsibility:** encode/decode the [protocol.md §3.1](../protocol.md#3-framing) message frame, compute/verify IEEE CRC-32 over `VER…PAYLOAD`, correlate request/response by `ID`, and dispatch decoded CMDs to handlers by `OPCODE`.

**Public interface (sketch):**

```python
def decode(msg: bytes) -> Frame | None          # returns None / raises on structural error
def encode(type_, opcode, id_, payload) -> bytes
def crc32(buf) -> int                            # IEEE CRC-32 (zlib-compatible)

class Dispatcher:
    def register(self, opcode, handler) -> None
    def handle(self, frame: Frame) -> None        # routes CMD -> handler; emits RSP
```

**Key data structures:** `Frame` (namedtuple-like: `ver`, `type`, `opcode`, `id`, `payload`); the **dispatch table** — a dict mapping `OPCODE → handler` ([§7.2](#72-dispatch-table)); a small CRC-32 lookup table (or native CRC).

**Internal state:** stateless per message except the registered dispatch table. Events use `ID = 0` (FR-PROTO-4).

**Error behaviour:** CRC fail → drop + `EVT ERROR(ECRC)` referencing opcode if known (FR-PROTO-3); structurally invalid → `EBADREQ` (FR-PROTO-8); unknown/unsupported opcode → `EUNSUPPORTED` (FR-PROTO-9); `VER != 0x01` → refuse per versioning (FR-PROTO-7).

**Frozen-vs-native plan:** frozen first; CRC32 + frame pack/unpack are the second native candidate after `pyble_ble`.

**Satisfies:** FR-PROTO-1…10, FR-PROTO-6 (status mapping), IF-PROTO, D6.

### 4.3 `pyble_runner` — execution control

**Responsibility:** run a file or inline source on a **separate task**; capture `stdout`/`stderr` (via `pyble_console`); implement `STOP` (KeyboardInterrupt) and `SOFT_REBOOT`; own and emit `RUN_STATE`.

**Public interface (sketch):**

```python
class Runner:
    def run_file(self, path: str) -> int           # status; spawns runner task (FR-RUN-1)
    def run_source(self, src: str) -> int          # (FR-RUN-2)
    def stop(self) -> int                          # KeyboardInterrupt into runner (FR-RUN-5)
    def soft_reboot(self) -> int                   # soft-reset VM (FR-RUN-8)
    def state(self) -> int                         # idle/running/done/error
```

**Key data structures / state:** `RUN_STATE` enum (`idle` / `running` / `done` / `error`); a single runner-thread handle; a `busy` flag guarded by the single-writer lock (D4/SEC-3); the compiled code object for `mode: source`.

**Execution model:** a `RUN` while `state == running` returns `EBUSY` (FR-RUN-4). On launch: reply `RSP{status}` then emit `RUN_STATE(running)` (FR-RUN-1). `STOP` raises `KeyboardInterrupt` in the runner thread (using MicroPython's scheduled-exception / pending-interrupt mechanism) so it lands even against a tight loop (FR-RUN-5, NFR-SAFE-1). On normal return → `RUN_STATE(done)`; on uncaught exception → traceback to `CONSOLE_DATA(stderr)` then `RUN_STATE(error)` (FR-RUN-9). After `STOP`/exception, teardown is clean and the board returns to `idle` (FR-RUN-6/10). `SOFT_REBOOT` clears interpreter state and keeps the BLE link where possible (FR-RUN-8).

**Dependencies:** Layer-1 `_thread`, `asyncio`, the VM's exec primitives; `pyble_console` for stream capture; `pyble_agent` for the single-writer lock.

**Frozen-vs-native plan:** stays frozen — it is control logic, not a per-byte hot path.

**Satisfies:** FR-RUN-1…10, FR-MODE-2/3, NFR-SAFE-1/2, NFR-REL-1.

### 4.4 `pyble_fs` — filesystem bridge & workspace jail

**Responsibility:** implement the file opcodes (list/stat/get/put/delete/mkdir/rename), the windowed-upload state machine with CRC + resume, the `fs_root` path jail, and temp-write-then-rename atomicity.

**Public interface (sketch):**

```python
class FsBridge:
    def list(self, path) -> list
    def stat(self, path) -> tuple            # (size, crc32) or ENOENT (FR-FS-2)
    def get_begin(self, path, offset) -> tuple   # (status, total_size, crc32)
    def get_stream(self) -> None                 # streams FILE_GET_DATA events
    def put_begin(self, path, size, crc) -> tuple # (status, resume_offset) (FR-FS-7)
    def put_data(self, offset, data) -> None      # window write -> FILE_PUT_ACK
    def put_end(self, crc) -> int                 # verify whole-file CRC (FR-FS-6/14)
    def delete(self, path) -> int
    def mkdir(self, path) -> int
    def rename(self, src, dst) -> int
    def _resolve(self, path) -> str               # jail enforcement (FR-FS-10/11)
```

**Key data structures / state:** active-upload context (`path`, `tmp_path`, `total_size`, `expected_crc`, `ack_offset`, running CRC accumulator, window bookkeeping); the static file I/O buffer; `fs_root` constant. Only **one** transfer is active at a time (serialized by the single-writer lock).

**Jail design ([§9.3](#93-path-jail-enforcement)):** every path is normalized and verified to resolve inside `fs_root`; `..` traversal or absolute escape → `EACCES` (FR-FS-10). Layer-2/Layer-3 paths are a forbidden set → `EACCES` (FR-FS-11, SEC-4, CON-10). Only `.py`/data artifacts accepted; `.mpy`/`.pyc` rejected (FR-FS-12, CON-3).

**Upload integrity:** chunks land in a `.tmp` sibling; `FILE_PUT_END` verifies whole-file CRC before an atomic rename over the target; mismatch → `ECRC`, target untouched (FR-FS-6/9/14, NFR-REL-2/3). FS errors map to `ENOENT`/`ENOSPC`/`EACCES`/`EIO`/`ERANGE` (FR-FS-15).

**Frozen-vs-native plan:** frozen for orchestration; the **chunk write + incremental CRC** inner loop is a native candidate on C3 (D1).

**Satisfies:** FR-FS-1…16, IF-FS, NFR-PERF-2, NFR-REL-2/3, SEC-3/4, CON-3/10.

### 4.5 `pyble_console` — console tee

**Responsibility:** tee the running program's `stdout`/`stderr` to BLE as `CONSOLE_DATA` events (stream-tagged), feed `CONSOLE_INPUT` bytes to a program blocked on `input()`/`sys.stdin`, and optionally mirror to USB-serial for local debug.

**Public interface (sketch):**

```python
class Console:
    def attach(self) -> None        # redirect sys.stdout/stderr to the tee
    def detach(self) -> None
    def feed_input(self, data: bytes) -> None   # -> runner stdin (FR-CON-3)
    def write_out(self, data: bytes) -> None    # -> CONSOLE_DATA(stdout)
    def write_err(self, data: bytes) -> None    # -> CONSOLE_DATA(stderr)
```

**Key data structures / state:** an output staging buffer with **backpressure** ([§5.4](#54-console-backpressure)); a stdin queue feeding the runner; stream-tag constants (`stdout`/`stderr`). Output is observe-anywhere — emitted regardless of which client triggered the run (FR-CON-4).

**Dependencies:** `pyble_proto`/`pyble_ble` (TX), `pyble_runner` (stdin target), optional `sys`/UART for USB mirror (FR-CON-5, IF-USB — debug only, never a runtime transport).

**Frozen-vs-native plan:** frozen.

**Satisfies:** FR-CON-1…5, NFR-PERF-3.

### 4.6 `pyble_info` — device info & capabilities

**Responsibility:** assemble the `DEVICE_INFO` and `HELLO` reply payloads (incl. `device_id`/`label`/`has_identify`/`identify_led`); perform protocol-version + capability negotiation; supply the INFO-characteristic payload to `pyble_ble`; own the device-config store ([§4.8](#48-device-config-store--label--identify-led-nvs)) and handle `SET_LABEL`/`SET_IDENTIFY_LED`/`IDENTIFY`.

**Public interface (sketch):**

```python
class Info:
    def device_info(self) -> bytes        # chip, mpy ver, free_mem, fs_root, MTU,
                                          # device_id, label (FR-INFO-1)
    def hello_reply(self, offered_versions) -> tuple  # (proto_version, caps) | refuse (FR-INFO-5)
    def caps(self) -> dict                 # chip, mpy_version, fs_root, max_file_size,
                                           # put_window W, chunk_size, has_sd, free_mem,
                                           # device_id, label, has_identify, identify_led
    def info_payload(self) -> bytes        # DEVICE_INFO-equivalent for INFO read (FR-INFO-4)
    def set_label(self, payload) -> bytes        # 0x50 -> DeviceConfig.set_label (FR-IDENT-1)
    def set_identify_led(self, payload) -> bytes # 0x51 -> DeviceConfig.set_identify_led (FR-IDENT-2)
    def identify(self, payload) -> bytes         # 0x52 -> DeviceConfig.identify (FR-IDENT-3/4)
```

**Key data structures / state:** the `caps` dict (FR-INFO-3); supported `proto_versions`; SD-presence detection result (FR-INFO-6); the auto-run capability flag (opt-in, FR-BOOT-3 — flag name owned by [protocol.md §7](../protocol.md#7-hello--capabilities), OI-5); a handle to the device-config store ([§4.8](#48-device-config-store--label--identify-led-nvs)) supplying `device_id`/`label`/`has_identify`/`identify_led`. All chip-varying values read at runtime (D2) from `os.uname()`, `gc.mem_free()`, `sys.platform`.

**Negotiation:** `HELLO` is the first exchange after connect (FR-INFO-2); a client whose offered versions cannot be satisfied is refused rather than silently mis-spoken (FR-INFO-5). The agent advertises only what it implements (FR-PROTO-10).

**Frozen-vs-native plan:** frozen.

**Satisfies:** FR-INFO-1…6, FR-FS-13 (`fs_root` reporting), FR-BOOT-3 (auto-run flag surface), FR-IDENT-1/2/4 (label & identify config exposed via caps/`DEVICE_INFO`, see [§4.8](#48-device-config-store--label--identify-led-nvs)), BLD-13.

### 4.7 `pyble_agent` — boot & dispatch surface

**Responsibility:** the top-level wiring and lifecycle. It boots the agent, constructs and connects the modules, owns the **boot/runtime state machine** ([§6](#6-boot--runtime-state-machine)), registers handlers into `pyble_proto`'s dispatch table, and owns the **single-writer serialization lock** so file/run operations cannot interleave (SEC-3).

**Public interface (sketch):**

```python
def boot() -> None        # entry point from frozen manifest; init -> advertise -> serve
class Agent:
    def on_connect(self) -> None
    def on_disconnect(self) -> None
    def dispatch(self, frame) -> None   # delegates to pyble_proto.Dispatcher under the lock
```

**Key data structures / state:** the lifecycle FSM state; the single-writer lock (`_thread.allocate_lock` or asyncio lock); references to all module instances; a fail-safe handler that returns the board to advertising on a control-plane fault (FR-BOOT-6, NFR-REL-1).

**Boot policy:** initialize, start advertising, wait for connection (FR-BOOT-1); **never** auto-run `main.py` unless the opt-in flag is set (FR-BOOT-2/3/4/5, NFR-SAFE-3); reach advertising independent of workspace validity (FR-BOOT-4); the agent does not depend on an editable `boot.py`/`main.py` (FR-BOOT-5).

**Frozen-vs-native plan:** frozen (orchestration).

**Satisfies:** FR-BOOT-1…6, FR-MODE-1/4, SEC-3/6, NFR-REL-1, NFR-MAINT-2.

### 4.8 Device config store — label & identify-LED (NVS)

**Responsibility:** a tiny persisted **device-config store** holding exactly two pieces of per-device UX state — the **device label** (bounded UTF-8) and the **single optional identify-LED** (one GPIO number + active level) — plus the non-blocking **identify blink** actuator. It is owned by `pyble_info` (which reads it for caps/`DEVICE_INFO`) and read by `pyble_ble` (advertised name). It is **not** a routing/pin profile, capability map, or access-control surface (D7, CON-13, FR-IDENT-6, SEC-11).

**Public interface (sketch):**

```python
class DeviceConfig:
    def device_id(self) -> str             # stable MAC-derived suffix (XXXX), read-only
    def label(self) -> str                 # persisted label or "" (FR-IDENT-1)
    def set_label(self, text: str) -> int  # persist; ERANGE if over bound; "" clears (FR-IDENT-1, SEC-10)
    def identify_led(self):                # (gpio, active_level) or None (FR-IDENT-4)
    def set_identify_led(self, gpio, active_level) -> int  # persist one LED config (FR-IDENT-2)
    def has_identify(self) -> bool         # True iff an identify LED is configured (FR-IDENT-4)
    def identify(self, duration_ms) -> int # non-blocking blink; EUNSUPPORTED if unset (FR-IDENT-3/4)
```

**Persistence (NVS):** the label and identify-LED config live in a small **NVS namespace** (`esp32.NVS`, available identically on `esp32`/`-s3`/`-c3` — D2), **separate** from the LittleFS workspace ([§9.5](#95-device-config-persistence-nvs)). They survive reboot, so the advertised name, `has_identify`, and `identify_led` are stable across power cycles (FR-IDENT-5). The store is **outside** the `fs_root` path jail and unreachable by PBLE/1 file opcodes ([§9.3](#93-path-jail-enforcement)); it is mutated **only** through `SET_LABEL`/`SET_IDENTIFY_LED` under the single-writer lock (SEC-3).

**`device_id` derivation (initial ESP32 port):** the last two bytes of the BLE
MAC in uppercase hex (`XXXX`), computed once at boot — stable and ~unique
([protocol.md §2](../protocol.md#2-ble-transport-gatt)). It feeds the default
name and the `device_id` caps/`DEVICE_INFO` field, and is **never** used for
authorization (SEC-11, CON-7/SEC-7). Another platform port supplies an
equivalent stable, non-personal local suffix without changing the wire field.

**Advertised-name assembly (in `pyble_ble`):** the advertised name is `label` when a non-empty label is set, else `PyBLE-` + `device_id`. Setting a label (including clearing to `""`) calls `pyble_ble.set_adv_name(...)` so the change is visible in the scan list pre-connect; an over-length label is rejected (`ERANGE`) before it can reach the air (FR-BLE-12, FR-IDENT-1, SEC-10). The concrete label max-length is owned by [protocol.md](../protocol.md) (OI-6).

**Identify blink (non-blocking):** `IDENTIFY` schedules a bounded LED toggle on the BLE/agent context's timer/event-loop path (a `machine.Timer` or short-lived `asyncio` task), replies `RSP{OK}` immediately, and blinks for the protocol-bounded duration **without** blocking the dispatch loop or the runner task ([§5.5](#55-identify-blink-non-blocking)). With no identify LED configured it returns `EUNSUPPORTED (0x0A)` and changes no GPIO (FR-IDENT-3/4). The blink is cosmetic only and maps no hardware for user code (FR-IDENT-6, CON-13).

**Dispatch wiring:** `pyble_agent` registers `0x50 SET_LABEL → set_label`, `0x51 SET_IDENTIFY_LED → set_identify_led`, and `0x52 IDENTIFY → identify` into the [§7.2](#72-dispatch-table) table; each returns a [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) status. The wire payload shapes (label encoding, `SET_IDENTIFY_LED` GPIO+active-level encoding, blink-duration bound) are **owned by [protocol.md](../protocol.md)** and mirrored, never redefined here (D6, OI-6).

**Frozen-vs-native plan:** frozen (control/config logic, not a per-byte hot path).

**Satisfies:** FR-IDENT-1…6, FR-BLE-12, FR-INFO-1/4 (label/`device_id` fields), SEC-10/11, CON-13, OI-6.

## 5. Concurrency & task model

### 5.1 Two tasks, one link

Two cooperating execution contexts (D4):

- **BLE/agent context** — the asyncio event loop on the main task. It services NimBLE callbacks, runs reassembly/dispatch, executes all control-plane handlers (info/fs/console-input/run-control), and drains the TX queue. It must **never** block on user code.
- **Runner task** — spawned via `_thread` for each `RUN`. It executes user code with `sys.stdout`/`stderr` redirected to the console tee.

Because the link is serviced by the BLE/agent context and user code lives on the runner task, a `while True: pass` cannot wedge BLE or block `STOP` (FR-BLE-11, FR-RUN-3, NFR-SAFE-2).

### 5.2 STOP delivery

`STOP` is handled on the BLE/agent context (so it is always reachable) and raises `KeyboardInterrupt` into the runner thread via MicroPython's pending-exception/`schedule` mechanism, which lands even inside a tight bytecode loop (FR-RUN-5, NFR-SAFE-1). The runner's top frame wraps user code in a try/finally to guarantee teardown and a final `RUN_STATE` (FR-RUN-6/10).

### 5.3 Serialization (single active writer)

`pyble_agent` holds one lock that serializes mutating operations (file writes, `RUN`, `SOFT_REBOOT`) so concurrent commands cannot corrupt workspace or runner state (SEC-3). Read-only commands (`FILE_LIST`, `FILE_STAT`, `DEVICE_INFO`) and `STOP` are not blocked by a long upload's data phase beyond what correctness requires; `RUN` during `running` short-circuits to `EBUSY` without taking the lock's slow path (FR-RUN-4).

### 5.4 Console backpressure

The console tee writes into a bounded staging buffer drained by the TX notification path. When BLE is slower than the program's output, the tee applies backpressure: the runner thread blocks briefly on a full buffer rather than dropping data or growing the heap without bound (protects NFR-FP-HEAP and keeps console latency bounded, NFR-PERF-3). `CONSOLE_INPUT` bytes are queued and delivered to the runner's `stdin` (FR-CON-3).

### 5.5 Identify blink (non-blocking)

The `IDENTIFY` actuator ([§4.8](#48-device-config-store--label--identify-led-nvs)) must never wedge BLE or user code. The blink runs as a bounded, self-terminating job on the BLE/agent context (a `machine.Timer` or short-lived `asyncio` task), **not** on the runner thread: the handler replies `RSP{OK}` and returns to the dispatch loop immediately while the LED toggles for the protocol-bounded duration (FR-IDENT-3). It holds no long-lived lock, allocates no per-toggle heap, and stops on its own; a concurrent `RUN`/`STOP`/file op is unaffected. With no identify LED configured the handler returns `EUNSUPPORTED` and does nothing (FR-IDENT-4). The blink is cosmetic and never repurposed for GPIO routing, capability mapping, or access gating (FR-IDENT-6, CON-13).

## 6. Boot & runtime state machine

### 6.1 States

`INIT` → `ADVERTISING` → `CONNECTED` → `AGENT_MODE (idle)` ⇄ `RUN_MODE (running)` → (`done`|`error`) → back to `AGENT_MODE`. `STOP`/disconnect/fault paths return toward `ADVERTISING`/`AGENT_MODE`. `RUN_STATE` events are emitted on every transition (FR-MODE-3, FR-RUN-7).

### 6.2 State diagram (ASCII)

```text
        power-on
           |
           v
       +--------+   init ok        +-------------+
       |  INIT  |----------------->| ADVERTISING |<--------------------+
       +--------+                  +-------------+                     |
           |  control-plane fault         | central connects          |
           |  (fail-safe, FR-BOOT-6)      v                           |
           +--------------------->  +-----------+   disconnect         |
                                    | CONNECTED |---------------------+ |
                                    +-----------+                     | |
                                          | HELLO (first exchange)    | |
                                          v                           | |
                                  +------------------+                | |
                            +---->|  AGENT_MODE/idle |----------------+ |
                            |     +------------------+  disconnect      |
                            |        |    ^                             |
                       RUN  |        |    | RUN_STATE(done|error)       |
                  (RUN_STATE|        v    |  or STOP -> idle            |
                   running) |   +------------------+                    |
                            +---| RUN_MODE/running |                    |
                                +------------------+                    |
                                   |  SOFT_REBOOT: clear VM state,      |
                                   |  keep link if possible ------------+
                                   v
                            (KeyboardInterrupt on STOP -> teardown -> idle)
```

### 6.3 Cold-boot safety

On cold boot the board is **unowned**: it advertises and waits (SEC-6). It does **not** auto-run `main.py` unless the opt-in auto-run capability is enabled (FR-BOOT-2/3, NFR-SAFE-3); a broken or infinite-loop `main.py` cannot prevent advertising/connection (FR-BOOT-4). A control-plane fault fails safe back to `ADVERTISING` (FR-BOOT-6).

### 6.4 SOFT_REBOOT

`SOFT_REBOOT` clears interpreter state (re-init the VM heap/imports) and re-enters `AGENT_MODE`, keeping the BLE link where the platform allows (FR-RUN-8). It is distinct from a hardware reset and does not re-advertise unless the link drops.

## 7. Protocol & data structures

This section maps the [protocol.md](../protocol.md)-owned wire format to in-firmware structures. It **references**, never redefines, the wire bytes.

### 7.1 Frame ↔ struct mapping

The reassembled [protocol.md §3.1](../protocol.md#3-framing) message (`VER`/`TYPE`/`OPCODE`/`ID`/`LEN`/`PAYLOAD`/`CRC32`) decodes into the `Frame` structure ([§4.2](#42-pyble_proto--protocol-engine)). Header fields are read with `struct`/slicing; `LEN` is little-endian `uint16`; `CRC32` is IEEE CRC-32 over `VER…PAYLOAD`, little-endian, validated before dispatch (FR-PROTO-2/3).

### 7.2 Dispatch table

A dict maps each [protocol.md §4](../protocol.md#4-opcodes) opcode to its handler:

```text
0x01 HELLO        -> pyble_info.hello_reply
0x02 DEVICE_INFO  -> pyble_info.device_info
0x10 FILE_LIST    -> pyble_fs.list
0x11 FILE_STAT    -> pyble_fs.stat
0x12 FILE_GET_BEGIN -> pyble_fs.get_begin  (then get_stream emits 0x13/0x14)
0x15 FILE_PUT_BEGIN -> pyble_fs.put_begin
0x16 FILE_PUT_DATA  -> pyble_fs.put_data   (emits 0x41 FILE_PUT_ACK)
0x17 FILE_PUT_END   -> pyble_fs.put_end
0x18 FILE_DELETE / 0x19 MKDIR / 0x1A FILE_RENAME -> pyble_fs.*
0x20 RUN / 0x21 STOP / 0x22 SOFT_REBOOT -> pyble_runner.*
0x31 CONSOLE_INPUT  -> pyble_console.feed_input
0x50 SET_LABEL / 0x51 SET_IDENTIFY_LED / 0x52 IDENTIFY -> pyble_info (device config, §4.8)
```

Outbound EVTs (`0x13/0x14 FILE_GET_*`, `0x30 CONSOLE_DATA`, `0x40 RUN_STATE`, `0x41 FILE_PUT_ACK`) carry `ID = 0` (FR-PROTO-4). Every CMD handler returns a [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) status (FR-PROTO-1/5/6).

### 7.3 Buffer sizing

- **Reassembly buffer:** sized to `max_message` = the largest legal §3.1 message the agent accepts, derived from `max_file_size`/`chunk_size` in `caps`. Single static allocation (D3).
- **Per-fragment payload:** `MTU − 3` (ATT) − 1 (frag header), tracked from the negotiated MTU (FR-BLE-8). At MTU 247 this is 243 bytes.
- **File I/O buffer:** one MTU-sized chunk (NFR-PERF-2, chunk = one MTU).
- **TX staging:** bounded console + event queue ([§5.4](#54-console-backpressure)).

### 7.4 Windowed-upload state machine (resume + CRC)

Implements [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core):

```text
IDLE
  --FILE_PUT_BEGIN{path,size,crc}--> RESUMING
        (stat tmp prefix; reply resume_offset >=0)   (FR-FS-7)
  --> RECEIVING
        on FILE_PUT_DATA{offset,bytes}:
           if offset == ack_offset: write to .tmp, update running CRC,
              advance ack_offset; else hold/ignore gap
           emit FILE_PUT_ACK{ack_offset}             (FR-FS-5, NFR-PERF-2)
        window: up to W unacked chunks (ref agent W=8, queue depth W+2)  (FR-FS-4)
  --FILE_PUT_END{crc}--> VERIFY
        whole-file CRC == expected ?
           yes -> atomic rename(.tmp -> target) -> RSP OK   (FR-FS-6/9)
           no  -> ECRC, leave target untouched, keep/discard .tmp  (FR-FS-14)
  --> IDLE
```

Download (`FILE_GET_*`) is the symmetric streamer: `FILE_GET_BEGIN{path,offset}` → `RSP{status,total_size,crc32}`, then a streamer emits `FILE_GET_DATA{offset,bytes}` events and a final `FILE_GET_END{crc32}` (FR-FS-3). Resume on reconnect uses `FILE_STAT` to learn the verified partial size (NFR-REL-2).

## 8. Memory & footprint design

### 8.1 Per-chip heap budget approach

Static, boot-time allocation of all large buffers (D3) makes resource
headroom repeatable enough to measure after HELLO and after transfer workloads.
The current pre-v1 release measures the owned exact profiles
`esp32-4mb` and `esp32-s3-n16r8`. The S3's PSRAM is useful Python headroom but
MUST NOT conceal internal-RAM pressure, so the gate records Python GC memory
and internal ESP-IDF heap separately. The design still targets the
**ESP32-C3 floor** for v1.0 (single-core RISC-V, ~400 KB SRAM —
[hardware.md §1](../hardware.md#1-supported-chip-families-v1)); C3 measurement
is deferred until matching hardware exists and remains the binding v1.0 gate.

### 8.2 Static vs dynamic

Hot-path buffers (reassembly, file I/O, TX staging) are static and reused; per-message Python allocations are minimized to keep GC pauses out of the console/transfer latency path (NFR-PERF-3) and to avoid heap fragmentation under sustained transfer (NFR-REL-3).

### 8.3 NimBLE tuning

NimBLE is the only stack built (CON-5, FR-BLE-9; Bluedroid excluded saves flash and RAM). The board overlay tunes NimBLE buffer counts/sizes to the minimum that sustains MTU 247 windowed transfer, validated on C3 (NFR-FP-TPUT).

### 8.4 Frozen modules

The agent ships as **frozen `.py`** in the manifest, so module bytecode lives in flash, not heap. This is the primary flash/heap lever before native (D1).

### 8.5 Meeting the NFR-FP gates

The normative metric definitions, sample counts, payload generator, timer
boundaries, reliability workload, and outward-rounding formulas are frozen in
[specs.md §5.3](specs.md#53-footprint-gates-nfr-fp). This design deliberately
separates static build facts from runtime HIL facts:

- the release builder obtains `application_image_bytes` from the exact
  `application.bin` copied from `micropython.bin`, parses
  `factory_partition_bytes`, derives headroom, and verifies the immutable
  candidate against the committed ceiling/floor;
- a bounded PBLE RUN probe executes `gc.collect()`, `gc.mem_free()`,
  `gc.mem_alloc()`, and `esp32.idf_heap_info(2052)` on the MicroPython VM
  thread; the host never calls MicroPython GC internals from the NimBLE task;
- the existing HELLO/INFO `free_mem` value is recorded only as
  `heap_default_free_bytes`, because `MALLOC_CAP_DEFAULT` may include S3
  PSRAM;
- the host HIL runner asserts EN/reset through the selected serial adapter,
  starts a service-UUID-filtered scanner before release, rejects stale
  advertising during the one-second quiet interval, and times release to the
  first fresh matching on-air advertisement with a monotonic clock; and
- the transfer runner requires HELLO `mtu=247`, `window=8`, and `chunk=229`,
  uses no diagnostic overrides, validates GET offsets as contiguous and
  unique, and keeps PUT/GET timing separate from the multi-file
  integrity/reliability workload.

No production firmware metric capability is needed for this design. In
particular, GC/internal-heap values remain a bounded qualification probe rather
than volatile HELLO/INFO fields, and the external scanner measures the on-air
event rather than a firmware-local “advertise requested” timestamp.

#### 8.5.1 HIL bench structure

`tests/firmware_tests/hil/oi1_profile_bench.py` is the single profile-level
orchestrator. It has two modes:

- **baseline** emits canonical raw observations but cannot approve a release;
- **verify** loads the committed policy, executes the same frozen workload,
  evaluates every threshold, and emits the completed observation object.

Shared PBLE transfer, RUN-probe, metric, and canonical-JSON helpers live in
`tests/firmware_tests/hil/_pble_bench.py`. The existing
`f11_reliability_bench.py` and `file_roundtrip_bench.py` reuse those helpers
and retain their standalone CLIs. The central wrapper must distinguish an
observed MTU from a requested or fallback value: HELLO's device-side
negotiated `mtu` is authoritative, a backend-reported value must agree, and a
fallback must never certify MTU 247.

The bench accepts an explicit profile ID, expected PBLE chip value, BLE
address, and reset serial device. It refuses any profile outside the current
policy order, including `esp32-c3-4mb`. It records the central OS, BLE backend
and adapter, Python/bench identity, board/module description, candidate
identity and hashes, every integer sample, retransmit/rewind counts,
disconnects, integrity results, and a SHA-256 of the retained redacted raw
log. It writes atomically and never silently drops a successful sample.

#### 8.5.2 Threshold policy lifecycle

The exact machine policy is
`firmware/qualification/oi1-gates.json`, schema 1. Its shape and nine threshold
keys are frozen in specs.md §5.3.3. Initially the measurement tooling and
negative tests land while release qualification remains pending. The
maintainer then:

1. runs the engineering baseline on the two exact owned profiles;
2. runs `assemble-oi1-baseline` against the immutable staged inputs and the
   two bench fragments so the tool creates the canonical, redacted evidence
   under `docs/validation/firmware/oi1/`, derives every threshold with the
   frozen formulas, and atomically updates the policy with its evidence
   SHA-256;
3. reviews and commits those mechanically assembled files; and
4. builds the final tagged candidate and reruns verify-mode HIL on both exact
   profiles.

A policy has exactly two threshold-bearing profile entries and one deferred
C3 profile ID. C3 continues through source build, two-root reproducibility,
structural application-partition fit, and the six-role license audit; those
checks do not manufacture a C3 resource threshold or public support claim.

#### 8.5.3 Release evidence and failure semantics

Candidate generation embeds the parsed policy, its exact-byte SHA-256, the
matching baseline-evidence digest, and immutable build measurements in
`PYBLE_HIL_RECORDS_V2`. Its runtime observation is pending. Finalization may
fill observations, operator fields, and derived checks only; it must prove the
policy and build portions remain byte/semantically equal to the candidate.
The `assemble-hil-report` helper accepts only bounded per-profile mutable
evidence, copies candidate-frozen fields from the pending report, derives the
footprint/reliability pass from validated observations, and emits the completed
V2 report atomically before finalization.

The validator recomputes image/headroom arithmetic, sample counts, heap
minima, latency maximum, goodput from recorded durations, threshold
comparisons, and reliability totals. It rejects missing/extra fields, booleans
as integers, wrong units/order/profile/hash, an unknown-MTU fallback, a C3 row
or C3 numeric policy entry, or a value crossing its bound. Any firmware,
manifest, policy, or candidate-identity change invalidates the evidence.

### 8.6 ESP32-C3 mitigation

If the frozen-Python agent does not fit C3's flash/heap with usable user-code headroom, the **design changes** (move the [§4.1](#41-pyble_ble--ble-peripheral--transport)/[§4.2](#42-pyble_proto--protocol-engine)/[§4.4](#44-pyble_fs--filesystem-bridge--workspace-jail) hot paths into a `USER_C_MODULE`), **not** the constraint (NFR-FP-C3, D1). The PBLE/1 wire contract is invariant across the move (NFR-MAINT-3). Trigger point is owned by OI-3.

## 9. Filesystem & storage design

### 9.1 VFS / LittleFS

The workspace is a MicroPython VFS (LittleFS) rooted at `fs_root` (IF-FS). The agent does not reformat or repartition at runtime; the partition table is part of the per-chip build artifact (BLD-5).

### 9.2 Workspace layout

```text
fs_root/
  main.py           # user entry (run on demand; auto-run opt-in only)
  lib/*.py          # user modules
  data/*            # user data
  project.json      # optional project metadata
```

This is Layer 4 — served, not part of the agent. `.mpy`/`.pyc` are neither required nor accepted (FR-FS-12, CON-3).

### 9.3 Path-jail enforcement

`pyble_fs._resolve` normalizes each requested path (collapse `.`/`..`, reject absolute escapes) and confirms the result is within `fs_root`; otherwise `EACCES` (FR-FS-10). A forbidden-path set covers Layer-2/Layer-3 locations so the control plane can never be overwritten via PBLE/1 (FR-FS-11, SEC-4, CON-10). User code at runtime is **not** jailed — it uses standard `os`/`vfs` freely (FR-FS-16).

### 9.4 Atomicity

Uploads write to a `.tmp` sibling and `os.rename` over the target only after whole-file CRC verification, so a target file is never corrupted mid-transfer or by a dropped link (FR-FS-9, NFR-REL-2/3). FS errors map to PBLE/1 status codes (FR-FS-15).

### 9.5 Device config persistence (NVS)

The device label and identify-LED config persist in a small **NVS namespace** (`esp32.NVS`) — **not** in the LittleFS workspace and **not** under `fs_root`. This keeps the per-device UX state stable across reboot (FR-IDENT-5) while staying **outside** the path jail ([§9.3](#93-path-jail-enforcement)) and outside anything user code or PBLE/1 file opcodes can reach. It is read at boot to derive the advertised name and the identity caps, and written only by `SET_LABEL`/`SET_IDENTIFY_LED`. It is **not** a routing/pin profile or capability map (D7, CON-13, FR-IDENT-6).

## 10. Build system design

Implements the initial ESP32 build described by
[firmware.md §6](../firmware.md#6-build--distribution),
[`versions.lock`](../../../firmware/versions.lock), and
[`firmware/upstream/README.md`](../../../firmware/upstream/README.md). A future
target port defines its own pinned, reproducible artifact and provisioning
pipeline while retaining the shared PBLE/1 conformance gates.

### 10.1 Pipeline

```text
1. read versions.lock  (single source of truth: MicroPython + ESP-IDF pins)  BLD-1
2. SHA-drift gate: verify checked-out submodule SHA == versions.lock;
   refuse to proceed on mismatch                                             BLD-2
3. install ESP-IDF from the pin into a GITIGNORED dir (not an outer submodule) BLD-11
4. create one retained .sources/<target>/micropython checkout per target;
   verify its locked commit, canonical origin, and clean tracked tree;
   COPY board_overlays/<target>/ into only that target's checkout
   ports/esp32/boards/  (canonical submodule stays pristine)                CON-4, D5,
                                                                             BLD-14
   apply firmware/patches/micropython-<tag>/* if any (default: zero)        CON-12, BLD-15
5. rebuild mpy-cross from the pinned MicroPython                            BLD-10
6. invoke the esp32 port build with USER_C_MODULES (native) + frozen
   manifest (agent .py), mapping PyBLE target -> IDF target                 BLD-3/4
7. emit merged firmware.bin + application + bootloader + partition table
   + flasher_args.json                                                       BLD-5
8. validate the merged image, flasher args, component roles/placements, and
   partitions against the frozen current release profiles; normalize only
   component names                                                           BLD-17
9. generate the exact current-release-profile ESP Web Tools manifests plus
   release.json/schema, SHA256SUMS, provenance, release/recovery/HIL documents
                                                                              BLD-6/18/19/20
10. retain all three target checkouts; bind each application project description
    to its exact checkout, then reconcile all six application/bootloader linked
    inventories, exact frozen Python inputs, prebuilt blobs, and compiler
    runtimes against the pinned SBOM toolchain and fail-closed license policy;
    generate THIRD_PARTY_LICENSES.txt mechanically                           BLD-8/14
11. run no-leak, SPDX, manifest/integrity/license/reproducibility gates       CON-6,
                                                                             BLD-14/18
12. publish identical immutable bytes to the versioned same-origin path
    and matching GitHub Release only after every included profile passes HIL;
    the current pre-v1 gate covers esp32-4mb and esp32-s3-n16r8, while C3 is
    unavailable until a later candidate                                      BLD-7/21/22
```

### 10.2 Entry points

`firmware/scripts/build.sh <target>` builds exactly one of `esp32` | `esp32-s3` | `esp32-c3`; `build_all.sh` builds all three (BLD-3). Target→IDF mapping (`esp32`→`esp32`, `esp32-s3`→`esp32s3`, `esp32-c3`→`esp32c3`) comes from `versions.lock [targets]` (BLD-4). Upstream upgrades go only through `upgrade_micropython.sh` (BLD-9).

### 10.3 Reproducibility & releases

Builds are reproducible from a clean checkout given the pins; a release requires
two clean builds to yield byte-identical released parts after documented
deterministic normalization (NFR-REL-4, BLD-14). Each of those two build roots
uses this identical relative generated-source layout:

```text
<build-root>/
  .sources/
    esp32/micropython/
    esp32-s3/micropython/
    esp32-c3/micropython/
```

Each directory is an independent checkout of the MicroPython repository URL
and full commit pinned in `versions.lock`. Before it is admitted, its `origin`
URL MUST equal that canonical locked URL, `HEAD` MUST equal the locked commit,
and its tracked tree MUST be clean. The target's application
`project_description.json` `project_path` MUST resolve to
`.sources/<target>/micropython/ports/esp32` in that same build root; a
description that names the canonical submodule, another target's checkout, or
an escaped/symlinked location is fatal.

All target-scoped mutable preparation, including board-copy and ESP-IDF
submodule/managed-component materialization, runs inside that target's checkout
and target build directory. No target may share, replace, delete, or mutate
another target's checkout or `ports/esp32/managed_components`. The three
checkouts remain retained until linked-inventory/license audit, bundle
validation, and the two-root comparison have all completed.

Isolation does not establish a second proof root. Candidate-controlled inputs
in the canonical PyBLE checkout — including `versions.lock`, board overlays,
`firmware/pyble`, literal manifests, release tooling and policy/evidence, and
the pinned generator/compiler inputs under `firmware/upstream/micropython` —
remain independently hash-bound in the semantic audit receipt and are compared
with the selected build inputs. A target-local checkout cannot substitute
unreviewed bytes for those canonical proof inputs.

The release-packaging design,
exact public tree, manifest, separate integrity/provenance metadata, recovery,
HIL report, activation, and rollback are frozen in
[browser-flashing.md](browser-flashing.md). Identical immutable bytes publish
both at the versioned `pyble.dev` path and through the matching GitHub Release,
with exact release-profile parity: two qualified profiles in the current
pre-v1 release and all three at v1.0 (BLD-7/17…22). `DEVICE_INFO`/HELLO,
`manifest.json`/`release.json`, tag, and release notes make agent/protocol/
upstream/source/artifact versions recoverable (BLD-13); the agent follows
SemVer (BLD-12).

### 10.4 Patches directory

`firmware/patches/micropython-<tag>/` holds any unavoidable patch with a written reason, applied only at build prep, re-reviewed for retirement each upgrade; the default is **zero** patches (CON-12, BLD-15).

### 10.5 Source layout (frozen)

> **FROZEN for v1.0 (G0 · 2026-07-01; browser-release paths amended
> 2026-07-29 · `[docs]`).** This is the authoritative firmware source tree. It
> realizes the six-module agent (NFR-MAINT-2), the chip-agnostic Layer-3 /
> Layer-2-overlay split (NFR-MAINT-1, CON-4), and the clean-submodule build
> (CON-1/2/12, BLD-*). Adding a path is a `[docs]` amendment; the layout itself
> does not change per-story. Freezing the layout does **not** populate any module
> file — module bodies are authored per-story under TDD by their owning
> engineer.

```text
firmware/
  versions.lock                     # single source of truth for the pins (BLD-1)         [build-smith]
  release-tools.lock                # hash-pinned SBOM/release Python closure (BLD-8)      [build-smith]
  licenses/
    license-policy.json             # reviewed source/archive -> SPDX/text/NOTICE policy   [build-smith]
    excluded-cves.yaml              # hash-pinned offline SBOM input; empty by policy      [build-smith]
    texts/                          # exact reviewed third-party license/NOTICE texts       [build-smith]
  upstream/
    README.md                       # clean-submodule rationale (F-15)                    [build-smith]
    micropython/                    # Layer 1 — pinned submodule, pristine (CON-1/2)      [build-smith / .gitmodules]
  pyble/                            # Layer 3 — frozen-Python agent package (NFR-MAINT-2)
    __init__.py                     # empty placeholder package at S1 (do NOT populate)   [build-smith scaffold]
    pyble_agent.py                  # boot + dispatch surface + single-writer lock         [runtime-engineer]
    pyble_ble.py                    # NimBLE peripheral, GATT, fragmentation               [ble-transport-engineer]
    pyble_proto.py                  # frame codec, CRC32, dispatch                          [protocol-engineer]
    pyble_runner.py                 # RUN/STOP/SOFT_REBOOT, RUN_STATE                       [runtime-engineer]
    pyble_fs.py                     # filesystem bridge + workspace jail                    [storage-engineer]
    pyble_console.py                # stdout/stderr tee + stdin feed                        [runtime-engineer]
    pyble_info.py                   # DEVICE_INFO/HELLO/caps + device-config store          [identity-engineer]
  user_c_modules/
    pyble/                          # Layer 3 native hot paths — LATER, OI-3 (pble_*.c)    [ble-/protocol-engineer]
  board_overlays/
    esp32/  esp32-s3/  esp32-c3/    # Layer 2 — per-chip overlay, copied at build prep     [build-smith]
  scripts/
    build.sh  build_all.sh          # per-target / all-three build (BLD-3/4)               [build-smith]
    release_bundle.py               # deterministic manifest/integrity/license bundle      [build-smith]
    upgrade_micropython.sh          # controlled pin bump (BLD-9)                           [build-smith]
  build/releases/                   # generated candidate/public bundles; gitignored        [build output]
  patches/
    micropython-<tag>/              # unavoidable patches, default ZERO (CON-12, BLD-15)   [build-smith]
tests/
  firmware_tests/
    host/test_release_bundle.py     # manifest/merge/schema/hash/license fixtures           [firmware-test-author]
    test_release_bundle.sh          # shell entrypoint for CI/release gates                 [firmware-test-author]
    ...                             # remaining host, conformance, and HIL tests
tools/
  ci/                               # repo-wide gate scripts (no-leak, SPDX, SHA-drift)    [build-smith]
.github/
  workflows/                        # CI: no-leak · SPDX · SHA-drift · 3-chip build matrix [build-smith]
```

### 10.6 Standard NeoPixel manifest contract

ADR-0018 adds one standard user-runtime package without adding an agent module
or upstream patch. All three lean target manifests explicitly call
`require("neopixel")`, freeze the same board-owned `_boot.py`, and avoid the
broad upstream networking bundle. A host resolver test follows manifest
includes and requires, proving each target selects exactly one upstream
`micropython/drivers/led/neopixel/neopixel.py` plus the firmware-embedded PyBLE
boot lifecycle, while structure tests reject a copied PyBLE driver,
GPIO/default table, upstream edit, or inert target image (FR-BOOT-1…6,
FR-LIB-1..3, BLD-16).

Every target leaves `MICROPY_BOARD_STARTUP` at the pinned ESP32 port default,
`boardctrl_startup()`. PyBLE MUST NOT replace that hook merely to initialize
NVS: the upstream default already initializes NVS, records the physical flash
size, and provides the fallback VFS-partition behavior. The frozen PyBLE
`_boot.py` starts the agent only after the VM and filesystem are ready.

The C3 overlay additionally includes the pinned upstream
`boards/sdkconfig.riscv`, resolves `CONFIG_COMPILER_OPTIMIZATION_SIZE=y`, keeps
`CONFIG_ESP_SYSTEM_HW_STACK_GUARD` disabled because the pinned ESP-IDF release
documents false RISC-V NLR panics for that guard, and enables the UART REPL for
debug parity. Its release configuration is DIO/80 MHz/4 MiB with the custom
partition table and an explicit ESP-image silicon window of
`min_chip_rev_full=3` through `max_chip_rev_full=199` (ESP32-C3 revision v0.3
or newer). Host configuration tests inspect the fully resolved SDK and
MicroPython board configuration; comments or a partial fragment do not satisfy
this contract.

Cross-build verification starts from fresh generated freeze state and inspects
the generated frozen content—not orphaned `frozen_mpy/*.mpy` intermediates—for
the NeoPixel module. It records artifact deltas, keeps the C3 footprint gate,
and runs `from neopixel import NeoPixel` before and after soft reboot on all
three targets. An optional visual HIL script accepts the GPIO explicitly,
drives one dim pixel for a bounded interval, and clears it in `finally`
(FR-LIB-4).

### 10.7 Release license inventory contract

The exact audit algorithm and `esp-idf-sbom` pin are frozen in
[browser-flashing §6](browser-flashing.md#6-licensing-and-release-notes).
Application and bootloader inventories for every profile are separate inputs;
their union is not inferred from an ESP-IDF component list alone. The audit
reconciles map-file archive members, `project_description.json`,
`compile_commands.json`, generated frozen content, prebuilt blobs, and
compiler/newlib runtime archives against `license-policy.json`. It runs
offline with isolated caches and rejects any unknown or stale input before a
candidate can be promoted.

Pinned nested manifests are resolved by their literal package/module
selections, and the result must equal generated frozen content. Archive member
names are a multiset: duplicate basenames are legal, while absent map members
or an unbound archive remain fatal. Build-generated component archives are
selected in policy only by stable component topology. Ordinary archive
membership is derived from the exact component object-output directory and
archive-member multiset, not from unique source paths. Every linked compile
output is consumed exactly once by an archive or by an exact map `LOAD`
direct-object path. A compile output absent from both is classified as
build-only/unlinked rather than forced into redistributed evidence. Its source
path stays in the hash-bound compile-command document and still passes exact
root validation, but its output/source bytes are not redistributed inputs. The
JSON output path and compiler `-o` path must resolve identically under their
distinct specified bases, as must the JSON source and compiler `-c` source. One
source may have both a `main` archive output and a direct ELF output. The
direct-object set must also equal the safely parsed `.o`/`.obj` arguments in the
role's hash-bound `link.txt`.
The pinned generated-header, repository PyBLE C-source, retained Berkeley DB,
and zero-byte IDF ELF-anchor shapes are the only described/compiled-source
exceptions. The generated `main` binding carries the linker-command hash,
metadata-input records, and direct output/source records in addition to its
archive-only sources. Exact
project-description/compile/map hashes, source hashes, member lists, and
generated archive digests are derived after the build and live in the receipt,
never in committed policy. Tests run equivalent clean builds below different
absolute roots, require one shared policy to accept both, require distinct
receipt bindings, and reject any policy attempt to predeclare a generated
value. The complete generated context is observed again after all SBOM runs;
mutating a source, metadata input, direct object, or link document during that
window is fatal. A nested selector covers the exact CMake
target/archive/object-directory topology below an empty `CONFIG_ONLY` owner.
Tests use the real Mbed TLS shape,
classify separately compiled Everest/p256m object-library outputs as unlinked,
and reject a path-only selector, synthetic component, object-directory escape,
unmatched linked compile output, or archive/member mismatch. Opaque,
frozen-source, prebuilt, and admitted versioned-toolchain inputs retain reviewed
predeclared digests.

External GCC distributions remain in the installed ESP-IDF tools download
cache; they are not copied into the repository. Schema-v2 policy pins the
logical URL-basename filename, size, digest, format, and top-level archive root,
separately from the installed version directory. Each toolchain also has one
exact, nonempty `compiler_frontends` catalog of unique
installed-root-relative path/SHA-256 records; the initial Xtensa and RISC-V
records contain exactly the prefixed `gcc` and `g++` pair, not one
representative compiler. The observer derives the tools home and
`dist/<filename>` only from
the complete executable set parsed from compile commands, the versioned
ESP-IDF installation layout, and the hash-bound pinned `tools/tools.json`
record. Every compile-command entry is attributed to exactly one catalog
frontend, every frontend is observed, and all frontends derive the same
installed root, trusted tools home, metadata identity, and distribution.

Tests reject missing, extra, or duplicate frontends, a mixed/sibling frontend
root, frontend digest drift, frontend or ancestor symlinks, installed bytes
that differ from the cached distribution, policy/caller cache paths, metadata
or filename disagreement, a sibling version, cache/install symlink escape,
distribution digest/size drift, unsafe members, and archive-root drift.
Private observations retain exact absolute executable paths for verification;
validated results and receipts retain only the canonical relative frontend
catalog and contain no host-absolute tools-home, cache, frontend,
installed-root, or runtime path.

All six exact raw SBOM outputs and all six normalized reviewed documents stay
with build-review evidence. Raw package fields and relationship graphs are
validated as exact evidence, including literal `NOASSERTION` states; reviewed
immutable metadata is added only in the normalized layer with explicit policy
attribution. Supplemental packages cover redistributed frozen or linked inputs
that the raw ESP-IDF graph omits: NeoPixel plus the contributing
`libmbedcrypto.a`, `libmbedtls.a`, and `libmbedx509.a` archives in the initial
profiles. Tests preserve omitted `PackageVersion` as an absent `versionInfo`
property for the real-shaped LAN867x/TinyUSB records and reject an invented
empty or reviewed value. Supplemental choice tests retain Mbed TLS's original
`(Apache-2.0 OR GPL-2.0-or-later)` evidence while selecting only
`Apache-2.0` for redistribution. Resolved runtime cases include
libgcc/libstdc++ with the GCC exception, newlib libc/libc_nano/libm_nano with
the complete reviewed newlib terms, and Xtensa `libxt_hal.a` with its pinned
MIT attribution. A reviewed input-expression allowlist permits those exact
runtime terms without rewriting the concrete broad raw toolchain expression;
identifier-only subsets and unreviewed alternate expressions fail. Exact
no-gap/no-duplicate coverage is release blocking: each observed item is
consumed by one resolution record, while that record carries an explicit
many-to-many package/input attribution.

The literal frozen-manifest observer derives canonical per-target evidence:
the complete unique, lexically ordered traversed-manifest inventory of
repository-logical path/SHA-256 records and the complete unique destination to
selected-source repository-logical path/SHA-256, literal optimization, and
metadata-version mapping. A non-null metadata version is a bounded ASCII
version token, never an arbitrary string or path. Tests require the semantic
receipt to bind those
records, require the public verifier to repeat the traversal and recompute
them, reject any host-absolute path, and reject a selected source or traversed
manifest changed after the build.

The same per-target gate reconstructs frozen bytecode from clean temporary
state with the pinned `mpy-cross` and pinned manifest/MPY generators, compares
the exact retained `.mpy` set and bytes, then compares the complete regenerated
`frozen_content.c`; the final pinned `mpy-tool.py` pass uses the byte-proven
retained MPY paths so its original-source comments also match. A once-per-audit
clean temporary `mpy-cross` build from the pinned MicroPython source must be
byte-identical to the admitted executable. Generator,
compiler, and replayed C-compilation subprocesses receive only the
release-defined controlled environment. The gate replays the unique exact
`frozen_content.c` compile argument vector, replacing only `-o`, and requires
the rebuilt object bytes to equal the unique owning linked-archive member. The
semantic receipt binds the architecture, qstr digest, logical
generator/compiler path hashes, destination/MPY hashes, owning archive/member,
and object hash. Tests
mutate source bytes while restoring timestamps, manifest metadata/optimization
or order, the qstr header, retained `.mpy`, compiler/generator bytes,
architecture, copied board files, and frozen C; they also cover missing,
extra, duplicate, and symlinked retained MPY paths, an internally-consistent
replacement C/MPY/qstr set with an unchanged linked object, inherited loader
or Python environment knobs, and assert that no temporary or host-absolute
path reaches public evidence. Every `(profile, role, frozen destination)` is
consumed by exactly one resolved input; cloning a frozen tree/input under a
second identifier is fatal.

Shipped raw aggregate/source packages without an exclusive input use
`allow-aggregate` and one exact same-profile/role raw-relationship path to an
input-owning `allow` resolution. Tests cover the 24 NimBLE, ESP-IDF, FreeRTOS,
lwIP, project, and heap-TLSF occurrences, keep them in the notice, and reject
input reuse, invented/cyclic/cross-role paths, aggregate-to-aggregate targets,
or `not-shipped` masquerading. The 18 genuinely unshipped occurrences retain
`not-shipped`. Its committed zero-input proof contains only profile/role and
an empty match set; the validator derives the exact project-description,
compile-command, and map hashes into the receipt. Tests require the derived
proof—not only raw policy JSON—to participate in the receipt semantic hash.
Top-level `shipment_review: {path, sha256}` independently binds a strict
canonical JSON ledger with the exact JSON integer `schema_version: 1` and the
complete sorted
`occurrences` array of exact `{profile_id, role, spdx_id, disposition}`
records. Tests require unique no-gap/no-extra raw occurrence coverage, the
three-value disposition vocabulary, strict integer schema types (never a
boolean or numerically-equal float), canonical lexical order, exact agreement
with resolutions, and receipt coverage of both the policy record and
normalized classifications. They reject a fully formed
aggregate-to-not-shipped substitution even when its mutable resolution and
zero-input proof were changed consistently. The ledger has no build hash and
is not duplicated inside resolution records.

The same strict integer rule applies at every other release schema boundary:
build provenance, the TOML tool lock, policy v2, audit receipt, embedded HIL
record, and `release.json`. Tests inject booleans and numerically-equal floats
at each parser boundary and require rejection before semantic use.

License texts are a hash-bound identifier catalog, not an untyped list. Every
SPDX identifier, exception, and approved `LicenseRef` appearing in any raw,
reviewed, resolved-input, or supplemental expression has one exact complete
text record. Tests distinguish the ESP-IDF component newlib terms from the
larger pinned-toolchain runtime newlib terms, byte-compare the GPLv3 and GCC
exception texts with both locked toolchain distributions, and preserve the
MicroPython BSD-1-Clause/Berkeley rescission, Mbed TLS option selection,
NimBLE/opaque-library notices, and managed-component source proof. Raw
nonselected controller and BLE Mesh records are covered once by explicit
zero-input `not-shipped` resolutions and do not leak into the public notice.
Verbatim supporting NOTICE/COPYRIGHT/license/SBOM/source/attribution artifacts
live in the separate required `review_files` catalog, where exact
repository-relative bytes are bound to a purpose and immutable commit, tree,
or managed-component identity. Tests reject duplicate or missing records,
path escape/symlinks, byte drift, and evidence with no source identity.

The public tree contains the deterministic complete
`THIRD_PARTY_LICENSES.txt`. The npm/web closure has a separate website notice
and never contaminates the firmware-embedded dependency inventory.

- **Native names:** native modules are `pble_*.c` / `pble_*.h` under `firmware/user_c_modules/pyble/` (naming per [CLAUDE.md](../../../CLAUDE.md); codec files `pble_*`). They are OI-3 and out of scope until HIL forces them (D1, [§8.6](#86-esp32-c3-mitigation)).
- **Ownership** in brackets is the routing target for each path; the firmware-architect freezes the layout, the named engineer authors the body, and firmware-test-author is the sole author of `[red]` tests under `tests/firmware_tests/`.
- **Root stays clean** ([CLAUDE.md](../../../CLAUDE.md) GOLDEN RULE): no new top-level entries; everything above lives under `firmware/`, `tests/`, `tools/`, `.github/`.

## 11. Per-chip design notes

Chip facts are owned by [hardware.md §1](../hardware.md#1-supported-chip-families-v1); the agent (Layer 3) is identical across all three (D2, NFR-MAINT-1). Differences live in the board overlay (Layer 2).

- **esp32 (baseline):** two-core Xtensa, ~520 KB SRAM. The conservative reference; runner task and BLE/agent task can sit on separate cores. Tightest heap among the dual-core parts but not the binding constraint.
- **esp32-s3:** two-core Xtensa, ~512 KB SRAM, PSRAM common, native USB. Most
  headroom; the USB-serial debug mirror (FR-CON-5, IF-USB) is most useful here.
  The chip-agnostic Layer-3 design must not require PSRAM because C3 has none,
  but the **initial S3 browser image profile** is deliberately narrower:
  `esp32-s3-n16r8` requires 16 MiB flash plus 8 MiB Octal PSRAM. A different S3
  memory topology requires another provisioning profile and HIL row; it is not
  silently accepted by family detection (BLD-17).
- **esp32-c3 (hardest — validate early):** single-core RISC-V, ~400 KB SRAM,
  least RAM. The **binding footprint constraint** (NFR-FP-C3). With one core,
  the BLE/agent and runner tasks time-share; STOP responsiveness
  ([§5.2](#52-stop-delivery)) and console backpressure
  ([§5.4](#54-console-backpressure)) must be validated here first. If
  frozen-Python does not fit, hot paths go native (D1,
  [§8.6](#86-esp32-c3-mitigation)). The known `esp32-c3-4mb` provisioning
  profile is defined only for C3 silicon revision v0.3 or newer but remains
  unavailable in the current pre-v1 release pending exact-profile HIL. Its
  exact image revision window appears in release metadata only after a later
  candidate qualifies it.

## 12. Error handling & status mapping

Every CMD returns a [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) 1-byte status (FR-PROTO-6). Firmware error paths map as:

| Firmware condition | PBLE/1 status | Requirement |
|---|---|---|
| Success | `OK (0x00)` | FR-PROTO-6 |
| Malformed/structurally invalid frame | `EBADREQ (0x01)` | FR-PROTO-8 |
| Missing file/dir | `ENOENT (0x02)` | FR-FS-2/15 |
| Path escapes jail / forbidden / control-plane write | `EACCES (0x03)` | FR-FS-10/11, SEC-4 |
| Filesystem full | `ENOSPC (0x04)` | FR-FS-15 |
| Underlying I/O failure | `EIO (0x05)` | FR-FS-15 |
| Allocation failure | `ENOMEM (0x06)` | FR-PROTO-6 |
| RUN while running | `EBUSY (0x07)` | FR-RUN-4, SEC-3 |
| CRC mismatch (frame or whole-file) | `ECRC (0x08)` | FR-PROTO-3, FR-FS-14 |
| Bad offset/length, or over-length device label | `ERANGE (0x09)` | FR-FS-15, FR-IDENT-1, SEC-10 |
| Unsupported opcode/feature; `IDENTIFY` with no identify LED configured | `EUNSUPPORTED (0x0A)` | FR-PROTO-9, FR-IDENT-4 |
| Unexpected internal fault | `EINTERNAL (0xFF)` | FR-PROTO-6, FR-BOOT-6 |

A CRC-failed frame is dropped and answered with `EVT ERROR(ECRC)` referencing the opcode if known (FR-PROTO-3). A control-plane fault is caught and the board fails safe to advertising (FR-BOOT-6, NFR-REL-1).

## 13. Security design

- **Pairing baseline (SEC-1/2):** v1.0 relies on BLE link-layer pairing/encryption ([protocol.md §10](../protocol.md#10-security-note-v1)); no application-layer auth — a connected client is trusted. No partial app-layer auth ships in v1.0.
- **Single active writer (SEC-3):** `pyble_agent`'s lock serializes file/run mutations; concurrent `RUN` → `EBUSY` ([§5.3](#53-serialization-single-active-writer)).
- **Non-writable control plane (SEC-4):** the path jail + forbidden-path set make Layer 2/3 unreachable by PBLE/1 file commands (FR-FS-11, CON-10).
- **Advertisement contents (SEC-5):** only the PyBLE Service UUID + short device name; no personal/user-identifying data **by default**. A user-set device label (`SET_LABEL`) may replace the name and is broadcast — bounded and non-PII (SEC-10 below). The default `PyBLE-XXXX` suffix is cosmetic, never an access key.
- **Broadcast label is bounded & non-PII (SEC-10):** a user-set `SET_LABEL` value **replaces** the advertised name and is therefore broadcast pre-connect; the board **bounds its length** (over-length → `ERANGE`) and the label is never required — the default `PyBLE-XXXX` carries no personal data. The app warns the user against putting PII in a broadcast label ([app.md](../app.md)).
- **Identity is display-only, never authorization (SEC-11):** `device_id`, `label`, and the identify-LED config are for recognition/display and the board's own UX. The agent **MUST NOT** gate access or branch trust on MAC, `device_id`, or `label` (consistent with SEC-7, CON-7); cold-boot trust remains simply "the connected client" (SEC-6).
- **Unowned cold boot (SEC-6):** advertise + wait; trust is simply the connected client; no stored owner/board identity, no MAC gating (SEC-7, CON-7).
- **On-device only (SEC-8):** no telemetry, no off-device transmission by default; consistent with offline-first (NFR-OFF-1/2).
- **No physical-output safety guard (NFR-SAFE-4):** the agent contains no hardware-output, calibration, or routing module (CON-8/9); physical safety is the user program's concern.
- **Future app-layer token (SEC-9):** deferred; if added, negotiated additively via HELLO caps with no breaking wire change.

## 14. Test design

This is where the Technical Design meets **Test-Driven Development** ([§0](#0-naming-note-acronym-clash)). The five verification categories of [PRD §1B.3](../prd.md) / [specs.md §2.2](specs.md) — *unit*, *conformance*, *build*, *size*, *HIL* — map onto the modules below. Each module's behaviour is pinned by a `[red]` test before code.

### 14.1 Per-module verification approach

| Module | unit (host) | conformance | build | size | HIL |
|---|---|---|---|---|---|
| `pyble_proto` | frame codec, CRC32, ID correlation, error-status mapping | full opcode round-trip vs fake transport | SPDX/no-leak lint | — | — |
| `pyble_ble` | fragment/reassemble logic (pure), adv-name = label-else-`PyBLE-XXXX` | fragmentation vs MTU matrix | NimBLE-only config | NimBLE buffer sizing | adv/scan-filter, MTU 247, INFO read, label shows in scan |
| `pyble_fs` | jail resolution, CRC accumulate, temp-rename | put/get window + resume + CRC vs fake | — | file-buffer footprint | multi-file upload, dropped-link resume |
| `pyble_runner` | state-machine transitions | RUN/STOP/RUN_STATE sequence | — | — | STOP vs `while True: pass`, traceback→stderr |
| `pyble_console` | tee + backpressure logic | CONSOLE_DATA stream tagging | — | staging-buffer footprint | live stdout/stdin latency |
| `pyble_info` | caps assembly (incl. device_id/label/has_identify/identify_led), label bound→ERANGE, identify EUNSUPPORTED-when-unset, version negotiation | HELLO/DEVICE_INFO identity fields, SET_LABEL/SET_IDENTIFY_LED/IDENTIFY round-trip | — | — | real chip/mpy/free_mem/has_sd, label↔NVS persist across reboot, non-blocking blink |
| `pyble_agent` | dispatch wiring, lock serialization | EBUSY, single-writer | frozen-manifest build | flash/heap gates | cold-boot safety, fail-safe |

### 14.2 Shared fake transport

PBLE/1 **conformance** tests run against an **in-memory fake transport** shared between the firmware agent and the Dart `pble` client ([app.md](../app.md)), so both ends are tested against the same byte sequences — the contract is validated once, both sides honor it (FR-PROTO-1, NFR-MAINT-3, IF-PROTO). This is the cross-language guard that protocol changes do not silently diverge.

### 14.3 Build, size, and HIL gates

- **build:** SHA-drift gate (BLD-2), no-leak gate (CON-6), SPDX lint
  (NFR-MAINT-4), per-target build sanity (BLD-3/4/5), exact manifest/profile
  validation (BLD-6/17), provenance/integrity/license/reproducibility gates
  (BLD-8/14/18/19), and public-byte parity (BLD-7/22). Reproducibility
  fixtures verify the exact three-checkout layout in both build roots,
  application-project-path binding, locked commit and canonical origin,
  clean tracked trees, retained source availability during audit, and
  target-isolated managed components; they reject cross-target checkout
  reuse, overwrite, early deletion, path escape/symlinks, or canonical-proof
  drift. License fixtures cover
  the pinned literal asyncio/NeoPixel manifests, duplicate archive members,
  real tag/value `NOASSERTION` plus concrete-license records, verified
  external toolchain inputs, generated component receipts, exact raw/reviewed
  evidence sets, supplemental source-tree packages, identifier-to-text
  catalog coverage, byte-distinct framework/toolchain newlib terms, exact
  toolchain-distribution license bytes from the trusted ESP-IDF download cache,
  exact metadata/cache/install binding with distinct archive and version roots,
  absence of host-absolute paths in receipts, and profile-specific zero-input
  not-shipped proof. Supplemental source-tree digests exclude Python bytecode
  cache artifacts while the audit rejects any such artifacts in the retained
  checkout; release builds force bytecode generation off so checkout-local
  absolute paths cannot contaminate otherwise identical source evidence.
- **size:** enforce the total application-image ceiling and derived
  factory-partition headroom floor during build/candidate validation. Continue
  structural application-fit checks on all three source targets, including
  deferred C3. Heap, boot, goodput, and reliability are not mislabeled as
  static size gates.
- **HIL:** the release-blocking bench runs on every exact profile included in
  the release. For the current pre-v1 candidate that is exactly
  `esp32-4mb` and `esp32-s3-n16r8`; it covers the frozen §8.5 resource
  workload, multi-file integrity (NFR-REL-5), STOP authority (NFR-SAFE-1),
  cold-boot safety (NFR-SAFE-3), candidate-browser install, and
  interrupted-flash recovery from an access-controlled,
  production-equivalent HTTPS deployment (BLD-20/21). C3 HIL and
  footprint/goodput gates remain open, block C3 enablement, and block v1.0.
  Public activation then needs only the non-destructive origin/integrity smoke
  defined by BLD-22.

### 14.4 Required red matrix for pre-v1 qualification

The first implementation commit after this freeze is `[red]` and covers:

- `tests/firmware_tests/host/test_oi1_profile_bench.py`: fake BLE central and
  reset transport; exact workload/sample counts; stale-advertisement
  rejection; HELLO MTU/window/chunk enforcement; deterministic payload bytes;
  strict GET offset validation; timer boundaries; retransmit accounting;
  heap-marker parsing; canonical evidence; baseline versus verify mode; and
  explicit C3 refusal;
- `tests/firmware_tests/host/test_footprint_gates.py`: exact two-profile policy
  order, exact C3 deferral, all nine threshold keys/types, evidence hash,
  application bytes/headroom arithmetic, derivation algorithms, threshold
  boundary pass, one-unit crossing failure, and continued structural C3 build
  validation without C3 qualification numbers;
- `tests/firmware_tests/host/test_release_bundle.py` and
  `test_release_finalization.py`: the exact HIL V2 marker and keys, V1
  rejection, candidate null observations, policy/build immutability, public
  observation recomputation, candidate-release binding, missing/extra/wrong-
  type/wrong-unit/wrong-count/wrong-profile/wrong-order/wrong-hash fixtures,
  manufactured-MTU rejection, and candidate-to-public mutation envelope;
- `tests/firmware_tests/host/test_audited_candidate_validation.py`: policy and
  baseline evidence remain source/audit bound while C3 retains build/license
  audit participation but cannot acquire a public row; and
- shell entry points `test_oi1_profile_bench.sh` and
  `test_footprint_gates.sh`, wired into the applicable host/release gate.

Tests use fake transports and fixtures; real hardware execution occurs only
after the `[green]` bench/tooling commit. Production firmware caps, app code,
and PBLE/1 bytes are intentionally outside this minimal change.

## 15. Traceability

Design element → satisfied requirement IDs. Each `FR-*` block has at least one design home.

| Design element (section) | Module(s) | Requirement IDs |
|---|---|---|
| BLE peripheral, GATT, adv, MTU, fragmentation, advertised-name assembly ([§4.1](#41-pyble_ble--ble-peripheral--transport), [§4.8](#48-device-config-store--label--identify-led-nvs)) | pyble_ble | FR-BLE-1…12, IF-BLE, CON-5, SEC-5 |
| Frame codec, CRC32, dispatch, status map ([§4.2](#42-pyble_proto--protocol-engine), [§7](#7-protocol--data-structures), [§12](#12-error-handling--status-mapping)) | pyble_proto | FR-PROTO-1…10, IF-PROTO |
| Runner, STOP, SOFT_REBOOT, RUN_STATE ([§4.3](#43-pyble_runner--execution-control), [§5](#5-concurrency--task-model)) | pyble_runner | FR-RUN-1…10, FR-MODE-2/3, NFR-SAFE-1/2 |
| FS bridge, jail, windowed upload, resume, atomicity ([§4.4](#44-pyble_fs--filesystem-bridge--workspace-jail), [§7.4](#74-windowed-upload-state-machine-resume--crc), [§9](#9-filesystem--storage-design)) | pyble_fs | FR-FS-1…16, IF-FS, NFR-PERF-2, NFR-REL-2/3, CON-3/10 |
| Console tee, stdin feed, backpressure, USB mirror ([§4.5](#45-pyble_console--console-tee), [§5.4](#54-console-backpressure)) | pyble_console | FR-CON-1…5, NFR-PERF-3, IF-USB |
| Device info, HELLO/caps, version negotiation ([§4.6](#46-pyble_info--device-info--capabilities)) | pyble_info | FR-INFO-1…6, FR-FS-13, FR-BOOT-3, BLD-13 |
| Device config store (label + identify-LED), identity caps, non-blocking identify, dispatch wiring ([§4.8](#48-device-config-store--label--identify-led-nvs), [§5.5](#55-identify-blink-non-blocking), [§9.5](#95-device-config-persistence-nvs)) | pyble_info + pyble_ble + pyble_agent | FR-IDENT-1…6, FR-BLE-12, FR-INFO-1/4, SEC-10/11, CON-13, OI-6 |
| Boot, lifecycle FSM, dispatch surface, single-writer ([§4.7](#47-pyble_agent--boot--dispatch-surface), [§6](#6-boot--runtime-state-machine)) | pyble_agent | FR-BOOT-1…6, FR-MODE-1/4, SEC-3/6, NFR-REL-1 |
| Two-task model, STOP delivery, serialization ([§5](#5-concurrency--task-model)) | runner+agent | FR-RUN-3, FR-BLE-11, NFR-SAFE-1/2, SEC-3 |
| Memory/footprint levers, native plan ([§8](#8-memory--footprint-design)) | all | NFR-FP-FLASH/HEAP/BOOT/TPUT/C3/GATE/CLOSE, NFR-PERF-1/4 |
| Chip-agnostic Layer 3 ([§2.2](#22-chip-agnostic-layer-3), [§11](#11-per-chip-design-notes)) | all | NFR-MAINT-1, CON-4 |
| Build pipeline, SHA gate, overlay copy-in, release manifest/integrity/provenance/recovery bundle ([§10](#10-build-system-design)) | scripts | BLD-1…22, CON-1/2/11/12, NFR-REL-4, NFR-MAINT-4 |
| Native-without-contract-change ([§2.1](#21-native-c-agent-from-day-one), [§8.6](#86-esp32-c3-mitigation)) | proto/ble/fs | NFR-MAINT-3 |
| Security design ([§13](#13-security-design)) | all | SEC-1…11, NFR-OFF-1/2, NFR-SAFE-4, CON-6/7/8/9/13 |
| Test design, fake transport, gates ([§14](#14-test-design)) | all | NFR-FP-GATE, NFR-REL-5, NFR-MAINT-2/3, all *verify* traces |
| Offline-first (no network) ([§13](#13-security-design)) | all | NFR-OFF-1/2, SEC-8 |
| IF-MACHINE (hardware via standard `machine`) ([§9.3](#93-path-jail-enforcement), [§11](#11-per-chip-design-notes)) | (user code) | IF-MACHINE, CON-9 |

**Requirements with no dedicated design element:** none. `SEC-9` is intentionally deferred (no v1.0 design surface beyond the additive-caps note in [§13](#13-security-design)). The `NFR-FP-*` measurement and enforcement design is frozen in §8.5; only evidence-derived per-profile numbers remain OI-1. Likewise the concrete label max-length, `SET_IDENTIFY_LED` encoding, and `IDENTIFY` blink-duration bound are owned by [protocol.md](../protocol.md) and tracked by OI-6, not invented here.

## 16. Risks & open questions

- **R1 — Footprint on ESP32-C3 (binding).** C3 real-hardware resource numbers
  remain deferred, so C3 cannot appear in the current pre-v1 bundle and v1.0
  cannot close. Mitigation once matching hardware is available: run the same
  frozen method, and use native `USER_C_MODULE` hot paths if needed
  ([§8.6](#86-esp32-c3-mitigation)). The two-profile pre-v1 qualification does
  not waive or predict the C3 result (OI-1, NFR-FP-CLOSE).
- **R2 — Frozen→native trigger point.** Which paths move to C, and on which chip the budget forces it, is undecided until HIL measurement (OI-3). The module boundaries ([§4](#4-module-design)) are drawn to make the move contract-neutral (NFR-MAINT-3).
- **R3 — iOS/Android BLE MTU quirks.** Central platforms negotiate MTU differently and may not grant 247; the firmware must operate correctly across the negotiated MTU down to the default (FR-BLE-8). Fragmentation/reassembly is tested across an MTU matrix ([§14.1](#141-per-module-verification-approach)).
- **R4 — Single-core C3 STOP latency.** With one core the runner and BLE/agent task time-share; STOP must still land promptly against a tight loop ([§5.2](#52-stop-delivery)). Validate on C3 HIL first ([§11](#11-per-chip-design-notes)).
- **R5 — Candidate pins not yet selected or HIL-approved.** `versions.lock`
  values (MicroPython v1.28.0 / ESP-IDF v5.5.1) remain proposed defaults until
  selected as candidate-frozen inputs before the release builds and HIL
  (OI-2). Candidate-freezing makes the input immutable; it does not approve
  C3 compatibility or public release. A pin change creates a new candidate and
  reruns all build, audit, deployment, and exact-profile HIL gates through
  `upgrade_micropython.sh` (BLD-9/19/21).
- **R6 — PBLE/1 still DRAFT.** Opcode/UUID/status numbers are provisional until [protocol.md](../protocol.md) §2/§4 freeze (OI-4); the single constants mirror (D6) localizes the churn.
- **R7 — Auto-run caps flag naming.** The opt-in `main.py` auto-run flag name/encoding is owned by [protocol.md §7](../protocol.md#7-hello--capabilities) and must be fixed before F-12 (OI-5).
- **R8 — Identity/identify wire constants not frozen.** The label max-length, the `SET_IDENTIFY_LED` GPIO+active-level encoding, and the `IDENTIFY` blink-duration bound are owned by [protocol.md](../protocol.md) and must be frozen before FR-IDENT/FR-BLE-12 implementation (OI-6); the single constants mirror (D6) localizes the churn.
