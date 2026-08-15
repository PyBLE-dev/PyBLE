# PyBLE Agent Firmware — Requirements Specification

Status: **DRAFT (per-section freeze in effect)** · Owner: project maintainer · Last updated: 2026-08-15

### Freeze ledger (per-section, per PRD §1B.4)

Sections are frozen one at a time before the stories that cite them start. A
frozen section MUST NOT change except via a `[docs]` amendment that lands before
any dependent code. Freezing is cumulative with the gates in the
[public roadmap](../../ROADMAP.md).

| Section | Requirement IDs | Freeze status | Freeze act | Notes |
|---|---|---|---|---|
| §5.1 Reliability | NFR-REL-1…5 | **FROZEN v1.0** | G0 · 2026-07-01 · `[docs]` | Wire-independent; unblocks X-03 (NFR-REL-4). |
| §5.6 Maintainability | NFR-MAINT-1…4 | **FROZEN v1.0** | G0 · 2026-07-01 · `[docs]` | Unblocks X-01 (NFR-MAINT-4) + module/layout freeze (NFR-MAINT-2). |
| §6 Constraints | CON-1…13 | **FROZEN v1.0 (amended)** | G0 · 2026-07-01; display amendments 2026-08-01; image-split and erased-install-default amendments 2026-08-03 · `[docs]` | ADR-0023 admits the inert Layer-4 driver; ADR-0024 admits one exact-board companion and bounded boot hook; ADR-0028 confines both to a separate exact-board build; ADR-0029 enables the splash only in that exact image after erase. None adds Layer-3 display control, automatic detection, or a routing profile. |
| §8 Build, versioning & distribution | BLD-1…22 | **FROZEN v1.0 (amended)** | G0 · 2026-07-01; browser-release amendment 2026-07-29; exact-board split 2026-08-03; heterogeneous v0.6.0 release 2026-08-12 · `[docs]` | ADR-0033 freezes one five-profile v0.6.0 bundle with four ESP Web Serial images plus verified Pico UF2/BOOTSEL while preserving historical v0.4.2/v0.5.1 contracts. |
| §4 Functional (FR-BLE/PROTO/RUN/FS/CON/INFO/BOOT/MODE/IDENT) | FR-* | DRAFT (FR-BLE/FR-PROTO numbers frozen) | — | Inherits PBLE/1 numbers; frozen per M1 story as protocol.md §§ freeze. **protocol.md §4 opcodes + §8 status are FROZEN (2026-07-01), closing OI-4** — FR-BLE-8/10 and FR-PROTO-1…10 opcode/status numbers are now stable (F-01/F-02 DoR met). **protocol.md §6 (RUN-file) / §7 (HELLO caps) / §9 (version) froze 2026-07-01 (S3)** — FR-INFO-1..6, FR-PROTO-7/10, FR-RUN (RUN-file) and the FR-IDENT-1 / FR-BLE-12 **label** bound (24 B) are now stable (F-03/F-16/F-22/F-04 DoR met). **protocol.md §6 fully froze 2026-07-01 (S4)** — RUN{source}, STOP, SOFT_REBOOT, CONSOLE_DATA/INPUT + the OI-6 identify remainder (SET_IDENTIFY_LED/IDENTIFY/caps) are now stable (F-05/F-06/F-07/F-23 DoR met), **closing OI-6**. **Transactional RUN admission was clarified 2026-08-14**: local acceptance of one connection-bound zero-wait `RSP{OK}` submission is the execution cut, with exact-state rollback and no side effect on submission failure. **protocol.md §5 froze 2026-07-01 (S5)** — the file-transfer wire (read + windowed upload + workspace jail) is stable (FR-FS-1..16, F-08/F-09/F-17 DoR met); **§2–§9 are now all frozen**, only §10 (Security) remained DRAFT. The jail chokepoint (`pble_fs_resolve` + forbidden set: `fs_root` confinement, reserved `.pbltmp` suffix, reserved agent prefixes) is firmware-internal per ADR-0006 (the agent/overlay are embedded, not vfs paths). **protocol.md §10 (Security) + §5 resume behaviour + the OI-5 `auto_run` cap / `SET_AUTORUN` 0x23 froze 2026-07-01 (S6)** — SEC-1..11, FR-FS-7, FR-BOOT-1..6 / FR-MODE-1/4 / NFR-SAFE-3 are now stable (F-10/F-11/F-12/F-18 DoR met). **PBLE/1 §2–§10 are now ALL frozen — the wire is complete for v1.0.** |
| §5.2–§5.3 PERF/FP measurement contract | NFR-PERF/FP | **FROZEN pre-v1 (amended)** | Pre-v1 qualification amendment · 2026-07-30; repeatability amendment 2026-08-02; profile-split amendment 2026-08-03; five-profile amendment 2026-08-12 · `[docs]` | Historical v0.5 uses the exact three-profile policy schema 2. ADR-0033 freezes the v0.6.0 five-profile successor baseline schema 2, policy schema 3, and target-discriminated metrics without changing historical evidence. |
| [ESP32-C3 engineering qualification](ports/esp32-c3-4mb.md) | C3-G0…C3-G7 | **FROZEN; all results pending** | ADR-0032 · 2026-08-12 · `[docs]` | Selects ESP32-C3-MINI-1-N4 v0.4/4 MiB/no-PSRAM as reference hardware for the existing generic profile; freezes build, behavior, C3 OI-1 baseline, dual-app HIL, and console-flood control-priority gates without admitting a public C3 release. |
| §5.4–§5.5 SAFE/OFF | NFR-SAFE/OFF | DRAFT | — | Frozen per dependent story. |
| §7 External interfaces, §9 Security | IF-*, SEC-* | §9 SEC-* **FROZEN** (2026-07-01, S6) | — | SEC-1..11 mirror the frozen [protocol.md §10](../protocol.md#10-security-note-v1): pairing/encryption baseline (non-gating), connected-client-trust, single active writer (SEC-3), no MAC/label gating (SEC-7/11), no PII in adv (SEC-10), no telemetry (SEC-5). IF-* frozen per story alongside their protocol.md §§. |
| §4.11 Optional ST7789 user runtime | FR-TFT-1…7 | **FROZEN v0.5.0 (amended)** | ADR-0023 · 2026-08-01; ADR-0028 packaging amendment 2026-08-03 · `[docs]` | Additive exact-board Layer-4 library contract; only `waveshare-esp32-s3-lcd-147b` freezes it; no PBLE/1 or agent capability change. |
| §4.12 Exact-board boot splash | FR-SPLASH-1…9 | **FROZEN v0.5.1 (amended)** | ADR-0024 · 2026-08-01; frozen-resolution amendment 2026-08-02; ADR-0028 image split and ADR-0029 erased-install default 2026-08-03 · `[docs]` | Factory-enabled after an erased exact-board install, persistently disableable, exact-board image only; frozen-only resolution; BLE-ready fail-open frame; stable app QR; exact private-HIL-to-public-release admission. |

**2026-08-15 §4 functional amendment:** default-MTU ordinary responses use a
bounded session-bound callout pump; `STOP` and `SOFT_REBOOT` perform their side
effect only after their connection-bound response submission succeeds.

**PBLE/1 dependency:** [protocol.md §2 (transport)](../protocol.md#2-ble-transport-gatt), [§3 (framing)](../protocol.md#3-framing), [§4 (opcodes)](../protocol.md#4-opcodes), and [§8 (status)](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) are **FROZEN for v1.0**; the GATT UUID base, the §3.1 frame + §3.2 fragmentation, the opcode set + numbers, and the status set + numbers are now stable inputs to FR-BLE-1/8/10 and FR-PROTO-1…10. The §4/§8 freeze (2026-07-01) **closes OI-4** and completes the DoR for F-01 and F-02. **protocol.md §6/§7/§9 froze 2026-07-01 (S3)** — HELLO/caps, the RUN-file path, the version policy, and the 24 B label bound are stable, meeting DoR for F-03/F-16/F-22/F-04. **protocol.md §6 fully froze 2026-07-01 (S4)** — STOP/SOFT_REBOOT/console/RUN-source + the identify encodings, **closing OI-6** (F-05/F-06/F-07/F-23 DoR met).

## 1. Purpose, scope & document role

### 1.1 Purpose

This document is the **detailed firmware requirements specification** for the
initial ESP32-family v1 PyBLE agent port. It derives from and expands
[PRD §10 (Functional Requirements: Agent Firmware)](../prd.md) into
individually-testable, traceable requirements, each carrying a stable
requirement ID and a source/verification/story trace. It is the authority for
*what this port must do*; the companion [TDD.md](TDD.md) (Technical Design
Document) is the authority for *how it does it*. Future MicroPython + BLE MCU
families implement the same PBLE/1/control-plane contract through a
platform-specific target adapter and require their own derived requirements,
resource gates, provisioning contract, and HIL matrix.

### 1.2 Scope

For the initial ESP32 port, the firmware covers **Layers 1–3** of the
four-layer model defined in [firmware.md §1](../firmware.md#1-four-layer-rule)
and [PRD §1A.4](../prd.md):

- **Layer 1** — upstream MicroPython (ESP32 port), consumed as a pinned submodule.
- **Layer 2** — the per-chip board overlay (`esp32` / `esp32-s3` /
  `esp32-c3`) plus an independently selected exact-board variant when its
  dependency set differs (`waveshare-esp32-s3-lcd-147b`).
- **Layer 3** — the PyBLE agent: the protected control plane (`pyble_ble`, `pyble_proto`, `pyble_runner`, `pyble_fs`, `pyble_console`, `pyble_info`).

**Layer 4** (the user workspace) is **out of scope** as agent firmware — it
is content the agent serves and runs, not part of the control plane. The
agent's relationship to Layer 4 (the workspace jail) is in scope and specified
in [§4.4](#44-filesystem-bridge--workspace-jail-fr-fs). Two separately frozen
display carve-outs are in scope: the inert optional Layer-4 runtime in
[§4.11](#411-optional-st7789-user-runtime-fr-tft), and the exact-profile
Layer-2/4 companion in
[§4.12](#412-exact-board-boot-splash-fr-splash). Neither is a Layer-3
agent module or PBLE/1 hardware capability.

The Flutter app ([app.md](../app.md), [PRD §9](../prd.md)) is out of scope.

### 1.3 Document role & precedence

Per the doc hierarchy ("the more specific spec wins on its own topic"):

- [PRD §10](../prd.md) is the apex firmware requirement set; this document is its detailed expansion and MUST stay consistent with it.
- [firmware.md](../firmware.md) is the firmware **overview**; this document is the detailed requirements layer beneath it.
- [protocol.md (PBLE/1)](../protocol.md) **owns** the wire format (frame bytes, opcodes, status codes, UUIDs). This document MUST NOT redefine those; it references the relevant `§` and states only firmware *behaviour* against them.
- [hardware.md](../hardware.md) **owns** platform eligibility, the current
  support matrix, and target specifications. This document references them; it
  does not restate datasheet facts.

Where this document and [TDD.md](TDD.md) touch the same topic, this document wins on *requirements* (what/why); TDD.md wins on *design* (how).

## 2. References & definitions

### 2.1 Normative references

- [PRD](../prd.md) — apex requirements, especially §1A.4, §1B, §10, §11, §13, §14, §16.2, §17, §18.
- [firmware.md](../firmware.md) — agent firmware overview (four-layer rule, modules, chip targets, runtime rules, build, footprint).
- [browser-flashing.md](browser-flashing.md) — exact initial provisioning
  profiles, merged-image manifest, integrity/provenance bundle, recovery, and
  browser/HIL release gate.
- [protocol.md (PBLE/1)](../protocol.md) — BLE wire protocol: §2 transport, §3 framing, §4 opcodes, §5 file transfer, §6 run/stop/console, §7 HELLO/caps, §8 status codes, §9 versioning, §10 security.
- [hardware.md](../hardware.md) — supported chip families, board requirements, pin reference.
- [architecture.md](../architecture.md) — three-piece system view, clean-room boundary.
- [`firmware/versions.lock`](../../../firmware/versions.lock) — pinned upstream MicroPython + ESP-IDF.
- [`firmware/upstream/README.md`](../../../firmware/upstream/README.md) — clean-submodule rationale.
- [AGENTS.md](../../../AGENTS.md), [CLAUDE.md](../../../CLAUDE.md) — repo governance, no-leak gate.
- [Public roadmap](../../ROADMAP.md) and GitHub issues — firmware, protocol, and
  infrastructure work.

### 2.2 Definitions

- **Agent** — the Layer-3 `pyble_*` module set; the board-side control plane.
- **Control plane** — the always-running agent that services the BLE link and PBLE/1 commands, independent of any user program.
- **Workspace** — the Layer-4 user file region (`/main.py`, `/lib/*.py`, `/data/*`, optional `/project.json`) rooted at `fs_root`.
- **Workspace jail** — the constraint that PBLE/1 file commands may only read/write within `fs_root`.
- **Runner** — the task that executes user code (file or inline source).
- **HIL** — hardware-in-the-loop testing on every exact real-hardware profile
  claimed by a release. The current v0.4.2 public-beta profile set is exactly
  `esp32-4mb` and `esp32-s3-n16r8`: its supplemental production-browser rows
  passed, while its formal qualification matrix remains pending. The v1.0
  matrix additionally requires `esp32-c3-4mb`. The earlier v0.5.1
  source-candidate matrix was exactly
  `esp32-4mb`, `esp32-s3-n16r8`, and
  `waveshare-esp32-s3-lcd-147b`; each needs independent final-candidate HIL
  before qualification; it completed no exact-byte qualification. Current
  v0.6.0 source retains those prospective public profiles (PRD §1B.3,
  §10.12).
- **Frozen-Python agent** — agent modules baked into the firmware image as `.py` (frozen at build); the recommended first implementation.
- **Native agent** — hot paths moved to a `USER_C_MODULE` for throughput/RAM, behind the unchanged PBLE/1 contract.
- **Frozen user runtime** — an importable helper selected into an image for
  explicit use by Layer-4 programs. It is not an agent/control-plane module,
  capability claim, pin profile, or boot-time hardware owner.
- **Exact-board companion** — a factory-enabled-after-erase, persistently
  disableable frozen helper named for one
  physical board and usable only after an explicit choice. It is neither
  automatic detection nor a stored/transmitted routing profile; its bounded
  boot hook remains outside the PBLE/1 capability and trust surfaces.
- **Verification categories** (PRD §1B.3, cited in each requirement's `verify:`): *unit* (host-side native/unit), *conformance* (PBLE/1 protocol conformance), *build* (build sanity / SHA gate), *size* (static application-image/partition gate), *HIL* (runtime hardware-in-the-loop resource and behaviour gates).

## 3. System context

### 3.1 Four-layer model

The initial ESP32 firmware realizes Layers 1–3 of the
[firmware.md §1](../firmware.md#1-four-layer-rule) model:

```text
Layer 1  Upstream MicroPython (ESP32 port)  — pinned submodule, never edited in place
Layer 2  Board overlay                       — per-chip config: esp32 / esp32-s3 / esp32-c3
Layer 3  PyBLE agent (pyble_*)               — the protected control plane (in scope)
Layer 4  User workspace + optional user libs — /main.py, /lib/*.py, /data/*; explicit program control
```

The agent is the control plane and user code is just a program it runs; a frozen `while True: pass` MUST NOT wedge BLE or block `STOP` (PRD §1A.3 rejection 5, [firmware.md §5](../firmware.md#5-runtime-rules)).

### 3.2 Initial chip targets & the single pin

One agent codebase MUST build for three ESP-IDF targets — `esp32`, `esp32s3`, `esp32c3` — all on NimBLE, driven by the single MicroPython + ESP-IDF pin in [`versions.lock`](../../../firmware/versions.lock). Chip facts are owned by [hardware.md §1](../hardware.md#1-supported-chip-families-v1); **ESP32-C3 is the footprint constraint** ([§5](#5-non-functional-requirements), [PRD §10.13](../prd.md)).

### 3.3 Firmware scope: in / out

| In scope (this spec) | Out of scope |
|---|---|
| BLE peripheral + GATT (RX/TX/INFO), advertising, MTU, fragmentation | The app, `lib/pble/` Dart client ([app.md](../app.md)) |
| PBLE/1 engine: framing, CRC32, dispatch (behaviour only) | The PBLE/1 *wire definition* ([protocol.md](../protocol.md) owns it) |
| Runner: run/stop/soft-reboot, RUN_STATE | User code semantics; board-specific hardware drivers |
| Filesystem bridge + workspace jail; frozen-library selection contract in §4.10/§4.11 | GPIO routing, actuator/lab/calibration/display control in the agent |
| Console tee; device info / capabilities | Chip datasheets ([hardware.md](../hardware.md) owns them) |
| Boot/lifecycle; execution modes | Wi-Fi / USB-serial *runtime* transports |
| Build, versioning, distribution, footprint gates | App store distribution of the app |

## 4. Functional requirements

Requirement voice is MUST / SHOULD / MAY. Each line: **ID** — statement — *(source; verify; story)*.

### 4.1 BLE peripheral & GATT (FR-BLE)

- **FR-BLE-1** — The agent MUST expose exactly **one** primary GATT service on the PyBLE-owned 128-bit UUID base (`7079626c-…`, encoding ASCII `pybl`). — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL, conformance; story: F-01)*
- **FR-BLE-2** — The service MUST provide an **RX** characteristic (app → board) supporting **Write** and **Write-Without-Response**. — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL; story: F-01)*
- **FR-BLE-3** — The service MUST provide a **TX** characteristic (board → app) supporting **Notify**. — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL; story: F-01)*
- **FR-BLE-4** — The service MUST provide an **INFO** characteristic (board → app) supporting **Read** that returns a payload byte-equivalent to a `DEVICE_INFO` response, so a client can identify a board before subscribing to TX. — *(source: PRD §10.7, §18.3, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL, conformance; story: F-01, F-03)*
- **FR-BLE-5** — On power-up the board MUST advertise the Service UUID together with a default device name `PyBLE-XXXX`, where `XXXX` is the **last two bytes of the board's BLE MAC in uppercase hex** (e.g. `PyBLE-9F3A`); this default MUST be **stable across reboots** and ~unique so a client can recognize the board. — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL, conformance; story: F-01)*
- **FR-BLE-6** — The advertisement MUST allow the app to scan **filtered to the Service UUID**, not a raw device list. — *(source: PRD §8.1, §10.7; verify: HIL; story: F-01)*
- **FR-BLE-7** — The agent MUST accept an MTU request of **247**. — *(source: PRD §10.7, §13.4, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL; story: F-01)*
- **FR-BLE-8** — The agent MUST operate correctly across the negotiated MTU down to ATT MTU 23, using a usable per-packet payload of `MTU − 3` (ATT) minus the 1-byte fragmentation header. At ATT MTU 23, the reference agent MUST deliver its largest 491-byte ordinary encoded response as at most 26 fragments under the bounded response-delivery contract in FR-PROTO-6; early HELLO MUST NOT depend on MTU 247 having arrived first. — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt), [§3.2](../protocol.md#3-framing); verify: conformance, HIL; story: F-01, F-02)*
- **FR-BLE-9** — The BLE peripheral MUST use **NimBLE** on all three targets (Bluedroid not built). — *(source: PRD §10.1, §16.2, [firmware.md §4](../firmware.md#4-chip-targets-and-release-profiles); verify: build; story: F-01, F-13/14)*
- **FR-BLE-10** — The agent MUST implement PBLE/1 fragmentation/reassembly over RX/TX per [protocol.md §3.2](../protocol.md#3-framing). `FIRST` MUST abandon an incomplete receive run. A generic-response pump MUST retain the exact failed-fragment offset/index after `PBLE_TX_AGAIN` while it still owns the logical message, because the failed packet was not accepted. It MUST restart the identical encoded frame from `FIRST` only after a successful single-fragment `RUN`, `STOP`, or `SOFT_REBOOT` response changed the mutex-protected TX stream generation. — *(source: PRD §10.7, [protocol.md §3.2](../protocol.md#3-framing); verify: conformance; story: F-02, P-02)*
- **FR-BLE-11** — The BLE/agent task MUST keep servicing the link while a user program runs, so the link never depends on user-code progress. The generic-response callout MUST attempt exactly one zero-wait fragment per NimBLE-host callback and then return: success rearms after one RTOS tick when data remains; transient pressure rearms after at most 15 ms. A callback MUST NOT sleep, loop, retry inline, or block on TX capacity. Non-control/bulk TX MUST NOT interleave with its logically owned partial response; the single-fragment `RUN`, `STOP`, and `SOFT_REBOOT` response paths remain zero-wait and MAY preempt between fragments. — *(source: PRD §10.6, §13.3, [firmware.md §5](../firmware.md#5-runtime-rules); verify: unit, HIL; story: F-06)*
- **FR-BLE-12** — When a device label is set ([§4.9](#49-device-identity--identify-fr-ident), `SET_LABEL`), the persisted label MUST **replace** the default `PyBLE-XXXX` as the advertised device name so it is visible in the scan list **before connecting**; clearing the label (empty value) MUST restore the `PyBLE-XXXX` default. The advertised label MUST be bounded to the same length limit the board enforces on `SET_LABEL` (FR-IDENT-1). — *(source: PRD §10.7, [protocol.md §2](../protocol.md#2-ble-transport-gatt), [§4](../protocol.md#4-opcodes); verify: HIL, conformance; story: F-01)*

### 4.2 Protocol engine (FR-PROTO)

- **FR-PROTO-1** — The agent MUST implement the **full** PBLE/1 v1.0 opcode set in [protocol.md §4](../protocol.md#4-opcodes); none are optional in v1.0. — *(source: PRD §10.8, [protocol.md §4](../protocol.md#4-opcodes); verify: conformance; story: F-02)*
- **FR-PROTO-2** — The agent MUST encode and decode the §3.1 message frame (`VER`/`TYPE`/`OPCODE`/`ID`/`LEN`/`PAYLOAD`/`CRC32`) per [protocol.md §3.1](../protocol.md#3-framing); it MUST NOT redefine the wire format. — *(source: PRD §10.8, [protocol.md §3.1](../protocol.md#3-framing); verify: unit, conformance; story: F-02, P-01)*
- **FR-PROTO-3** — The agent MUST validate the IEEE CRC-32 over `VER…PAYLOAD` of every reassembled message; a frame whose CRC fails MUST be **dropped** and answered with `EVT ERROR(ECRC)` referencing the opcode if known. — *(source: PRD §10.7, §10.8, [protocol.md §3.2](../protocol.md#3-framing), [§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: unit, conformance; story: F-02, P-01)*
- **FR-PROTO-4** — The agent MUST correlate requests and responses by the 1-byte `ID`, echoing the request `ID` in the matching `RSP`; events MUST use `ID = 0`. A queued response MUST preserve its opcode and ID and remain bound to the originating connection generation and MicroPython VM epoch; a reused numeric connection handle or retained link MUST NOT receive bytes from earlier session or VM work. — *(source: [protocol.md §3.1](../protocol.md#3-framing); verify: conformance; story: F-02)*
- **FR-PROTO-5** — The agent MUST dispatch each decoded CMD to its handler by `OPCODE`. — *(source: PRD §10.3 (`pyble_proto`); verify: unit; story: F-02)*
- **FR-PROTO-6** — Every admitted command MUST return the correct PBLE/1 1-byte status in its `RSP`, including error cases (`EBADREQ`, `ENOENT`, `EACCES`, `ENOSPC`, `EIO`, `ENOMEM`, `EBUSY`, `ECRC`, `ERANGE`, `EUNSUPPORTED`, `EINTERNAL`). Before invoking an ordinary synchronous side-effecting handler, the reference dispatcher MUST atomically reserve one whole encoded response in a fixed depth-2 pool; deferred filesystem commands MUST reserve a pool ticket before host-to-worker enqueue and carry its slot incarnation, connection generation, and VM epoch. Reservation failure MUST invoke no handler, enqueue no work, and make no unreserved response attempt; it MUST terminate/cancel the originating session so bounded observable link loss, not a silent live-session drop, is the refusal outcome. If a deferred filesystem enqueue is full after reservation, no filesystem operation runs and the dispatcher MUST publish `EBUSY` through that same reserved slot. When a fully encoded response enters the ready FIFO, one absolute 1000 ms publication deadline begins with no progress extension. A pre-created host callout retains the failed-fragment position on transient pressure under exclusive logical ownership; it restarts from `FIRST` only after a successful single-fragment `RUN`, `STOP`, or `SOFT_REBOOT` response changes the TX stream generation. Disconnect, VM-epoch change, or token mismatch cancels the item; deadline expiry on a still-live session MUST terminate that session. Every required termination MUST atomically change the exact connection token from `OPEN` to `CLOSING` before doing anything else; `CLOSING` MUST fail every admission/live check for commands, tickets, all TX, and specialized handlers while remaining available only for exact lifecycle cleanup. The ESP reference agent MUST arm a pre-created, task-dispatched watchdog for one non-extending absolute 2500 ms deadline before making exactly one host-context `ble_gap_terminate` call. Only return `0` or `BLE_HS_EALREADY` may await exact disconnect/reset with the watchdog armed. Any other return, watchdog-arm failure, or watchdog expiry MUST immediately invoke public non-returning `esp_restart()`; the agent MUST NOT retry termination or call `ble_hs_sched_reset`. A termination-failure GAP event MUST NOT clear `CLOSING` or cancel the watchdog. Exact disconnect/reset MUST cancel the watchdog and idempotently invalidate the token and all bound work before later advertising/admission; stale watchdog work MUST revalidate the token/deadline and cannot affect a reused handle. Completion/cancellation MUST signal exactly once for the exact slot incarnation that transitions to complete; repeating either operation on an already-complete incarnation MUST be idempotent, and recycle MUST drain stale signals before reuse. Before old VM threads can be deleted, an allocation-free idempotent linker wrapper around `mp_thread_deinit` MUST use one authoritative admission/activity lock: close admission, invalidate old tokens, and wait for all complete-CMD and exact-epoch callback activity to leave under one absolute 2500 ms drain deadline. Timeout, counter invariant failure, or lifecycle-timer disarm failure MUST call non-returning `esp_restart()`. Only after the drain may it disarm soft-reboot/identify timers, synchronize TX/callout ownership, detach runner/console worker pointers, and call the exact upstream function. The soft-reboot callback MUST carry its armed epoch and enter/leave activity around rooted `SystemExit`/scheduler access; identify callbacks MUST revalidate epoch before GPIO changes. Exactly once per new VM, every PyBLE ESP board overlay's `MICROPY_PORT_INIT_FUNC` MUST atomically rotate the VM epoch and live connection generation with old-ticket invalidation; prevent future callout scheduling; synchronize with pool/TX ownership; hard-recycle all pool incarnations; and drain completion signals. A previously queued callout MUST revalidate the exact epoch/incarnation and touch nothing; reset MUST NOT depend on callout deinitialization or queued-event removal. Repeated agent initialization within one VM is idempotent. A final boot readiness barrier MUST reopen only after both fresh workers have entered, all handler/console wiring is safe, and auto-run admission has completed; a boot-wiring failure leaves admission closed. The linker options and release map/nm build checks MUST prove that all ESP targets resolve `mp_thread_deinit` through the wrapper (including forced wrapper retention) and execute the per-`mp_init` hook, with no upstream source edit. The RUN/STOP/SOFT_REBOOT specialized exception is FR-RUN-1/5/8: each uses its connection-bound, single-fragment, zero-wait response attempt before its corresponding side effect, and submission failure MUST suppress generic fallback and the side effect. — *(source: PRD §10.8, [protocol.md §3.2](../protocol.md#3-framing), [§6](../protocol.md#6-run--stop--console), [§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: unit, conformance, build, HIL; story: F-02, P-04)*
  Failed-session termination uses retained
  `CLOSED`/`OPEN`/`CLOSING`/`CLEANING`/`RESTARTING` state initialized once per
  chip boot, not per MicroPython VM. The task-dispatched one-shot MUST be
  created successfully before NimBLE starts. GAP CONNECT MUST mint and open an
  exact nonzero-generation token under the session lock before exposing it;
  failure to open MUST restart rather than overwrite retained state. Every TX
  attempt MUST carry its originating full token to the sole Notify exit. Arm,
  GAP-error, deadline, timer-stop, and residual-rearm failures MUST atomically
  claim terminal `RESTARTING` before public non-returning `esp_restart()`;
  later disconnect/reset/open operations cannot clear that claim. Exact
  disconnect/reset MUST claim `CLEANING` before timer action. Normal `OPEN`
  cleanup has no termination timer; `CLOSING` cleanup may invalidate work and
  advertise only after `esp_timer_stop()` returns `ESP_OK`, with every other
  result restarting. An early callback MUST rearm only `deadline - now`; a
  stale callback MUST have no effect even while a reused handle's successor is
  `CLOSING`. `BLE_GAP_EVENT_TERM_FAILURE` MUST be an explicit state/timer/work/
  advertising no-op. The agent MUST NOT use `nimble_port_stop`, direct
  NimBLE/controller teardown, or a private ESP restart entry point as a
  termination fallback.

  The same absolute 2500 ms wrapper deadline covers activity drain,
  soft-reboot/identify timer disarm, prevention of future callout scheduling,
  and acquisition of the physical recursive TX mutex; an inactive or
  already-fired lifecycle timer is idempotent disarm success and any other
  failure restarts. Persistent FS/runner workers are excluded from this wrapper
  activity count; the FS worker's entire-dispatch busy state is used only by
  the pre-acceptance `SOFT_REBOOT` quiescence gate. The
  wrapper MUST retain TX-mutex ownership while it detaches pointers, sets both
  `pble_runner_sysexit` and `pble_fs_put_file` to `MP_OBJ_NULL`, and calls
  `__real_mp_thread_deinit`, releasing only after old tasks have been deleted.
  Epoch reset MUST defensively set both roots to `MP_OBJ_NULL` again before
  new-VM registration. A queued static response-callout event carries no old
  frame pointer: it enters lifecycle activity, is a no-op while closed/not
  ready, and otherwise re-peeks the current ticket/incarnation/session under
  lock. Therefore a peek paused across wrapper reset blocks recycle until the
  callback leaves. If the wrapper or port-init seam observes a connection in
  `CLOSING`, it MUST immediately `esp_restart()` rather than reopen a rotated
  generation or disarm the independent termination watchdog. A slot reserve
  MUST drain its binary completion semaphore before exposing the new
  incarnation. The waiter MUST loop after every wake and recheck the exact
  incarnation plus authoritative state under the pool mutex: matching
  `RESERVED`/`READY` means a stale wake and continues; exact `COMPLETE` returns;
  incarnation mismatch cancels. The physical give remains outside that mutex,
  including when an old give is delayed across hard recycle/reserve or races a
  new completion.
- **FR-PROTO-7** — The agent MUST emit and accept only `VER = 0x01` frames for PBLE/1 and MUST reject/refuse other versions per the versioning policy. — *(source: PRD §18.1, [protocol.md §3.1](../protocol.md#3-framing), [§9](../protocol.md#9-versioning-policy); verify: conformance; story: F-02, P-03)*
- **FR-PROTO-8** — An admitted malformed or structurally invalid request MUST be answered with `EBADREQ` through the same bounded, session-bound response path; local response-capacity refusal follows FR-PROTO-6's no-handler, session-termination outcome. — *(source: [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: conformance; story: F-02)*
- **FR-PROTO-9** — A well-formed request for an opcode/feature the agent does not support MUST be answered with `EUNSUPPORTED`. — *(source: PRD §10.8, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: conformance; story: F-02)*
- **FR-PROTO-10** — The agent MUST NOT require or assume use of any capability it did not advertise in HELLO (`caps`); the wire behaviour MUST match the advertised baseline. — *(source: PRD §10.8, §18.3, [protocol.md §7](../protocol.md#7-hello--capabilities); verify: conformance; story: F-03, P-03)*

### 4.3 Runner & execution control (FR-RUN)

- **FR-RUN-1** — `RUN { mode: file }` MUST execute a `.py` file from the workspace only after local Notify acceptance of its matching `RSP{OK}`, then emit `RUN_STATE(running)`. The ESP reference handler MUST make a provisional, non-observable reservation and copy first, attempt that connection-bound one-fragment response exactly once without waiting, and wake the runner exactly once only on `PBLE_TX_OK`. Mutex contention, no connection, a changed connection, or Notify backpressure MUST restore the exact prior runnable state and cause no response fallback, worker wake, execution, console output, or RUN event. At ATT MTU 23 the 11-byte response frame fits within the 19 PBLE/1 message bytes carried by one fragment. — *(source: PRD §8.2, §10.6, [protocol.md §6](../protocol.md#6-run--stop--console); verify: unit, HIL, conformance; story: F-04)*
- **FR-RUN-2** — `RUN { mode: source }` MUST execute an inline source snippet with the same lifecycle as a file run. — *(source: PRD §10.8, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL, conformance; story: F-05)*
- **FR-RUN-3** — The runner MUST execute user code on a task **separate** from the BLE/agent task. — *(source: PRD §10.6, §13.3, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-04, F-06)*
- **FR-RUN-4** — Only one user program MUST run at a time; a `RUN` issued while a program is running MUST be answered with `EBUSY`. — *(source: PRD §10.6, §14.1, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: conformance, HIL; story: F-04)*
- **FR-RUN-5** — Only after the connection-bound, single-fragment, zero-wait `RSP{OK}` submission succeeds, `STOP` MUST interrupt the runner by raising `KeyboardInterrupt`, and MUST land promptly even against a tight loop (e.g. `while True: pass`). Response-submission failure MUST leave execution unchanged, emit no generic fallback, and perform no interrupt. — *(source: PRD §8.3, §10.6, §13.3, [protocol.md §6](../protocol.md#6-run--stop--console), [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-06)*
- **FR-RUN-6** — On `STOP` or on an uncaught exception the runner MUST tear down cleanly and report the resulting `RUN_STATE`. — *(source: PRD §8.2, §13.3, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL; story: F-06)*
- **FR-RUN-7** — The agent MUST emit `RUN_STATE` events on every state transition (`idle` / `running` / `done` / `error`) so the app drives UI state without polling. — *(source: PRD §10.6, [protocol.md §6](../protocol.md#6-run--stop--console), [§4](../protocol.md#4-opcodes); verify: conformance, HIL; story: F-04)*
- **FR-RUN-8** — `SOFT_REBOOT` MUST submit an observable `RSP{OK}` before it
  soft-resets the MicroPython VM (clearing interpreter state), MUST defer VM
  teardown for the bounded delivery grace defined by the reference design, and
  SHOULD keep the BLE link where possible. A response-submission failure MUST
  leave the VM running; a second request while reset is pending MUST return
  `EBUSY`. The command MUST first close FS admission and atomically prove the FS
  worker idle and queue empty without blocking; failure MUST reopen the gate,
  return `EBUSY`, and perform no reboot side effect. After that quiescence cut,
  non-reboot admission is provisionally closed. Successful response submission
  and timer arm MUST commit the closure through teardown; failure of either
  MUST reopen all gates and leave the VM intact. On the next VM initialization, after prior
  MicroPython threads have been deleted, the agent MUST atomically rotate the
  VM epoch and live connection generation with old-ticket invalidation;
  prevent future response-callout scheduling and require any already-queued
  callback to revalidate its exact epoch/incarnation; synchronize with
  pool/TX ownership; hard-recycle response slots and drain their completion signals; reset the FS
  queue/transfer state; reset the runner semaphore, state machine, request
  buffers, and worker pointer; reset console buffers and BLE RX reassembly;
  and reopen admission only after both fresh workers have entered, final boot
  handler/console wiring is safe, and auto-run admission has completed. An
  allocation-free `mp_thread_deinit` linker wrapper MUST close/invalidate and
  detach worker pointers before deletion; every PyBLE ESP overlay's
  `MICROPY_PORT_INIT_FUNC` MUST perform exactly one epoch rotation/hard reset per
  new `mp_init`. Repeated initialization in one VM is idempotent, and any boot-wiring failure
  leaves admission closed. Old-epoch work MUST NOT execute or publish. — *(source: PRD §8.3, §10.8,
  [protocol.md §6](../protocol.md#6-run--stop--console); verify: unit, HIL;
  story: F-06)*
- **FR-RUN-9** — Normal completion MUST yield `RUN_STATE(done)`; an uncaught exception MUST stream the traceback as `CONSOLE_DATA(stderr, …)` and then emit `RUN_STATE(error)`. — *(source: PRD §8.2, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL, conformance; story: F-04, F-07)*
- **FR-RUN-10** — After `STOP` the agent MUST return the board to `RUN_STATE(idle)`. — *(source: PRD §8.3, §10.6, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL; story: F-06)*

### 4.4 Filesystem bridge & workspace jail (FR-FS)

- **FR-FS-1** — `FILE_LIST` MUST list a workspace directory rooted at `fs_root`. — *(source: PRD §8.4, §10.8, [protocol.md §4](../protocol.md#4-opcodes); verify: conformance, HIL; story: F-08)*
- **FR-FS-2** — `FILE_STAT` MUST return the size and CRC of one path (used for resume), and `ENOENT` for a missing path. — *(source: PRD §8.4, §10.8, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-08, F-10)*
- **FR-FS-3** — Download (`FILE_GET_BEGIN` / `FILE_GET_DATA` / `FILE_GET_END`) MUST stream a file from an offset and report a whole-file CRC for the app to verify. Its deferred queue item MUST carry a reserved response ticket with slot incarnation, originating connection generation, and VM epoch; revalidate immediately before and after each VFS operation/chunk and before publishing worker-scratch output; and complete the matching `RSP` before emitting dependent `FILE_GET_DATA`/`FILE_GET_END` events. Every physical data/end event attempt MUST bind the exact `{handle, connection generation, VM epoch}` and serialize its final token check plus Notify with GAP lifecycle; an outer worker check alone is insufficient. Disconnect or VM reset cancels/recycles the ticket. No VFS operation/chunk may start after invalidation; an indivisible operation validly started before invalidation may finish, but its owner MUST revalidate afterward and emit, publish, or start nothing further. — *(source: PRD §8.4, §10.8, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: unit, conformance, HIL; story: F-08)*
- **FR-FS-4** — Upload (`FILE_PUT_BEGIN` / `FILE_PUT_DATA` / `FILE_PUT_END`) MUST accept windowed chunks with a sliding window of up to `W` unacknowledged chunks (`W` from HELLO; the reference agent advertises **W=8** with receiver queue depth `W+2`). Clients read `W` from caps and adapt — "up to W" client semantics are unchanged. `FILE_PUT_DATA` queue items MUST carry exact `{handle, connection generation, VM epoch}` ownership, validate immediately before and after the VFS chunk write, and emit no ACK or further effect after invalidation. FS enqueue+insertion, dequeue-to-busy, and the non-blocking `SOFT_REBOOT` quiescence close plus idle/queue-empty decision MUST share synchronization; `worker_busy` MUST span the entire dequeued dispatch. A dequeued worker that loses that cut MUST cancel before starting a VFS operation and release any response ticket it owns. — *(source: PRD §8.4, §10.8, §13.4, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-09, F-11; reference-agent W raised 4→8 2026-07-04 `[docs]` to lift stop-and-wait upload throughput — no wire change, §5 offset/watermark ACK is W-agnostic; RAM cost ≈ +1 kB (4 queue slots × ~250 B), within the ESP32-C3 heap floor per NFR-FP-HEAP)*
- **FR-FS-5** — The agent MUST emit `FILE_PUT_ACK { ack_offset }` carrying the highest contiguous byte offset written, so the app advances the window and retransmits gaps. Each ACK retry MUST retain the transfer's exact `{handle, connection generation, VM epoch}` and serialize its final token check plus Notify with GAP lifecycle; it MUST NOT retarget a current global handle. — *(source: PRD §8.4, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-09)*
- **FR-FS-6** — `FILE_PUT_END { crc32 }` MUST verify the whole-file CRC and report a transfer `OK` **only** after a full-file CRC match. — *(source: PRD §8.4, §10.8, §13.1, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-09)*
- **FR-FS-7** — On a `FILE_PUT_BEGIN` for a path that already holds a verified partial prefix, the agent MUST return `resume_offset > 0` so the upload resumes rather than restarting. — *(source: PRD §8.4, §13.1, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-10)*
- **FR-FS-8** — `FILE_DELETE`, `MKDIR`, and `FILE_RENAME` MUST be supported, each returning the correct status. Deferred operations MUST validate their exact response/session/VM token immediately before and after the VFS call; work invalidated before the call MUST perform no mutation, and work invalidated after it MUST publish no late response or event. — *(source: PRD §8.4, §10.8, [protocol.md §4](../protocol.md#4-opcodes); verify: conformance, HIL; story: F-09)*
- **FR-FS-9** — Uploads MUST use **temp-write-then-rename** so a file is never corrupted mid-transfer. — *(source: PRD §8.4, §10.4, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL, unit; story: F-09)*
- **FR-FS-10** — File operations MUST be confined to `fs_root`; any path that escapes it (`..` traversal, absolute paths outside the root) MUST be rejected with `EACCES`. — *(source: PRD §10.4, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: unit, conformance; story: F-09)*
- **FR-FS-11** — The agent control plane (Layer 3) and board overlay (Layer 2) MUST be **forbidden paths**, not writable (or replaceable) via PBLE/1 file commands; such attempts MUST return `EACCES`. — *(source: PRD §10.2, §10.4, §14.1; verify: unit, conformance; story: F-09)*
- **FR-FS-12** — The workspace bridge MUST be **`.py`/data only**; the agent MUST NOT require, generate, or depend on `.mpy`/`.pyc` in the workspace, nor accept them as transfer artifacts. — *(source: PRD §1A.3 rejection 6, §10.4, §10.14; verify: unit, conformance; story: F-09)*
- **FR-FS-13** — The agent MUST report the writable workspace root as `fs_root` in `DEVICE_INFO`/HELLO. — *(source: PRD §10.4, §10.8, [protocol.md §7](../protocol.md#7-hello--capabilities); verify: conformance, HIL; story: F-03)*
- **FR-FS-14** — A whole-file CRC mismatch on `FILE_PUT_END` MUST return `ECRC` and MUST NOT replace the target file. — *(source: PRD §10.8, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: unit, conformance, HIL; story: F-09)*
- **FR-FS-15** — Filesystem errors MUST map to their PBLE/1 status codes (`ENOENT`, `ENOSPC`, `EACCES`, `EIO`, `ERANGE`) rather than failing silently. — *(source: PRD §9.2, §10.8, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); verify: conformance; story: F-08, F-09)*
- **FR-FS-16** — The jail constrains the **PBLE/1 file bridge** only; user code MAY touch the filesystem normally at runtime via standard MicroPython `os`/`vfs`. — *(source: PRD §10.4, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-09)*

### 4.5 Console (FR-CON)

- **FR-CON-1** — The agent MUST tee the running program's `stdout`/`stderr` to BLE as `CONSOLE_DATA` events. — *(source: PRD §8.2, §10.3, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL, conformance; story: F-07)*
- **FR-CON-2** — `CONSOLE_DATA` events MUST distinguish the `stdout` and `stderr` streams. — *(source: PRD §9.4, [protocol.md §6](../protocol.md#6-run--stop--console); verify: conformance, HIL; story: F-07)*
- **FR-CON-3** — `CONSOLE_INPUT { bytes }` MUST feed bytes to a program blocked on `input()`/`sys.stdin`. — *(source: PRD §8.2, §10.8, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL; story: F-07)*
- **FR-CON-4** — The console MUST be **observe-anywhere**: `stdout`/`stderr` MUST stream regardless of which client triggered the run. — *(source: PRD §8.2, §10.8, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL; story: F-07)*
- **FR-CON-5** — The agent MAY also mirror `stdout`/`stderr` to USB-serial when present, for **local debugging only**; USB serial MUST NOT be a runtime PBLE/1 transport. — *(source: PRD §10.3, §11.2, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-07)*

### 4.6 Device info / capabilities (FR-INFO)

- **FR-INFO-1** — `DEVICE_INFO` MUST report at least `chip`, MicroPython version, free memory, `fs_root`, MTU, the stable `device_id` (the MAC-derived suffix, per FR-BLE-5), and `label` (the user-set device label, or empty when unset). — *(source: PRD §8.1, §10.8, [protocol.md §2](../protocol.md#2-ble-transport-gatt), [§4](../protocol.md#4-opcodes); verify: conformance, HIL; story: F-03)*
- **FR-INFO-2** — `HELLO` MUST be the **first** exchange after connect, performing protocol-version and capability negotiation per [protocol.md §7](../protocol.md#7-hello--capabilities). — *(source: PRD §10.5, §18.3, [protocol.md §7](../protocol.md#7-hello--capabilities); verify: conformance, HIL; story: F-03)*
- **FR-INFO-3** — The HELLO reply `caps` MUST include `chip`, `mpy_version`, `fs_root`, `max_file_size`, `put_window` (`W`), `chunk_size`, `has_sd`, `free_mem`, `device_id` (the stable MAC-derived suffix), `label` (the user-set label, or empty), `has_identify` (whether the board supports `IDENTIFY`), and `identify_led` (the configured identify-LED GPIO, or null). The client MUST offer an Identify action **only** when `has_identify` is set. These identity/identify caps are **additive within PBLE/1**; an older client simply ignores them. — *(source: PRD §10.8, §18.3, [protocol.md §7](../protocol.md#7-hello--capabilities), [§9](../protocol.md#9-versioning-policy); verify: conformance; story: F-03)*
- **FR-INFO-4** — A read of the INFO characteristic MUST return a `DEVICE_INFO`-equivalent payload so a client can identify a board before subscribing. — *(source: PRD §10.7, §18.3, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL, conformance; story: F-01, F-03)*
- **FR-INFO-5** — The agent MUST reply to `HELLO` with a chosen `proto_version` it supports, and MUST refuse (rather than silently mis-speak) a client whose offered versions it cannot satisfy. — *(source: PRD §18.3, [protocol.md §7](../protocol.md#7-hello--capabilities), [§9](../protocol.md#9-versioning-policy); verify: conformance; story: F-03, P-03)*
- **FR-INFO-6** — `caps.has_sd` MUST reflect actual SD-card presence on the board. — *(source: PRD §10.3 (`pyble_info`), §10.8, [protocol.md §7](../protocol.md#7-hello--capabilities); verify: HIL; story: F-03)*

### 4.7 Boot & lifecycle (FR-BOOT)

- **FR-BOOT-1** — On power-up the agent MUST initialize, start BLE advertising, and **wait for a connection**. — *(source: PRD §8.3, §10.5, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-12)*
- **FR-BOOT-2** — By default the agent MUST NOT auto-run the user's `main.py`; the board boots into agent mode regardless of workspace contents. — *(source: PRD §1A.4, §8.3, §10.5; verify: HIL; story: F-12)*
- **FR-BOOT-3** — Auto-run MUST be **opt-in only**, gated behind an explicit capability flag surfaced in `DEVICE_INFO`/HELLO. — *(source: PRD §10.5, §13.3, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL, conformance; story: F-12)*
- **FR-BOOT-4** — The agent MUST reach the advertising state independently of user-workspace validity; a syntactically broken or infinite-loop `main.py` MUST NOT prevent advertising or connection. — *(source: PRD §10.5, §13.1; verify: HIL; story: F-12)*
- **FR-BOOT-5** — The agent MUST NOT depend on an editable `boot.py`/`main.py` for its own operation. — *(source: PRD §1A.3 rejection 5, §10.2; verify: HIL; story: F-12)*
- **FR-BOOT-6** — A control-plane fault MUST fail safe to the advertising state rather than wedging the board. — *(source: PRD §13.1, §10.5; verify: HIL; story: F-12)*

### 4.8 Execution modes (FR-MODE)

- **FR-MODE-1** — The agent MUST support **agent mode (idle)**: advertising and/or connected, servicing PBLE/1 file/info/console-input commands with no user program executing; `RUN_STATE` reports `idle`. — *(source: PRD §10.6, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL, conformance; story: F-03, F-12)*
- **FR-MODE-2** — The agent MUST support **run mode**: a user program executes on the runner task while the BLE/agent task continues to service the link; `RUN_STATE` reports `running`, then `done` or `error`. — *(source: PRD §10.6, [firmware.md §5](../firmware.md#5-runtime-rules); verify: HIL; story: F-04)*
- **FR-MODE-3** — Every mode transition MUST be emitted as a `RUN_STATE` event. — *(source: PRD §10.6, [protocol.md §6](../protocol.md#6-run--stop--console); verify: conformance, HIL; story: F-04)*
- **FR-MODE-4** — The agent MUST remain in agent mode (not auto-enter run mode) on cold boot unless the auto-run capability (FR-BOOT-3) is enabled. — *(source: PRD §10.5, §10.6; verify: HIL; story: F-12)*

### 4.9 Device identity & identify (FR-IDENT)

These are **per-device configuration the agent owns for its own
screenless-pairing UX** — a human-readable label and a single optional
status-LED to blink. They map **no** hardware for user code, are **not** a
routing/pin profile or board-capability map, and **never** gate access (see
CON-13, SEC-10/11). They exist because many initial and future supported boards
are screenless.

- **FR-IDENT-1** — `SET_LABEL` MUST persist a **bounded-length UTF-8** device label to NVS and, on success, MUST make that label the advertised device name (FR-BLE-12) and the `DEVICE_INFO.label`/HELLO `label` value; an **empty** label MUST clear the stored label, restoring the `PyBLE-XXXX` default. An over-length label MUST be rejected with `ERANGE` and MUST NOT be stored. — *(source: PRD §10.7, §14.2, [protocol.md §4](../protocol.md#4-opcodes), [§2](../protocol.md#2-ble-transport-gatt), [§10](../protocol.md#10-security-note-v1); verify: conformance, HIL; story: F-03)*
- **FR-IDENT-2** — `SET_IDENTIFY_LED` MUST persist a **single** identify status-LED configuration — one GPIO number plus its active level — to NVS. This is **device config for the IDENTIFY blink only**: it MUST NOT be exposed to user code, MUST NOT map or reserve hardware for user-code routing, and MUST NOT be treated as a routing/pin profile. — *(source: PRD §11.1, §11.3, [protocol.md §4](../protocol.md#4-opcodes), [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware); verify: conformance, unit (structure); story: F-03)*
- **FR-IDENT-3** — `IDENTIFY` MUST blink the configured identify LED for a **bounded duration** so the user can spot the physical board, and MUST do so on a **non-blocking path** that does not stall the BLE/agent task or a running user program (FR-BLE-11, FR-RUN-3). — *(source: PRD §10.6, §13.3, [protocol.md §4](../protocol.md#4-opcodes), [§6](../protocol.md#6-run--stop--console); verify: HIL, conformance; story: F-03)*
- **FR-IDENT-4** — `IDENTIFY` MUST return `EUNSUPPORTED` (0x0A) when no identify LED has been configured, and the board MUST report `has_identify = false` and `identify_led = null` in HELLO/`DEVICE_INFO` until one is configured. — *(source: PRD §10.8, [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp), [§7](../protocol.md#7-hello--capabilities); verify: conformance; story: F-03)*
- **FR-IDENT-5** — The device label and the identify-LED configuration MUST **survive reboot** (persisted in NVS), so the advertised name, `has_identify`, and `identify_led` are stable across power cycles. — *(source: PRD §10.7, §10.5; verify: HIL, conformance; story: F-03, F-12)*
- **FR-IDENT-6** — The identify blink MUST be **cosmetic only**: it MUST NOT be used for, or be repurposable as, GPIO routing for user code, a board-capability map, or any access-gating signal. — *(source: PRD §1A.3 rejection 3, §11.1, §11.3, [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware); verify: unit (structure); story: F-01, F-03)*

### 4.10 Standard user-code libraries (FR-LIB)

> **FROZEN 2026-07-28 (`[docs]`, [ADR-0018](../../decisions/0018-standard-micropython-neopixel.md)).**
> This is an additive user-runtime/build contract. It changes no PBLE/1 byte,
> capability, agent module, or board profile.

- **FR-LIB-1** — Every `esp32`, `esp32-s3`, and `esp32-c3` firmware image MUST make the pinned upstream MicroPython `neopixel.NeoPixel` API importable offline by user file/source runs and after a soft reboot. MUST (*source: PRD §9.8, §11.3; verify: resolved-manifest/build/HIL; story: F-24/A-31*)
- **FR-LIB-2** — The module MUST be selected from the pristine pinned MicroPython/micropython-lib tree through each target's frozen manifest; PyBLE MUST NOT copy, fork, patch, or replace it with a custom WS2812 driver. MUST (*source: PRD §1A, §10.9, §10.10; verify: build/structure; story: F-24*)
- **FR-LIB-3** — Bundling NeoPixel MUST NOT add an agent GPIO abstraction, PBLE/1 opcode/capability, board/onboard-LED name, pin/count/colour default, or target-specific user-code routing. GPIO, pixel count, index, colour, timing, and physical suitability remain explicit user-program/runtime concerns. MUST (*source: PRD §9.8, §11.3; verify: unit/no-leak/HIL; story: F-24/A-31*)
- **FR-LIB-4** — Release validation MUST resolve exactly one `neopixel.py`
  for each of the four build variants, record the per-variant firmware-size
  delta, and run a runtime import smoke on every exact profile included in
  that release. The historical v0.4.2 runtime-qualification matrix is the two
  published-beta profiles in §2.2 and remains open beyond the supplemental
  browser run. The v0.6.0 matrix requires fresh independent import evidence
  for all four ESP profiles in §2.2, including `esp32-c3-4mb`. Pico does not
  inherit this claim: its separate OI-P4 remains open until the upstream
  package and required RP2 runtime primitive are validated. Any visual
  LED smoke MUST take an operator-supplied GPIO, use a bounded dim sequence,
  and turn the pixel off on exit. MUST (*source: PRD §10.11, §10.13, §13.3;
  verify: build/size/HIL; story: F-24*)

This NeoPixel contract applies to the three initial ESP32-family images.
A future platform port MUST NOT claim equivalent support until it validates the
upstream package and required runtime primitive for that target.

### 4.11 Optional ST7789 user runtime (FR-TFT)

> **FROZEN v0.5.0 · 2026-08-01; HIL operator-deadline amendment 2026-08-02;
> packaging amendment 2026-08-03 (`[docs]`,
> [ADR-0023](../../decisions/0023-explicit-st7789-user-runtime.md),
> [ADR-0028](../../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).** This is
> an additive Layer-4 user-runtime/build contract. It changes no PBLE/1 byte,
> agent module or capability, or initial chip target. The runtime is packaged
> only in the separate `waveshare-esp32-s3-lcd-147b` provisioning image; the
> lean `esp32-s3-n16r8` image omits it. That installer distinction is not a
> PBLE/1 board-selection or connection gate.

- **FR-TFT-1** — The `waveshare-esp32-s3-lcd-147b` image MUST freeze exactly
  one PyBLE-authored
  module named `pyble_st7789` from
  `firmware/python_modules/pyble_st7789.py`. The lean `esp32-s3`, `esp32`, and
  `esp32-c3` manifests MUST NOT select that optional module. The number of
  initial chip targets remains exactly three, the build-variant count is four,
  and all continue to use the single MicroPython/ESP-IDF pin. — *(source:
  ADR-0023, ADR-0028; verify: resolved manifest, build, structure; story:
  ADR-0023/0028 increment)*
- **FR-TFT-2** — Importing `pyble_st7789` MUST be inert: it MUST NOT import or
  configure `machine.SPI`/`machine.Pin`, allocate a framebuffer, change a GPIO,
  send a display command, sleep, or start a task. Construction is the first
  permitted hardware side effect, and the module MUST remain importable in a
  user file/source run and after a soft reboot. — *(source: ADR-0023; verify:
  unit, build, HIL; story: ADR-0023 increment)*
- **FR-TFT-3** — The complete v0.5.0 public surface MUST be the callable
  `rgb565(red, green, blue)` and class `ST7789` with the exact positional
  constructor
  `ST7789(spi_id, baudrate, polarity, phase, sck_pin, mosi_pin, cs_pin,
  dc_pin, reset_pin, backlight_pin, width, height, x_offset, y_offset, bgr,
  inversion)`. Each `*_pin` value is an explicit, already-constructed
  `machine.Pin` object; the driver contains and converts no GPIO numbers. The
  module contains no board pin, bus, geometry,
  offset, colour-order, inversion, or clock default. The class MUST expose
  `fill(colour)`, `pixel(x, y, colour)`,
  `line(x0, y0, x1, y1, colour)`,
  `rect(x, y, width, height, colour)`,
  `fill_rect(x, y, width, height, colour)`,
  `text(value, x, y, colour)`, `show()`, `backlight(enabled)`, and
  `deinit()`. No rotation, PWM-brightness, touch, SD, IMU, or battery API is
  claimed. Scalar arguments and all six pin arguments MUST be validated before
  any GPIO is driven, SPI object is created, framebuffer is allocated, command
  is sent, or sleep occurs. Every pin argument MUST be an instance of the
  lazily imported `machine.Pin` type; merely callable objects MUST be rejected.
  — *(source: ADR-0023; verify: unit, API-structure; story: ADR-0023 increment)*
- **FR-TFT-4** — `rgb565` MUST accept integer red/green/blue channels in
  `0..255`, reject an out-of-range channel, and return
  `((red & 0xf8) << 8) | ((green & 0xfc) << 3) | (blue >> 3)`. Construction
  MUST own one `width × height × 2` RGB565 framebuffer, initialize the
  controller with the supplied colour order and inversion, and leave the
  active-high backlight off. Drawing methods MUST update only the framebuffer,
  clip to its visible geometry, and perform no SPI transfer until explicit
  `show()`. — *(source: ADR-0023; verify: unit, HIL; story: ADR-0023 increment)*
- **FR-TFT-5** — `show()` MUST program the inclusive ST7789 column/row window
  from the explicit offsets, issue RAM write, transmit framebuffer RGB565 in
  controller byte order using fixed internal chunks no larger than **4092
  bytes**, and leave chip select inactive. Any temporary byte-order mutation
  MUST be restored and chip select made inactive even when `SPI.write` raises.
  The framebuffer MUST remain valid for a retry. — *(source: ADR-0023; verify:
  unit, HIL; story: ADR-0023 increment)*
- **FR-TFT-6** — `backlight(enabled)` MUST accept a Boolean and drive the
  explicit backlight pin active-high. `deinit()` MUST be idempotent, turn the
  backlight off, leave chip select inactive, release the driver-owned SPI
  instance and framebuffer, and make subsequent drawing/transfer calls fail
  closed. A partial-construction failure MUST perform that same best-effort
  resource teardown. A `show()` failure MUST preserve the original exception,
  restore any temporarily swapped framebuffer bytes, force the backlight low
  and CS high on a best-effort basis, and retain the SPI instance, framebuffer,
  and open object state so a caller can retry the complete frame. Transfer
  failure MUST NOT deinitialize SPI or discard the framebuffer. — *(source:
  ADR-0023; verify: unit, HIL; story: ADR-0023 increment)*
- **FR-TFT-7** — The driver MUST be fresh clean-room MIT source carrying an
  SPDX MIT header. Vendor demo source or initialization code MUST NOT be copied
  or selected as a build input. Build tests MUST bind the canonical first-party
  source, prove the per-target manifest cardinality in FR-TFT-1, include it in
  source/license audit, and retain independent four-variant flash/headroom
  gates.
  Exact-board HIL on the connected ESP32-S3-LCD-1.47B MUST prove 16 MiB flash
  and 8 MiB Octal PSRAM, import before/after reboot, a bounded 172 × 320
  colour/text/corner pattern at offset `(34, 0)` using explicit
  `machine.SPI(1)` at 40 MHz, polarity 0 and phase 0, backlight off/on/off,
  cleanup, and PBLE/1 responsiveness during repeated refresh. The exact-board
  workload MUST NOT substitute SPI bus 2. Final qualification MUST be one
  exclusive private result bound to the exact candidate `firmware.bin` byte
  length, full-file SHA-256, and a non-personal session identifier. Before
  drawing, the runner MUST derive and record the exact ordered immutable span
  map from that merged image: `[0x00000, 0x09000)` for bootloader/padding plus
  partition table and `[0x10000, firmware.bin length)` for the factory
  application. The length MUST be greater than `0x10000` and no greater than
  the frozen factory-partition end `0x210000`; it MUST NOT extend into the VFS.
  Local inspection MUST read one stable regular-file snapshot, detect an
  in-place same-size metadata change, and reject unequal repeated reads. It
  MUST reject a candidate whose intervening NVS/PHY-init image bytes are not
  erased `0xff`. The board MUST hash the concatenation of those
  same live raw-flash spans and match the locally derived immutable-span
  SHA-256. Mutable NVS `[0x09000, 0x0f000)` and PHY-init
  `[0x0f000, 0x10000)` bytes MUST be excluded from live equality; local-file
  naming, mutable data, or the agent version is not candidate proof. The span
  map, immutable byte count/digest, full-file byte length/digest, and session
  MUST be admitted by the production validator and bound into the canonical
  hash chain. It MUST then contain one display exercise with a
  deliberate non-personal operator confirmation of the frozen visible pattern,
  using a separate finite per-observation operator deadline greater than zero
  and no greater than **900 seconds** (default **900 seconds**). Time spent
  awaiting that cancellable callback MUST NOT consume the residual
  BLE/RUN/device-operation budget. Before prompting, the runner MUST preserve
  a cleanup reserve equal to the lesser of two seconds and one quarter of that
  device budget for release or STOP cleanup. The
  RUN MUST remain active, the backlight lit, and the central connected while
  confirmation is pending; after the callback the runner MUST reject any
  queued terminal/dark/malformed state or lost link before sending the visual
  release. Operator timeout or refusal MUST send bounded STOP, drain the
  remote dark/resource-cleanup evidence, fail qualification, and create no
  result. Timeout-driven cancellation of the prompt MUST NOT be reported as an
  operator-originated process-control exception. Operator deadline values and
  elapsed durations are orchestration controls and MUST NOT alter the private
  result schema, hash chain, or privacy allowlist. Qualification is then
  followed by exactly three ordered acknowledged-reboot/fresh-VM import
  cycles. Each cycle MUST carry its one-based index and the SHA-256 of the
  preceding canonical stage record, beginning with the candidate-verified
  exercise record, so results from different sessions or candidates cannot be
  combined. After every acknowledged reboot the runner MUST prove the old link
  closed, allow the delivery grace to elapse, and retry reconnect plus the
  sentinel-absent import under one bounded deadline. Only a transactional BLE
  connection-establishment failure with no retained partial link, the dedicated
  stale-VM result, or a narrowly typed transport loss independently corroborated
  by a disconnected central during that reset transition is retryable. A
  connection setup whose cleanup returns while still connected is terminal.
  Caps, protocol, import, stderr, RUN-state, cleanup, connected-link I/O, and
  harness failures are terminal. Cancellation and process-control exceptions
  MUST retain their original type after best-effort cleanup. Every connect,
  setup cleanup, probe, disconnect, and retry delay MUST consume the same
  residual deadline; connection setup MUST reserve its cleanup budget inside
  the timeout supplied by that deadline, and there is no independent attempt
  ceiling.
  The complete result MUST pass a production validator that enforces exact
  keys, candidate/session equality, three contiguous cycles, passed nested
  stages, a positive stdout marker-byte count for every accepted RUN summary,
  every predecessor/record digest, and the terminal digest before the exclusive
  writer admits it. Evidence MUST omit the BLE address, device ID,
  label, raw INFO, sentinel value, source, and raw console output. The
  pre-reboot marker, stderr, or RUN-state failure MUST prevent transmission of
  `SOFT_REBOOT`. — *(source: ADR-0023;
  verify: structure, build, size, HIL; story: ADR-0023 increment)*

### 4.12 Exact-board boot splash (FR-SPLASH)

> **FROZEN v0.5.0 · 2026-08-01; HIL operator-deadline amendment 2026-08-02;
> exact-image and erased-install-default amendments 2026-08-03 (`[docs]`,
> [ADR-0024](../../decisions/0024-opt-in-waveshare-boot-splash.md),
> [ADR-0028](../../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md),
> [ADR-0029](../../decisions/0029-enable-waveshare-splash-after-erased-install.md)).** This
> section is a narrow exact-board exception to the otherwise inert display
> boundary. It adds no PBLE/1 byte, app-side board gate, automatic hardware
> detection, or runtime routing profile. Its separate provisioning profile is
> an explicit build/install boundary. Missing configuration remains
> electrically inert.

- **FR-SPLASH-1** — The `waveshare-esp32-s3-lcd-147b` image MUST freeze exactly
  one canonical,
  first-party MIT module named `pyble_waveshare_lcd147b` from
  its exact-board overlay. The lean `esp32-s3`, `esp32`, and `esp32-c3`
  manifests MUST NOT select it. Import MUST NOT import/configure
  `machine`, instantiate NVS, allocate a framebuffer, sleep, start a task,
  change GPIO/SPI/display state, or perform network I/O. It MUST NOT infer the
  board from chip, flash, PSRAM, MAC, device ID, label, advertising name, or
  panel traffic. Automatic boot MUST resolve the companion and every import it
  performs while rendering from frozen/built-in modules only; it MUST NOT load
  a same-named module or dependency from the mutable VFS or `/lib`. A VFS
  `pyble_waveshare_lcd147b.py` MUST be ignored on every target. — *(source:
  ADR-0024, ADR-0028; verify: unit, resolved manifest,
  build; story: ADR-0024/0028 increment)*
- **FR-SPLASH-2** — The complete public API MUST be
  `boot_splash_enabled()`, `enable_boot_splash()`,
  `disable_boot_splash()`, and `show_boot_splash()`, all with no arguments.
  `boot_splash_enabled()` MUST return true when NVS integer
  `pyble/lcd147splash` is exactly `1` and when reading an absent key raises the
  pinned ESP-IDF NVS-not-found code after an erased exact-board installation.
  Exact integer `0`, every other readable integer, NVS-open failures, and all
  other read failures MUST return false. Enable/disable MUST persist exact
  integer `1`/`0`, call
  `commit()`, and propagate a write/commit failure rather than report false
  success. Enable MUST perform no display I/O. After committing disabled,
  disable MUST make GPIO46 low on a best-effort basis. No PBLE/1 opcode,
  capability, board catalog, or MAC/label gate is added.
  `boot_splash_enabled()` MUST return Boolean; enable/disable MUST return
  `None`; `show_boot_splash()` MUST return Boolean as defined by FR-SPLASH-7.
  — *(source:
  ADR-0024; verify: unit, conformance-absence, HIL; story: ADR-0024 increment)*
- **FR-SPLASH-3** — The exact-board variant's frozen `_boot.py` MUST call
  `pble_ble.init_agent()` first, then attempt the optional splash,
  then start the existing runner/filesystem workers, console tee, and opt-in
  `/main.py` autorun in their frozen order. Missing module, disabled state,
  readiness timeout, NVS/display exception, or cleanup exception MUST be
  contained without boot output and MUST NOT prevent that ordinary lifecycle.
  The lean S3, classic, and C3 boot files MUST contain no companion import or
  readiness wait and MUST NOT touch a display GPIO.

  Before importing the optional companion, boot MUST copy the current
  `sys.path` contents, replace that same path list's contents with exactly
  `.frozen`, and keep the restriction in force through the complete guarded
  companion call so its lazy imports cannot fall back to VFS. One `finally`
  MUST restore the exact saved path contents before either worker starts, on
  success and on every import/readiness/render/cleanup or process-control
  failure. Lean ESP32-S3, classic ESP32, and ESP32-C3 MUST treat the absent
  frozen module as absent even when a VFS lookalike exists. This transaction
  runs before any
  MicroPython worker is launched; no second splash task is permitted.

  The companion MUST provide one boot-internal ordering seam named
  `_boot_evidence()`, absent from `__all__`, that returns the immutable tuple
  for the latest `_maybe_show_boot_splash(...)` invocation in the current VM.
  Each invocation MUST reset that tuple before recording `("guard-enter",)`;
  the evidence MUST remain RAM-local to that boot VM and MUST NOT be persisted,
  transmitted, logged, or printed. The exact disabled sequence MUST be:

  ```python
  (
      ("guard-enter",),
      ("enabled", False),
      ("return", False),
  )
  ```

  The exact successful enabled sequence MUST be:

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

  Other boot outcomes MAY end with `("fault",), ("return", False)` or a
  false readiness observation followed by `("return", False)`, but no event
  may contain exception text, display contents, BLE address, MAC/device ID,
  label, raw INFO, or another identity/raw field. Calling the public
  `show_boot_splash()` explicitly MUST neither reset nor append boot evidence.
  — *(source: ADR-0024; verify: unit/structure, build, HIL; story: ADR-0024
  increment)*
- **FR-SPLASH-4** — In the exact-board build only, `pble_ble` MUST expose one
  boot-internal bounded readiness helper. The lean S3, classic, and C3 builds
  MUST compile out its Event Group, state, and Python API. In the exact build
  its state MUST become ready only after `ble_gap_adv_start` returns
  success or while a connection is active; synchronization alone is not
  readiness. The state MUST be cleared when neither advertising nor a
  connection is active and on NimBLE reset; an already-active advertisement
  MUST remain ready across an `EALREADY` race. Connection/disconnection,
  advertising restart, and soft-reset persistence MUST remain race-safe.
  Event Group allocation failure MUST NOT fail agent initialization or BLE:
  readiness MUST remain false and every wait MUST return false. NimBLE reset
  MUST also clear any cached connection handle before readiness is recomputed.
  The enabled boot hook MUST wait no more than **1,500 ms**, release the
  MicroPython GIL while waiting,
  and skip display I/O when readiness is not reached. — *(source: ADR-0024;
  verify: native unit/structure, build, HIL; story: ADR-0024 increment)*
- **FR-SPLASH-5** — `show_boot_splash()` MUST use only the documented
  ESP32-S3-LCD-1.47B configuration: `machine.SPI(1)` at 40 MHz, polarity 0,
  phase 0, SCLK GPIO40, MOSI GPIO45, CS GPIO42, D/C GPIO41, reset GPIO39,
  active-high backlight GPIO46, visible geometry 172 × 320, offset `(34, 0)`,
  BGR order, and inversion. It MUST render one deterministic frame containing
  the PyBLE identity, exact visible text `BLE READY` and `pyble.dev/app`, and
  `Firmware v` followed by the dynamic frozen `pyble.__version__`. It MUST
  contain no BLE address, MAC/device ID, label, owner data, raw INFO, or
  runtime-downloaded value. `BLE READY` MUST mean a boot snapshot observed on
  a zero-wait readiness recheck immediately before the panel is lit, not a
  promise that retained pixels track later link state. — *(source: ADR-0024; verify: unit/golden frame,
  HIL; story: ADR-0024 increment)*
- **FR-SPLASH-6** — The QR payload MUST be exactly
  `https://pyble.dev/app`. The reviewed matrix MUST be QR Model 2, Version 2,
  byte mode, error correction M, mask 2, 25 × 25 modules, rendered black on a
  white four-module quiet zone at five pixels per module, producing a
  165 × 165 square at `(3, 52)`. In every row, bit 24 MUST represent X=0,
  bit 0 X=24, and the upper seven bits MUST be zero. The 25 unsigned 32-bit
  big-endian row masks MUST
  hash to SHA-256
  `6b00240151e36ff2fdbb1d556d6f3b0dd75f8fcce13683ea21033e8149687875`
  and decode independently to the exact HTTPS payload. Firmware MUST NOT ship
  a runtime QR encoder, redirect lookup, URL shortener, tracker, or remote QR
  dependency. — *(source: ADR-0024; verify: unit/independent decode, visual
  HIL; story: ADR-0024 increment)*
- **FR-SPLASH-7** — A successful splash MUST allocate only the existing
  172 × 320 RGB565 driver framebuffer, perform exactly one complete
  `show()` while the backlight remains low, then deinitialize the driver and
  collect garbage immediately so SPI and framebuffer are released. It MUST
  perform one zero-wait readiness recheck and assert GPIO46 high only when it
  succeeds, so the controller's retained frame becomes visible without a sleep
  or background task. `show_boot_splash()` MUST return true only after that
  retained-light action and false on final readiness loss. On every failure
  after pin construction it MUST
  best-effort leave CS high and backlight low, deinitialize any SPI/framebuffer,
  preserve the original explicit-call exception, and let the boot wrapper fail
  open. A later ordinary `pyble_st7789.ST7789` construction MUST be able to
  take over the display. — *(source: ADR-0024; verify: unit/fault injection,
  HIL; story: ADR-0024 increment)*
- **FR-SPLASH-8** — Exact-board qualification MUST bind to the same immutable
  candidate identity required by FR-TFT-7 and exercise both persisted states.
  Disabled reboot MUST prove normal BLE availability with no splash call;
  enabled reboot MUST prove the readiness-before-display order, BLE
  connection/HELLO while the retained frame is visible, a deliberate operator
  confirmation of layout/version, a real scan resolving to the exact HTTPS QR
  payload, safe disable, and subsequent ordinary TFT-driver construction and
  cleanup. Each required splash observation MUST use the same separate finite
  per-observation operator deadline defined by FR-TFT-7; its layout confirmation
  and real QR scan share one aggregate budget across any retry. Only measured
  callback-await time is excluded from the existing residual reset/reconnect/
  HELLO/probe deadline. The callback MUST run on the connected post-reset
  central before its first HELLO, and the runner MUST recheck that same link
  before continuing. Operator timeout, refusal, a stale/dark observation, or
  link loss MUST create no evidence. The current link MUST be closed using the
  preserved device cleanup reserve, after which the existing best-effort
  disable-and-darken transaction receives its own bounded device-operation
  deadline. After enablement may have persisted, any failed qualification MUST
  attempt the same disable-and-darken cleanup. If the initiating qualification
  failure and the cleanup failure are both ordinary exceptions, the runner
  MUST re-raise the exact initiating exception object; the cleanup failure MUST
  NOT replace it. Evidence MUST be bounded, exclusive, hash-linked, and omit
  the same personal/raw fields forbidden by FR-TFT-7. Host fakes MUST cover every
  pre-arm/failure path but cannot substitute for that operator and hardware
  record. The production website route MUST meet
  [website.md §3.1](../website.md#31-app-beta-distribution) before the
  QR-bearing firmware is publicly released. — *(source: ADR-0024; verify:
  structure, build, HIL, production smoke; story: ADR-0024 increment)*
- **FR-SPLASH-9** — Every fresh public finalization whose source-era frozen
  manifest includes `pyble_waveshare_lcd147b` (introduced in `0.5.0`, including
  a `0.5.0` prerelease) MUST consume exactly one exclusive private combined
  qualification result. The file MUST be bounded, canonical strict UTF-8 JSON,
  a stable regular non-symlink with one link and mode `0600`, and unchanged
  across repeated reads and the complete copy-on-write promotion. The release
  gate and the HIL writer MUST call the same pure, source-controlled strict
  validator; a weaker release-only reconstruction or an import of executable
  BLE orchestration is not an authority.

  The strict result MUST be `passed` for exact profile
  `waveshare-esp32-s3-lcd-147b`, model `ESP32-S3-LCD-1.47B`, and the release firmware
  version. It MUST bind the candidate profile's exact merged `firmware.bin`
  full length/SHA-256 and the recomputed immutable spans
  `[0x00000,0x09000)` plus `[0x10000,firmware.bin length)`, including exact
  immutable length/SHA-256. It MUST also validate the complete nested
  ADR-0023/0024 stage semantics, sanitized positive RUN-marker summaries,
  production `/app` evidence, all predecessor/record hashes, the terminal
  record, and the top result digest. A rehashed semantic mutation MUST fail.

  The pending `release.json` digest exists before real-board HIL and is the
  non-circular candidate selector. Public finalization MUST bind that digest
  to a derived, non-private HIL summary and MUST never copy the private result,
  session identifier, detailed observations, operator input, BLE identity, or
  raw data into the bundle. Source-era HIL is exact: releases before `0.5.0`
  retain `PYBLE_HIL_RECORDS_V2`/schema `2` with its original five-key object;
  the rejected shared-image engineering contract remains V3 and MUST NOT be
  published under the split source; v0.5.1 retains
  `PYBLE_HIL_RECORDS_V4`/schema `4`, while the v0.6.0 five-profile successor
  MUST use `PYBLE_HIL_RECORDS_V5`/schema `5`. Both retain the top-level
  `waveshare_lcd147b_qualification` extension. It is JSON `null` in a
  candidate and is replaced only by the validator-derived passed summary
  during finalization. V2 or V3 for a split release, V4 for an older release,
  missing/extra evidence, an already-filled candidate summary, a private-file
  change, or any binding mismatch MUST publish nothing. The promotion envelope
  remains exactly `HIL_REPORT.md`, `release.json`, and `SHA256SUMS`; the private
  result is never a release-tree path. — *(source: ADR-0024; verify: shared
  validator unit/parity, release finalization, retained-v0.4.2 validation,
  exact-board HIL; story: ADR-0024 increment)*

## 5. Non-functional requirements

### 5.1 Reliability (NFR-REL)

> **FROZEN for v1.0 (G0 · 2026-07-01 · `[docs]`).** Amend only via a `[docs]` commit before dependent code.

- **NFR-REL-1** — The agent (control plane) MUST stay alive and BLE-responsive even when user code crashes, loops, or exhausts its own resources. — *(source: PRD §13.1, §13.3; verify: HIL; story: F-06)*
- **NFR-REL-2** — A file transfer MUST be reported successful only after a whole-file CRC match; a partial transfer MUST be resumable from the verified offset, not restarted from zero by default. — *(source: PRD §13.1, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: HIL, conformance; story: F-10)*
- **NFR-REL-3** — File transfer MUST never silently corrupt or duplicate data across a dropped link. — *(source: PRD §13.1; verify: HIL, unit; story: F-10, F-11)*
- **NFR-REL-4** — Firmware builds MUST be **reproducible** from the pinned versions: the same commit + `versions.lock` MUST yield equivalent artifacts. — *(source: PRD §13.1, §10.11; verify: build; story: X-03)*
- **NFR-REL-5** — A multi-file upload MUST complete without dropping the connection (the v1.0 reliability acceptance). — *(source: PRD §4.1, §10.1, §7.1; verify: HIL; story: F-11)*

### 5.2 Performance (NFR-PERF)

- **NFR-PERF-1** — At MTU 247, BLE throughput MUST meet the frozen per-profile PUT and GET goodput floors in [§5.3](#53-footprint-gates-nfr-fp) on every exact profile included in a release. No profile, including C3 or RP2, may borrow a floor or passing result from another row. — *(source: PRD §13.4, §10.13; verify: HIL; story: F-11, F-13/14)*
- **NFR-PERF-2** — File transfer MUST use windowed chunks (`W` advertised in HELLO caps; reference-agent default window **`W=8`**, chunk sized to one MTU) with cumulative-offset ACKs. — *(source: PRD §13.4, [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core); verify: conformance, HIL; story: F-09; reference-agent W raised 4→8 2026-07-04 `[docs]`, no wire change)*
- **NFR-PERF-3** — Interactive console latency (`CONSOLE_INPUT` → echo, and `stdout` → event) MUST stay low enough to feel live. — *(source: PRD §13.4; verify: HIL; story: F-07)*
- **NFR-PERF-4** — The reset-to-advertisement **ceiling** MUST be the fixed product SLO in §5.3, while PUT/GET goodput **floors** MUST be derived from retained HIL baseline samples by the frozen formulas there; all three MUST then be enforced against the final candidate. — *(source: PRD §13.4, §10.13; ADR-0026; verify: HIL; story: F-13/14)*
- **NFR-PERF-5** — Before final-candidate PUT/GET timing begins, the exact
  transfer connection MUST complete the bounded link-tuning ladder and the HIL
  runner MUST retain candidate-bound, redacted link facts proving DLE, the
  profile-required PHY, and a successful connection-parameter update. A
  missing completion event, an exhausted rung, or an unsettled link MUST fail
  before throughput samples are collected; a favorable blind rerun MUST NOT
  substitute for these facts. — *(source: PRD §13.4, §10.13; ADR-0027;
  verify: unit, HIL; story: F-13/14)*

### 5.3 Footprint gates (NFR-FP)

> **FROZEN measurement contract (2026-07-30 · `[docs]`); exact-Waveshare
> operator-reset and BLE link-fact amendments (2026-08-13 · `[docs]`).** This contract freezes
> the release scope, metric meanings, workload, derivation formulas, and
> evidence schema before any threshold is selected. It does not invent or
> claim a numeric threshold.

The exact v0.4.2 public-beta bundle covers exactly the two enabled, not-yet-qualified profiles,
in this order: `esp32-4mb` and
`esp32-s3-n16r8`. Production-browser installation and interrupted-flash
recovery passed for both under the bounded exception in
[browser-flashing §10](browser-flashing.md#10-activation-and-rollback).
Each still MUST have a complete numeric policy and final-candidate HIL record
before the release may be called qualified. `esp32-c3-4mb` MUST NOT have a
threshold entry or HIL row in that historical policy.

The earlier v0.5.1 source-candidate qualification set was exactly, and in this order,
`esp32-4mb`, `esp32-s3-n16r8`, and
`waveshare-esp32-s3-lcd-147b`. Each MUST have a complete numeric policy and
final-candidate HIL record under that source-era contract. It completed no
exact-byte qualification and remains immutable historical evidence.

ADR-0033 replaces the prospective v0.6.0 scope with exactly, and in this
order, `esp32-4mb`, `esp32-s3-n16r8`,
`waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, and `rpi-pico2-w`. All five
require one fresh controlled baseline, an independent numeric policy row, and
passing final-candidate HIL. C3-G0…C3-G6 and Pico GP2 remain additional
release-blocking gates. No earlier-candidate evidence qualifies v0.6.0.

- **NFR-FP-FLASH** — The total shipped application image MUST not exceed its
  frozen per-profile ceiling and MUST leave at least the frozen headroom in the
  factory application partition. This total-image gate, not an unmeasurable
  “agent overhead” estimate, is the normative flash gate. A matched no-agent
  delta MAY be reported as supplemental evidence only. — *(source: PRD §10.13
  (FP-FLASH), §11.2; verify: size, build; story: F-13/14)*
- **NFR-FP-HEAP** — After connect + HELLO and after the frozen transfer
  workloads, Python GC headroom MUST meet its frozen per-profile floor.
  ESP-IDF profiles additionally enforce the three internal-heap floors; RP2
  forbids those inapplicable keys. Default-capability heap reported by the
  existing `free_mem` cap is diagnostic only and MUST NOT substitute for these
  gates, especially on a PSRAM-equipped S3. — *(source: PRD §10.13 (FP-HEAP);
  verify: HIL; story: F-13/14)*
- **NFR-FP-BOOT** — Controlled reset release → first fresh host scanner event
  containing the PyBLE service UUID MUST not exceed the fixed product ceiling.
  That callback proves a matching advertisement occurred but is not an on-air
  packet timestamp. A separate physical power-cycle advertising check MUST pass
  once per final profile record. — *(source: PRD §10.13 (FP-BOOT); ADR-0026;
  verify: HIL; story: F-12, F-13/14)*
- **NFR-FP-TPUT** — At an observed negotiated ATT MTU of exactly 247, committed
  PUT goodput and verified GET goodput MUST each meet the frozen per-profile
  floor on the same serial-attested, settled transfer connection, while the
  frozen reliability workload remains byte/CRC clean with no unexpected
  disconnect. — *(source: PRD §10.13 (FP-TPUT), ADR-0027; verify: HIL;
  story: F-11, F-13/14)*
- **NFR-FP-C3** — If the agent does not fit the ESP32-C3 flash/heap budget with usable user-code headroom, the **design** MUST change (e.g. native `USER_C_MODULE` hot paths per [§6](#6-constraints-con)), **not** the constraint. — *(source: PRD §10.13, §10.2; verify: size, HIL; story: F-13/14)*
- **NFR-FP-GATE** — Once frozen, the application-image ceiling/headroom floor
  MUST be enforced during build/candidate validation, and every runtime
  heap/boot/goodput/reliability threshold MUST be evaluated by the
  machine-readable final-candidate HIL validator. A crossing MUST fail the
  applicable gate. — *(source: PRD §10.13, §1B.3; verify: size, build, HIL;
  story: X-03, F-13/14)*
- **NFR-FP-CLOSE** — Every exact profile included in a qualified release is
  **release-blocking** until all of its thresholds are frozen and its
  hash-locked final-candidate evidence passes. For v0.6.0 this means exactly
  the five profiles above as one atomic set; C3 or Pico pending/failed blocks
  the whole qualified release. The exact v0.4.2 beta exception and the
  unqualified v0.5.1 candidate are historical and do not satisfy or waive this
  gate for v0.6.0. —
  *(source: PRD §10.12, §10.13, §7.1; verify: size, HIL; story: F-13/14)*

#### 5.3.1 Frozen metric definitions

All quantities are non-negative JSON integers; booleans are not integers.
Byte sizes are base-2 byte counts, durations use a monotonic host clock, and
goodput is integer bytes per second.

| Key | Frozen definition | Gate direction |
|---|---|---|
| `application_image_bytes` | Exact byte length of the bundled `application.bin`, whose authoritative build input is `micropython.bin`. It is not merged `firmware.bin`, ELF size, physical flash capacity, or an estimated agent-only delta. | `<= application_image_max_bytes` |
| `factory_partition_bytes` | Exact factory application-partition size parsed from the candidate partition table. | identity/arithmetic |
| `application_headroom_bytes` | `factory_partition_bytes - application_image_bytes`; a negative result is an unconditional failure. | `>= application_headroom_min_bytes` |
| `gc_free_bytes` | `gc.mem_free()` immediately after `gc.collect()` in a bounded PBLE RUN probe executed on the MicroPython VM thread. | `>= gc_free_min_bytes` |
| `gc_allocated_bytes` | `gc.mem_alloc()` from the same probe; retained as a diagnostic and not used as a substitute for `gc_free_bytes`. | report only |
| `idf_internal_free_bytes` | Sum of the free fields returned by `esp32.idf_heap_info(2052)`, where `2052 == MALLOC_CAP_INTERNAL \| MALLOC_CAP_8BIT`. | `>= idf_internal_free_min_bytes` |
| `idf_internal_largest_block_bytes` | Maximum largest-free-block field across those internal 8-bit heap regions. | `>= idf_internal_largest_block_min_bytes` |
| `idf_internal_minimum_free_bytes` | Sum of the minimum-free-ever fields across those regions. | `>= idf_internal_minimum_free_min_bytes` |
| `heap_default_free_bytes` | Existing HELLO/INFO `free_mem` value (`MALLOC_CAP_DEFAULT`); on S3 it may include PSRAM. | report only |
| `reset_to_service_advertisement_ms` | From controlled EN/reset release to the first fresh scanner event that contains the PyBLE service UUID, rounded up to whole milliseconds. | `<= reset_to_service_advertisement_max_ms` |
| `put_committed_goodput_bytes_per_second` | `floor(65536 * 10^9 / duration_ns)`, with time from immediately before sending `FILE_PUT_BEGIN` through the successful `FILE_PUT_END` response; only unique committed payload bytes are the numerator and `FILE_STAT` verification is outside the timer. | `>= put_committed_goodput_min_bytes_per_second` |
| `get_verified_goodput_bytes_per_second` | `floor(65536 * 10^9 / duration_ns)`, with time from immediately before sending `FILE_GET_BEGIN` through a valid `FILE_GET_END`; offsets MUST be contiguous and unique, and returned size, bytes, and whole-file CRC MUST match. | `>= get_verified_goodput_min_bytes_per_second` |

`transfer_link_facts` is a required object for the tenth controlled-reset
connection, which is also the connection used by all five round trips and the
reliability workload. Its exact shape is:

```text
{
  dle: {
    request_attempts: int,
    max_tx_octets: int,
    max_tx_time_us: int
  },
  phy: {
    required_2m: bool,
    request_attempts: int,
    updates: [{status: int, tx: int, rx: int}, ...],
    settled_tx: int,
    settled_rx: int
  },
  connection_parameters: {
    request_return_codes: [int, ...],
    updates: [{status: int, interval_units: int}, ...],
    settled_interval_units: int
  },
  tx_mbuf_starve_count: int
}
```

All integers are non-negative JSON integers and every list is ordered as
observed. `dle.request_attempts` is `1..4`, `max_tx_octets >= 244`, and
`max_tx_time_us > 0`. On both `esp32-s3-n16r8` and
`waveshare-esp32-s3-lcd-147b`, `phy.required_2m` is true,
`request_attempts` is `1..4`, at least one update is retained, and the settled
TX/RX values are exactly `2`/`2`. On classic `esp32-4mb`, the 2M rung is
compiled out: `required_2m` is false, `request_attempts` is zero, `updates` is
empty, and both settled values are zero. The connection-parameter request list
has `1..3` entries, the update list is non-empty, its final item has status
zero, and `settled_interval_units` equals that final item's interval and lies
in `12..24` (1.25 ms units). `tx_mbuf_starve_count` is captured from the same
session's disconnect line and is report-only; it does not replace the
goodput, integrity, or reliability gates.

For `esp32-4mb`, `esp32-s3-n16r8`, and `esp32-c3-4mb`, "captured from the
same session's disconnect line" retains the strict ADR-0027 UART meaning. The
exact Waveshare image instead compiles the qualification-only
`pble_ble._oi1_link_facts()` getter specified below. The getter is absent from
every other image and adds no opcode, characteristic, INFO/HELLO field, or
dynamic capability.

The Waveshare getter returns one atomic, non-consuming object with exactly the
keys `active` and `last_ended`. Each value is either JSON null or a record with
exactly these keys:

```text
{
  epoch: int,
  final: bool,
  settled: bool,
  overflow: bool,
  facts: transfer_link_facts
}
```

Every successful GAP connection in one boot receives an epoch in
`1..18446744073709551615`; it is strictly monotonic and MUST NOT wrap. An
epoch-exhausted or internally inconsistent getter call raises and therefore
cannot produce evidence. The active record has `final: false`. On disconnect,
firmware atomically copies it to `last_ended` with `final: true` before another
successful connection may receive the exact successor epoch. That ended copy
is immutable. `settled` means the same profile-exact DLE/PHY/connection-
parameter conditions above have completed. `overflow` latches true if a
bounded record cannot retain every observed item.

Both record kinds always carry the exact `transfer_link_facts` shape. Until a
fact exists, its scalar value is zero and its list is empty; such an incomplete
record has `settled: false` and cannot authorize throughput. PHY updates and
connection-parameter updates each have a hard capacity of eight ordered
items, and connection-parameter request return codes have capacity three.
Exceeding a capacity MUST retain only a bounded prefix and latch
`overflow: true`; the host MUST reject the whole record. All fact integers are
non-negative. Apart from the structural booleans and null record slots, the
returned values are numeric facts only. Firmware MUST NOT retain or return a
BLE address, connection handle, device identifier, label, filesystem path,
user source, arbitrary console text, or other user data.

DLE completion attribution MUST be independent of the numeric controller
handle and all earlier connections. For DATA_LEN_CHG, firmware MUST take one
snapshot of its cached live PBLE connection handle before confirming or
recording DLE and MUST use that snapshot for the handle-bound active-session
mutation. NONE or a snapshot stale against the retained active session fails
closed and cannot contribute a DLE fact; the record remains unsettled.
Firmware MUST NOT use `event->data_len_chg.conn_handle`, because the pinned
ESP-IDF real-HCI conversion does not populate that member even though callback
dispatch is connection-scoped. Disconnect invalidation and epoch/handle checks
remain mandatory. Neither an ESP-IDF patch nor a reduced maximum-connection
setting may substitute for this contract.

The heap probe MUST keep these measurements out of HELLO/INFO capabilities.
It uses existing standard MicroPython APIs and therefore adds no dynamic PBLE/1
capability and no INFO/HELLO equivalence ambiguity.

#### 5.3.2 Frozen qualification workload

For each exact profile and one immutable firmware/manifest candidate:

1. Perform **10** controlled reset samples. Start a service-UUID-filtered BLE
   scan, establish a complete consecutive **1,000 ms** interval with EN/reset
   asserted and no matching callback, release reset, and record the first fresh
   matching advertisement. Both acquisition of that quiet interval and
   post-release discovery are independently bounded at **15,000 ms**; a timeout
   is a gate failure, not a latency sample. Connect and complete HELLO after
   each successful sample.

   Scanner callbacks received before reset assertion is confirmed are discovery
   input only; they are not evidence about the quiet interval. Immediately after
   the synchronous `assert_reset()` seam returns, the harness MUST call the
   active watcher's quiet-window seam. That call MUST keep the scanner active,
   atomically discard every earlier retained matching timestamp and completion
   signal, and establish a new callback epoch. CoreBluetooth may deliver a
   callback queued before the operator-confirmed boundary after that boundary;
   such a callback restarts the quiet window instead of proving that the board
   remained powered. Every matching callback while reset is held MUST restart
   the required consecutive 1,000 ms window. Failure to obtain one complete
   window within 15,000 ms is a gate failure, so a target that continues to
   advertise cannot pass. A callback preceding the completed quiet window MUST
   neither become the measured post-release advertisement nor shorten the
   reset hold.

   Immediately after the release seam returns, the watcher MUST atomically
   discard the held-reset callback epoch and take the monotonic release-proxy
   timestamp before the event loop can process another scanner callback. The
   numeric sample ends at the first matching callback in that new post-release
   epoch. This also prevents an advertisement queued while the operator was
   reconnecting power or acknowledging the Waveshare release prompt from being
   misrepresented as a post-confirmation measurement.

   The exact `waveshare-esp32-s3-lcd-147b` profile has one bounded reset seam:
   its native USB serial RTS is not evidence that EN/reset was asserted, so
   every baseline and final-candidate sample MUST use the physical RESET button
   and the operator-confirmed sequence below. The scanner MUST already be
   active before the first prompt. In JSON string notation, the prompts,
   including capitalization, punctuation, and their final ASCII spaces, are
   exactly:

   ```text
   "Press and hold RESET on the Waveshare ESP32-S3-LCD-1.47B, keep holding it, then press Enter: "
   "Release RESET now, then press Enter immediately: "
   ```

   After the first prompt returns, the harness MUST establish the common
   bounded consecutive quiet window while RESET remains held. The operator MUST release
   RESET before acknowledging the second prompt. The numeric sample begins at
   the host monotonic timestamp taken immediately after that acknowledgement
   returns and ends at the first later matching scanner callback; a callback
   at or before that start boundary is invalid rather than a latency sample.
   This is the profile's explicit operator-confirmed release proxy because the
   physical switch has no host-readable edge. It retains the same 15,000 ms
   discovery timeout and fixed 3,000 ms gate. Its native USB serial endpoint is
   neither reset evidence nor a link-fact transport. The Waveshare harness MUST
   NOT open, reopen, read, or require a serial endpoint, and MUST NOT toggle
   native USB RTS or DTR. Its private link-fact evidence travels over the
   already connected PBLE/1 session under the qualification-only getter
   contract above; this transport begins only after the measured advertisement
   and therefore cannot enter the numeric reset timer.

   The operator seam is forbidden for `esp32-4mb`, `esp32-s3-n16r8`, and
   `esp32-c3-4mb`; those ESP profiles retain the explicit UART RTS-to-EN
   controller and release-edge timing. Pico retains its separately specified
   power-disconnect seam. The one final physical power-cycle check in step 7
   remains separate and unchanged for every profile.
2. Record one `heap_default_free_bytes` diagnostic and one gated heap snapshot
   (`gc_free_bytes`, `gc_allocated_bytes`, and the three internal-heap
   quantities) after each of those 10 HELLO exchanges.
3. For `esp32-4mb`, `esp32-s3-n16r8`, and `esp32-c3-4mb`, after disconnecting
   each of the first nine sessions, poll the runner's private serial input for
   at most **2,000 ms** until exactly one complete, parser-owned `link tune
   session end` record for that just-ended session is observed. Discard every
   byte, including the terminal count; none is evidence. A missing or duplicate
   terminal record is a gate failure. Clear all residual private serial state
   before the next controlled reset so a delayed terminal record cannot enter
   the following session's parser. Before releasing the tenth controlled reset,
   clear that same private serial-input buffer and begin link-fact capture.

   Waveshare instead makes one diagnostic reconnect after each of the first
   nine measured disconnects. `PbleCentral.connect` has its existing
   **20,000 ms** deadline; diagnostic HELLO and the nonce-bound getter RUN each
   have separate **2,000 ms** and **8,000 ms** deadlines, respectively. The
   getter-RUN bound is one absolute transport ceiling over command writes, RUN
   response, bounded CONSOLE_DATA pacing, and terminal RUN_STATE. This query
   uses the exact `pair` projection: the one atomic native
   `{active,last_ended}` copy is serialized unchanged. Its
   `last_ended` record MUST be final with a positive epoch, and its active
   record MUST be the exact non-wrapping successor. An absent, stale,
   non-successor, malformed, or overflowed boundary fails. The runner then
   disconnects the diagnostic session and discards both records. It retains no
   numeric fact from those nine sessions. Either record MAY be structurally
   valid but unsettled: the measured session ends immediately after HELLO and
   its heap probe, and the diagnostic successor has only just connected.
   Unsettled first-nine records cannot authorize throughput and MUST NOT be
   promoted into `transfer_link_facts`.

   On the tenth measured connection, after HELLO, every ESP path waits at most
   **5,000 ms** for the profile-exact DLE/PHY/connection-parameter facts in
   §5.3.1 to settle. No PUT/GET timer may start before that succeeds.
   This remains an independent outer settlement ceiling for Waveshare: each
   poll uses the exact `active` projection and receives
   `min(5,000 ms, remaining settlement budget)`. That projection calls the
   getter once, then serializes exactly
   `{active: copy.active, last_ended: null}`; a non-null `last_ended` fails. A
   snapshot returned at or after the outer deadline fails. Waveshare retains
   the active epoch only after
   `final: false`, `settled: true`, `overflow: false`, and exact fact
   validation; the UART profiles retain their existing parser. Arbitrary or
   identifying serial or console text MUST be discarded rather than retained.
4. On that same settled connection, which reports HELLO `mtu=247`, `window=8`,
   and `chunk=229`, run **5** PUT+GET round trips of exactly **65,536 bytes**
   with no chunk or window override. When the central backend exposes its
   negotiated ATT MTU, it MUST agree with the HELLO value; an unknown backend
   value MUST NOT be manufactured as evidence. Record one gated heap snapshot
   after each round trip.
5. The deterministic payload for zero-based sample `s` is the first 65,536
   bytes of concatenated SHA-256 blocks
   `SHA256("PyBLE-OI1-v1\\0" || UTF8(profile_id) || "\\0" || u32le(s) ||
   u32le(block_index))`, with `block_index` starting at zero.
6. Separately run the reliability workload once: **20 files × 16,384 bytes =
   327,680 bytes**. All 20 files MUST complete and match byte-for-byte, size,
   and CRC; unexpected disconnects, corruption, and failed statuses MUST all be
   zero. Retransmitted chunks/bytes and rewinds MAY be non-zero but MUST be
   counted. Record one final gated heap snapshot after this workload.

   Before the Waveshare transfer connection disconnects, run one more bounded
   **5,000 ms** `active` getter probe and require the same active epoch, a
   settled non-final, non-overflowed record, and the same validated ladder
   facts; its provisional starvation count is not evidence. Then disconnect,
   make one diagnostic reconnect, and query again. `last_ended` MUST be final
   and non-overflowed
   with the retained transfer epoch, while the diagnostic active epoch MUST be
   its exact non-wrapping successor. Derive the public `transfer_link_facts`
   solely from that immutable ended record, including the final starvation
   count, then disconnect the diagnostic session. The diagnostic BLE
   connect retains the existing **20,000 ms** bound; diagnostic HELLO and each
   final `pair` getter RUN/query have their own **2,000 ms** and **8,000 ms**
   bounds, respectively. The harness MUST NOT compress the whole reconnect
   transaction into either shorter deadline.

   The other ESP profiles instead disconnect and wait at most **2,000 ms** for
   the same UART session's final TX-mbuf-starvation fact before sealing
   `transfer_link_facts`. Pico retains its §5.3.5 observation path.
7. Perform one real physical power-cycle check and require a fresh PyBLE
   service advertisement. This is a pass/fail safety check; human timing is
   not used as a numeric latency sample.

Thus each heap floor is derived from exactly **16** snapshots: 10 post-HELLO,
5 post-round-trip, and 1 post-reliability. The numeric qualification is a
controlled-hard-reset proxy for cold boot because it provides an external
release-to-host-discovery boundary; the physical power-cycle check prevents
that proxy from replacing real power-on behaviour.

#### 5.3.3 Baseline, threshold derivation, and policy

The derivation algorithm is frozen before measurement. Define
`floor_q(x) = q * floor(x/q)` and `ceil_q(x) = q * ceil(x/q)`.

- `application_image_max_bytes` is the exact application byte count from two
  clean, independently retained build roots; the two application images MUST
  first be byte-identical.
- `application_headroom_min_bytes` is the exact corresponding
  `factory_partition_bytes - application_image_bytes`.
- Each GC/internal-heap floor is `floor_1024(min(all 16 samples))`.
- `reset_to_service_advertisement_max_ms` is the fixed product SLO `3,000` for
  every qualified profile. The clock ends at a host scanner callback, whose
  acquisition and delivery tail cannot be separated from firmware boot by this
  measurement. The ten baseline samples therefore characterize the system but
  do not fit this user-visible ceiling.
- Each PUT/GET goodput floor is
  `floor_100(floor(95 * min(the 5 samples) / 100))`. The exact integer 5%
  allowance is applied before outward quantization because each whole-transfer
  duration includes host scheduling and many BLE acknowledgement windows.

Application image/headroom remain exact and heap retains only its 1,024-byte
outward quantization. Reset detection uses exactly the ADR-0026 product SLO;
there is no reset baseline arithmetic, per-profile fitting, discarded sample,
or candidate-specific allowance. Goodput receives exactly the integer 5%
allowance before at most 99 bytes/s of outward quantization. No result from
another profile may enter a baseline-derived threshold. Integrity counts,
retransmit/rewind counts, disconnect counts, sample counts, and the physical
power-cycle check receive no allowance.

Raw baseline samples and environment metadata MUST be retained as redacted,
canonical JSON at
`docs/validation/firmware/oi1/<40-hex-source-commit>.json`.
Canonical bytes are UTF-8 JSON with lexicographically sorted object keys,
two-space indentation, LF line endings, no trailing whitespace, and one final
LF; arrays retain the normative order below.
That baseline object has exactly `schema_version` (integer `1`),
`measurement_contract` (string `"oi1-pre-v1-v1"`), `source_commit` (the same
40 lowercase hex used in its filename), `firmware_version`, `created_at` (UTC
RFC3339), `profile_order` (the exact three-profile order), and `profiles`.
Each of its three profile objects has exactly:

```text
profile_id
target
board_manufacturer
board_model
module_marking
device_flash_capacity_bytes
device_psram_capacity_bytes
firmware_sha256
manifest_sha256
environment
oi1_build
oi1_observation
```

`environment` has exactly `desktop_os`, `ble_backend`, `ble_adapter`, and
`python_version`, all non-empty strings. `oi1_build` and completed
`oi1_observation` use the exact objects in
[browser-flashing.md §9.2](browser-flashing.md#9-automated-and-hil-acceptance).
The baseline is engineering derivation evidence, not a release HIL record: it
has no candidate release digest, operator approval, installer/recovery check,
or public-release status.

Retained baseline files are immutable history. A controlled refresh MUST add
a new source-commit-scoped file and MUST NOT edit or remove earlier evidence.
The active policy pointer and all three profile threshold objects then change
as one unit; profiles or successful samples from different baselines MUST NOT
be mixed. For a v0.5.x source release, the active baseline firmware release
core MUST be at least `0.5.0` and MUST NOT be newer than the source release
core. The retained pre-`0.5.0` release contract keeps its historical baseline
semantics. The v0.6.0 successor instead follows §5.3.5. These are source-era
rules, not a requirement to reinterpret an older baseline.

The baseline source commit identifies the pre-policy source and immutable
measurement inputs. Evidence and policy commits necessarily produce a later
final-candidate source identity. The v0.5.x final candidate MUST therefore be
rebuilt after the refresh, and the same three profiles MUST pass verify-mode
HIL; the engineering baseline observations MUST NOT be reused as release
approval. The corresponding v0.6.0 five-profile rule is frozen in §5.3.5.

For a v0.5.x source candidate, `firmware/qualification/oi1-gates.json` MUST
then contain exactly:

- `schema_version: 2`;
- `qualification_scope: "pre-v1"`;
- `profile_order: ["esp32-4mb", "esp32-s3-n16r8",
  "waveshare-esp32-s3-lcd-147b"]`;
- `deferred_profiles: ["esp32-c3-4mb"]`;
- `workload`, with the exact constants and payload generator from §5.3.2;
- `derivation`, naming the exact algorithms and quantization units above;
- `baseline_evidence`, with the repository-relative path and exact lowercase
  SHA-256 of the canonical baseline JSON; and
- `profiles`, in `profile_order`, each containing exact `profile_id`, build
  `target`, and a `thresholds` object with the nine gate keys defined above:
  application maximum, application headroom minimum, four heap minima,
  reset-to-advertisement maximum, and PUT/GET goodput minima.

The policy validator MUST require all nine numeric keys. All threshold values
MUST be positive integers. The policy MUST contain no C3 threshold object. A
final candidate is evaluated against this committed policy; the engineering
baseline derives the policy but does not itself approve a release.

For source releases at or after `0.5.0`, the exact derivation identifiers are
`floor-min-1024-v1`, `fixed-product-slo-3000-v3`, and
`floor-95pct-min-100-v2` for heap, reset, and goodput respectively. The
superseded private-candidate reset identifier
`ceil-max-plus-300-10-v2` MUST NOT qualify a public `0.5.0` release. A retained
source release before `0.5.0` MUST continue to validate against its historical
`floor-min-1024-v1`, `ceil-max-10-v1`, and `floor-min-100-v1` identifiers and
formulas; the amendment MUST NOT reinterpret an already-published release.

#### 5.3.4 Candidate-bound evidence

The release HIL document MUST use the exact source-era V2/V4/V5 contract in
[browser-flashing.md §9](browser-flashing.md#9-automated-and-hil-acceptance).
The policy bytes, baseline-evidence digest, candidate identity, per-profile
build measurements, raw sample arrays, environment, and raw-log digest MUST be
machine-verifiable. Candidate generation freezes the policy and build
measurements; finalization may add HIL observations and operator sign-off but
MUST NOT change those frozen fields. A changed firmware, manifest, policy, or
candidate identity invalidates the affected evidence.

#### 5.3.5 v0.6.0 five-profile successor policy and evidence

ADR-0033 adds a successor contract without reinterpreting §§5.3.1–5.3.4.
Those sections remain authoritative for the historical V2/V4 source eras;
v0.6.0 uses the same workload, timer boundaries, derivation arithmetic,
reliability totals, immutable-baseline rules, and exact-byte candidate binding
with the target discrimination below.

The controlled v0.6.0 baseline has schema version `2`, measurement contract
`"oi1-five-profile-v1"`, and exactly `schema_version`,
`measurement_contract`, `source_commit`, `firmware_version`, `created_at`,
`profile_order`, and `profiles`. `profile_order` is exactly:

```json
[
  "esp32-4mb",
  "esp32-s3-n16r8",
  "waveshare-esp32-s3-lcd-147b",
  "esp32-c3-4mb",
  "rpi-pico2-w"
]
```

The successor `firmware/qualification/oi1-gates.json` has exactly:

- `schema_version: 3`;
- `qualification_scope: "v0.6.0-five-profile"`;
- the exact `profile_order` above;
- `workload`, retaining every §5.3.2 constant except that the PUT window is
  profile-specific;
- `derivation`, retaining the exact application/image, headroom,
  `floor-min-1024-v1`, `fixed-product-slo-3000-v3`, and
  `floor-95pct-min-100-v2` algorithms;
- `baseline_evidence`, binding the canonical schema-2 baseline path and
  SHA-256; and
- five `profiles` entries in order, each with exactly `profile_id`, `target`,
  `resource_kind`, `transport`, and `thresholds`.

The first four rows use `resource_kind: "esp-idf"`. Their build facts,
five-field heap snapshots, NimBLE `transfer_link_facts`, and exact nine
threshold keys remain those in §§5.3.1–5.3.3. C3 uses the same shape but has
its own measurements and thresholds; C3-G4 is the baseline input, never a
substitute for final-candidate verify mode.

The Pico row uses `resource_kind: "rp2"`. Its build object has exactly:

```text
firmware_bin_bytes
firmware_image_limit_bytes
firmware_image_headroom_bytes
```

The limit is exactly `1572864`; headroom is limit minus the exact raw
`firmware.bin` length, must be non-negative, and is independently checked
against the raw image bound to the released UF2 provenance. Its threshold
object has exactly:

```text
firmware_bin_max_bytes
firmware_image_headroom_min_bytes
gc_free_min_bytes
reset_to_service_advertisement_max_ms
put_committed_goodput_min_bytes_per_second
get_verified_goodput_min_bytes_per_second
```

Each Pico heap snapshot has exactly `gc_free_bytes` and
`gc_allocated_bytes`; ESP-IDF heap fields are forbidden. Its transport object
has exactly `required_att_mtu`, `required_put_window`,
`required_chunk_bytes`, and `link_facts_kind`, with values `247`, `4`, `229`,
and `"btstack-observed-v1"`. Each ESP transport object has the same keys with
window `8` and `link_facts_kind: "nimble-settled-v1"`. The Pico observation's
target-specific transport facts contain exactly `ble_host` (`"btstack"`),
`observed_att_mtu` (`247`), `observed_window` (`4`),
`observed_chunk_bytes` (`229`), and `console_tx_budget_ms` (`103`). For Pico,
that last name denotes the maximum empty-to-full token-bucket refill horizon
in milliseconds, derived exactly as
`ceil(TX_CAPACITY / TX_REFILL_PER_MS) = ceil(2048 / 20) = 103`; it is not the
ESP per-Notify wait budget. ESP DLE/PHY/session-end fields are forbidden. The
bench MUST import the exact positive runtime constants, recheck the ceiling
formula, and reject an operator-selectable or unequal numeric replacement.

Every V5 profile record additionally binds both real-app results. `app_hil`
has exactly `ipad` and `android`; each entry has exactly non-empty
`app_version`, `app_build`, and `os_major`, plus `status: "passed"` in a
completed record. Both are pending in a candidate, and neither platform can
stand in for the other. C3-G0…C3-G6 and Pico GP2 are separately derived
profile-gate summaries as frozen in
[browser-flashing.md §9.5](browser-flashing.md#95-pyble_hil_records_v5-five-profile-heterogeneous-release).
No numeric value or passed result is established by this specification.

### 5.4 Software safety (NFR-SAFE)

This is software-level safety of the IDE/agent, **not** hardware/actuator safety (out of scope, [§6](#6-constraints-con)).

- **NFR-SAFE-1** — `STOP` MUST be **authoritative**: it MUST promptly interrupt the runner, tear down cleanly, and report `RUN_STATE`. — *(source: PRD §13.3, §8.3, [protocol.md §6](../protocol.md#6-run--stop--console); verify: HIL; story: F-06)*
- **NFR-SAFE-2** — User code MUST NOT be able to wedge BLE or the agent: the runner runs on a task separate from the BLE/agent task so the link and `STOP` remain serviceable under any user-code behaviour. — *(source: PRD §1A.3 rejection 5, §13.3, §10.2; verify: HIL; story: F-06)*
- **NFR-SAFE-3** — Cold boot MUST be safe: advertise and wait, never auto-run `main.py` unless explicitly enabled (FR-BOOT-2/3). — *(source: PRD §13.3, §10.5; verify: HIL; story: F-12)*
- **NFR-SAFE-4** — The agent MUST NOT contain or imply any hardware-output, calibration, or other physical-safety guard; physical safety belongs to the user's own program. — *(source: PRD §13.3, §11.3, §4.3; verify: unit (structure review); story: F-01)*

### 5.5 Offline-first (NFR-OFF)

- **NFR-OFF-1** — The agent MUST function with no network connection of any kind; it MUST NOT require Wi-Fi onboarding or any server round-trip to operate. — *(source: PRD §13.5, §1A.3 rejection 2, §1A.3 rejection 8; verify: HIL; story: F-01)*
- **NFR-OFF-2** — The agent MUST require no account, cloud sync, or telemetry to edit, run, or manage code on a board. — *(source: PRD §13.5, §14.2, §15.1; verify: HIL, unit; story: F-01)*

### 5.6 Maintainability & reproducibility (NFR-MAINT)

> **FROZEN for v1.0 (G0 · 2026-07-01 · `[docs]`).** NFR-MAINT-2's six-module layout is frozen; the source-tree layout that realizes it is frozen in [TDD.md §10.5](TDD.md#105-source-layout-frozen).

- **NFR-MAINT-1** — Within the initial ESP32 port, the shared agent core MUST
  contain no per-chip product logic; chip differences MUST live in the Layer-2
  board overlay. Across MicroPython ports, platform-specific BLE, runtime,
  storage, identity, and build code MUST remain behind the broader target
  adapter boundary. — *(source: PRD §10.1, §10.2,
  [firmware.md §4](../firmware.md#4-chip-targets-and-release-profiles); verify: build, unit; story:
  F-13/14)*
- **NFR-MAINT-2** — The agent MUST be organized as the six single-responsibility modules `pyble_ble` / `pyble_proto` / `pyble_runner` / `pyble_fs` / `pyble_console` / `pyble_info`. — *(source: PRD §10.3, [firmware.md §3](../firmware.md#3-modules); verify: unit (structure); story: F-01…F-09)*
- **NFR-MAINT-3** — Moving hot paths from frozen-Python to a native `USER_C_MODULE` MUST NOT change the PBLE/1 wire contract. — *(source: PRD §10.2, §16.2, [firmware.md §2](../firmware.md#2-agent-base-native-vs-frozen); verify: conformance; story: F-13/14)*
- **NFR-MAINT-4** — Every PyBLE firmware source file MUST carry the `SPDX-License-Identifier: MIT` header. — *(source: PRD §15.1, [AGENTS.md](../../../AGENTS.md); verify: build (lint); story: X-01)*

## 6. Constraints (CON)

> **FROZEN for v1.0 (G0 · 2026-07-01; display amendments 2026-08-01 ·
> `[docs]`).** All CON-1…13 are clean-room/build/carve-out constraints that
> inherit no PBLE/1 opcode/UUID/status number. ADR-0023 admits the explicit
> inert Layer-4 library in FR-TFT. ADR-0024/ADR-0029 admit only the named
> companion and fail-open boot hook in FR-SPLASH; it does not permit Layer-3
> display control, automatic board detection, or a stored/transmitted routing
> profile. Amend only via a `[docs]` commit before dependent code.

- **CON-1** — Upstream MicroPython MUST be consumed as a **pinned submodule** and MUST NEVER be edited in place. — *(source: PRD §1A.3 rejection 4, §10.9, §10.10, [`firmware/upstream/README.md`](../../../firmware/upstream/README.md); verify: build; story: X-03)*
- **CON-2** — PyBLE MUST NOT fork MicroPython; it builds an agent **around** upstream. — *(source: PRD §1A.3 rejection 4, §4.3, §6.2; verify: build; story: X-03)*
- **CON-3** — The workspace and any future PyBLE package format MUST be **`.py` source only**; no `.mpy`/`.pyc` in the workspace or in transfer. — *(source: PRD §1A.3 rejection 6, §10.14, §4.3; verify: unit, conformance; story: F-09)*
- **CON-4** — Per-chip configuration MUST live **only** in the Layer-2 board overlay, copied into the upstream `ports/esp32/boards/` tree at build prep so the submodule stays pristine. — *(source: PRD §10.2, §10.11; verify: build; story: X-03, F-13/14)*
- **CON-5** — The initial ESP32 firmware MUST use **NimBLE** on all three v1
  targets; Bluedroid MUST NOT be built in. A future platform port MAY use
  another conforming BLE peripheral stack. — *(source: PRD §10.1, §16.2;
  verify: build; story: F-01)*
- **CON-6** — All firmware source, including an optional frozen user runtime,
  MUST be **MIT / clean-room**: it MUST contain no closed-source wire protocol,
  opcodes, proprietary UUIDs/advertising prefixes, copied vendor demo code,
  board/routing profiles, or lab-domain/calibration code; the no-leak,
  provenance, SPDX, and license gates MUST pass. — *(source: PRD §1A.1,
  §1A.2, §16.3, ADR-0023, ADR-0024; verify: build (no-leak/license gate); story:
  X-02)*
- **CON-7** — The firmware MUST NOT impose, store, or transmit a generalized
  board routing/pin profile and MUST NOT gate by MAC or board identity. The
  module named for the exact board in FR-SPLASH MAY contain only
  that board's published display wiring for its own cosmetic frame; it MUST
  NOT expose a routing lookup, mediate user-code pins, detect/select hardware,
  or change the app/agent capability model. — *(source: PRD §1A.3 rejection
  3, §11.1, §11.3, [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware),
  ADR-0024; verify: unit (structure); story: F-01/ADR-0024 increment)*
- **CON-8** — Layer 3 MUST NOT contain any GPIO-routing,
  hardware-output-safety, display-control/branding, calibration, or
  board-profile module. An image MAY freeze a generic Layer-4 user library
  only when a separately frozen `FR-*` contract (FR-TFT) keeps it
  inert at import, free of board pin/default tables, explicitly constructed by
  user code, and outside the agent/capability surface. One exact-board
  companion MAY own named-board pins only under FR-SPLASH when it is inert at
  import, factory-enabled only after erase in the exact profile, persistently
  disableable, bounded after actual BLE
  readiness, and fail-open; this remains Layer 2/4 glue, never a seventh agent
  module. — *(source: PRD §10.3, §11.3, §4.3, ADR-0023, ADR-0024;
  verify: unit (structure); story: F-01/ADR-0024 increment)*
- **CON-9** — Hardware primitives MUST be exposed through standard
  MicroPython (`machine`, `framebuf`, `os`, etc.), and the agent MUST NOT
  mediate or abstract GPIO. A frozen Layer-4 helper MAY compose those
  primitives only after explicit construction by user code; it MUST NOT add a
  PBLE/1 hardware abstraction, hidden routing, automatic board selection, or
  boot-time output, except the explicitly persisted, exact-board,
  readiness-gated and fail-open frame frozen by FR-SPLASH. — *(source: PRD §11.3,
  [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware),
  ADR-0023, ADR-0024; verify: unit (structure); story: F-01/ADR-0024 increment)*
- **CON-10** — The agent (Layer 3) MUST NOT be editable or replaceable by user code (Layer 4). — *(source: PRD §10.2, §10.4, §14.1; verify: conformance, unit; story: F-09)*
- **CON-11** — A **single** MicroPython + ESP-IDF pin (from `versions.lock`) MUST drive all three chip targets. — *(source: PRD §1A.4, §10.9, §10.11; verify: build; story: X-03)*
- **CON-12** — The default upstream patch count MUST be **zero**; any unavoidable patch MUST be isolated under `firmware/patches/micropython-<tag>/` with a written reason, applied only at build prep, and re-reviewed for retirement at every upgrade. — *(source: PRD §1A.3 rejection 4, §10.10, [firmware.md §6](../firmware.md#6-build--distribution); verify: build; story: X-03)*
- **CON-13** — The identify-LED configuration MUST be **one optional config integer** (a single GPIO + active level) owned by the agent for the IDENTIFY blink only. It is explicitly **NOT** a routing/pin profile, board-capability map, or actuator mapping, and MUST NOT be exposed to user-code routing or used to mediate/abstract GPIO for user code (see CON-7, CON-8, CON-9, FR-IDENT-2/6). — *(source: PRD §1A.3 rejection 3, §11.1, §11.3, [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware); verify: unit (structure); story: F-01, F-03)*

## 7. External interfaces (IF)

- **IF-BLE** — The board's primary external interface is the BLE GATT service (RX Write / TX Notify / INFO Read) carrying **PBLE/1** frames; the wire definition is owned by [protocol.md §2](../protocol.md#2-ble-transport-gatt) and [§3](../protocol.md#3-framing). — *(source: PRD §10.7, §16.2, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: HIL, conformance; story: F-01, F-02)*
- **IF-PROTO** — All app↔board messages MUST conform to the PBLE/1 framing, opcode, and status definitions in [protocol.md §3](../protocol.md#3-framing)/[§4](../protocol.md#4-opcodes)/[§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp); the firmware references these and MUST NOT redefine them. — *(source: PRD §10.8, [protocol.md](../protocol.md); verify: conformance; story: F-02)*
- **IF-USB** — For the initial ESP32 port, USB serial is an interface for
  **initial flashing** (the natural esp-web-tools channel) and **optional local
  debug** console mirroring only; it MUST NOT be a runtime PBLE/1 transport.
  Future ports document their own one-time provisioning method. — *(source:
  PRD §11.2, §1A.3 rejection 1, §10.3; verify: HIL; story: F-07)*
- **IF-FS** — The agent MUST present the user workspace over a MicroPython VFS / LittleFS-style filesystem rooted at `fs_root`. — *(source: PRD §16.2, §10.4, [firmware.md §3](../firmware.md#3-modules); verify: HIL; story: F-08)*
- **IF-MACHINE** — The board's hardware is exposed to user code via standard
  MicroPython runtime primitives (`machine`, `framebuf`, `neopixel`, etc.) and
  optional explicitly constructed Layer-4 helpers such as `pyble_st7789`; it
  is never an agent-mediated interface. The exact-board companion
  in FR-SPLASH composes those same primitives but adds no PBLE/1 hardware
  interface (see CON-9, FR-LIB, FR-TFT, and FR-SPLASH). —
  *(source: PRD §11.3,
  [hardware.md §4](../hardware.md#4-what-pyble-does-not-do-with-hardware),
  ADR-0023, ADR-0024; verify: HIL; story: F-04/F-24/ADR-0024 increment)*

## 8. Build, versioning & distribution (BLD)

> **FROZEN v1.0 (amended) for the initial ESP32 v1 port (G0 · 2026-07-01;
> browser-release amendments 2026-07-29 through 2026-07-31; exact-board split
> amendment 2026-08-03; heterogeneous five-profile amendment 2026-08-12 ·
> `[docs]`).**
> BLD-1…22 are the build/versioning contract build-smith implements. The
> 2026-07-29 amendments tighten BLD-5…8/13/14 and add BLD-17…22 before
> X-10/X-11 code; the 2026-07-30 amendment froze the historical two-profile
> subset and ADR-0028 replaced the v0.5.1 set with three profiles. ADR-0033
> replaces the v0.6.0 candidate set with five profiles without approving them
> and retains the immutable same-origin directory as canonical for v0.x, with
> an optional byte-identical mirror. The concrete
> `versions.lock` values
> remain proposed under OI-2 until selected as candidate-frozen inputs before
> release builds/HIL; candidate-freezing is immutability, not HIL approval.
> The *schema and rules* are frozen. Future
> platform ports define equivalent pinned build, artifact, provisioning, and
> HIL contracts. Amend only via a `[docs]` commit before dependent code.

- **BLD-1** — [`firmware/versions.lock`](../../../firmware/versions.lock) MUST be the single source of truth for the pinned MicroPython tag+commit and ESP-IDF version+commit. — *(source: PRD §10.9, §17.1; verify: build; story: X-03)*
- **BLD-2** — The build prep MUST verify the checked-out upstream submodule SHA against `versions.lock` and **refuse to proceed on mismatch** (SHA-drift gate); CI MUST run this on every PR. — *(source: PRD §10.9, §17.1; verify: build; story: X-03)*
- **BLD-3** — `firmware/scripts/build.sh <variant>` MUST build exactly one of
  `esp32`, `esp32-s3`, `waveshare-esp32-s3-lcd-147b`, or `esp32-c3`;
  `build_all.sh` MUST build all four variants in independent retained roots. —
  *(source: PRD §10.11, [firmware.md §6](../firmware.md#6-build--distribution),
  ADR-0028; verify: build; story: X-03)*
- **BLD-4** — The build MUST map each PyBLE variant to its IDF target
  (`esp32`→`esp32`, both S3 variants→`esp32s3`, `esp32-c3`→`esp32c3`)
  and apply the matching board overlay before invoking the port build; it MUST
  NOT silently substitute a different toolchain version or collapse the two S3
  artifacts. — *(source: PRD §10.11, ADR-0028,
  [`versions.lock`](../../../firmware/versions.lock); verify: build; story:
  X-03)*
- **BLD-5** — Each successful per-target build MUST emit the merged
  `firmware.bin`, bootloader, partition table, application image, and
  authoritative ESP-IDF `flasher_args.json`. Release packaging MUST normalize
  the application component name to `application.bin` without changing its
  bytes, validate that `firmware.bin` is the deterministic merge at the
  authoritative settings/offsets, and MUST NOT infer offsets from filenames. —
  *(source: PRD §10.12, [firmware.md §6](../firmware.md#6-build--distribution),
  [browser-flashing §3](browser-flashing.md#3-same-origin-versioned-layout);
  verify: build; story: X-03, X-10)*
- **BLD-6** — Release packaging MUST emit one profile-scoped
  `manifest.json` per exact ESP-IDF profile, each compatible with ESP Web Tools and
  containing exactly one build matching the schema, family, merged-image path,
  and base offset in
  [browser-flashing §4](browser-flashing.md#4-esp-web-tools-manifest), so a
  compatible-profile user can flash from `pyble.dev/flash` with no local toolchain and a
  connected family other than the selected profile is rejected rather than
  offered another release image. The `rpi-pico2-w` profile instead MUST carry
  exact UF2 size/SHA-256 metadata and the verified-download/manual-BOOTSEL
  action; it MUST NOT receive an ESP manifest, offset, or Web Serial action. —
  *(source: PRD §10.12, §15.3,
  [firmware.md §6](../firmware.md#6-build--distribution); verify: build, HIL;
  story: X-10)*
- **BLD-7** — One release MUST publish the complete, immutable, release-profile
  bundle at the canonical versioned same-origin path. A v0.x mirror is optional
  and every corresponding file and byte MUST be identical when one is
  published. v1.0 and later MUST additionally publish the matching
  byte-identical GitHub Release. The v0.6.0 candidate bundle MUST target
  exactly the five profiles in §5.3 and MUST NOT become public until all five
  qualify. The immutable v0.4.2 public-beta bundle remains the historical
  two-profile exception and its GitHub publication MUST remain marked as a
  pre-release; it MUST NOT be expanded or reinterpreted. The v0.5.1 source
  candidate remains unqualified historical identity and MUST NOT be retagged
  or repackaged. —
  *(source: PRD §10.12, §18.2,
  [browser-flashing §3](browser-flashing.md#3-same-origin-versioned-layout);
  verify: build, release; story: X-11)*
- **BLD-8** — Every release MUST carry a mechanically generated
  `THIRD_PARTY_LICENSES.txt` satisfying
  [browser-flashing §6](browser-flashing.md#6-licensing-and-release-notes); an
  unknown, missing, or license-incompatible resolved dependency MUST fail the
  build. The audit MUST reconcile compile commands with regular-file component
  sources and with only those ESP-IDF directory source markers that remain
  below their declaring component root; a marker covers compiled descendants
  but MUST NOT recursively admit uncompiled files. It MUST separately
  hash-bind the pinned `main` generated headers, reconcile every linked compile
  output exactly once to an archive member or exact direct-object linker-map
  `LOAD` and linker-command object, permitting only redundant complete `.`
  segments in a direct-`LOAD` path or an expanded `LINK_LIBRARIES` object
  operand. The latter is normalized only for object identity while its raw
  spelling remains linker-command-hash-bound; literal `$in` objects remain
  strictly canonical. Every other noncanonical or unmatched path form is
  rejected. Every map `LOAD`, including a whitespace-aliased
  `^\s*LOAD\s+` near-match, and every reconstructed linker word MUST be
  classified exactly once as a reconciled direct object, validated archive,
  admitted frontend, frozen option/operand, or exact output; a noncanonical or
  unknown `LOAD`, a bare positional word, or an archive admitted only by its
  suffix is fatal. GNU-ld forwarding is restricted to the one-atom `-Wl,`
  catalog frozen in browser-flashing §6; `-Xlinker`, `--for-linker`, every
  unlisted atom, and every unbound external control/output file are fatal. For
  every ESP role it MUST non-executingly reproduce
  the final linker argv with the bounded parser over the exact single ELF edge
  and linker rule retained in `build.ninja` and `CMakeFiles/rules.ninja`, and
  bind the canonical argv and both graph-file hashes; invocation state and an
  absent/fabricated `link.txt` cannot substitute. It MUST then classify
  build-only outputs as unlinked,
  retain source/output/metadata hashes in the generated `main` binding, repeat
  that observation after SBOM execution to close input races, and admit the
  pinned PyBLE, retained Berkeley DB, and zero-byte IDF ELF-anchor exceptions
  only in the exact roots, names, and object topologies frozen in
  [browser-flashing §6](browser-flashing.md#6-licensing-and-release-notes).
  The same release gate MUST use the independent, reviewed RP2 policy and
  observer frozen in browser-flashing §6. It safely reconciles the exact
  `link.txt`, structural linker map, archive/direct-object ownership, and
  literal frozen manifest with no gaps across MicroPython core/`rp2`, lwIP,
  Mbed TLS, littlefs, oofatfs, libm, pico-sdk, BTstack, CYW43, TinyUSB, and the
  pinned ARM GNU runtime. Every C/C++ object in the final firmware target MUST
  have its one declared, safely parsed, hash-bound compiler depfile; assembly
  objects bind their sources directly and unlinked host-tool depfiles are not
  firmware inputs. Every included byte MUST have one most-specific owner or
  exact generated derivation. That closure MUST cover
  the selected three CYW43 Wi-Fi/Bluetooth/NVRAM payload headers, with ordinary
  driver code and each payload assigned to separate most-specific owners, the
  distinct CMSIS source/header license classes, `libm.h`, `fdlibm.h`, the
  exact BSD-3-Clause `re1.5` and Zlib `uzlib` dependency files, and GCC/newlib
  headers. A broad MicroPython or `lib/` root MUST NOT stand in for those
  component terms. Each CYW43 payload remains `review-required` until exact
  authoritative redistribution terms bind its selected bytes; a broad driver
  grant or older byte-different payload license cannot substitute. The
  cache MUST bind `pico2_w`, `rp2350-arm-s`, and the exact C/C++/ASM compiler
  frontends. Every observed installed toolchain byte MUST be byte-identical to
  its member in the hash/size/root-pinned official binary tar and installed
  manifest; a version string alone is insufficient. Custom `LicenseRef`
  approval is confined to the exact hash-bound `allow`/`project-owned` owner
  that carries its complete text, while `review-required` remains observable
  and release-blocking. The audit MUST bind the exact retained checkout and
  nested SHAs/origins, complete reviewed license/notice bytes, and identical
  before/after observations into the schema-v2 receipt. Its evidence and
  notice MUST be exact children of one new publication root committed by one
  no-replace rename; two arbitrary output paths are not an atomic publication
  contract. ESP-IDF SBOM evidence MUST NOT be fabricated or reused for RP2. —
  *(source: PRD §15.2, §15.3,
  [firmware.md §6](../firmware.md#6-build--distribution); verify: build; story:
  X-11)*
- **BLD-9** — Upstream upgrades MUST go only through the controlled workflow (`firmware/scripts/upgrade_micropython.sh`): bump `versions.lock` in its own commit, rebuild `mpy-cross`, pass host + conformance + applicable footprint gates, candidate-freeze the exact updated lock before release-candidate generation, and validate that candidate on every exact profile included in the release — all five for v0.6.0 — before public-release approval. The workflow MUST never be replaced by hand-editing during a build. — *(source: PRD §10.9, §17.1, §17.3; verify: build, HIL; story: X-03)*
- **BLD-10** — `mpy-cross` MUST be rebuilt from the pinned MicroPython. Every
  release build MUST force a from-scratch compile into a fresh output
  directory and atomically replace the admitted executable; a retained
  executable or object graph MUST NOT satisfy the rebuild step. Every
  all-profile build MUST then require the retained compiler from every target
  to be a regular, non-symlink executable with identical bytes, and atomically
  admit those bytes at the canonical audit path only after the complete matrix
  succeeds. A missing, divergent, or incomplete matrix MUST preserve the
  previously admitted compiler unchanged. Every
  admitted and audit-proof rebuild MUST use `SOURCE_DATE_EPOCH` equal to the
  exact candidate PyBLE source commit's decimal committer timestamp recorded
  in build provenance; wall-clock date and caller overrides MUST NOT affect its
  bytes. — *(source: PRD §10.9, §16.2,
  [`versions.lock`](../../../firmware/versions.lock); verify: build; story:
  X-03)*
- **BLD-11** — ESP-IDF MUST be installed from the pin into a **gitignored** directory (not an outer submodule); MicroPython `lib/` deps come from the standard port build. — *(source: PRD §10.9, §17.1; verify: build; story: X-03)*
- **BLD-12** — The firmware agent MUST follow **SemVer**
  (`MAJOR.MINOR.PATCH`); a backward-incompatible change bumps MAJOR.
  `firmware/versions.lock` `[pyble].agent_version` is the canonical agent
  version for a source commit, and the importable `pyble.__version__` used by
  `DEVICE_INFO`/HELLO MUST equal it exactly. — *(source: PRD §18.1; verify:
  build; story: X-11)*
- **BLD-13** — A release MUST make the firmware-agent version, PBLE/1 version,
  upstream MicroPython/ESP-IDF and applicable ARM GNU versions and commits,
  PyBLE source commit, image profile, provisioning kind, and artifact hashes
  recoverable from `DEVICE_INFO`/HELLO,
  `manifest.json`, `release.json`, tag, and release notes as applicable. All
  surfaces MUST identify the same release. — *(source: PRD §18.1, §18.2,
  §10.8; verify: build, conformance, release; story: X-11)*
- **BLD-14** — Builds MUST be reproducible from a clean checkout given the
  pinned versions. A public release requires two clean builds from the same
  source and pinned toolchain to produce byte-identical released parts after
  documented deterministic-build normalization. Within each reproducibility
  build root, all five release profiles MUST build from independent retained
  MicroPython checkouts at `.sources/<profile>/micropython`, using the exact
  §5.3 profile IDs; the two roots MUST use that same relative layout. Each ESP
  build MUST be bound by its ESP-IDF application project description to its
  corresponding checkout at the exact locked commit. The RP2 build MUST bind
  its CMake cache, ELF provenance, board, and pinned ARM GNU identity to its
  own checkout at that same MicroPython commit. Every checkout has the
  canonical locked origin and a clean tracked tree. A profile MUST NOT share
  or overwrite another profile's mutable source, build, or managed-component
  state. The checkouts MUST remain available through license
  audit and candidate validation, while proof inputs from the canonical
  candidate checkout remain independently hash-bound. Before application
  configuration or compilation, the runner MUST deterministically map the
  exact retained MicroPython checkout prefix to `/MICROPYTHON` and the exact
  PyBLE checkout prefix to `/PYBLE` in compiler debug, macro, and source-file
  paths, with the more-specific mapping winning when nested; preserve
  ESP-IDF's `/IDF_BUILD` mapping; and replace any ambient path-map flags.
  Neither clean source/build root may remain in any whole ELF. Both builds'
  ESP whole-ELF hashes, embedded application-descriptor ELF hashes,
  application images, and merged images MUST be byte-identical per profile;
  Pico `firmware.elf`, raw `firmware.bin`, and released `firmware.uf2` MUST be
  byte-identical.
  Root-local paths in non-shipped generated frozen-content comments may differ,
  but each root MUST independently reproduce its own generated input. —
  *(source: PRD §10.11,
  §13.1, [browser-flashing §2](browser-flashing.md#2-version-and-provenance);
  verify: build; story: X-03, X-11)*
- **BLD-15** — Any upstream patch MUST reside under `firmware/patches/micropython-<tag>/` with a written reason and apply only at build prep (default zero, see CON-12). — *(source: PRD §10.10, [firmware.md §6](../firmware.md#6-build--distribution); verify: build; story: X-03)*
- **BLD-16** — The resolved frozen manifest for every initial ESP32-family
  target MUST contain exactly one pinned upstream `neopixel` module. Build
  verification MUST inspect generated frozen content or the running image, not
  stale intermediate `.mpy` files. — *(source: FR-LIB, ADR-0018; verify:
  build/HIL; story: F-24)*
- **BLD-17** — The v0.6.0 browser candidate MUST target exactly the five
  profiles and order in §5.3. The first four retain the memory qualifications,
  merge settings, browser-image base offsets, and component offsets frozen in
  [browser-flashing §1](browser-flashing.md#1-release-image-profiles); Pico
  uses only the verified-UF2/manual-BOOTSEL contract there. Family detection
  MUST NOT be represented as proof of flash/PSRAM compatibility.
  The immutable v0.4.2 public-beta bundle MUST remain exactly `esp32-4mb` plus
  `esp32-s3-n16r8` under its historical contract and MUST NOT acquire the new
  profile. The v0.5.1 source candidate retains its three-profile historical
  identity. C3 and Pico MUST remain visibly pending and inactive until their
  target gates and the complete five-profile v0.6.0 candidate pass. —
  *(source: website §7, hardware §1.1; verify: build, HIL, website; story:
  X-10)*
- **BLD-18** — Release packaging MUST generate the exact versioned layout,
  schema-validated `release.json`, SHA-256/size metadata, and `SHA256SUMS`
  defined in
  [browser-flashing §§3–5](browser-flashing.md#3-same-origin-versioned-layout).
  v0.6.0 MUST use release schema 4 with exactly the five ordered profiles and
  discriminated ESP/UF2 metadata. The v0.5.1 source-era contract retains
  release schema 3 and its three-profile order; immutable v0.4.2 replay
  retains release schema 2 and its historical two-profile order.
  Manifest paths MUST be relative, same-origin, version-confined, and free of
  redirects. — *(source: website §7; verify: build, website; story: X-10,
  X-11)*
- **BLD-19** — Release provenance MUST bind one SemVer, annotated tag, clean
  PyBLE source commit, candidate-frozen `versions.lock` bytes and upstream
  commits, exact toolchain, build
  environment, patch count, and artifact hashes as specified in
  [browser-flashing §2](browser-flashing.md#2-version-and-provenance). Any
  upstream pin change after candidate-freezing creates a new candidate and
  requires every build, audit, deployment, and exact-profile HIL gate to
  restart; candidate-freezing itself is not HIL or public-release approval. Any
  changed release byte outside the copy-on-write administrative promotion
  envelope frozen in
  [browser-flashing §9](browser-flashing.md#9-automated-and-hil-acceptance)
  invalidates prior approval and HIL evidence. The envelope may change only
  the completed HIL report, its exact status/digest fields in `release.json`,
  and the corresponding `SHA256SUMS` entries; all other bytes remain identical
  to the protected candidate. — *(source: PRD §17–§18; verify: build, release;
  story: X-11)*
- **BLD-20** — Every bundle MUST include version-matched release notes,
  third-party license notices, recovery instructions, and a HIL report that
  satisfy [browser-flashing §§6, 8, and
  9](browser-flashing.md#6-licensing-and-release-notes). — *(source: PRD
  §15.2–§15.3, website §7; verify: build, review, HIL; story: X-11)*
- **BLD-21** — The final hash-locked artifact set MUST pass the complete
  automated matrix and, on an access-controlled production-equivalent HTTPS
  candidate, its target-exact provisioning plus interrupted-install recovery
  on real hardware for every exact profile included in that release: Web
  Serial for ESP and verified UF2/manual BOOTSEL for Pico. Except for the exact,
  digest-bound v0.4.2 public-beta exception in browser-flashing §10, the public
  action remains disabled until this passes.
  One chip, simulation, an older binary, or build-only evidence MUST NOT
  substitute for another profile. — *(source: PRD §1B.3, website §7,
  [browser-flashing §9](browser-flashing.md#9-automated-and-hil-acceptance);
  verify: build, HIL; story: X-10, X-11)*
- **BLD-22** — A version directory is immutable after publication. Activation
  and rollback MUST use the state transition and exact-version selection in
  [browser-flashing §10](browser-flashing.md#10-activation-and-rollback);
  neither operation may mutate an existing bundle. — *(source: website §6.1,
  §7; verify: release, production smoke; story: X-11)*

## 9. Security & privacy (SEC)

- **SEC-1** — v1.0 MUST use **BLE link-layer pairing/encryption** as the security baseline ("personal board on a workbench" model). — *(source: PRD §14.1, [protocol.md §10](../protocol.md#10-security-note-v1); verify: HIL; story: F-01)*
- **SEC-2** — v1.0 MUST NOT add application-layer authentication; at the application layer a connected client is trusted. No partial/implicit app-layer auth may ship in v1.0. — *(source: PRD §14.1, §14.3, [protocol.md §10](../protocol.md#10-security-note-v1); verify: conformance; story: F-01)*
- **SEC-3** — The agent MUST enforce a **single active writer per connection**: only one user program runs at a time (`EBUSY` otherwise) and file/run operations are serialized so concurrent writers cannot corrupt workspace state. — *(source: PRD §14.1, §10.6; verify: conformance, HIL; story: F-04, F-09)*
- **SEC-4** — The agent MUST keep its control plane **non-writable** by user code, so "trusted client" never extends to overwriting the agent itself (see CON-10, FR-FS-11). — *(source: PRD §14.1, §10.4; verify: conformance, unit; story: F-09)*
- **SEC-5** — The BLE advertisement MUST carry only the PyBLE Service UUID and a device name — the non-PII `PyBLE-XXXX` default or, if set, the user's device label. The default name MUST contain no personal or user-identifying data; the board MUST NOT require a label to be set or require it to contain PII. — *(source: PRD §14.2, [protocol.md §2](../protocol.md#2-ble-transport-gatt), [§10](../protocol.md#10-security-note-v1); verify: HIL; story: F-01)*
- **SEC-6** — On cold boot the board MUST be **unowned**: it advertises and waits, and the trust model is simply the connected client (no stored owner or board identity). — *(source: PRD §14.1, §8.3, §10.5, [protocol.md §10](../protocol.md#10-security-note-v1); verify: HIL; story: F-12)*
- **SEC-7** — The agent MUST NOT gate access by board identity or MAC, and MUST NOT build any remote registry of users or boards. — *(source: PRD §14.2, §11.1; verify: unit (structure), HIL; story: F-01)*
- **SEC-8** — All user content (workspace files, console output) MUST stay on-device; the agent MUST NOT transmit anything off-device by default (no telemetry). — *(source: PRD §13.5, §14.2, §15.1; verify: unit, HIL; story: F-01)*
- **SEC-9** — A future application-layer pairing token is **deferred and undecided** for v1.0; if added it MUST be negotiated through HELLO capabilities (additive, no breaking wire change within PBLE/1). — *(source: PRD §14.3, §4.2, [protocol.md §10](../protocol.md#10-security-note-v1), [§9](../protocol.md#9-versioning-policy); verify: conformance; story: —)*
- **SEC-10** — Because the device label is **broadcast** in the advertisement, the board MUST bound the label length and MUST reject an over-length label with `ERANGE` (FR-IDENT-1); the board MUST NOT require a label and the default `PyBLE-XXXX` is non-PII. (The app, out of scope here, warns the user against putting PII in a broadcast label.) — *(source: PRD §14.2, [protocol.md §10](../protocol.md#10-security-note-v1), [§2](../protocol.md#2-ble-transport-gatt); verify: conformance, HIL; story: F-01, F-03)*
- **SEC-11** — `device_id`, the device label, and the identify-LED configuration are for **recognition/display only**; the agent MUST NOT gate access, authorize commands, or branch its trust model on the MAC, `device_id`, or label (reinforces SEC-7, CON-7). `SET_LABEL`, `SET_IDENTIFY_LED`, and `IDENTIFY` are ordinary control commands under the v1 connected-client trust model. — *(source: PRD §14.1, §14.2, §11.1, [protocol.md §10](../protocol.md#10-security-note-v1); verify: unit (structure), conformance, HIL; story: F-01, F-03)*

## 10. Traceability matrix

| Requirement ID(s) | PRD § | Story (F-/X-) | Verification method |
|---|---|---|---|
| FR-BLE-1…12 | §10.7, §10.6, §13.3 | F-01, F-02, F-06, F-13/14 | HIL, conformance, build |
| FR-PROTO-1…10 | §10.7, §10.8, §18.1 | F-02, F-03, P-01, P-03, P-04 | unit, conformance |
| FR-RUN-1…10 | §8.2, §8.3, §10.6 | F-04, F-05, F-06 | HIL, conformance |
| FR-FS-1…16 | §8.4, §10.4, §10.8 | F-08, F-09, F-10, F-11 | conformance, HIL, unit |
| FR-CON-1…5 | §8.2, §9.4, §10.3 | F-07 | HIL, conformance |
| FR-INFO-1…6 | §8.1, §10.8, §18.3 | F-03, P-03 | conformance, HIL |
| FR-BOOT-1…6 | §8.3, §10.5, §13.1 | F-12 | HIL, conformance |
| FR-MODE-1…4 | §10.5, §10.6 | F-03, F-04, F-12 | HIL, conformance |
| FR-IDENT-1…6 | §10.7, §11.1, §11.3, §14.2 | F-01, F-03, F-12 | conformance, HIL, unit |
| FR-LIB-1…4, BLD-16 | §9.8, §10.9, §10.11, §11.3 | F-24, A-31 | resolved manifest, build, size, HIL |
| FR-TFT-1…7 | §10.9, §10.11, §11.3, §13.3, §15.1 | ADR-0023 increment | unit, resolved manifest, build, size, HIL |
| FR-SPLASH-1…9 | §10.5, §10.9, §10.11, §11.3, §13.3, §14.2 | ADR-0024 increment | unit, resolved manifest, build, HIL, production smoke, release finalization |
| NFR-REL-1…5 | §13.1, §13.3, §10.11 | F-06, F-10, F-11, X-03 | HIL, build, unit |
| NFR-PERF-1…5 | §13.4, §10.13 | F-07, F-11, F-13/14 | HIL, size, unit |
| NFR-FP-FLASH/HEAP/BOOT/TPUT/C3/GATE/CLOSE | §10.13, §1B.3, §7.1 | F-12, F-13/14, X-03 | size, HIL, build |
| NFR-SAFE-1…4 | §13.3, §10.5, §11.3 | F-06, F-12, F-01 | HIL, unit |
| NFR-OFF-1…2 | §13.5, §14.2, §15.1 | F-01 | HIL, unit |
| NFR-MAINT-1…4 | §10.1, §10.2, §10.3, §15.1 | F-13/14, F-01…F-09, X-01 | build, unit, conformance |
| CON-1…13 | §1A.3, §10.9–§10.11, §10.14, §11.1, §11.3 | X-02, X-03, F-01, F-03, F-09, F-13/14, ADR-0023/0024 increments | build, unit, conformance |
| IF-BLE/PROTO/USB/FS/MACHINE | §10.7, §11.2, §11.3, §16.2 | F-01, F-02, F-07, F-08, F-04, F-24, ADR-0023/0024 increments | HIL, conformance |
| BLD-1…22 | §10.9–§10.12, §15.2–§15.3, §17, §18 | X-03, X-10, X-11 | build, release, website, HIL |
| SEC-1…11 | §14, §10.4, §10.6, §11.1 | F-01, F-03, F-04, F-09, F-12 | HIL, conformance, unit |

## 11. Open items

These are tracked, release-blocking where noted; they MUST be closed before the v1.0 tag.

- **OI-1 — Per-profile resource numbers pending HIL.** The measurement method,
  exact current scope, evidence contract, and threshold derivation are frozen
  in §5.3. Numeric thresholds remain open. The v0.6.0 portion closes only when
  all five ordered profiles have one committed schema-3 policy row and passing
  final-candidate V5 evidence, including C3-G0…C3-G6 and Pico GP2. That state
  MUST be described as **“qualified for the five-profile v0.6.0 release”**,
  not as universal future-board qualification. — *(verify: size, build, HIL)*
- **OI-2 — v0.4.2 pin selection is closed; current-candidate selection and
  release approval remain open.** The exact historical `versions.lock` bytes
  for MicroPython `v1.28.0` and ESP-IDF `v5.5.1` were selected and
  candidate-frozen for v0.4.2 ([PRD §10.9](../prd.md),
  [§17.1](../prd.md), [`versions.lock`](../../../firmware/versions.lock)).
  That historical selection and the supplemental browser run were not complete
  hardware approval. Before current release builds and HIL, the exact committed
  lock bytes are now source-selected with agent version v0.6.0. Before any
  release build or HIL, that exact committed state MUST be deliberately frozen
  as the candidate input. Selection is still not hardware approval: the exact
  candidate MUST pass HIL on every included profile in §5.3. Earlier v0.5.1
  candidate evidence cannot qualify v0.6.0. C3 and Pico are mandatory for the
  atomic v0.6.0 qualified release. A pin
  change creates a new candidate and resets all candidate-bound evidence. —
  *(verify: build, HIL)*
- **OI-3 — Frozen → native split point TBD.** The agent starts frozen-Python; the decision of which hot paths (BLE I/O, framing, file chunking) move to a native `USER_C_MODULE`, and on which chip the budget forces it, is open and determined by HIL footprint/throughput measurement ([firmware.md §2](../firmware.md#2-agent-base-native-vs-frozen), [PRD §10.2](../prd.md)). The PBLE/1 wire contract MUST NOT change across the move (NFR-MAINT-3). — *(verify: size, conformance, HIL)*
- **OI-4 — PBLE/1 opcode/status freeze dependency. ✅ CLOSED 2026-07-01 (`[docs]`).** [protocol.md §2](../protocol.md#2-ble-transport-gatt)/[§3](../protocol.md#3-framing) froze at G0 and [§4 (opcodes)](../protocol.md#4-opcodes)/[§8 (status)](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) froze here — status-only, no wire byte changed. The opcode set + numbers and the 1-byte status set + numbers are now stable for v1.0, so FR-BLE-1/8/10 and FR-PROTO-1…10 no longer inherit provisional numbers; F-01/F-02 DoR is met. Each dependent story still MUST cite its frozen spec section per [PRD §1B.4](../prd.md). Payload-level encodings for the identity/identify opcodes remain **OI-6**. — *(verify: conformance)*
- **OI-5 — Auto-run capability flag naming. ✅ CLOSED 2026-07-01 (`[docs]`).** The opt-in `main.py` auto-run cap is **`auto_run`** (u8, 0=off default / 1=on), set via the additive **`SET_AUTORUN` (0x23)** opcode ([protocol.md §7](../protocol.md#7-hello--capabilities)/[§4](../protocol.md#4-opcodes)), persisted at NVS `pyble/autorun` (owned by `pble_boot`), entry `/main.py`. FR-BOOT-3 DoR met (F-12). — *(verify: conformance)*
- **OI-6 — Label/identify wire encodings. ✅ FULLY CLOSED 2026-07-01 (`[docs]`).** Label half (S3): label max = **24 bytes UTF-8** (over-length → `ERANGE`), frozen in [protocol.md §7](../protocol.md#7-hello--capabilities). Identify remainder (S4): `SET_IDENTIFY_LED` = `[gpio:u8][active_level:u8]` (empty clears; `ERANGE`/`EBADREQ`), `IDENTIFY` = optional `[duration_ds:u8]` (1–50 ds, default 20, 5 Hz), and caps `has_identify`/`identify_led` (gpio byte or `0xFF`), frozen in [protocol.md §4](../protocol.md#4-opcodes)/[§7](../protocol.md#7-hello--capabilities). FR-IDENT-1..6 / FR-BLE-12 DoR met (F-22/F-23). — *(verify: conformance)*

<!-- SPDX-License-Identifier: MIT -->
