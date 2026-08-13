# PyBLE Agent Firmware — Technical Design Document (TDD)

Status: **DRAFT** · Owner: project maintainer · Last updated: 2026-08-12

> **Frozen at G0 (2026-07-01, `[docs]`):** the source-tree layout ([§10.5](#105-source-layout-frozen)), which realizes the frozen NFR-MAINT-2 six-module design and the [specs.md](specs.md) §5.1/§5.6/§6/§8 freeze. Design narrative elsewhere in this doc remains DRAFT and is pinned per-story by its `[red]` tests ([§4](#4-module-design)).
>
> **Frozen pre-v1 resource-qualification design (2026-07-30, `[docs]`):**
> [§8.5](#85-meeting-the-nfr-fp-gates) and
> [§14.3](#143-build-size-and-hil-gates) freeze the historical two-profile
> measurement contract and its source-era amendments before dependent `[red]`
> tests. Historical split v0.5 uses OI-1 policy schema 2, release schema 3, and
> HIL V4. ADR-0033 adds the v0.6.0 five-profile successor: policy schema 3,
> release schema 4, and HIL V5. Immutable v0.4.2 replay retains its exact
> two-profile release/HIL V2 contract. Every v0.6.0 result remains pending.
>
> **Frozen optional ST7789 user-runtime design (2026-08-01, `[docs]`,
> [ADR-0023](../../decisions/0023-explicit-st7789-user-runtime.md)):**
> [§2.9](#29-explicit-layer-4-st7789-runtime),
> [§4.9](#49-pyble_st7789--optional-layer-4-user-runtime),
> [§10.7](#107-st7789-manifest-and-source-contract), and the corresponding
> §14 test/HIL rows freeze the additive user-library boundary. ADR-0028
> restricts that library to the exact-board build variant; it adds no PBLE/1
> surface or chip target.
>
> **Frozen exact-board image split (2026-08-03, `[docs]`,
> [ADR-0028](../../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)):**
> the build matrix has four variants over three IDF targets. Generic S3 is
> lean; only `waveshare-esp32-s3-lcd-147b` contains the display modules,
> splash boot wrapper, and native readiness seam. The earlier v0.5.1
> three-profile candidate did not complete qualification and remains history.
>
> **Frozen ESP32-C3 engineering-qualification design (2026-08-12, `[docs]`,
> [ADR-0032](../../decisions/0032-qualify-generic-esp32-c3-4mb-on-reference-hardware.md)):**
> [§5.4](#54-console-backpressure) freezes whole-message control priority under
> console flood and [§11](#11-per-chip-design-notes) binds it to the
> ESP32-C3-MINI-1-N4 reference contract. All observations remain pending; this
> design records no passing C3 result.
>
> **Frozen heterogeneous v0.6.0 release design (2026-08-12, `[docs]`,
> [ADR-0033](../../decisions/0033-qualify-v060-as-five-profile-heterogeneous-release.md)):**
> one atomic candidate orders four ESP Web Serial profiles followed by
> `rpi-pico2-w` with verified UF2/manual BOOTSEL. C3-G0…C3-G6 and Pico GP2
> remain gates. Two clean builds, policy schema 3, release schema 4, V5 exact-
> byte HIL, and both-platform app HIL are required before activation.

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
3). Layer 4 (the user workspace) is served, not designed here. The narrow
exception is the optional frozen Layer-4 `pyble_st7789` user-runtime selected
at build time and specified in [§4.9](#49-pyble_st7789--optional-layer-4-user-runtime);
it is not an agent module. The Flutter app ([app.md](../app.md)) is out of scope
except where the firmware shares an in-memory fake transport with the Dart
`pble` client for conformance tests ([§14](#14-test-design)).

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

### 2.9 Explicit Layer-4 ST7789 runtime

**Decision (D9):** `pyble_st7789` is a generic, clean-room MIT Layer-4 user
library, not a seventh agent module and not a Layer-2 routing profile. The
canonical source lives at `firmware/python_modules/pyble_st7789.py`; build prep
copies it into generated board input only for exact-variant manifest
resolution, and only the `waveshare-esp32-s3-lcd-147b` manifest freezes it.
Import is definition-only and does not import
`machine`, allocate a framebuffer, or touch hardware. An explicit `ST7789(...)`
call owns/configures the SPI bus and drives the explicitly supplied Pin
objects. No board name, pin, geometry, offset,
colour-order, inversion, or clock value exists in the module. — *(implements
ADR-0023; satisfies FR-TFT-1…3 and CON-8/9.)*

This selection neither detects nor claims a display. It belongs to the separate
`waveshare-esp32-s3-lcd-147b` provisioning image; lean
`esp32-s3-n16r8` freezes neither the driver nor the companion. The build matrix
has four variants (`esp32`, `esp32-s3`, `waveshare-esp32-s3-lcd-147b`, and
`esp32-c3`) over three IDF targets. Exact-board values remain confined to the
manually chosen app example, the exact overlay, and exact-profile HIL.

### 2.10 Explicit exact-board boot identity, never detection

**Decision (D10):** `pyble_waveshare_lcd147b` is one named-board companion,
not a board probe, routing profile, seventh agent module, or PBLE/1 capability.
Its import is definition-only. The pinned NVS-not-found error for a missing
`pyble/lcd147splash` key is enabled so a freshly erased exact-board install
shows its QR splash. Exact integer `0`, other readable values, and other NVS
failures are disabled; exact integer `1` is enabled. The public enable/disable
calls commit `1`/`0`.
The exact-board boot wrapper attempts it after
native-agent init and before worker startup. It first saves the current
`sys.path` contents,
replaces that same list's contents with only `.frozen`, and keeps the frozen-
only resolution scope around the import and complete guarded call. The
companion checks the flag before waiting or importing
`machine`/`pyble_st7789`. This entire wrapper exists only in the exact-board
overlay. Lean generic S3, classic ESP32, and C3 freeze no companion, execute no
splash NVS lookup or display import path, and compile out the splash-only
native readiness Event Group and `wait_ready` API. The exact wrapper restores
the exact path contents in `finally` before any worker or user boot code runs.

An enabled boot waits on a native FreeRTOS event bit for at most 1,500 ms. The
bit is set only after NimBLE accepts advertising or a GAP connection succeeds,
not merely after host synchronization. One frame is then transferred with the
exact published board wiring. Driver deinit releases SPI and framebuffer,
`gc.collect()` reclaims the buffer, and only then does a zero-wait readiness
recheck permit the active-high backlight so ST7789 GRAM remains visible without
a timer or sleeping boot. Readiness-event allocation failure is nonfatal and
makes every wait false. Every error closes CS/backlight, releases resources,
and returns control to the ordinary boot lifecycle. The bounded transaction
remains serialized on the main VM while the native BLE host establishes
readiness; no second display task exists, so there is no concurrent startup SPI
owner. The readiness wait may release the GIL safely because runner/filesystem
workers are created only after the frozen path is restored. — *(implements
ADR-0024; satisfies
FR-SPLASH-1…9 and preserves FR-BOOT-4/6.)*

## 3. Architecture overview

### 3.1 The four layers

```text
+--------------------------------------------------------------+
| Layer 4  USER RUNTIME  (served, not part of the agent)       |
|          workspace + optional inert pyble_st7789 library     |
+--------------------------------------------------------------+
| Layer 3  PYBLE AGENT  (control plane — this design)          |
|   pyble_agent  (boot + dispatch surface)                     |
|   pyble_ble  pyble_proto  pyble_runner                       |
|   pyble_fs   pyble_console pyble_info                        |
+--------------------------------------------------------------+
| Layer 2  TARGET ADAPTER / BOARD OVERLAY                     |
|          (four variants over IDF esp32/esp32s3/esp32c3)     |
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

All six functional modules plus `pyble_agent` are **Layer 3**. They depend
downward only on Layer-1 MicroPython APIs and a single Layer-2 constants module
(D2). No Layer-3 module imports another chip-specific symbol directly.
`pyble_st7789` is independently frozen Layer-4 content: neither the agent nor
the default boot path imports it; the enabled exact-board companion imports it
only after BLE readiness. It imports no Layer-3 module. — *(NFR-MAINT-1,
NFR-MAINT-2, FR-TFT-2, FR-SPLASH-1…4.)*

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
    def wait_ready(self, timeout_ms: int) -> bool      # exact-board build only; boot-internal
    def on_connect(self, cb) -> None
    def on_disconnect(self, cb) -> None
```

**Key data structures / state:** the GATT table (Service/RX/TX/INFO UUIDs from the [protocol.md §2](../protocol.md#2-ble-transport-gatt) constants mirror); a single **reassembly buffer** (static, sized `max_message`, see [§7.3](#73-buffer-sizing)); a fragment-index tracker (`FIRST`/`LAST`/`index mod 64`); negotiated MTU; connection handle; the **advertised name** — the device label when set, else `PyBLE-` + `device_id` (the last two BLE-MAC bytes in uppercase hex), used for the name only, never for access control ([§4.8](#48-device-config-store--label--identify-led-nvs), CON-7/SEC-7/SEC-11).

**Advertised-name assembly:** at boot the name is `PyBLE-` + `device_id`; when `SET_LABEL` sets a non-empty label, `pyble_ble.set_adv_name(label)` updates the advertisement so the label shows in the scan list pre-connect; clearing the label restores `PyBLE-` + `device_id` (FR-BLE-12). Length bounding/validation happens in the device-config store before the value reaches the air ([§4.8](#48-device-config-store--label--identify-led-nvs), SEC-10).

**Exact-board boot-readiness event:** only the
`waveshare-esp32-s3-lcd-147b` build enables this native seam. Its native init
creates one persistent FreeRTOS Event
Group before starting NimBLE. `pble_advertise` checks every field/start return
and refreshes `READY` from truth: a live connection, a zero
`ble_gap_adv_start` return, or `ble_gap_adv_active()` (including an
`EALREADY` race) is ready; when neither connection nor advertising is active
it clears the bit. A successful GAP connect sets it because the PBLE/1
transport is then more available than advertising. A failed connect and
disconnect clear it before re-advertising; ADV_COMPLETE clears and restarts
only while disconnected; NimBLE reset clears it and `pble_synced`.
Re-advertising sets it again only after acceptance or confirmed active state.
Reset also clears the cached connection handle before any readiness
recomputation. Event Group allocation failure does not fail BLE initialization:
the group remains null and `wait_ready` always returns false.
This order closes the `on_sync`/boot and soft-reset races: the event object and
bit survive a MicroPython VM reset, while a NimBLE reset explicitly invalidates
them. The internal MicroPython `wait_ready(timeout_ms)` validates an integer in
`0..1500`, releases the GIL, calls `xEventGroupWaitBits` with no clear-on-exit,
and returns whether the bit was observed before the one supplied deadline. It
never treats `pble_synced` as readiness and never runs VM code from the NimBLE
task (FR-SPLASH-4). Lean `esp32-s3`, classic `esp32`, and `esp32-c3` compile
out the Event Group, all associated transitions, and the MicroPython
`wait_ready` symbol.

**Release link-tuning state machine:** every connection starts a fresh bounded
ladder on the NimBLE default event queue. DLE runs first (`251` octets,
`2120` µs, four attempts maximum). On S3/C3, 2M PHY preference is a distinct
second phase with at most four attempts. Connection parameters (`12..24`
interval units, latency zero, four-second supervision, three submissions
maximum) are a third phase. The 200 ms one-shot callout is rearmed after an
unconfirmed phase or nonzero submission and is the progress guarantee;
`DATA_LEN_CHG`, `PHY_UPDATE_COMPLETE`, and `CONN_UPDATE` may advance or retry
the ladder but a missing event can never strand it. PHY and connection-
parameter requests are never submitted back-to-back from one callout.
Disconnect stops the callout and clears all phase state. Fixed ERROR-level log
records cover every request and completion so the OI-1 runner can attest the
exact transfer connection without adding a PBLE/1 field (NFR-PERF-5,
ADR-0027).

**Dependencies:** Layer-1 `bluetooth`; the protocol constants mirror (UUIDs, frag-header bits); the device-config store ([§4.8](#48-device-config-store--label--identify-led-nvs)) for the label/`device_id` feeding the advertised name. Calls up into `pyble_proto` via the `on_message` callback.

**Frozen-vs-native plan:** frozen first. Reassembly, the per-fragment copy loop, and TX fragmentation are prime **native** candidates (D1) since they run per packet.

**Satisfies:** FR-BLE-1…12, FR-SPLASH-3/4, NFR-PERF-5, IF-BLE, CON-5 (NimBLE only), SEC-5 (advertisement contents).

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

**Execution model:** a `RUN` while `state == running` returns `EBUSY` (FR-RUN-4). On launch: reply `RSP{status}` then emit `RUN_STATE(running)` (FR-RUN-1). `STOP` raises `KeyboardInterrupt` in the runner thread (using MicroPython's scheduled-exception / pending-interrupt mechanism) so it lands even against a tight loop (FR-RUN-5, NFR-SAFE-1). On normal return → `RUN_STATE(done)`; on uncaught exception → traceback to `CONSOLE_DATA(stderr)` then emit `RUN_STATE(error)` (FR-RUN-9). After `STOP`/exception, teardown is clean and the board returns to `idle` (FR-RUN-6/10). `SOFT_REBOOT` submits its one-packet `RSP{OK}`, arms one pre-created 250 ms one-shot, and only the timer callback schedules `SystemExit` on the main task. The pending flag rejects duplicate reboot requests; a TX failure cancels reset. This separates local Notify acceptance from VM teardown while keeping the handler non-blocking and bounded (FR-RUN-8).

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

**Boot policy:** initialize and request advertising (FR-BOOT-1). The exact-board
variant then attempts its separately guarded splash; lean generic S3, classic,
and C3 proceed directly. All variants start runner and filesystem workers,
attach the console tee, then consider autorun. The exact splash wrapper is
nested and fail-open, so its disabled state, timeout, or exception cannot
skip worker startup. The agent **never** auto-runs `main.py` unless the
independent auto-run flag is set (FR-BOOT-2/3/4/5, NFR-SAFE-3); it reaches
advertising independent of workspace and display validity (FR-BOOT-4); and it
does not depend on editable `boot.py`/`main.py` (FR-BOOT-5).

**Frozen-vs-native plan:** frozen (orchestration).

**Satisfies:** FR-BOOT-1…6, FR-SPLASH-3/4, FR-MODE-1/4, SEC-3/6, NFR-REL-1, NFR-MAINT-2.

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

### 4.9 `pyble_st7789` — optional Layer-4 user runtime

**Responsibility:** provide a small explicit framebuffer driver over standard
MicroPython `machine.SPI`/`machine.Pin` and `framebuf` for user programs. It is
not imported by `_boot.py`, the agent, or another frozen module. It advertises
no capability and owns no PBLE/1 command (D9, CON-8/9).

**Frozen public API:**

```python
def rgb565(red, green, blue) -> int

class ST7789:
    def __init__(self, spi_id, baudrate, polarity, phase,
                 sck_pin, mosi_pin, cs_pin, dc_pin, reset_pin, backlight_pin,
                 width, height, x_offset, y_offset, bgr, inversion)
    def fill(self, colour) -> None
    def pixel(self, x, y, colour) -> None
    def line(self, x0, y0, x1, y1, colour) -> None
    def rect(self, x, y, width, height, colour) -> None
    def fill_rect(self, x, y, width, height, colour) -> None
    def text(self, value, x, y, colour) -> None
    def show(self) -> None
    def backlight(self, enabled) -> None
    def deinit(self) -> None
```

`__all__` is exactly `("ST7789", "rgb565")`. Constructor inputs have no
defaults. The six `*_pin` inputs are explicit, already-constructed
`machine.Pin` objects; the driver contains and converts no GPIO numbers. Only
construction lazily imports `machine.Pin` and `machine.SPI`, rejects every pin
that is not an instance of that exact runtime `Pin` type, and creates
`SPI(spi_id, baudrate=baudrate, polarity=polarity, phase=phase, sck=...,
mosi=...)`. Scalar validation occurs before output is driven: dimensions are
positive, offsets are non-negative and the inclusive window fits 16-bit
ST7789 addressing; baud rate is positive; polarity/phase are each zero or one;
and `bgr`/`inversion` are Boolean. Pin validation also precedes every GPIO
write, SPI construction, framebuffer allocation, controller command, and
sleep; accepting an arbitrary callable as a pin is forbidden. `rgb565`
validates three integer channels in `0..255` and implements the exact FR-TFT-4
expression.

**Construction and controller state:** construction owns the SPI instance and
one `bytearray(width * height * 2)` wrapped by
`framebuf.FrameBuffer(..., framebuf.RGB565)`. It first establishes safe output
levels (CS inactive/high and active-high backlight low), performs a bounded
hardware reset, then emits the clean-room minimum controller sequence in this
order: software reset (`0x01`), sleep out (`0x11`), RGB565 pixel format
(`0x3a, 0x55`), memory-access control (`0x36`, BGR bit `0x08` iff `bgr`),
inversion on/off (`0x21`/`0x20`), normal display on (`0x13`), and display on
(`0x29`), with controller-documented bounded delays around reset, sleep-out,
and display-on. Each command transaction makes CS active only for that
transaction and restores it high in `finally`. Construction does not issue a
RAM write and leaves the backlight off.

**Framebuffer and transfer:** drawing calls delegate to `framebuf` and clip to
the visible `width × height` buffer; none performs SPI I/O. `show()` sends
`CASET (0x2a)` with `[x_offset, x_offset + width - 1]`, `RASET (0x2b)` with
`[y_offset, y_offset + height - 1]`, then `RAMWR (0x2c)`, all as inclusive
big-endian 16-bit coordinates. Framebuffer RGB565 words are transferred
high-byte first. The implementation uses an even fixed internal chunk size no
larger than 4092 bytes; it may byte-swap one chunk in place, but a `finally`
restores that chunk before advancing or propagating an SPI failure. An outer
`finally` makes CS inactive. Therefore the entire framebuffer is byte-identical
after success or failure and can be retried (FR-TFT-5).

**Output ownership and cleanup:** `backlight(enabled)` accepts only Boolean and
drives the supplied pin high/low. `deinit()` is idempotent; it turns the
backlight off, leaves CS high, deinitializes the driver-owned SPI object, drops
the framebuffer references, and marks the object closed. Drawing, display, or
backlight calls after closure raise `RuntimeError`. A partial-constructor error
performs that same best-effort backlight/CS/SPI/framebuffer teardown without
masking the original error. Transfer failure has a different, deliberately
retryable boundary: `show()` restores any swapped chunk, forces backlight low
and CS high on a best-effort basis, preserves the original exception, and
retains the SPI instance, framebuffer, and open state. It does not deinitialize
SPI or discard the framebuffer; a subsequent `show()` retries the complete
window and frame (FR-TFT-5/6).

**Clean-room boundary:** only public ST7789 command definitions/controller
documentation, official board electrical facts, and tests are design inputs.
The unlicensed vendor demo archive is neither copied, imported, vendored,
hashed as a source dependency, nor used as an initialization-code source. The
canonical module is first-party MIT with an SPDX header and is included in the
ordinary source/license audit (FR-TFT-7, CON-6).

**Satisfies:** FR-TFT-1…7, IF-MACHINE, CON-6/8/9.

### 4.10 `pyble_waveshare_lcd147b` — exact-board splash companion

**Responsibility:** provide a factory-enabled-after-erase, persistently
disableable boot-splash choice and render one
fail-safe identity/app-discovery frame on the Waveshare
ESP32-S3-LCD-1.47B. It is exact-variant-only frozen Layer-2/4 glue. It owns no PBLE/1
handler or capability, is not used for connection selection, and never probes
for a board.

**Frozen public API:**

```python
def boot_splash_enabled() -> bool
def enable_boot_splash() -> None
def disable_boot_splash() -> None
def show_boot_splash() -> bool
```

`__all__` contains exactly those four names. The module-level body defines only
constants, functions, and the immutable QR rows; it does not import `machine`,
`esp32`, `pyble`, or `pyble_st7789`. Each dependency is lazy and follows the
guard order below.

**Persistence:** `boot_splash_enabled()` opens `esp32.NVS("pyble")` only when
called and reads `lcd147splash` with `get_i32`. Only the pinned
`ESP_ERR_NVS_NOT_FOUND` error returns true for the exact profile's
erased-install default; exact integer `1` returns true, while exact `0`, every
other readable integer, open failures, and other read errors return false. Enable and
disable set exact integer `1`/`0` and commit. Their write/commit exceptions
propagate. Enable returns
without importing `machine`. Disable next performs a best-effort
`Pin(46, Pin.OUT, value=0)` so an already retained frame goes dark; a GPIO
failure does not reverse or misreport the committed disabled state.

**Boot-internal guard:** `_maybe_show_boot_splash(wait_ready)` is deliberately
absent from `__all__`. It checks `boot_splash_enabled()` first. Only true calls
the supplied native readiness function with exactly `1500`; only a true result
calls `show_boot_splash()`. It returns a Boolean observation and contains all
ordinary exceptions. The companion is absent from generic S3 entirely, so the
factory-enabled fallback cannot affect or add display work to that image.

The guard also owns a deliberately narrow boot-order observation seam.
`_boot_evidence()`, likewise absent from `__all__`, returns the immutable tuple
last produced by `_maybe_show_boot_splash(...)` in this VM. At guard entry the
module replaces the prior tuple with `()` and appends only fixed-schema tuple
events by tuple replacement; no list or mutable event object is exposed. The
disabled path is exactly:

```python
(
    ("guard-enter",),
    ("enabled", False),
    ("return", False),
)
```

The successful enabled path is exactly:

```python
(
    ("guard-enter",),
    ("enabled", True),
    ("wait-ready", 1500, True),
    ("display-start",),
    ("frame-show",),
    ("resources-released",),
    ("wait-ready", 0, True),
    ("backlight-high",),
    ("return", True),
)
```

The renderer accepts a private optional event sink only from the boot guard,
placing events immediately after the corresponding successful operation.
False readiness records its exact timeout and Boolean result. An ordinary
exception adds only `("fault",)` and the fail-open `("return", False)`; its
type, message, and object are never retained. The seam contains no identity,
display-content, raw protocol, timestamp, or address field; it is neither
persisted nor emitted on PBLE/1, stdout, logs, or the display. Direct public
`show_boot_splash()` calls supply no sink and therefore neither clear nor add
boot evidence.

**Reviewed QR artifact:** the exact 25-bit rows, with bit 24 corresponding to
X=0, are:

```text
1fcf87f 104ee41 175155d 1758f5d 175315d 1056341 1fd557f 0017700 17c2e7c
1ca55a2 097720b 06a13c1 0bc7ef7 181452a 166f27b 113a131 166e1f4 0019b18
1fccd57 1059b1b 17597f7 175c0df 175300d 104e7b9 1fd207f
```

The renderer first paints a 165 × 165 white square at `(3, 52)`, then paints
each set module as a 5 × 5 black rectangle at
`(3 + (column + 4) * 5, 52 + (row + 4) * 5)`. The white perimeter is therefore
the exact four-module quiet zone. Host tests hash every row as unsigned
32-bit big-endian and independently decode the matrix to
`https://pyble.dev/app`; the firmware does not encode QR data.

**Frame layout:** one 172 × 320 RGB565 framebuffer uses navy
`rgb565(8, 15, 31)`, white, black, brand blue `rgb565(45, 91, 255)`, muted
blue-grey `rgb565(148, 163, 184)`, and ready green
`rgb565(34, 197, 94)`. A 30 × 30 brand-blue prompt tile begins at `(10, 10)`;
`>_` is at `(16, 21)`, `PyBLE` at `(48, 14)`, `PYTHON OVER BLE` at `(48, 27)`,
and the brand divider is exactly `(0, 45, 172, 2)`. The QR uses `(3, 52)` above.
`SCAN TO INSTALL` is at `(26, 225)`, `pyble.dev/app` at `(34, 243)`, a 6 × 6
green ready mark is at `(36, 270)`, `BLE READY` is at `(50, 269)`, and
`Firmware v{pyble.__version__}` is at `(26, 296)`. QR pixels remain pure
black/white; no logo overlays its symbol or quiet zone. `BLE READY` is a
snapshot: readiness must have been observed again immediately before the
backlight-high action, but retained panel RAM does not claim to track a later
disconnect or NimBLE reset.

**Hardware/resource transaction:** `show_boot_splash()` first imports
`machine.Pin`, creates active-high backlight GPIO46 low and CS GPIO42 high with
explicit constructor values, then the remaining exact pins, and only then
imports/constructs `pyble_st7789.ST7789` with SPI 1, 40 MHz, mode 0, geometry,
offset, BGR, and inversion from FR-SPLASH-5. It lazily reads
`pyble.__version__`, composes the frame, and calls `show()` exactly once while
the backlight remains low. It then calls driver `deinit()`, clears the local
driver reference, calls `gc.collect()`, lazily imports `pble_ble`, and calls
`wait_ready(0)`. A false result returns false with the backlight low. A true
result makes GPIO46 high as the final successful hardware action and returns
true. ST7789 GRAM retains the frame while SPI and the approximately 110 KiB
framebuffer are free.

One outer `finally` handles partial pin, constructor, draw, transfer, deinit,
and collection failure. Until the final high write succeeds it best-effort
deinitializes a constructed driver, makes CS high and backlight low, and
preserves the original exception for an explicit `show_boot_splash()` caller.
The boot-internal wrapper converts that failure to false so startup proceeds.

**Satisfies:** FR-SPLASH-1…9, FR-BOOT-4/6, IF-MACHINE, CON-6…9.

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

For the frozen C3 engineering gate, TX scheduling has two behavioral classes:
control (`RSP`, `RUN_STATE`, and other lifecycle traffic) and bulk
(`CONSOLE_DATA`). Bulk admission always leaves the two `msys_1` blocks needed
to submit the one-fragment STOP response (data plus ATT wrapper); paced
terminal idle then reuses returned capacity. One PBLE/1 message remains
atomic across all of its fragments, because the app owns a single reassembly
buffer; control therefore never interleaves inside an already-started bulk
message. At the next complete-message boundary, a pending STOP response wins
before another console message, followed by `RUN_STATE(idle)`. Backpressure,
reserved transport credits, a priority queue, or another bounded mechanism MAY
realize the invariant; tests bind the observable capacity, ordering, valid
reassembly, and 500 ms terminal deadline rather than an unproved lock layout.
This is required for both a quiet tight loop and a loop continuously printing
to stdout
([C3-G2](ports/esp32-c3-4mb.md#c3-g2--run-console-and-authoritative-stop-frozen)).

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

The independent exact-board splash flag changes only local display identity,
not ownership or run mode. When disabled (the default), the boot performs no
display wait or GPIO operation. When enabled, the real BLE-ready event precedes
one bounded display transaction; a 1,500 ms timeout or any companion failure
falls through to worker/console/autorun setup. The QR destination and rendered
version contain no device identity and confer no trust. A VM soft reset reruns
the same guard: an already connected or successfully advertising native agent
retains the ready event, while a NimBLE reset clears it until a new successful
advertising/connection event (FR-SPLASH-3…5, SEC-6/8).
Immediately before the panel is lit, readiness is sampled again with zero
wait. Thus visible `BLE READY` records a true boot snapshot, not continuous
link state; later radio state may change while retained GRAM remains visible.

### 6.4 SOFT_REBOOT

`SOFT_REBOOT` clears interpreter state (re-init the VM heap/imports) and
re-enters `AGENT_MODE`, keeping the BLE link where the platform allows
(FR-RUN-8). It is distinct from a hardware reset and does not re-advertise
unless the link drops. The ESP32 reference path pre-creates one `esp_timer`
one-shot during runner registration. After the handler successfully submits
`RSP{OK}`, it arms that timer for 250 ms and returns without a duplicate
dispatcher response. Only the callback schedules the main-task `SystemExit`.
The delay spans several negotiated connection intervals without making the
host task sleep; duplicate reboot requests are `EBUSY`, and a response or timer
setup failure leaves the VM intact. Exact-board HIL repeats
acknowledgement → reconnect → fresh-import cycles so source ordering alone can
never certify delivery. The qualification runner disconnects the acknowledged
connection, waits at least the delivery grace, and retries reconnect plus the
fresh-VM probe under one bounded deadline; a connection made during the reset
transition cannot fail or pass the candidate prematurely. Retry eligibility is
limited to a transactionally cleaned-up BLE connection-establishment failure
with no retained partial link, a dedicated stale-VM result, or a narrowly typed
transport loss during the reset-transition probe when the central independently
reports `is_connected == false`. The same I/O failure while still connected,
or any caps, protocol, import, stderr, RUN-state, harness, or cleanup failure is
terminal. Connection setup reserves its cleanup budget inside the timeout it
receives; cancellation and process-control exceptions keep their original type
after best-effort cleanup. Connect, setup cleanup, probe, disconnect, and retry
delay each receive only the current residual deadline, and polling continues
until that deadline rather than an attempt-count ceiling. A disconnect error
counts as an already-closed link only when the central independently reports
`is_connected == false`.

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
The historical v0.4.2 public-beta qualification work measures the owned exact
profiles `esp32-4mb` and `esp32-s3-n16r8`. Its supplemental production-browser
rows passed, while its formal resource and remaining HIL rows stay open. The
v0.5.1 source-candidate contract measures the three exact profiles `esp32-4mb`,
`esp32-s3-n16r8`, and `waveshare-esp32-s3-lcd-147b` independently. S3 PSRAM is
useful Python headroom but
MUST NOT conceal internal-RAM pressure, so the gate records Python GC memory
and internal ESP-IDF heap separately. The v0.6.0 five-profile candidate
includes the **ESP32-C3 floor** (single-core RISC-V, ~400 KB SRAM —
[hardware.md §1](../hardware.md#1-supported-chip-families-v1)). Its
candidate-bound measurement is mandatory and remains pending until the C3
resource and HIL gates pass; source support or attached hardware alone is not
qualification evidence.

### 8.2 Static vs dynamic

Hot-path buffers (reassembly, file I/O, TX staging) are static and reused; per-message Python allocations are minimized to keep GC pauses out of the console/transfer latency path (NFR-PERF-3) and to avoid heap fragmentation under sustained transfer (NFR-REL-3).

### 8.3 NimBLE tuning

NimBLE is the only stack built (CON-5, FR-BLE-9; Bluedroid excluded saves flash and RAM). The board overlay tunes NimBLE buffer counts/sizes to the minimum that sustains MTU 247 windowed transfer, validated on C3 (NFR-FP-TPUT).

### 8.4 Frozen modules

The agent ships as **frozen `.py`** in the manifest, so module bytecode lives in flash, not heap. This is the primary flash/heap lever before native (D1).

The exact-board-only `pyble_st7789` module is separately classified as a frozen
Layer-4 user runtime, not agent memory. Import creates no framebuffer or
hardware object. Construction alone allocates `width * height * 2` bytes plus
bounded object overhead; for the exact 172 × 320 panel the pixel buffer is
110,080 bytes. Transfer uses a fixed scratch-free/in-place chunk of at most
4092 bytes and restores byte order after each write. The
`waveshare-esp32-s3-lcd-147b` image and runtime-headroom gates measure this
addition independently; lean generic S3 thresholds measure bytes without it,
and no C3 budget or target selection is silently weakened
(FR-TFT-1/4/5/7).

### 8.5 Meeting the NFR-FP gates

The normative metric definitions, sample counts, payload generator, timer
boundaries, reliability workload, and metric-specific derivation formulas are frozen in
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
  first fresh matching host scanner callback with a monotonic clock; and
- the transfer runner requires HELLO `mtu=247`, `window=8`, and `chunk=229`,
  uses no diagnostic overrides, validates GET offsets as contiguous and
  unique, and keeps PUT/GET timing separate from the multi-file
  integrity/reliability workload.

No production firmware metric capability is needed for this design. In
particular, GC/internal-heap values remain a bounded qualification probe rather
than volatile HELLO/INFO fields. The external scanner measures end-to-end host
delivery of an event proving a matching advertisement occurred; it provides
neither an on-air packet timestamp nor a firmware-local “advertise requested”
timestamp.

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
address, and target-appropriate reset adapter. For v0.6.0 it accepts only the
five schema-3 policy rows in exact order. It records the central OS, BLE backend
and adapter, Python/bench identity, board/module description, candidate
identity and hashes, every integer sample, retransmit/rewind counts,
disconnects, integrity results, the target-specific transport-facts object
from specs.md §5.3.1/§5.3.5, and a SHA-256 of the retained redacted raw log.
For classic ESP32, generic S3, and C3, after each of the first nine disconnects
the bench waits at most 2,000 ms for exactly one complete parser-owned UART
session-end record, discards every private byte and terminal count, and clears
residual state. The tenth session retains the ADR-0027 UART settlement and
post-disconnect seal path unchanged.

Waveshare uses `WaveshareHardwareExecutor` and an operator-only reset
controller with no serial dependency. Its exact image alone exposes the hidden
`pble_ble._oi1_link_facts()` native getter. `oi1_link_fact_probe_source(nonce)`
invokes that getter through ordinary PBLE/1 RUN and emits one
`__PYBLE_OI1_LINK_FACTS_<nonce>=<json>` stdout line.
`parse_oi1_link_fact_probe_output` requires strict ASCII, exactly one matching
line, exact keys/types, epochs in `1..2^64-1`, fixed list capacities, and a
bounded total output; it discards all other stdout. `run_oi1_link_fact_probe`
also requires RUN status OK, no stderr, one terminal RUN_STATE(done), and its
bounded deadline. It never adds a wire constant or capability.

After each of the first nine Waveshare measured disconnects, the executor
makes a diagnostic reconnect with separate deadlines: 20 seconds for
`PbleCentral.connect`, 2 seconds for diagnostic HELLO, and 2 seconds for the
getter RUN. It requires a final last-ended record and its exact non-wrapping
active successor, disconnects, and discards both. Those two boundary records
MAY be unsettled because neither the just-ended short sample nor the newly
connected diagnostic session is a transfer session; exact structure, epochs,
finality, and `overflow=false` remain mandatory. On the tenth
connection it polls the active record for no more than 5,000 ms until the
record is settled, non-final, non-overflowed, and profile-valid, then retains
its epoch before timing. It probes the same active epoch again after the final
heap snapshot and before disconnect. A final diagnostic reconnect uses the
same separate 20-second connect, 2-second HELLO, and 2-second getter-RUN
deadlines. The getter must expose that epoch as immutable `last_ended` and its
exact active successor. Only the
ended record's `facts`, including its final starvation
count, enters evidence. Missing/null, stale, non-successor, wrapped,
overflowed, malformed, duplicate-marker, stderr, RUN error, and timeout cases
all fail closed; unsettled additionally fails for the tenth transfer record,
but is permitted only for discarded first-nine boundary records. The raw log
is exclusively created mode `0600`
before its first write,
independent of ambient umask, and a pre-existing path is rejected. The result
writes atomically and never silently drops a successful sample. RP2 instead
uses its frozen BTstack observation and reset adapter and forbids ESP-only
session/DLE/PHY fields. The RP2 bench imports the portable console's exact
`TX_CAPACITY = 2048` bytes, `TX_REFILL_PER_MS = 20` bytes/ms, and derived
`TX_BUDGET_MS = 103` ms. It independently requires the exact integer ceiling
formula `(TX_CAPACITY + TX_REFILL_PER_MS - 1) // TX_REFILL_PER_MS` and records
that value as `console_tx_budget_ms`. There is no CLI or environment override
for this source-bound fact.

#### 8.5.2 Threshold policy lifecycle

The exact v0.6.0 machine policy is
`firmware/qualification/oi1-gates.json`, schema 3. Its five rows and target-
specific threshold shapes are frozen in specs.md §5.3.5. Historical schema-2
evidence retains specs.md §5.3.3 semantics. Initially the measurement tooling and
negative tests land while release qualification remains pending. The same
sequence governs a controlled refresh:

The tracked file can still contain the historical schema-1/two-profile policy
while this RED workflow is open; that state is deliberately release-blocking,
not a schema-3 default. No contributor may widen it by copying old numbers or
choosing plausible C3/Pico thresholds. Only the five successful controlled
baseline fragments and `assemble-oi1-baseline` may replace it, together with
the newly created commit-scoped schema-2 baseline evidence. A host release
readiness test reads the committed file itself and stays RED until those exact
generated bytes exist.

1. runs one engineering baseline on all five exact profiles from the
   same pre-policy source and immutable inputs;
2. runs `assemble-oi1-baseline` against the immutable staged inputs and the
   five bench fragments so the tool creates the canonical, redacted evidence
   under `docs/validation/firmware/oi1/`, derives every threshold with the
   frozen source-era formulas (including the fixed reset product SLO and
   metric-specific goodput allowance), and atomically updates the policy with
   its evidence SHA-256;
3. reviews and commits those mechanically assembled files; and
4. builds the final tagged candidate and reruns verify-mode HIL on all five
   exact profiles.

Profiles or successful samples from different baselines MUST NOT be mixed. For
a firmware source release core at or after `0.5.0`, the active baseline
firmware release core is at least `0.5.0` and not newer than the source release
core. This does not force a new baseline for every patch release; it prevents
the `0.5.0` source era from silently retaining the pre-`0.5.0` policy. Baseline
HIL derives policy only, so no result collected before the policy/source
commits substitutes for final-candidate verify-mode HIL.

Beginning with the `0.5.0` source era, reset-to-advertisement is the fixed
3,000 ms end-to-end product SLO identified by
`fixed-product-slo-3000-v3`, and goodput derivation applies exactly 95/100 with
integer arithmetic before 100 bytes/s floor quantization. The host-observed
reset metric remains useful as a user-visible scan-list bound but is not used
as a tight firmware-only regression statistic. Static image/headroom, heap,
integrity, reliability, and physical-cycle assertions remain unchanged.
Historical pre-`0.5.0` policies retain their v1 derivation identifiers and
arithmetic; the superseded private v2 reset policy cannot qualify public
`0.5.0` bytes.

A schema-3 policy has exactly the five ordered threshold-bearing rows in
specs.md §5.3.5. Four ESP rows use the existing application/partition,
five-field heap, and NimBLE link facts. Pico uses raw-image limit/headroom,
two-field GC snapshots, and BTstack facts. No row may borrow values from
another target. All thresholds and final-candidate observations remain pending.

#### 8.5.3 Release evidence and failure semantics

Candidate generation embeds the parsed policy, its exact-byte SHA-256, the
matching baseline-evidence digest, and immutable build measurements in
the source-era record selected by browser-flashing.md §9: immutable `v0.4.2`
replay retains `PYBLE_HIL_RECORDS_V2` schema 2; the rejected pre-split v0.5
engineering shape is V3 and cannot publish split bytes; v0.5.1 retains
`PYBLE_HIL_RECORDS_V4` schema 4; v0.6.0 uses
`PYBLE_HIL_RECORDS_V5` schema 5. Current v0.6.0 observations remain pending.
Finalization may fill observations, operator fields, and derived
checks only; it must prove the policy and build portions remain
byte/semantically equal to the candidate.
The `assemble-hil-report` helper accepts only bounded per-profile mutable
evidence, copies candidate-frozen fields from the pending report, derives the
footprint/reliability pass from validated observations, and emits the completed
source-era report atomically before finalization.

The validator recomputes image/headroom arithmetic, sample counts, heap
minima, latency maximum, goodput from recorded durations, threshold
comparisons, reliability totals, and the profile-exact transfer-link facts. It
rejects an unsettled or exhausted link, a missing final disconnect fact,
missing/extra fields, booleans as integers, wrong units/order/profile/hash, an
unknown-MTU fallback, a target-inappropriate resource/transport field, or a
value crossing its bound. Any firmware,
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
4. create one retained .sources/<profile>/micropython checkout per release profile;
   verify its locked commit, canonical origin, and clean tracked tree;
   COPY board_overlays/<variant>/ into only that variant's checkout
   ports/esp32/boards/  (canonical submodule stays pristine)                CON-4, D5,
                                                                             BLD-14
   apply firmware/patches/micropython-<tag>/* if any (default: zero)        CON-12, BLD-15
5. rebuild mpy-cross from the pinned MicroPython                            BLD-10
6. invoke each ESP port build with USER_C_MODULES + frozen manifest, and the
   RP2 build with its portable frozen agent and pinned ARM GNU toolchain      BLD-3/4
7. emit each ESP merged/component/flasher-args set and Pico ELF/raw BIN/UF2  BLD-5
8. validate ESP merged images/flasher args/components/partitions and validate
   Pico UF2/raw-image identity and image budget; normalize only allowed names BLD-17
9. generate four profile-scoped ESP Web Tools manifests, Pico verified-UF2
   metadata, release schema 4, SHA256SUMS, provenance, recovery, and V5 HIL
                                                                              BLD-6/18/19/20
10. retain all five profile checkouts; bind each build description/provenance
    to its exact checkout, then reconcile all eight application/bootloader linked
    inventories, exact frozen Python inputs, prebuilt blobs, and compiler
    runtimes against the pinned SBOM toolchain and fail-closed license policy;
    add the RP2 linked/frozen/toolchain inventory, and generate
    THIRD_PARTY_LICENSES.txt mechanically                                    BLD-8/14
11. run no-leak, SPDX, manifest/integrity/license/reproducibility gates       CON-6,
                                                                             BLD-14/18
12. publish identical immutable bytes to the versioned same-origin path
    and matching GitHub Release only after every included profile passes HIL;
    the v0.6.0 gate covers all five ordered profiles; the immutable digest-
    bound v0.4.2 historical exception remains
    only a two-profile hardware-tested beta/GitHub pre-release after its scoped
    production-browser install/recovery run                                  BLD-7/21/22
```

### 10.2 Entry points

`firmware/scripts/build.sh <variant>` builds exactly one of `esp32` |
`esp32-s3` | `waveshare-esp32-s3-lcd-147b` | `esp32-c3`; `build_all.sh`
builds all four independently (BLD-3). Variant→IDF mapping is
`esp32`→`esp32`, both S3 variants→`esp32s3`, and
`esp32-c3`→`esp32c3` (BLD-4). Upstream upgrades go only through
`upgrade_micropython.sh` (BLD-9).

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
    waveshare-esp32-s3-lcd-147b/micropython/
    esp32-c3/micropython/
    rpi-pico2-w/micropython/
```

Each directory is an independent checkout of the MicroPython repository URL
and full commit pinned in `versions.lock`. Before it is admitted, its `origin`
URL MUST equal that canonical locked URL, `HEAD` MUST equal the locked commit,
and its tracked tree MUST be clean. The target's application
`project_description.json` `project_path` MUST resolve to
`.sources/<variant>/micropython/ports/esp32` in that same build root. Pico's
CMake cache, link command, map, and dependency metadata MUST instead resolve
to `.sources/rpi-pico2-w/micropython/ports/rp2`. A build description that
names the canonical submodule, another profile's checkout, or an
escaped/symlinked location is fatal.

All profile-scoped mutable preparation, including board-copy, ESP-IDF
submodule/managed-component materialization, and RP2 frozen-module generation,
runs inside that profile's checkout and build directory. No profile may share,
replace, delete, or mutate another profile's checkout or managed build state.
The five checkouts remain retained until linked-inventory/license audit,
bundle validation, and the two-root comparison have all completed.

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
with exact source-era profile parity: two hardware-tested beta profiles in v0.4.2,
retained as immutable history; the unfinished three-profile v0.5.1 source candidate
retained only as history; and exactly five profiles in the pending v0.6.0
candidate. No v0.6.0 profile is published until the atomic five-profile gate
passes (BLD-7/17…22). `DEVICE_INFO`/HELLO,
`manifest.json`/`release.json`, tag, and release notes make agent/protocol/
upstream/source/artifact versions recoverable (BLD-13); the agent follows
SemVer (BLD-12).

### 10.4 Patches directory

`firmware/patches/micropython-<tag>/` holds any unavoidable patch with a written reason, applied only at build prep, re-reviewed for retirement each upgrade; the default is **zero** patches (CON-12, BLD-15).

### 10.5 Source layout (frozen)

> **FROZEN for v1.0 (G0 · 2026-07-01; browser-release paths amended
> 2026-07-29; display runtime/companion paths amended 2026-08-01 and split into
> an exact-board overlay 2026-08-03 · `[docs]`).** This is
> the authoritative firmware source tree. It
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
    rp2-license-policy.json         # independent RP2 linked/frozen/runtime policy          [build-smith]
    excluded-cves.yaml              # hash-pinned offline SBOM input; empty by policy      [build-smith]
    texts/                          # exact reviewed third-party license/NOTICE texts       [build-smith]
    evidence/rp2/                   # exact RP2 dependency/toolchain evidence bytes          [build-smith]
    notices/rp2/                    # exact source-header and attribution notices            [build-smith]
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
  python_modules/                   # optional Layer-4 frozen user runtimes
    pyble_st7789.py                 # explicit ST7789 driver (exact-board variant only)     [runtime-engineer]
  user_c_modules/
    pyble/                          # Layer 3 native hot paths — LATER, OI-3 (pble_*.c)    [ble-/protocol-engineer]
  board_overlays/
    esp32/  esp32-s3/  esp32-c3/     # lean Layer-2 variants, copied at build prep          [build-smith]
    waveshare-esp32-s3-lcd-147b/     # exact-board esp32s3 build variant                    [build-smith]
      pyble_waveshare_lcd147b.py    # exact-board fresh-install splash companion           [runtime-engineer]
    rpi-pico2-w/                    # RP2350/CYW43 portable frozen-agent overlay             [build-smith]
  scripts/
    build.sh  build_all.sh          # per-variant / all-four build (BLD-3/4)               [build-smith]
    build_rp2.sh                    # retained-source Pico ELF/BIN/UF2 build                 [build-smith]
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
  workflows/                        # CI: no-leak · SPDX · SHA-drift · 4-variant/3-chip matrix [build-smith]
```

### 10.6 Standard NeoPixel manifest contract

ADR-0018 adds one standard user-runtime package without adding an agent module
or upstream patch. All four build-variant manifests explicitly call
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
and runs `from neopixel import NeoPixel` before and after soft reboot on every
release profile (and on C3 before it is enabled). An optional visual HIL script accepts the GPIO explicitly,
drives one dim pixel for a bounded interval, and clears it in `finally`
(FR-LIB-4).

### 10.7 ST7789 manifest and source contract

Build prep copies canonical `firmware/python_modules/pyble_st7789.py` into the
generated exact-board directory without placing board values in the generic
driver. Only `board_overlays/waveshare-esp32-s3-lcd-147b/manifest.py` selects
it with one literal `module("pyble_st7789.py", ...)` entry. The lean ESP32-S3,
classic ESP32, and ESP32-C3 manifests select zero copies. This variant maps to
the existing `esp32s3` IDF target but produces the separate
`waveshare-esp32-s3-lcd-147b` image, manifest, and browser selector; it MUST NOT
reuse or alter `esp32-s3-n16r8` bytes (D9, ADR-0028, FR-TFT-1).

The resolver test follows the copied/generated input and proves exact source
identity and cardinality per target. Structure/license tests require the
canonical SPDX MIT source, reject a second/copied/vendor driver or board pin
table, verify import never requests `machine`, and admit the file as
first-party MIT in the linked/frozen source inventory. Generated frozen
content, not a stale `.mpy`, is the build proof. Exact-board build size and
headroom have their own OI-1 row; generic S3 is measured without the module
(FR-TFT-2/7, CON-6).

### 10.8 Exact-board companion manifest and boot contract

The canonical
`firmware/board_overlays/waveshare-esp32-s3-lcd-147b/pyble_waveshare_lcd147b.py`
is copied only with the exact-board Layer-2 overlay. Its manifest entry is
literal and exactly once; lean ESP32-S3, classic ESP32, and ESP32-C3 resolve
zero copies. The companion is
first-party MIT source in the same generated-frozen-content, SPDX, no-leak,
source-inventory, size, and reproducibility gates as the driver. It does not
create another IDF target, PBLE/1 capability, detector, or upstream patch; it
does define a separate build variant and public image profile
(D10, ADR-0028, FR-SPLASH-1).

The lean `esp32`, `esp32-s3`, and `esp32-c3` overlays share the ordinary boot
lifecycle and contain no splash wrapper. Only the exact-board `_boot.py`,
immediately after `pble_ble.init_agent()`, opens one nested `try`, copies
`sys.path[:]`, and
replaces the original path list in place with `['.frozen']`. That scope imports
`pyble_waveshare_lcd147b` and calls its internal guard with
`pble_ble.wait_ready`, so the companion plus its lazy `machine`, driver,
`time`, and `pyble` dependencies resolve only as frozen/built-in modules. A
`finally` restores the saved path contents before control can reach worker
startup. In-place mutation ensures any existing reference to the path observes
the same restricted/restored object.

Every exact-board companion exception is contained before the existing worker
imports; a VFS or `/lib` lookalike is unreachable. The other three variants
contain no companion import to intercept.
Structure and executable host tests assert the exact order, same path-object
restoration after success and every fault, and prove there is still exactly one
runner worker and one filesystem worker. The splash starts no task and cannot
consume the runner. Resolved exact-board source tests additionally prove that the NVS
guard precedes both the readiness call and every lazy hardware/driver import
(FR-SPLASH-1…4). Only the exact variant enables and links the splash-readiness
native seam; generic S3 must have no Event Group allocation or `wait_ready`
symbol.

### 10.9 Release license inventory contract

The exact audit algorithm and `esp-idf-sbom` pin are frozen in
[browser-flashing §6](browser-flashing.md#6-licensing-and-release-notes).
Application and bootloader inventories for every profile are separate inputs;
their union is not inferred from an ESP-IDF component list alone. The audit
reconciles map-file archive members, `project_description.json`,
`compile_commands.json`, generated frozen content, prebuilt blobs, and
compiler/newlib runtime archives against `license-policy.json`. It runs
offline with isolated caches and rejects any unknown or stale input before a
candidate can be promoted.

RP2 uses its own `rp2-license-policy.json` and observer, never an invented ESP
SBOM. Tests safely parse the exact shell-free `link.txt` and structural GNU
linker map, reconcile each contributing archive member and direct object to
one exact source owner, retain non-contributing command inputs without calling
them shipped, and reject response files, shell syntax, path escape, symlinks,
duplicates, malformed maps/archives, basename matches, link/map disagreement,
or missing and ambiguous ownership. No-gap fixtures include MicroPython core
and `ports/rp2`, lwIP, Mbed TLS, both littlefs generations, oofatfs, libm,
pico-sdk, BTstack and its actually linked third parties, CYW43, TinyUSB, and
every contributing ARM GNU/newlib runtime archive. Deleting or substituting
one class fails even when the remaining evidence is canonically rehashed.

The same fixtures derive every compiler depfile belonging to the linked
firmware target from its C/C++ DependInfo records; assembly records, for which
CMake does not emit `.o.d`, bind their source bytes directly. Unlinked host
tools' depfiles are excluded. Tests parse GNU Make escaping/continuations
without execution, require each declared depfile target/object and DependInfo
source to agree, and hash every depfile and included byte. They reject a
missing/extra target depfile, a hidden second rule,
variable/function/directive syntax, malformed escape, duplicate dependency,
source mismatch, missing file, unowned include, generated input without exact
derivation, path escape, and terminal or ancestor symlinks. Mutating only a
header or depfile while restoring timestamps changes the semantic hash and
fails public replay.

Real-shaped dependency fixtures require the exact Pico 2 W CYW43 Wi-Fi/CLM,
Bluetooth, and NVRAM payload headers and reject an alternate payload from the
same checkout. They assign ordinary CYW43 driver code and each of those three
payloads to separate most-specific owners, bind both header and embedded-data
digests, and keep every payload owner `review-required` until authoritative
terms identify that exact selected byte closure. A broad CYW43 owner or an
older byte-different firmware grant fails. Tests allow source and selected
expressions to retain the same unresolved choice only for `review-required`;
an admitted owner must select one reviewed arm. They also assign `libm.h`,
`fdlibm.h`, the exact observed BSD-3-Clause `re1.5` sources and header, the
exact observed Zlib `uzlib` sources and headers, Apache-only CMSIS Core
headers, the
dual-marked CMSIS system source/header, Raspberry Pi BSD CMSIS/device headers,
GCC built-in headers, and newlib target headers to their distinct
most-specific owners. A broad pico-sdk, libm, `lib/`, MicroPython, or toolchain
root cannot erase those classes.

Cache/toolchain fixtures require `PICO_BOARD=pico2_w`,
`PICO_PLATFORM=rp2350-arm-s`, exact retained board/SDK paths, and one pinned
`arm-none-eabi-gcc` C/ASM plus `arm-none-eabi-g++` C++ frontend, with matching
`PICO_COMPILER_*` values. They reject an omitted frontend, PATH or sibling
compiler, mixed roots, digest drift, or cache disagreement. The exact official
ARM GNU binary tar is retained below the derived toolchain cache, verified by
locked URL-basename/size/SHA-256/format/root, safely parsed, and used to
byte-compare every observed frontend, header, runtime input, and installed
release manifest. Tests reject installed-only evidence, a caller-selected
cache, absent or changed archive/manifest, unsafe/duplicate members, and an
installed file not equal to its unique official-tar member.

The policy's canonical source-owner catalog uses namespace/path roots and
separate source and selected SPDX expressions. Tests require exact retained
MicroPython and nested gitlink SHAs, clean trees, canonical origins, actual
CMake-selected source paths, and the pinned toolchain distribution identity;
a sibling checkout or pico-sdk's unselected nested copy cannot substitute.
BTstack requires both its complete stock non-commercial license and the
pico-sdk supplemental `pico_btstack/LICENSE.RP` grant selected for this exact
Pico 2 W image. Ordinary CYW43 driver code requires the complete Pico-device
grant rather than its generic non-commercial file, while the selected Wi-Fi,
Bluetooth, and NVRAM payload owners additionally require exact authoritative
redistribution mappings and remain release-blocking without them. Neither
supplemental grant may be represented as BSD. Mbed TLS preserves its source
choice and reviewed Apache-2.0 selection, while fdlibm-derived libm and distinct libgcc/newlib
classes retain their own notices, expressions, and exceptions. Every observed
owner contributes, every contributing input has exactly one most-specific
owner, and complete license plus required NOTICE/COPYRIGHT bytes are
digest-bound. Tests reject an unused owner, an owner gap or tie, partial text,
wrong identifier, missing attribution, changed byte, or one broad MicroPython
or toolchain expression standing in for the heterogeneous closure.

Custom `LicenseRef` tests are owner-scoped without adding an approval-list
field: the exact `allow`/`project-owned` owner record must carry every custom
token in its own expressions and the matching complete text path/digest. A
same-named token or text on another owner cannot authorize it. A complete
`review-required` record remains observable and changes the semantic hash, but
audit generation fails atomically until that exact owner is independently
changed to `allow`.

Publication tests stage `evidence/` and `THIRD_PARTY_LICENSES.txt` below one
hidden sibling of an absent output root, fsync the complete pair, and expose it
with one no-replace rename. They inject failure before that rename, process
interruption after it, and a concurrent destination creator. The only admitted
outcomes are no output, the contender's untouched root, or the complete
evidence-plus-notice pair; a half-published pair and notice replacement fail.

The RP2 frozen-manifest tests execute no manifest code: only reviewed literal
operations and arguments may select a traversed manifest, source,
destination, optimization, or metadata value. They require the literal result
to equal the generated frozen content and linked owner, and reject imports,
assignments, control flow, computed/unknown calls, directory recursion,
unresolved values, duplicates, escape, and symlinks. The observer hashes the
ELF, CMake cache, link/map documents, provenance, archives, objects, sources,
frozen inputs/output, checkout metadata, policy, license/notice bytes, and
toolchain inputs before the eight ESP runs and repeats the full semantic
observation immediately before publication. A byte change with restored
timestamps is fatal. Tests require schema-v2 receipt coverage of all eight ESP
identities and exactly the seven RP2 roles, plus the canonical five-profile
schema-v1 release inventory; missing, extra, reordered, cross-profile, and
self-consistently rehashed substitutions fail.

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

All eight v0.6 exact raw SBOM outputs and all eight normalized reviewed
documents stay with build-review evidence. Retained v0.5.1 and v0.4.2 replay
fixtures keep their frozen source-era counts and shapes. Raw package fields
and relationship graphs are validated as exact evidence, including literal
`NOASSERTION` states; reviewed immutable metadata is added only in the
normalized layer with explicit policy attribution. Supplemental packages
cover redistributed frozen or linked inputs that the raw ESP-IDF graph omits:
NeoPixel plus the contributing
`libmbedcrypto.a`, `libmbedtls.a`, and `libmbedx509.a` archives in the initial
profiles. Tests preserve omitted `PackageVersion` as an absent `versionInfo`
property for the real-shaped ESP-IDF LAN867x/TinyUSB records and reject an
invented empty or reviewed value. Those records never satisfy Pico coverage:
RP2 independently proves its selected MicroPython `lib/tinyusb` checkout,
linked sources, and complete notice in the `tinyusb` role. Supplemental choice
tests retain Mbed TLS's original
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
byte-identical to the admitted executable. The production builder must first
create that admitted executable from scratch in a fresh output directory and
atomically replace any retained executable; build-system freshness shortcuts
or retained objects cannot satisfy BLD-10. After the five-profile build
completes, the matrix driver requires all retained compiler copies to be
regular, non-symlink executables with identical bytes before it atomically
updates the canonical audit path. Missing, divergent, or incomplete matrices
must leave the prior canonical compiler unchanged. Generator,
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

Chip facts are owned by [hardware.md §1](../hardware.md#1-supported-chip-families-v1); the agent (Layer 3) is identical across all three IDF targets (D2, NFR-MAINT-1). Packaging differences live in four build-variant overlays (Layer 2).

- **esp32 (baseline):** two-core Xtensa, ~520 KB SRAM. The conservative reference; runner task and BLE/agent task can sit on separate cores. Tightest heap among the dual-core parts but not the binding constraint.
- **esp32-s3:** two-core Xtensa, ~512 KB SRAM, PSRAM common, native USB. Most
  headroom; the USB-serial debug mirror (FR-CON-5, IF-USB) is most useful here.
  The chip-agnostic Layer-3 design must not require PSRAM because C3 has none,
  but the **initial S3 browser image profile** is deliberately narrower:
  `esp32-s3-n16r8` requires 16 MiB flash plus 8 MiB Octal PSRAM. A different S3
  memory topology requires another provisioning profile and HIL row; it is not
  silently accepted by family detection (BLD-17). The generic variant is lean:
  it freezes neither `pyble_st7789` nor `pyble_waveshare_lcd147b`, contains no
  splash boot wrapper or exact pin values, and compiles out the readiness seam.
  The separate `waveshare-esp32-s3-lcd-147b` variant maps to the same `esp32s3`
  IDF target and N16R8 topology but owns those display additions, its own
  firmware bytes, OI-1 row, manifest, web selector, and exact-profile HIL.
  Matching chip/memory does not collapse the variants or identify peripherals
  (D9/D10, ADR-0028, FR-TFT-1/7, FR-SPLASH-1…4).
- **esp32-c3 (hardest — validate early):** single-core RISC-V, ~400 KB SRAM,
  least RAM. The **binding footprint constraint** (NFR-FP-C3). With one core,
  the BLE/agent and runner tasks time-share; STOP responsiveness
  ([§5.2](#52-stop-delivery)) and console backpressure/control priority
  ([§5.4](#54-console-backpressure)) must be validated here first. The selected
  ESP32-C3-MINI-1-N4 v0.4/4 MiB/no-PSRAM engineering reference, complete gate
  matrix, and public-admission boundary live in the
  [derived C3 contract](ports/esp32-c3-4mb.md); every result remains pending. If
  frozen-Python does not fit, hot paths go native (D1,
  [§8.6](#86-esp32-c3-mitigation)). The known `esp32-c3-4mb` provisioning
  profile is defined only for C3 silicon revision v0.3 or newer but remains
  unavailable in the current v0.4.2 public beta pending exact-profile HIL. Its
  exact image revision window appears in pending v0.6.0 schema-4 metadata, but
  its action remains inactive until C3-G0…C3-G6 and common HIL pass.

- **rpi-pico2-w (selected, qualification pending):** single-core-agent model on RP2350 —
  BTstack SYNC events on the main thread, supervisor-owned execution, STOP via
  the dupterm interrupt-char channel. Design is owned by the derived port spec
  ([ports/rpi-pico2-w.md](ports/rpi-pico2-w.md)); nothing in §5 (ESP32 task
  model) applies to it. Its v0.6.0 row uses verified UF2/manual BOOTSEL,
  RP2-specific resource/BTstack evidence, and remains inactive until GP2 and
  common V5 HIL pass.

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
- **No physical-output safety guard (NFR-SAFE-4):** the agent contains no
  actuator, calibration, or user-code routing module (CON-8/9); physical safety
  is the user program's concern. The exact-board frame is bounded and
  factory-enabled only after erase in that profile; persistent disable remains
  authoritative. It is
  cosmetic identity/app-discovery output, not an actuator guard or abstraction
  (FR-SPLASH).
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
| `pyble_console` | tee + backpressure and control-priority logic | CONSOLE_DATA stream tagging; whole-message non-interleaving | — | staging-buffer/transport-reserve footprint | live stdout/stdin latency; C3 print-flood STOP response then idle in <500 ms |
| `pyble_info` | caps assembly (incl. device_id/label/has_identify/identify_led), label bound→ERANGE, identify EUNSUPPORTED-when-unset, version negotiation | HELLO/DEVICE_INFO identity fields, SET_LABEL/SET_IDENTIFY_LED/IDENTIFY round-trip | — | — | real chip/mpy/free_mem/has_sd, label↔NVS persist across reboot, non-blocking blink |
| `pyble_agent` | dispatch wiring, lock serialization | EBUSY, single-writer | frozen-manifest build | flash/heap gates | cold-boot safety, fail-safe |
| `pyble_st7789` (Layer 4) | inert import; API/signature; RGB565; controller sequence; clipping; byte order; 4092-byte chunk bound; failure cleanup | no PBLE/1 surface | exact-board-only source/manifest/license resolution; generic S3 omission | independent exact-board image/headroom gate | exact 172 × 320 pattern, backlight, reboot import, concurrent PBLE responsiveness |
| `pyble_waveshare_lcd147b` (exact-board companion) | inert import/default; exact NVS transaction; guard ordering; QR/golden frame; fault cleanup | no PBLE/1 surface | exact-board overlay/manifest/native-seam resolution; other-variant omission | independent exact-board image + framebuffer-reclaimed heap | disabled/enabled reboot, BLE-ready ordering, real QR scan, retained frame, driver reuse |

### 14.2 Shared fake transport

PBLE/1 **conformance** tests run against an **in-memory fake transport** shared between the firmware agent and the Dart `pble` client ([app.md](../app.md)), so both ends are tested against the same byte sequences — the contract is validated once, both sides honor it (FR-PROTO-1, NFR-MAINT-3, IF-PROTO). This is the cross-language guard that protocol changes do not silently diverge.

### 14.3 Build, size, and HIL gates

- **build:** SHA-drift gate (BLD-2), no-leak gate (CON-6), SPDX lint
  (NFR-MAINT-4), per-target build sanity (BLD-3/4/5), exact manifest/profile
  validation (BLD-6/17), provenance/integrity/license/reproducibility gates
  (BLD-8/14/18/19), and public-byte parity (BLD-7/22). Reproducibility
  fixtures verify the exact four-variant checkout layout in both build roots,
  application-project-path binding, locked commit and canonical origin,
  clean tracked trees, retained source availability during audit, and
  target-isolated managed components; they reject cross-target checkout
  reuse, overwrite, early deletion, path escape/symlinks, or canonical-proof
  drift. License fixtures cover
  the pinned literal asyncio/NeoPixel manifests, the exact-board-only canonical
  `pyble_st7789` source/cardinality and first-party MIT classification, the
  exact-board companion source/cardinality and first-party MIT
  classification,
  duplicate archive members,
  complete RP2 compiler-depfile/include ownership, selected CYW43 payloads,
  distinct CMSIS/libm/toolchain-header classes, exact RP2 cache/compiler
  identity, and official ARM GNU binary-tar/install byte parity,
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
- **size:** enforce each ESP application-image ceiling and factory-partition
  headroom floor plus Pico raw-image ceiling/headroom during build/candidate
  validation. Heap, boot, goodput, and reliability are not mislabeled as
  static size gates.
- **HIL:** the release-blocking bench runs on every exact profile included in
  the release. For v0.6.0 that is exactly the five profiles in ADR-0033 order;
  each independently covers the frozen §8.5 resource
  workload, multi-file integrity (NFR-REL-5), STOP authority (NFR-SAFE-1),
  cold-boot safety (NFR-SAFE-3), candidate-browser install, and
  target-specific interrupted-install recovery and both-platform app HIL from
  an access-controlled, production-equivalent HTTPS deployment (BLD-20/21).
  C3-G0…C3-G6 and Pico GP2 remain open and block the atomic release; no passed
  observation is recorded.
  The historical v0.4.2 matrix remains exactly `esp32-4mb` plus
  `esp32-s3-n16r8`. Its supplemental production-browser run completed only the
  browser-install and interrupted-recovery rows for both profiles; the other
  formal rows remain open. Its exact public-beta activation follows the bounded
  exception in browser-flashing §10 rather than claiming BLD-21 completion, and
  that evidence MUST NOT qualify the v0.6.0 five-profile candidate.

The ADR-0023/0024 feature HIL is the additional exclusive gate for the separate
`waveshare-esp32-s3-lcd-147b` release-profile row. On the connected
ESP32-S3-LCD-1.47B it records the 16 MiB flash/8 MiB Octal-PSRAM identity,
imports `pyble_st7789` before and after soft reboot, draws a bounded 172 × 320
colour/text/four-corner pattern using explicit `machine.SPI(1)` at 40 MHz mode
0 and offset `(34, 0)`, proves construction leaves the active-high backlight
off and explicit on/off works, cleans up in `finally`, and completes PBLE/1
INFO/STOP responsiveness probes while repeated `show()` calls run. The source
assertion rejects SPI bus 2 for this exact board. Visual/operator evidence
supplements automated fake-SPI command and byte assertions; it does not alter
web release metadata.

The combined runner maintains two clocks. Each contiguous BLE/RUN/device stage
keeps its existing residual deadline of at most 120 seconds. Each required
human observation separately receives at most 900 seconds. Immediately before
a live callback, the runner proves that the device deadline retains its
STOP/link-cleanup reserve: the lesser of two seconds and one quarter of the
device budget. On callback completion or failure it
advances the absolute device deadline by exactly the measured callback-await
interval, leaving the amount of device-operation time unchanged, while
decrementing the observation's aggregate operator budget. The containing
orchestrator therefore does not place an additional unpaused device deadline
around the callback-bearing exercise. An operator timeout cancels and drains
the cancellable stdin task, but that harness-induced cancellation is not saved
or re-raised as operator process control. A callback-originated cancellation or
other process-control exception retains its existing exact precedence.

During the TFT observation, the remote RUN stays active and lit. Before a
confirmation can release it, all notifications queued during the wait are
checked for a terminal state, a dark marker, malformed evidence, or link loss.
Refusal, timeout, or stale state sends bounded `STOP` instead, then drains the
remote `finally` through its dark and cleanup markers before the initiating
failure escapes. A successful operator wait changes no accepted result key or
hash input.

The reboot stage MUST prove a new VM epoch, not merely a new BLE connection. It
first runs a bounded source probe that appends a runner-owned sentinel to the
volatile `sys.path`, verifies that probe completed, and only then sends
`SOFT_REBOOT`. The fresh-connection post-reboot source MUST fail if that
sentinel remains before importing `pyble_st7789`. Final qualification repeats
the acknowledged reboot → reconnect → sentinel-absent import sequence exactly
three times after one exercise. Before that exercise, a bounded source probe
uses `esp.flash_read` plus SHA-256 to hash the ordered runtime-immutable spans
derived from the local merged image: `[0x00000, 0x09000)` for the bootloader,
padding, and partition table, followed by `[0x10000, firmware.bin length)` for
the factory application. The merged-image length is bounded by the exact
factory-partition end `0x210000`, never the 16 MiB device/VFS capacity. Local
inspection uses repeated reads of one regular descriptor and before/after
device, inode, mode, size, mtime, and ctime identity; a same-size in-place
change, unequal repeated read, or non-erased intervening NVS/PHY-init image byte
is terminal. Qualification stops
before drawing unless the live concatenated-span digest equals the locally
computed immutable-span digest; runtime-owned NVS and PHY-init bytes are not
compared. The exercise record also contains an explicit Boolean operator
confirmation plus the fixed non-personal pattern identifier; absence or refusal
is terminal.

One exclusive private result records the candidate full-file byte length and
SHA-256, the exact immutable span map/byte count/SHA-256, a non-personal random
session identifier, and all four canonical stage records.
Cycle `1` binds the candidate-verified exercise-record digest; each later cycle
binds its predecessor cycle-record digest. Cycle numbers are one-based and
contiguous. This hash chain prevents accidental mixing across sessions,
candidates, or retries. A strict production validator recomputes the chain,
checks exact keys and nested passed-stage invariants, and rejects any duplicate
top-level identity or zero-byte RUN marker summary before the exclusive writer
accepts qualification evidence.
The result retains only exact public-version redacted capabilities, validated
counters, state names, full candidate identity, live immutable-span identity,
confirmation, and chain digests—never the BLE address, device ID, label, raw
INFO, sentinel text, source, or raw console bytes. A
failed/missing pre-reboot marker, stderr, or terminal RUN error stops before
`SOFT_REBOOT` is sent.

ADR-0024 extends that same exclusive exact-board candidate session for the
`waveshare-esp32-s3-lcd-147b` release-profile row. Before the ordinary TFT exercise, the
runner records a disabled-state reboot that reaches PBLE/1 without invoking
display code, enables `pyble/lcd147splash`, performs an acknowledged VM reboot,
and reconnects under the same candidate/deadline rules. It proves READY was
established before display work, HELLO succeeds while the retained frame is
lit, and post-splash free heap does not retain the 172 × 320 × 2 framebuffer.
The operator confirms the frozen layout and dynamic version and scans the real
panel with a camera to exact `https://pyble.dev/app`. The subsequent ADR-0023
exercise constructs the generic driver on SPI 1, replaces the splash, and
cleans up, proving ownership transfer. A further enabled soft reboot redraws
without losing BLE; final disable commits zero and makes the backlight low.
After enablement may have persisted, any failed qualification MUST attempt the
same disable-and-darken cleanup. If the initiating qualification failure and
the cleanup failure are both ordinary exceptions, the runner MUST re-raise the
exact initiating exception object; the cleanup failure MUST NOT replace it.
The added records join the existing candidate/session hash chain and privacy
allowlist (FR-SPLASH-8).

For each enabled splash phase, the layout confirmation and physical QR scan
are one observation and share one aggregate 900-second operator budget even if
a stale VM forces another connection attempt. Only time actually spent inside
the callback is excluded from the one reset/reconnect/HELLO/probe deadline.
The callback begins on the freshly connected central before its first HELLO;
that same link is checked again before HELLO and the exact boot probe. Failure
closes the current link using the preserved device reserve, then the existing
best-effort disable-and-darken transaction receives its independent bounded
cleanup deadline. No failed or timed-out observation reaches the exclusive
writer.

#### 14.3.1 ADR-0024 release-admission boundary

The combined runner and release finalizer share one pure standard-library
schema validator under `firmware/qualification/`; BLE transport, operator
prompts, and executable HIL orchestration remain outside that module. The
runner validates with it before its exclusive mode-`0600` writer creates the
private canonical result. Finalization loads the same validator from the
audited candidate source tree, admits one stable bounded result, and adds only
release-byte binding: exact
`waveshare-esp32-s3-lcd-147b/firmware.bin` full size/SHA-256,
the locally recomputed immutable-span map/size/SHA-256, release version, and
the pre-HIL candidate `release.json` digest. The input is read repeatedly from
one regular non-symlink descriptor and is compared again after late public
validation. It is never staged or copied.

The release summary contains exactly:

```text
schema_version
status
profile_id
board_model
firmware_version
candidate_release_json_sha256
candidate_firmware_sha256
candidate_firmware_size_bytes
candidate_attestation_sha256
candidate_attestation_size_bytes
production_app_evidence_sha256
production_app_active_release_path
terminal_record_sha256
qualification_result_sha256
```

All four identity fields are exact, `status` is `passed`, all digests are
lowercase 64-hex, sizes are positive exact integers, and candidate/attestation
values are recomputed from the bundled exact-board merged image. The summary exposes no
session or detailed/private evidence. Its production-app digest commits the
strict evidence object; its active release path remains a canonical versioned
`/firmware/v<SemVer>/release.json` path. Its terminal and result digests commit
the complete strict combined chain.

HIL marker selection follows the same source-introduction release-core rule
as first-party frozen-source auditing. Immutable `v0.4.2` replay retains the
exact five-key `PYBLE_HIL_RECORDS_V2` schema `2` and MUST not contain the new
field. The rejected pre-split v0.5 engineering baseline used V3 and MUST NOT
qualify or publish split bytes. A split v0.5 candidate and public release use
`PYBLE_HIL_RECORDS_V4` schema `4`, retain the OI-1 records for all three
profiles, and add exactly `waveshare_lcd147b_qualification`. Candidate creation writes
JSON `null`; the completed operator report must retain null; after validating
the private result, finalization alone substitutes the derived passed summary
in the staged report. Fresh and replay public validation recompute its
candidate firmware/attestation bindings. A source-era marker mismatch,
non-null candidate input, missing private result, extra key, wrong summary,
or private-result TOCTOU is terminal and leaves no output. Split v0.5 also
requires release schema 3 and OI-1 policy schema 2. v0.6.0 instead uses five
ordered `PYBLE_HIL_RECORDS_V5` rows, release schema 4, policy schema 3, and the
Waveshare/C3/Pico derived summaries; all start null/pending and finalization is
atomic. v0.4.2 replay retains release schema 2 and its historical two-profile
evidence. The existing
three-file administrative promotion envelope is unchanged (FR-SPLASH-9,
BLD-19…21).

### 14.4 Required red matrix for pre-v1 qualification

The first implementation commit after this freeze is `[red]` and covers:

- `tests/firmware_tests/host/test_oi1_profile_bench.py`: fake BLE central and
  reset transport; exact workload/sample counts; stale-advertisement
  rejection; HELLO MTU/window/chunk enforcement; deterministic payload bytes;
  strict GET offset validation; timer boundaries; retransmit accounting;
  heap-marker parsing; canonical evidence; baseline versus verify mode; exact
  five-profile order; and ESP/RP2 adapter discrimination;
- `tests/firmware_tests/host/test_footprint_gates.py`: exact schema-3
  five-profile policy order, ESP/RP2 threshold keys/types, evidence hash,
  application/raw-image headroom arithmetic, derivation algorithms, threshold
  boundary pass, one-unit crossing failure, and rejection of cross-target fields;
- `tests/firmware_tests/host/test_release_bundle.py` and
  `test_release_finalization.py`: historical HIL V2/V4 plus exact V5 marker
  and keys, older/wrong-era rejection,
  rejection, candidate null observations, policy/build immutability, public
  observation recomputation, candidate-release binding, missing/extra/wrong-
  type/wrong-unit/wrong-count/wrong-profile/wrong-order/wrong-hash fixtures,
  manufactured-MTU rejection, and candidate-to-public mutation envelope;
- `tests/firmware_tests/host/test_v060_qualification_workflow.py`: the actual
  committed schema-3/five-profile policy and baseline digest, source-bound
  non-operator-selectable Pico console pacing, no-replace private gate-result
  creation, and candidate-bound five-fragment completion generation that
  rejects operator-authored gate maps;
- `tests/firmware_tests/host/test_audited_candidate_validation.py`: policy and
  baseline evidence remain source/audit bound while C3 retains build/license
  audit participation but cannot acquire a public row; and
- shell entry points `test_oi1_profile_bench.sh` and
  `test_footprint_gates.sh`, wired into the applicable host/release gate.

Tests use fake transports and fixtures; real hardware execution occurs only
after the `[green]` bench/tooling commit. Production firmware caps, app code,
and PBLE/1 bytes are intentionally outside this minimal change.

### 14.5 Required red matrix for ADR-0023

Before the runtime lands, host tests MUST cover: S3 exactly-one and other
targets zero manifest resolution from the canonical source; SPDX/first-party
MIT provenance and rejection of vendor/copied/pin-table sources; import with a
guard that fails if `machine` is requested or any hardware/allocation fake is
called; the exact constructor/method surface; RGB565 boundaries and invalid
channels; scalar validation before outputs; reset/init command/data ordering;
address-window offsets; drawing/clipping; every SPI payload at most 4092 bytes;
wire byte order; framebuffer and CS restoration on an injected write failure;
active-high backlight; idempotent deinit; and partial-construction cleanup.

The HIL runner consumes explicit Pin objects and panel parameters, never a
board default table. It is bounded by duration/refresh count, uses `try/finally`
to switch the backlight off and deinitialize, and emits retained board,
firmware, pattern, PBLE-responsiveness, and operator-observation evidence. A
host fake cannot substitute for that exact-board record. Host tests nevertheless
MUST fail closed on every pre-arm boundary, simulate a stale VM during the
delivery grace, distinguish retryable transition errors from terminal protocol
or import defects, prove deadline-wide reconnect recovery without an attempt
ceiling, verify transactional notification-setup cleanup and old-link closure,
reject a live candidate-digest mismatch before drawing, require the operator
confirmation, mutate every three-cycle hash-chain link through the production
validator, round-trip the complete result through the exclusive evidence
writer, and prove all personal/raw fields remain absent (FR-TFT-1…7).

### 14.6 Required red matrix for ADR-0024

Before implementation, host tests MUST cover:

- import/default electrical inertness, exact four-name `__all__`, NVS
  missing/zero/non-one/read-failure behavior, exact integer write + commit,
  commit-failure propagation, best-effort disable blanking, and proof that the
  disabled guard never calls readiness or imports `machine`/the display driver;
- three lean boot sources with no splash path, plus the exact-board boot's
  agent-init → guarded-splash → runner → filesystem → console → autorun
  → GC order, including injected import/readiness/display failures that still
  start both existing workers and add no thread; executable VFS lookalikes for
  the companion and lazy dependencies MUST remain unexecuted on every target,
  while the same original `sys.path` object and exact contents MUST be restored
  before worker startup after success, missing frozen module, readiness fault,
  render fault, cleanup fault, and a non-`Exception` process-control exit;
- native Event Group allocation/idempotence, every field/start return path,
  nonfatal allocation failure with BLE initialization preserved,
  confirmed-active `EALREADY`, connect/fail/disconnect/ADV_COMPLETE/reset
  transitions including reset-time connection-handle clearing, soft-reset
  retention, exact integer timeout validation, bounded
  tick conversion, no clear-on-wait, and GIL release/reacquire;
- exact board Pin constructor values, SPI/configuration arguments, palette,
  every frame coordinate/text value, dynamic version, privacy-field absence,
  one `show()` with backlight low, deinit/collection before the final
  zero-wait readiness recheck/backlight-high action, false-on-final-readiness-
  loss behavior, snapshot semantics, and ordinary driver reuse; every Pin/constructor/draw/
  transfer/deinit/GC/final-light fault is injected and checked for original
  exception plus CS-high/backlight-low/resource cleanup;
- all 25 QR rows, upper-bit/bit-order invariants, big-endian row digest,
  165 × 165 placement/quiet zone, independent exact-payload decode, and a
  golden 172 × 320 framebuffer; and
- independent device/operator clock validation: finite `(0, 900]` operator
  values and the 900-second default; a callback whose elapsed time exceeds the
  device budget but not the operator budget; aggregate splash budget across a
  stale retry; unchanged residual HELLO/probe/RUN cleanup time; timeout-driven
  prompt cancellation distinguished from real process control; bounded
  STOP/link close and disable/darken on timeout; rejection of queued dark,
  terminal, malformed, or disconnected state; no result write; and unchanged
  evidence keys, hashes, and privacy allowlist; and
- exact-board exactly-one versus other-variant zero manifest/source cardinality,
  generated frozen content, SPDX/no-leak/licence inventory, build/size/
  reproducibility gates, the extended strict HIL validator/writer, and website
  `/app` production-readiness evidence without personal/raw result fields; and
- validator parity on a result produced by the complete fake combined runner;
  fully rehashed nested semantic tampering; bounded/canonical/exclusive-file
  admission and same-size TOCTOU; exact-board install and immutable-span binding;
  V2 historical versus V4 split source eras with V3 rejected; mandatory finalizer input;
  null-to-derived summary promotion; unchanged three-file envelope; no private
  result copy; and retained v0.4.2 public validation.

The exact-board runner remains unarmed until candidate bytes and the production
landing route are proven. Hardware execution occurs only after the `[green]`
implementation and never converts a missing operator scan/visual observation
into a pass (FR-SPLASH-1…9).

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
| Optional inert ST7789 user runtime, exact-board-only manifest, clean-room and feature HIL ([§2.9](#29-explicit-layer-4-st7789-runtime), [§4.9](#49-pyble_st7789--optional-layer-4-user-runtime), [§10.7](#107-st7789-manifest-and-source-contract), [§14.5](#145-required-red-matrix-for-adr-0023)) | `pyble_st7789` (Layer 4) + build/HIL | FR-TFT-1…7, IF-MACHINE, CON-6/8/9 |
| Default-off exact-board splash, exact-variant BLE-ready event, stable app QR and HIL ([§2.10](#210-explicit-exact-board-boot-identity-never-detection), [§4.10](#410-pyble_waveshare_lcd147b--exact-board-splash-companion), [§10.8](#108-exact-board-companion-manifest-and-boot-contract), [§14.6](#146-required-red-matrix-for-adr-0024)) | `pyble_waveshare_lcd147b`, `pble_ble`, boot + build/HIL | FR-SPLASH-1…9, FR-BOOT-4/6, IF-MACHINE, CON-6…9 |
| Two-task model, STOP delivery, serialization ([§5](#5-concurrency--task-model)) | runner+agent | FR-RUN-3, FR-BLE-11, NFR-SAFE-1/2, SEC-3 |
| Memory/footprint levers, native plan ([§8](#8-memory--footprint-design)) | all | NFR-FP-FLASH/HEAP/BOOT/TPUT/C3/GATE/CLOSE, NFR-PERF-1/4 |
| Chip-agnostic Layer 3 ([§2.2](#22-chip-agnostic-layer-3), [§11](#11-per-chip-design-notes)) | all | NFR-MAINT-1, CON-4 |
| Build pipeline, SHA gate, overlay copy-in, release manifest/integrity/provenance/recovery bundle ([§10](#10-build-system-design)) | scripts | BLD-1…22, CON-1/2/11/12, NFR-REL-4, NFR-MAINT-4 |
| Native-without-contract-change ([§2.1](#21-native-c-agent-from-day-one), [§8.6](#86-esp32-c3-mitigation)) | proto/ble/fs | NFR-MAINT-3 |
| Security design ([§13](#13-security-design)) | all | SEC-1…11, NFR-OFF-1/2, NFR-SAFE-4, CON-6/7/8/9/13 |
| Test design, fake transport, gates ([§14](#14-test-design)) | all | NFR-FP-GATE, NFR-REL-5, NFR-MAINT-2/3, all *verify* traces |
| Offline-first (no network) ([§13](#13-security-design)) | all | NFR-OFF-1/2, SEC-8 |
| IF-MACHINE (hardware via standard primitives and explicit Layer-4 helpers) ([§4.9](#49-pyble_st7789--optional-layer-4-user-runtime), [§9.3](#93-path-jail-enforcement), [§11](#11-per-chip-design-notes)) | (user code) | IF-MACHINE, CON-9, FR-TFT-2/3 |

**Requirements with no dedicated design element:** none. `SEC-9` is intentionally deferred (no v1.0 design surface beyond the additive-caps note in [§13](#13-security-design)). The `NFR-FP-*` measurement and enforcement design is frozen in §8.5; only evidence-derived per-profile numbers remain OI-1. Likewise the concrete label max-length, `SET_IDENTIFY_LED` encoding, and `IDENTIFY` blink-duration bound are owned by [protocol.md](../protocol.md) and tracked by OI-6, not invented here.

## 16. Risks & open questions

- **R1 — Footprint on ESP32-C3 (binding).** C3 real-hardware resource numbers
  remain pending, so the selected v0.6.0 row cannot pass and the atomic release
  cannot activate. Mitigation: run the same
  frozen method, and use native `USER_C_MODULE` hot paths if needed
  ([§8.6](#86-esp32-c3-mitigation)). Other profile results do not waive or
  predict the C3 result (OI-1, NFR-FP-CLOSE).
- **R2 — Frozen→native trigger point.** Which paths move to C, and on which chip the budget forces it, is undecided until HIL measurement (OI-3). The module boundaries ([§4](#4-module-design)) are drawn to make the move contract-neutral (NFR-MAINT-3).
- **R3 — iOS/Android BLE MTU quirks.** Central platforms negotiate MTU differently and may not grant 247; the firmware must operate correctly across the negotiated MTU down to the default (FR-BLE-8). Fragmentation/reassembly is tested across an MTU matrix ([§14.1](#141-per-module-verification-approach)).
- **R4 — Single-core C3 STOP latency.** With one core the runner and BLE/agent task time-share; STOP must still land promptly against a tight loop ([§5.2](#52-stop-delivery)). Validate on C3 HIL first ([§11](#11-per-chip-design-notes)).
- **R5 — v0.4.2 candidate pins are selected but not fully HIL-approved.** The
  exact `versions.lock` values (MicroPython v1.28.0 / ESP-IDF v5.5.1) are
  candidate-frozen for v0.4.2 (OI-2). Candidate-freezing makes the input
  immutable; it does not approve the remaining formal matrix, C3 compatibility,
  or a qualified release. A pin change creates a new candidate and reruns all
  build, audit, deployment, and exact-profile HIL gates through
  `upgrade_micropython.sh` (BLD-9/19/21).
- **R6 — PBLE/1 still DRAFT.** Opcode/UUID/status numbers are provisional until [protocol.md](../protocol.md) §2/§4 freeze (OI-4); the single constants mirror (D6) localizes the churn.
- **R7 — Auto-run caps flag naming.** The opt-in `main.py` auto-run flag name/encoding is owned by [protocol.md §7](../protocol.md#7-hello--capabilities) and must be fixed before F-12 (OI-5).
- **R8 — Identity/identify wire constants not frozen.** The label max-length, the `SET_IDENTIFY_LED` GPIO+active-level encoding, and the `IDENTIFY` blink-duration bound are owned by [protocol.md](../protocol.md) and must be frozen before FR-IDENT/FR-BLE-12 implementation (OI-6); the single constants mirror (D6) localizes the churn.
