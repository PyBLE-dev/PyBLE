# PyBLE App — Requirements Specification

Status: **DRAFT** · Owner: project maintainer · Last updated: 2026-08-15

## 1. Purpose, Scope & Document Role

### 1.1 Purpose

This document is the **detailed requirements specification for the PyBLE app** — the single Flutter, tablet-first MicroPython IDE for iPadOS and Android that edits, runs, and manages MicroPython on compatible boards over Bluetooth Low Energy. The app is target-neutral and discovers PBLE/1 agents by service and capability; classic ESP32, ESP32-S3, and ESP32-C3 are the initial firmware targets, not an app allowlist. It derives the apex app requirements of [PRD §9](../prd.md) into individually-testable, traceable requirements, and pulls in the app-facing obligations of [PRD §5](../prd.md), [§6.1](../prd.md), [§12](../prd.md), [§13](../prd.md), [§14](../prd.md), [§15](../prd.md), [§16.1](../prd.md), [§17.2](../prd.md), [§18](../prd.md), and [§19](../prd.md).

### 1.2 Scope

In scope: every behaviour of the Flutter app — the BLE adapter (`lib/ble/`), the PBLE/1 client (`lib/pble/`), the `Connection` API seam, and all UI surfaces (editor, console, files, run control, connect flow, Blocks, plots, error explanation, localization, layout). Out of scope: the wire protocol itself (owned by [protocol.md](../protocol.md)), the agent firmware (owned by [firmware.md](../firmware.md) and `../firmware/specs.md`), and the board hardware contract (owned by [hardware.md](../hardware.md)).

### 1.3 Document role & hierarchy

Per the apex rule "more specific spec wins on its own topic" ([PRD §5](../prd.md)):

- [PRD §9](../prd.md) is the **apex** app requirement set; this spec expands it and MUST stay consistent with it.
- [app.md](../app.md) is the app **overview**; it **owns** the package/directory layout ([app.md §2](../app.md#2-packages--directories)) and the `Connection`/`FakeConnection` seam ([app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to)). This spec references those rather than restating the directory list.
- [protocol.md](../protocol.md) **owns** the PBLE/1 wire format (framing, opcodes, status codes); this spec references its sections and does **not** redefine frame bytes or opcode numbers.
- This spec (`specs.md`) is the **detailed app requirements** layer; the companion [TDD.md](TDD.md) is the engineering design that satisfies it.

### 1.4 The Connection / FakeConnection testability principle

Binding on the whole document ([PRD §9](../prd.md), [app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to), [app.md §7](../app.md#7-testing)): every functional requirement MUST bind to the `Connection` interface (or narrow callbacks derived from it) and MUST be testable against a `FakeConnection`. **No UI widget imports `lib/ble/` directly**, and only `lib/pble/` knows the wire format.

## 2. References & Definitions

### 2.1 Referenced documents

- [PRD](../prd.md) — apex product requirements (esp. §5, §6.1, §9, §12–§19).
- [app.md](../app.md) — app overview: layering, packages, `Connection` API, connect flow, platform notes, testing.
- [architecture.md](../architecture.md) — three-piece system view, clean-room boundary, technology choices.
- [protocol.md](../protocol.md) — PBLE/1 wire protocol (transport, framing, opcodes, file transfer, HELLO, status codes).
- [hardware.md](../hardware.md) — supported chip families and the read-only pin reference.
- [firmware.md](../firmware.md) — agent firmware overview; detailed firmware specs at [../firmware/specs.md](../firmware/specs.md).
- ADRs under [../../decisions/](../../decisions/) — e.g. [ADR-0002 (fresh protocol)](../../decisions/0002-fresh-protocol.md), [ADR-0003 (MIT)](../../decisions/0003-license-mit.md).
- [Public roadmap](../../ROADMAP.md) and GitHub issues — app, protocol, and
  infrastructure work.
- Governance: [AGENTS.md](../../../AGENTS.md), [CLAUDE.md](../../../CLAUDE.md).

### 2.2 Definitions

- **Connection** — the abstract Dart interface every widget binds to (deviceInfo, run/stop/console, file ops, state), defined in [app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to).
- **FakeConnection** — an in-memory test double implementing `Connection`, used to exercise UI and client behaviour without a board.
- **lib/ble** — the `flutter_blue_plus` adapter: scan, connect, MTU, byte stream in/out, reconnect.
- **lib/pble** — the PBLE/1 client: codec, fragmentation, correlation, file-transfer state machine, console stream, error mapping; the only layer that knows the wire format. Exposes `Connection`.
- **ARB** — Application Resource Bundle: the `intl`-based localization string files (`en` day-one; parity enforced).
- **Drift** — the SQLite-based local persistence layer (`lib/data/`) for projects, settings, saved boards (offline-first).
- **golden test** — a Flutter widget snapshot test comparing rendered output to a stored reference image.
- **Verification methods** used throughout: `widget`, `golden`, `unit`, `conformance` (PBLE/1 round-trip on an in-memory transport), `integration` (end-to-end against a fake board / on-device smoke), `locale` (ARB parity check).

## 3. System Context

Per [app.md §1](../app.md#1-layering) the app is strictly layered:

```
UI widgets (editor · console · files · run control · connect · blocks · plots)
        │  (Connection / narrow callbacks only — no transport imports)
        ▼
PBLE/1 client      lib/pble/   ── exposes the Connection API
        │
        ▼
BLE adapter        lib/ble/    ── byte stream in / write out
        │
        ▼
flutter_blue_plus  ── BLE radio
```

There is exactly **one** app (no separate management/console build, [PRD §6.1](../prd.md)); it is tablet-first with **iPadOS and Android at feature parity at every milestone** ([PRD §13.6](../prd.md)). Widgets bind only to `Connection`; the wire format lives only in `lib/pble/`.

## 4. Functional Requirements

Requirement voice: MUST / SHOULD / MAY. Each line: **ID** — statement — *(source; verify; story)*.

### 4.1 BLE Adapter (`lib/ble/`) — FR-BLE

- **FR-BLE-1** — The adapter MUST scan with `flutter_blue_plus` **filtered to the PyBLE service UUID** ([protocol.md §2](../protocol.md#2-ble-transport-gatt)) and MUST surface only advertised `PyBLE-XXXX` devices with RSSI; it MUST NOT expose a raw, unfiltered BLE device list. MUST (*source: PRD §9.6, §8.1; verify: unit; story: A-01*)
- **FR-BLE-2** — The adapter MUST open a GATT connection to a selected device, subscribe to the TX (Notify) characteristic, and request **MTU 247**, correctly handling a negotiated MTU down to the BLE default. MUST (*source: PRD §9.6, §16.1; verify: unit/integration; story: A-02*)
- **FR-BLE-3** — The adapter MUST expose a byte-stream interface: an inbound `Stream<List<int>>` from TX notifications and a `write(bytes, {required withoutResponse})` to RX; it MUST map `withoutResponse: false` to acknowledged GATT Write and `true` to Write-Without-Response, and MUST NOT interpret frame contents. MUST (*source: app.md §2, [protocol.md §2](../protocol.md#2-ble-transport-gatt); verify: unit; story: A-02*)
- **FR-BLE-4** — The adapter MUST detect link loss and auto-reattempt connection, exposing connection-state transitions to the layer above; it MUST reconnect a saved board by remembered identifier. MUST (*source: PRD §8.1, §13.1; verify: unit/integration; story: A-03*)
- **FR-BLE-5** — The adapter MUST stop scanning before initiating a connection. MUST (*source: PRD §9.6; verify: unit; story: A-02*)
- **FR-BLE-6** — The adapter MUST request and handle platform BLE permissions and adapter-off state, surfacing them upward with enough detail for a localized rationale (iOS `NSBluetoothAlwaysUsageDescription`; Android 12+ `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT`; Android 11 and lower `BLUETOOTH`/`BLUETOOTH_ADMIN` capped at API 30 plus location handling; `ACCESS_COARSE_LOCATION` capped at API 28). Because BLE is the sole primary transport, the Android package MUST declare `android.hardware.bluetooth_le` as required. It MUST declare `android.hardware.bluetooth` and `android.hardware.location` as not required so legacy permissions do not filter otherwise-compatible BLE hardware. MUST (*source: PRD §9.6, §13.6, app.md §5; verify: integration; story: A-04*)
- **FR-BLE-7** — The adapter MUST remain a thin, mockable seam so scan/connect/reconnect are testable with a mocked transport and behaviour differences between iOS and Android are isolable. MUST (*source: PRD §23 (BLE risk), app.md §7; verify: unit; story: A-01/A-02/A-03*)
- **FR-BLE-8** — No UI widget MUST import `lib/ble/`; the adapter is reachable only through `lib/pble/`. MUST (*source: PRD §6.1, §16.1, app.md §1; verify: unit (import-boundary lint); story: A-02*)

### 4.2 PBLE/1 Client (`lib/pble/`) — FR-PBLE

The client implements the PBLE/1 wire contract; it references [protocol.md](../protocol.md) and does not redefine the wire.

- **FR-PBLE-1** — The client MUST encode and decode PBLE/1 messages per [protocol.md §3.1](../protocol.md#3-framing) (VER/TYPE/OPCODE/ID/LEN/PAYLOAD/CRC32) and MUST compute/verify the IEEE CRC-32 over header+payload. MUST (*source: PRD §9, §6.3; verify: conformance; story: P-01, A-13*)
- **FR-PBLE-2** — The client MUST fragment outbound messages and reassemble inbound messages across `MTU − 4` boundaries per [protocol.md §3.2](../protocol.md#3-framing) (FIRST/LAST/index-mod-64 header), reproducing the original message byte-identically. MUST (*source: PRD §6.3; verify: conformance; story: P-02, A-13*)
- **FR-PBLE-3** — The client MUST drop any reassembled frame whose CRC fails and MUST surface it as an error (mapping to `ECRC` per [protocol.md §3.2](../protocol.md#3-framing)/[§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp)), never delivering corrupt payload upward. MUST (*source: PRD §6.3; verify: conformance; story: P-01*)
- **FR-PBLE-4** — The client MUST correlate each `CMD` with its `RSP` by the 1-byte `ID` and MUST route `EVT` frames (`ID = 0`) to the appropriate stream (console, run-state, file-transfer acks/data). MUST (*source: protocol.md §3.1, §4; verify: conformance; story: A-13*)
- **FR-PBLE-5** — The client MUST implement HELLO version + capability negotiation per [protocol.md §7](../protocol.md#7-hello--capabilities): send `proto_versions[]` + `app_name`/`app_version`, receive `proto_version` + `caps`. MUST (*source: PRD §9.6, §18.3; verify: conformance; story: P-03, A-10*)
- **FR-PBLE-6** — The client MUST refuse, with a clear typed error, a board whose chosen `proto_version` it does not support. MUST (*source: PRD §18.3; verify: conformance; story: P-03*)
- **FR-PBLE-7** — The client MUST NOT issue any request for a capability the board did not advertise in HELLO `caps`. MUST (*source: PRD §6.3, §9.6, §18.3; verify: conformance; story: P-03, A-10*)
- **FR-PBLE-8** — The client MUST implement the windowed upload state machine per [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core): `FILE_PUT_BEGIN` → windowed `FILE_PUT_DATA` (up to `W` unacked chunks, `W` sourced from HELLO `caps.window`; the reference agent advertises `W=8`; fallback 4 when caps omit the key) advanced by `FILE_PUT_ACK` cumulative offsets with Go-Back-N gap retransmission → `FILE_PUT_END` with whole-file CRC. A put MUST be reported successful only on a full-file CRC match. MUST (*source: PRD §8.4, §9.2, §13.1; verify: conformance; story: A-13, P-/F-09*)
- **FR-PBLE-9** — The client MUST implement download streaming per [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core): `FILE_GET_BEGIN` → `FILE_GET_DATA` events → `FILE_GET_END`, verifying total size and whole-file CRC before reporting success. MUST (*source: PRD §8.4; verify: conformance; story: A-12*)
- **FR-PBLE-10** — The client MUST support **resume-on-reconnect**: after a drop, issue `FILE_STAT { path }`, learn the verified partial offset, and resume `FILE_PUT_BEGIN`/`FILE_GET_BEGIN` from that offset rather than restarting from zero. MUST (*source: PRD §8.4, §13.1; verify: conformance/integration; story: A-13, F-10*)
- **FR-PBLE-11** — The client MUST expose run control over the wire — `RUN { mode: file|source }`, `STOP`, `SOFT_REBOOT` — and surface `RUN_STATE` transitions (idle/running/done/error) as a stream per [protocol.md §6](../protocol.md#6-run--stop--console). MUST (*source: PRD §9.5; verify: conformance; story: A-11*)
- **FR-PBLE-12** — The client MUST expose the console stream from `CONSOLE_DATA` events (tagging `stdout`/`stderr`/`system`) and MUST send `CONSOLE_INPUT` for stdin. MUST (*source: PRD §9.4; verify: conformance; story: A-11*)
- **FR-PBLE-13** — The client MUST map every PBLE/1 status byte ([protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp): OK, EBADREQ, ENOENT, EACCES, ENOSPC, EIO, ENOMEM, EBUSY, ECRC, ERANGE, EUNSUPPORTED, EINTERNAL) to a distinct typed Dart exception so callers can branch on the failure. MUST (*source: PRD §9.2, §13.2; verify: conformance; story: P-04*)
- **FR-PBLE-14** — The client MUST be the **only** layer that knows the wire format; it MUST present all behaviour to widgets exclusively through the `Connection` interface. MUST (*source: PRD §16.1, app.md §1; verify: unit; story: A-10*)
- **FR-PBLE-15** — The client MUST be authored clean-room and carry no closed-source wire format, opcodes, or UUIDs (see [architecture.md §5](../architecture.md#5-clean-room--ip-boundary), [ADR-0002](../../decisions/0002-fresh-protocol.md)); the no-leak gate MUST pass over `lib/pble/`. MUST (*source: PRD §1A.2, §6.3; verify: unit (no-leak gate); story: X-02*)
- **FR-PBLE-16** — The neutral byte transport MUST expose `send(packet, {required acknowledged})`. `PbleEngine.request` MUST send every fragment with `acknowledged: true`; `PbleEngine.fire` MUST retain Write-Without-Response with `acknowledged: false`. One unchanged absolute request deadline MUST begin before the first fragment write and include every acknowledged write plus the matching response wait; write progress MUST NOT reset or extend it. MUST (*source: [protocol.md §2](../protocol.md#2-ble-transport-gatt), §3.2; verify: unit, integration; story: P-02/A-13*)

**A-13 `putFile` sliding-window increment — FROZEN (`[docs]` 2026-07-04).** This freezes the A-13 slice of FR-PBLE-8/-10 that supersedes the A-12 depth-1 (stop-and-wait) uploader ([TDD §8.4](TDD.md#84-file-transfer-state-machine)). No wire change — [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core) is FROZEN and the offset/watermark cumulative-ACK is window-agnostic; `W` is a client-side pacing parameter read from HELLO `caps.window`. The testable acceptance criteria the test authors (P-/A-13 conformance) MUST convert to `[red]`:

- **AC-1 (window bound)** — The uploader MUST keep **≤ W** `FILE_PUT_DATA` chunks outstanding (unacked) at any instant, where `W = caps.window` from HELLO (reference agent advertises 8; fallback 4 when the key is absent). It MUST NOT exceed W even when the board acks slowly. MUST
- **AC-2 (advance on cumulative ACK)** — On `FILE_PUT_ACK { ack_offset }` the uploader MUST advance the window base to `ack_offset` and release send credit for the newly-acked chunks, then send the next in-flight chunks up to the W bound. A single cumulative ACK MAY retire multiple chunks. MUST
- **AC-3 (Go-Back-N on gap/timeout)** — On a gap (an `ack_offset` that does not advance past a sent chunk after the board drops/re-acks) or an ACK timeout, the uploader MUST retransmit from `ack_offset` — i.e. resend every chunk at or after the current watermark — never assume a chunk past `ack_offset` was received. MUST
- **AC-4 (resume unchanged)** — When `FILE_PUT_BEGIN` returns `resume_offset > 0` (FR-PBLE-10), the window MUST start at `resume_offset`; the sliding-window loop is otherwise identical. MUST
- **AC-5 (progress monotonic)** — Reported `TransferProgress.sent` MUST be **monotonic non-decreasing** and driven by acked (watermark) bytes, never by optimistically-sent bytes, so a Go-Back-N resend never moves the progress bar backward. MUST
- **AC-6 (success gate unchanged)** — A put MUST be reported successful **only** on `FILE_PUT_END` `RSP OK` after a whole-file CRC match (FR-PBLE-8, NFR-REL-1); a window/Go-Back-N optimization MUST NOT relax this. MUST

### 4.3 Connection API (`Connection` surface, state & diagnostics) — FR-CONN

- **FR-CONN-1** — `Connection` MUST expose `deviceInfo()` returning chip, MicroPython version, free memory, fs root, and the screenless-identity fields `device_id` (the stable MAC-derived suffix) and `label` (the user-set device label, or empty) from HELLO/DEVICE_INFO / INFO read ([protocol.md §4](../protocol.md#4-opcodes) `0x02`, [§7](../protocol.md#7-hello--capabilities)); `device_id` is for recognition/display only and MUST NOT be used to authorize. MUST (*source: PRD §8.1, §9.6, app.md §3, protocol.md §7; verify: unit (FakeConnection); story: A-10*)
- **FR-CONN-2** — `Connection` MUST expose `runFile(path)`, `runSource(source)`, `stop()`, and `softReboot()`. MUST (*source: PRD §9.5, app.md §3; verify: unit (FakeConnection); story: A-11*)
- **FR-CONN-3** — `Connection` MUST expose a `console` stream of `ConsoleEvent { stream: stdout|stderr|system, bytes }` and a `sendInput(text)` method. MUST (*source: PRD §9.4, app.md §3; verify: unit (FakeConnection); story: A-11*)
- **FR-CONN-4** — `Connection` MUST expose the file operations `listDir`, `getFile` (with progress), `putFile` (with progress), `delete`, `mkdir`, and `rename`. MUST (*source: PRD §8.4, §9.2, app.md §3; verify: unit (FakeConnection); story: A-12*)
- **FR-CONN-5** — `Connection` MUST expose an observable connection state (`disconnected`/`connecting`/`ready`/`running`) as a `ValueListenable<ConnState>` (or equivalent) so widgets drive UI without polling. MUST (*source: app.md §3, PRD §13.2; verify: widget; story: A-11/A-22*)
- **FR-CONN-6** — `Connection` MUST surface connection diagnostics — state, signal/RSSI, negotiated MTU, and negotiated `caps` (including `device_id`, `label`, `has_identify`, and the configured `identify_led` or null) — for display. MUST (*source: PRD §9.6, protocol.md §7; verify: widget; story: A-22*)
- **FR-CONN-7** — Every `Connection` method and stream MUST be implementable by a `FakeConnection` with no BLE dependency, and the production conformance + widget suites MUST exercise both. MUST (*source: PRD §9, app.md §3/§7; verify: unit/widget; story: A-10..A-13*)
- **FR-CONN-8** — The `Connection` surface MUST expose only the board-control verbs in scope (deviceInfo, run/stop/soft-reboot, console, file ops); it MUST NOT expose any session-lock/heartbeat, board-identity gating, pairing-token, or managed-fleet operation (the non-goals enumerated in [PRD §4.3](../prd.md)). MUST (*source: PRD §9.6, §4.3, app.md §3; verify: unit; story: A-10*)
- **FR-CONN-9** — `Connection` MUST report progress for `getFile`/`putFile` via a progress callback so the UI can render transfer progress. MUST (*source: PRD §9.2, §13.4; verify: unit/widget; story: A-12*)
- **FR-CONN-10** — `Connection` MUST expose `setLabel(label)` sending `SET_LABEL` ([protocol.md §4](../protocol.md#4-opcodes) `0x50`) to persist a bounded UTF-8 device label that becomes the advertised name and `DEVICE_INFO.label`; an empty label MUST clear it back to the default `PyBLE-XXXX`. This is the board's own per-device UX configuration — NOT a routing/pin profile, board-capability map, or access-gating mechanism. MUST (*source: PRD §9.6, §4.3, app.md §3, protocol.md §4/§10; verify: unit (FakeConnection); story: A-22*)
- **FR-CONN-11** — `Connection` MUST expose `setIdentifyLed({ gpio, activeLevel })` sending `SET_IDENTIFY_LED` ([protocol.md §4](../protocol.md#4-opcodes) `0x51`) to persist the **single** optional identify status-LED GPIO and active level. This is device configuration for the IDENTIFY blink ONLY; it MUST NOT be exposed to user code and MUST NOT be treated as a routing/pin profile or board-capability map. MUST (*source: PRD §9.6, §4.3, app.md §3, protocol.md §4; verify: unit (FakeConnection); story: A-22*)
- **FR-CONN-12** — `Connection` MUST expose `identify()` sending `IDENTIFY` ([protocol.md §4](../protocol.md#4-opcodes) `0x52`) to blink the configured identify LED for a bounded duration; the app MUST offer the Identify action **only** when the board advertised `has_identify` (FR-CONN-6), MUST prompt the user to configure the identify LED (via `setIdentifyLed`, FR-CONN-11) when `identify_led` is null, and MUST surface `EUNSUPPORTED` (no identify LED configured) as a clear typed error rather than failing silently. MUST (*source: PRD §9.6, §18.3, app.md §3, protocol.md §4/§7; verify: unit (FakeConnection)/widget; story: A-22*)

### 4.4 Project & File Management — FR-PROJ

- **FR-PROJ-1** — The app MUST let a user create, open, and duplicate local projects. MUST (*source: PRD §9.1; verify: unit/integration; story: A-20*)
- **FR-PROJ-2** — The app MUST persist projects, settings, and saved boards locally and offline-first via Drift (`lib/data/`); a project MUST be fully usable with no account and no network. MUST (*source: PRD §9.1, §12, §13.5, §16.1; verify: unit/integration; story: A-20*)
- **FR-PROJ-3** — The app MUST associate a project with a saved board identifier (a lightweight `board_ref`, not a managed-fleet/profile table) so it can reconnect without re-scanning, and MUST NOT require any cohort/device binding (the non-goals of [PRD §4.3](../prd.md)). MUST (*source: PRD §9.1, §12.1; verify: unit; story: A-20*)
- **FR-PROJ-4** — Project files MUST mirror the workspace shape (`/main.py`, `/lib/*.py`, `/data/*`, optional `project.json`) and MUST hold `.py`/plain data only — never `.mpy`/`.pyc`. MUST (*source: PRD §10.14, §12.1; verify: unit; story: A-20*)
- **FR-PROJ-5** — The app SHOULD support exporting/importing a project as a local archive for backup or hand-off and MUST NOT require a cloud service to do so. SHOULD (*source: PRD §9.1; verify: integration; story: A-20*)
- **FR-PROJ-6** — On disconnect the app MUST preserve the user's work locally (open editor buffers, project files, run/console state) so nothing is lost across a dropped link. MUST (*source: PRD §13.1; verify: integration; story: A-03/A-20*)
- **FR-PROJ-7** — The app SHOULD capture point-in-time code snapshots (manual and pre-run) for local history/restore. SHOULD (*source: PRD §12.1; verify: unit; story: A-20*)

### 4.5 Workspace File Explorer (`lib/files/`) — FR-FILES

- **FR-FILES-1** — The explorer MUST display the board filesystem from `listDir` (`FILE_LIST`) rooted at the `fs_root` reported in DEVICE_INFO. MUST (*source: PRD §9.2, §8.4; verify: widget (FakeConnection); story: A-30*)
- **FR-FILES-2** — The explorer MUST support open, upload (`putFile`), download (`getFile`), rename, delete, and mkdir. MUST (*source: PRD §9.2; verify: widget; story: A-30*)
- **FR-FILES-3** — The explorer MUST surface PBLE/1 status codes (e.g. `ENOENT`, `ENOSPC`, `EACCES`) as actionable, localized messages rather than raw codes. MUST (*source: PRD §9.2, §13.2; verify: widget; story: A-30*)
- **FR-FILES-4** — Uploads and downloads MUST report progress and MUST be shown successful only on a full-file CRC match. MUST (*source: PRD §9.2, §8.4; verify: widget/integration; story: A-30*)
- **FR-FILES-5** — The explorer SHOULD support multi-select for bulk operations (e.g. multi-delete). SHOULD (*source: PRD §9.2; verify: widget; story: A-30*)
- **FR-FILES-6** — The explorer SHOULD distinguish the user workspace (`/main.py`, `/lib/*.py`, `/data/*`) from the agent control plane, which it MUST NOT present as editable. MUST/SHOULD (*source: PRD §9.2, §10.4, firmware.md §1; verify: widget; story: A-30*)
- **FR-FILES-7** — Transfers MUST be `.py`/data only; the explorer MUST NOT produce or transfer `.mpy`/`.pyc`. MUST (*source: PRD §9.2, §10.14, §4.3; verify: unit; story: A-30*)
- **FR-FILES-8** — The explorer MUST bind only to `Connection` file operations and MUST NOT import `lib/ble/`. MUST (*source: PRD §6.1, app.md §1; verify: unit; story: A-30*)

**Working-loop increment — FROZEN (A-30 subset · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md), [TDD §11.6](TDD.md#116-working-loop-provider-contract-frozen)).** In scope: `listDir` rooted at `fs_root` with into/up navigation, open-in-editor (`getFile` → editor buffer), upload-current-buffer (`putFile`), mkdir, delete, rename, `newFile`, continuous transfer progress + whole-file CRC success, typed-error → localized message, disabled-with-guidance while disconnected (FR-FILES-1/2/3/4/8, binding via the `Connection` seam only, CON-8). **Deferred:** multi-select bulk ops (FR-FILES-5); the control-plane non-editable predicate (FR-FILES-6 — the board still enforces `EACCES`, SEC-7); export-to-device-storage **Download** (needs local persistence + a new dep — open-in-editor is the read-into-app path this increment). `.py`/data-only holds (FR-FILES-7, CON-3).

### 4.6 Code Editor (`lib/editor/`) — FR-EDIT

- **FR-EDIT-1** — The editor MUST provide Python/MicroPython syntax highlighting, line numbers, and auto-indentation (`flutter_code_editor`, with a WebView-hosted editor as the documented fallback per [PRD §16.1](../prd.md)/§23). MUST (*source: PRD §9.3, §16.1; verify: widget; story: A-20*)
- **FR-EDIT-2** — The editor MUST offer Save and Run actions and MUST support multiple open files via tabs. MUST (*source: PRD §9.3; verify: widget; story: A-20*)
- **FR-EDIT-3** — The editor MUST provide find and SHOULD provide find/replace. MUST/SHOULD (*source: PRD §9.3; verify: widget; story: A-20*)
- **FR-EDIT-4** — The editor SHOULD support an external keyboard with common shortcuts (Save, Run, Stop, comment/uncomment, find). SHOULD (*source: PRD §9.3, §13.7; verify: widget; story: A-20*)
- **FR-EDIT-5** — Touch targets MUST be tablet-friendly and the editor MUST remain usable on a phone without layout breakage. MUST (*source: PRD §9.3, §13.2; verify: golden; story: A-20*)
- **FR-EDIT-6** — The editor MUST bind only to the `Connection` API for board actions and MUST NOT import `lib/ble/`. MUST (*source: PRD §9.3, §6.1, app.md §1; verify: unit; story: A-20*)
- **FR-EDIT-7** — Save MUST persist the edited file to the local project (offline-first); Run MUST upload then run through `Connection` per the §8.2 loop. MUST (*source: PRD §8.2, §9.1, §9.3; verify: integration; story: A-20/A-11*)

**Working-loop increment — FROZEN (A-20 subset · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md), [TDD §11.1](TDD.md#111-editor)/[§11.6](TDD.md#116-working-loop-provider-contract-frozen); run path superseded 2026-07-27 by [ADR-0013](../../decisions/0013-clean-room-blockly-one-way-file-backed.md)).** In scope: a monospace editable surface (`SignalCodeColors`-styled, no heavy code-editor dep) over a single volatile in-memory current document (name/content/dirty/boardPath), with **New** and (when connected) **Run**. Save and Run capture one normalized document snapshot; transfer completion marks it saved/bound only when the live document still equals that snapshot, so mid-transfer edits or a replacement document remain dirty. Run now uses the shared file-backed `putFile → runFile` action required by FR-EDIT-7 and shared with Blocks; `runSource` remains only for explicitly bounded snippets. The editor binds to `Connection` only (FR-EDIT-6, CON-8). **Deferred to A-24 / OI-1:** syntax highlighting, multi-file tabs, find/replace, external-keyboard shortcuts (FR-EDIT-1/2/3/4). FR-EDIT-7 Save-to-project and NFR-REL-3/FR-PROJ-6 buffers-survive-restart are **carried, not dropped** — the document provider's `openFromBoard`/`markSaved` are the A-24 persistence hooks; until then the buffer is volatile (RECORDED deviation, ADR-0010).

### 4.7 Console Panel (`lib/console/`) — FR-CONSOLE

- **FR-CONSOLE-1** — The console MUST render the live `console` stream (`CONSOLE_DATA`) and MUST visually distinguish `stdout`, `stderr`, and `system` streams. MUST (*source: PRD §9.4; verify: widget/golden; story: A-21*)
- **FR-CONSOLE-2** — The console MUST render Python tracebacks legibly. MUST (*source: PRD §9.4; verify: golden; story: A-21*)
- **FR-CONSOLE-3** — The console MUST reflect run state from `RUN_STATE` (idle/running/done/error) and the connection state. MUST (*source: PRD §9.4, §9.5; verify: widget; story: A-21*)
- **FR-CONSOLE-4** — The console MUST support feeding stdin via `sendInput` (`CONSOLE_INPUT`) for programs blocked on `input()`. MUST (*source: PRD §9.4; verify: widget (FakeConnection); story: A-21*)
- **FR-CONSOLE-5** — The console MUST display output regardless of which client triggered the run (observe-anywhere). MUST (*source: PRD §9.4, protocol.md §6; verify: integration; story: A-21*)
- **FR-CONSOLE-6** — The console SHOULD support copying console text and clearing the view (and SHOULD, post-v1, support search). SHOULD (*source: PRD §9.4, §7.2; verify: widget; story: A-21*)
- **FR-CONSOLE-7** — Switching UI tabs MUST NOT drop the console stream or an in-flight file transfer. MUST (*source: PRD §19.2; verify: widget/integration; story: A-21*)

**Working-loop increment — FROZEN (A-21 subset · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md), [TDD §11.4](TDD.md#114-console--error-explanation)/[§11.6](TDD.md#116-working-loop-provider-contract-frozen)).** In scope: render the live `console` stream into a capped-ring provider surviving tab/nav switches, `stdout`/`stderr`/`system` differentiated (`SignalCodeColors`), legible tracebacks, stdin row → `sendInput`, clear (+ optional copy), auto-scroll with scroll-lock, and a `RunState` indicator (FR-CONSOLE-1/2/3/4/5/6/7). Both the landscape strip and the Console surface render off the same provider. **Deferred:** the data-driven beginner **error explainer** (FR-ERR-1..4 → A-25) and `console_logs` Drift capture (DAT-5 → A-24); the raw `stderr` traceback still renders (never hidden, FR-ERR-2).

### 4.8 Run Control (`Run`/`Stop`/`Soft-Reboot`) — FR-RUN

- **FR-RUN-1** — The app MUST expose **Run** (`runFile`/`runSource`), **Stop** (`stop`), and **Soft-Reboot** (`softReboot`) — and only these board-control verbs; there MUST be no app-level hard-reset or safe-mode command (recovery beyond soft-reboot is a physical power cycle). MUST (*source: PRD §9.5, §8.3; verify: widget; story: A-11*)
- **FR-RUN-2** — **Stop** MUST be presented as authoritative: it MUST interrupt a running program (even a tight loop) and return the board to idle, reflected via `RUN_STATE`. MUST (*source: PRD §9.5, §13.3, firmware.md §5; verify: integration; story: A-11, F-06*)
- **FR-RUN-3** — The app MUST reflect the run lifecycle from `RUN_STATE` events and MUST disable **Run** while a program is running, surfacing `EBUSY` if the board reports it. MUST (*source: PRD §9.5, §10.6; verify: widget; story: A-11*)
- **FR-RUN-4** — Run actions MUST be driven by the `Connection` API so they are exercisable against a `FakeConnection`. MUST (*source: PRD §9.5; verify: unit/widget; story: A-11*)
- **FR-RUN-5** — The app MUST surface real BLE/run failures honestly at each recovery rung (STOP → soft reboot → cold-boot-safe) rather than hiding them. MUST (*source: PRD §8.3, §2, §13.2; verify: widget; story: A-11*)

**Working-loop increment — FROZEN (A-16 · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md), [TDD §11.6](TDD.md#116-working-loop-provider-contract-frozen); primary run path superseded 2026-07-27 by [ADR-0013](../../decisions/0013-clean-room-blockly-one-way-file-backed.md)).** The shell toolbar wires **Run** (verified `putFile` of the captured current editor buffer followed by `runFile` at that path), **Stop** (`stop`), and **Soft-reboot** (`softReboot`) — and only these verbs (FR-RUN-1). Successful Run marks the editor saved only if the live document still equals that captured upload snapshot; a document edited or replaced during transfer stays dirty and is never rebound to the uploaded path. `runFile` for an already-saved board file remains direct; `runSource` remains available for explicitly bounded snippets, not the primary app action. Enable/disable is derived from `ConnState` + `RunState` via `runAvailabilityProvider`: Run enabled only at `ready`, disabled while `running` with `EBusy` surfaced honestly (FR-RUN-2/3); disconnected shows a "connect a board" hint (FR-RUN-5). All run actions go through the `Connection` seam, exercisable against `FakeConnection` (FR-RUN-4). The run-control provider is owned by app-editor-console-engineer (`lib/editor`); the architect wires the toolbar buttons (FR-UI-3). No app-level hard-reset/safe-mode (FR-RUN-1).

### 4.9 GitHub Public-Repo Import (`lib/github_import/`) — FR-IMPORT

- **FR-IMPORT-1** — The app MUST import a folder of `.py` files from a **public** GitHub repository over HTTPS and write them to the board via `Connection.putFile`. MUST (*source: PRD §9.7, §8.4; verify: integration; story: A-33*)
- **FR-IMPORT-2** — Import MUST require no GitHub account, token, or authentication, and the app MUST NOT support Git push in v1.0. MUST (*source: PRD §9.7; verify: integration; story: A-33*)
- **FR-IMPORT-3** — The app MUST let the user select a subfolder/branch (ref) to import and SHOULD preview the file list before writing, warning on conflicts with existing board files. MUST/SHOULD (*source: PRD §9.7; verify: widget/integration; story: A-33*)
- **FR-IMPORT-4** — Imported files MUST be stored locally so work continues offline after import; the local project remains the source of truth (import is a project source, not the storage model). MUST (*source: PRD §9.7, §13.5; verify: integration; story: A-33*)
- **FR-IMPORT-5** — Import MUST be `.py`/data only and MUST NOT fetch or write `.mpy`/`.pyc`. MUST (*source: PRD §9.7, §10.14; verify: unit; story: A-33*)
- **FR-IMPORT-6** — The app MUST record import provenance (repo URL, ref, subpath, commit SHA, file count, timestamp) in the local `github_imports` data per §8. MUST (*source: PRD §12.1; verify: unit; story: A-33*)

### 4.10 Blocks & Plots — FR-BLOCKS / FR-PLOTS

- **FR-BLOCKS-1** — The app MUST provide a Blockly block editor (WebView, `lib/blocks/`) that generates an inspectable, board-neutral MicroPython subset with **no board-specific defaults**. The explicit `pyble_st7789` TFT surface MUST remain bundled and usable offline, but its generated import requires either the exact `waveshare-esp32-s3-lcd-147b` firmware or a separately user-installed API-compatible module; lean `esp32-s3-n16r8` firmware makes no bundled TFT-runtime claim. The app MUST NOT use a chip or provisioning-profile allowlist to hide, enable, select, or gate these tools. MUST (*source: PRD §9.8, §16.1; verify: integration; story: A-31*)
- **FR-BLOCKS-1A — Android input and test isolation (FROZEN · A-31 · `[docs]`
  2026-08-07).** Native GPIO fields in the example chooser MUST retain focus
  and accept ordinary software-keyboard input on supported Android tablets.
  Responsive keyboard-inset changes and every per-keystroke validation rebuild
  MUST retain the same role-scoped field/controller/input client, including
  staged multi-digit entry, deletion, and re-entry.
  Editing or validating a GPIO draft MUST NOT invoke the Blockly platform view;
  production generation occurs only after an explicit Preview, Create copy, or
  Replace workspace action. The bundled host MUST request configuration with a
  versioned JavaScript-channel readiness event emitted once per page generation
  and only after its authored API exists. An allowed main-frame reload MUST
  start a fresh host epoch, readiness gate, and bounded watchdog; an exact
  duplicate readiness event in one generation is swallowed and MUST NOT enter
  the document bridge. Readiness is committed only after host configuration
  succeeds; a failed or in-flight attempt MUST NOT consume the real readiness
  event. Every post-configuration bridge envelope MUST echo the positive Dart
  host epoch. A valid message from another epoch is ignored; a missing or
  malformed epoch fails visibly. Native WebView controller setup MUST execute
  and finish
  sequentially—JavaScript mode, JavaScript channel, then navigation delegate—
  before the single bundled-asset load begins. The startup future MUST own its
  error handler immediately and MUST stop between phases after disposal. A
  main-frame resource error with no assignable page epoch MUST rely on the
  owned asset-load rejection or generation watchdog rather than be attributed
  to a mutable host. Startup MUST NOT use a delay,
  poll, or automatic reload; it remains bounded by the existing watchdog and
  MUST fail visibly instead of polling without limit. Android device-test
  builds MUST use an application ID distinct from the normal
  `dev.pyble.pyble` launcher so test installation and cleanup cannot replace or
  uninstall the user-facing app. Android development, build, and run commands
  MUST name either the `production` or `integration` flavor; contributor
  guidance MUST NOT leave the application ID implicit.
  The native semantic-empty check MUST accept Blockly's canonical empty
  workspace serialization (`{}`) as empty, while null, malformed,
  variable-only, and non-empty graphs remain non-empty or unknown. A
  successfully loaded canonical empty workspace MUST show the empty-workspace
  actions and MUST NOT be labelled as still loading.
  CI MUST compile the `production` release APK after host tests so a dev-only
  integration plugin can neither break nor enter the production artifact.
  MUST (*source: PRD §13.6, §16.1; verify: widget/Android physical-device;
  story: A-31/X-11*)
- **FR-BLOCKS-1B — Explicit named pins (FROZEN · A-38 · `[docs]`
  2026-08-12).** Every GPIO identity slot in the authored Blockly host,
  example chooser/materializer, and bounded Python importer MUST accept either
  its existing explicit non-negative integer form or an ASCII, case-sensitive
  MicroPython `machine.Pin` name matching
  `^[A-Za-z][A-Za-z0-9_]{0,15}$`. The block input MUST accept ordinary Blockly
  `Number` or `String` values; examples MUST materialize integers as
  `math_number` and names as `text`; generated Python MUST keep integers bare
  and quote names (`Pin(2, ...)`, `Pin("LED", ...)`). The importer MUST accept
  single- or double-quoted names under the same grammar and retain its
  all-or-nothing semantic round-trip. Invalid identities MUST use the existing
  repairable/`invalid_gpio` paths. Names MUST remain explicit user program
  data: the app MUST NOT ship a per-board list, suggestion, default,
  autocomplete, translation, `DeviceInfo`/profile gate, or automatic example
  choice. Example-role uniqueness MUST compare canonical integer/name values;
  all new visible guidance/errors MUST be ARB-sourced. The connected
  MicroPython runtime remains authoritative for physical validity. MUST
  (*source: ADR-0031, ADR-0021; verify: unit/asset/widget/integration/HIL;
  story: A-38*)
- **FR-BLOCKS-2** — Generated code MUST be inspectable as plain `.py` and MUST flow through the same upload/run path as the text editor (§8.2). MUST (*source: PRD §9.8; verify: integration; story: A-31*)
- **FR-BLOCKS-3** — The app MUST allow running or saving the generated code through the `Connection` API. MUST (*source: PRD §9.8; verify: integration; story: A-31*)
- **FR-BLOCKS-4** — The block bridge MUST bind to `Connection`/neutral types
  and carry no board-specific profile, copied catalog/curriculum,
  domain-specific lesson flow, or proprietary/classroom pedagogy. Fresh generic
  onboarding examples are permitted only under FR-BLOCKS-7..9. MUST (*source:
  PRD §9.8, app.md §6; verify: unit (no-leak gate); story: A-31*)
- **FR-BLOCKS-5** — The GPIO toolbox MUST provide composable generic digital
  `machine.Pin` construction, write, and read blocks; generate the standard
  MicroPython import/calls; and require one explicit pin identity: either the
  existing non-negative integral numeric literal or FR-BLOCKS-1B's bounded
  user-entered name. It MUST NOT contain or infer a board pin map, suggested
  named onboard component, routing profile, or claimed default/safe pin. This
  integer/named-pin subset does not claim that a syntactically accepted
  identity exists or is electrically suitable on every MicroPython port;
  broader pin models require a later frozen block contract. MUST (*source: PRD
  §9.8, §11.3, ADR-0031; verify: unit/integration; story: A-31/A-38*)
- **FR-BLOCKS-6** — The **Time** toolbox category MUST provide
  `pyble_time_sleep_ms`, a statement block with a required explicit finite,
  non-negative integral `MILLISECONDS` literal, no shadow/default, and
  deterministic exact-once `from time import sleep_ms` generation. MUST
  (*source: PRD §9.8; verify: unit/integration; story: A-31*)
- **FR-BLOCKS-7** — The app MUST ship an offline, versioned catalog containing
  exactly the eight editable starter workspaces `hello-pyble`,
  `count-repeatedly`, `blink-led`, `blink-neopixel`, `read-button`,
  `button-controls-led`, `reusable-function`, and
  `waveshare-esp32-s3-lcd-147b`. Previewed source MUST be
  produced by the production Blockly Python generator rather than stored
  separately, and a loaded example MUST become ordinary Blockly workspace JSON.
  Hardware examples, including `blink-neopixel` and the exact-board TFT
  example, MUST keep every GPIO role disconnected until the user enters it.
  Localized TFT-example copy MUST name the exact Waveshare firmware or a
  user-installed API-compatible module as the runtime prerequisite and state
  that lean generic S3 firmware does not bundle it.
  MUST (*source: PRD §9.8; verify: unit/integration; story: A-31*)
- **FR-BLOCKS-8** — Example Preview MUST NOT mutate the active workspace.
  Create copy MUST load an independent editable clone only over a semantically
  empty workspace; a non-empty or invalid workspace MUST require confirmed
  Replace workspace. GPIO examples MUST require the user to enter every GPIO
  role before preview/copy, with pairwise-distinct canonical integer-or-name
  identities for separate roles, a localized duplicate-pin error, and no
  supplied, suggested, or remembered pin.
  No example operation may automatically Run, Save, write a board file, or
  replace the text-editor document. MUST (*source: PRD §9.8, §11.3; verify:
  unit/widget/integration; story: A-31*)
- **FR-BLOCKS-9** — Examples MUST be reachable from a prominent empty-workspace
  action, the persistent Blocks action strip, and an Examples toolbox category;
  all three entry points MUST open the same chooser. At constrained widths the
  strip MUST retain Examples in an accessible overflow, while compact chooser
  widths MUST use the adaptive bottom-sheet presentation and wider widths the
  dialog presentation. All example copy, validation, wiring, warning,
  confirmation, error, and semantics text MUST be ARB-sourced; controls MUST
  meet the app's accessibility target rules; and a loaded copy MUST use the
  normal workspace revision, recreation, rotation, and persistence/recovery
  path. Loaded success MUST NOT be announced before the active host acknowledges
  the restored candidate snapshot. MUST (*source: PRD §9.8, §9.10, §13.7, §19;
  verify: locale/widget/golden/integration; story: A-31*)
- **FR-BLOCKS-10** — A Blocks-origin Python file MUST have an exact-reopen
  companion at `<python-path>.pyble-blocks.json`. The version-1
  `pyble-blocks` envelope MUST bind the canonical source path, exact generated
  source text and UTF-8 byte length, non-security IEEE CRC-32 fingerprint,
  supported generator/Blockly versions, and ordinary workspace JSON. Blocks
  Save/Run MUST preflight both UTF-8 paths against PBLE/1's 128-byte ceiling
  before any PUT, upload the Python first and the matching sidecar last, and
  MUST NOT execute until both verified writes succeed. The coordinator MUST
  capture the local connection-facade session before the first PUT, revalidate
  it immediately before the sidecar PUT and Run, and refuse the next operation
  with a typed error if any attach/detach changed that session. This local
  action-consistency stamp MUST NOT be treated as board identity,
  authentication, or PBLE/1 data. Reopen MUST fail closed unless the adjacent
  Python matches the embedded source exactly and scratch
  restore→reserialize→production-generate preserves the workspace and source
  exactly. A stale, malformed, oversized, lossy, or unknown-version sidecar MUST
  leave the Python openable as text and MUST NOT mutate the active workspace.
  MUST (*source: ADR-0017; verify: unit/integration; story: A-31*)
- **FR-BLOCKS-11** — The app MUST provide an offline, all-or-nothing
  **Convert Python to Blocks** importer for the version-1 subset frozen in
  ADR-0017: simple literals/names and arithmetic/Boolean/comparison expressions;
  assignment and numeric change; one-argument `print`; `if`/`elif`/`else`,
  `while`, bounded literal non-empty `range`; bounded top-level procedures;
  explicit `machine.Pin` construction/read/write, including ADR-0031's bounded
  integer-or-quoted-name identity; explicit `time.sleep_ms`; and
  ADR-0018's exact standard NeoPixel subset (constructor, three-item RGB tuple,
  indexed assignment, `fill`, and `write` with a definitely bound receiver),
  plus ADR-0023's exact positional `ST7789` constructor, `rgb565`, framebuffer
  mutations, explicit `show`, and Boolean backlight subset with a definitely
  bound display receiver.
  Any syntax, unsupported construct, import/name/control-flow, numeric/resource,
  restore/generator, or semantic round-trip error MUST produce no candidate.
  The importer MUST NOT omit lines, emit a partial workspace, execute Python,
  use a raw-code escape block, choose/validate a board pin, or access the
  network. MUST (*source: ADR-0017, ADR-0018, ADR-0023, ADR-0031; verify:
  unit/asset/integration; story: A-31/A-38*)
- **FR-BLOCKS-12** — Exact reopen and Python conversion MUST share a
  non-mutating Preview/Create/Replace candidate flow. Diagnostics MUST carry a
  stable technical code/severity and one-based source range while all visible
  messages/actions/semantics are ARB-sourced. Preview MUST show the complete
  generated Python and target paths. Conversion MUST adopt
  `boardPathForDocument(capturedDocument)` as the Blocks target while exact
  reopen MUST adopt its validated bound source path; `/blocks.py` remains the
  default only for a workspace with no Python origin. Any captured document
  identity/content/name/path change MUST stale the candidate; Create MUST be
  limited to a structurally empty active workspace; Replace MUST be confirmed
  and atomic with rollback and active-host acknowledgement. Conversion and
  candidate actions MUST NOT implicitly Save, Run, replace the editor, mutate
  the console, call `Connection`, or perform board/network I/O. The compact
  bottom-sheet/wide-dialog surface MUST meet keyboard, screen-reader, focus,
  one-shot announcement, large-text/keyboard-inset, and 48 dp target
  requirements. MUST (*source: ADR-0017; verify:
  unit/widget/golden/locale/integration; story: A-31*)
- **FR-BLOCKS-13** — The **NeoPixel** toolbox category MUST provide the five
  stable composable types `pyble_neopixel_create`, `pyble_neopixel_rgb`,
  `pyble_neopixel_set_pixel`, `pyble_neopixel_fill`, and
  `pyble_neopixel_write`. They MUST generate only the standard
  `neopixel.NeoPixel` constructor, RGB tuple, indexed buffer assignment,
  `fill`, and explicit `write` APIs, with an exact-once unaliased import.
  Construction MUST reuse an explicit `Pin`, require a positive integral pixel
  count, and provide no GPIO/count/colour shadow or default. Mutation MUST NOT
  write automatically. Required-input and invalid-count failures MUST retain
  the editable workspace through the existing generator-error recovery path;
  no block may infer an onboard component, board/chip profile, GPIO, RGBW
  topology, timing, or brightness. MUST (*source: PRD §9.8, ADR-0018; verify:
  unit/asset/integration; story: A-31/F-24*)
- **FR-BLOCKS-14** — The **TFT Display** toolbox category MUST provide exactly
  the eight stable composable types `pyble_tft_create`, `pyble_tft_rgb565`,
  `pyble_tft_fill`, `pyble_tft_pixel`, `pyble_tft_rect`, `pyble_tft_text`,
  `pyble_tft_show`, and `pyble_tft_backlight`. Construction MUST take, in
  order, explicit `SPI_ID`, `BAUDRATE`, `POLARITY`, `PHASE`, `SCK`, `MOSI`,
  `CS`, `DC`, `RESET`, `BACKLIGHT`, `WIDTH`, `HEIGHT`, `X_OFFSET`, `Y_OFFSET`,
  `BGR`, and `INVERSION` values and generate the exact positional
  `ST7789(spi_id, baudrate, polarity, phase, sck_pin, mosi_pin, cs_pin, dc_pin,
  reset_pin, backlight_pin, width, height, x_offset, y_offset, bgr, inversion)`
  API. The six pin inputs MUST consume explicit `Pin` values, and every socket
  MUST be connected with no shadow/default. The other blocks MUST generate only
  `rgb565(red, green, blue)`, `display.fill(color)`,
  `display.pixel(x, y, color)`, `display.rect(...)` or
  `display.fill_rect(...)` from an explicit outline/filled choice,
  `display.text(text, x, y, color)`, `display.show()`, and
  `display.backlight(on)`. Framebuffer mutations MUST NOT imply `show`, and
  construction MUST NOT imply backlight-on. Imports MUST be exact-once and
  use-dependent: the constructor owns `from pyble_st7789 import ST7789`, the
  colour block owns `from pyble_st7789 import rgb565`, and ordinary GPIO blocks
  remain the sole owner of `from machine import Pin`. No TFT block may infer a
  bus, pin, geometry, offset, colour order, inversion, board identity, or
  display capability. The category MUST remain visible regardless of
  `DeviceInfo`, MUST NOT auto-select the exact-board example or gate a
  connection, and MUST surface an unavailable module through the ordinary
  generated-code import/runtime error path. MUST (*source: PRD §9.8,
  ADR-0023, ADR-0028; verify: unit/asset/integration; story: A-31/F-24*)

**A-31 increment — FROZEN (`[docs]` 2026-07-27,
[ADR-0013](../../decisions/0013-clean-room-blockly-one-way-file-backed.md)).**
The Blockly JSON workspace is authoritative in the baseline visual workflow,
which is one-way: **Blocks → generated Python**. ADR-0017 later adds only an
exact sidecar reopen and an explicit bounded Python import; it does not add
live bidirectional synchronization. Every material workspace change yields
one immutable `{source, workspaceJson, revision}` snapshot. Preview, Open in
editor, Save, and Run each await, revalidate, and freeze a fresh non-empty
snapshot acknowledged by the active host epoch; one action lock serializes
these source consumers. A Dart request ID echoed only by the corresponding
snapshot/error prevents ordinary change snapshots from authorizing an action.
Preview shows selectable, read-only plain `.py`; Save uploads
it to `/blocks.py`; Run uploads it to the same target and calls `runFile` only
after the CRC-verified upload succeeds. Recreated hosts return to loading and
cannot act until restoration publishes a new revision; delayed old-host
messages are ignored. These operations use the shared file-backed Dart program
actions also used by the text editor; the WebView never receives a `Connection`
or performs board I/O. Generator errors leave the workspace editable but disable
stale source actions until a valid snapshot arrives. Errors before the first
accepted epoch snapshot and host/startup failures are contained behind Retry;
the watchdog is not cancelled by a stale pre-restore revision. A confirmed
Start fresh discards unrecoverable retained JSON without changing the board.
“Open in editor” copies the freshly acknowledged snapshot into an independent
dirty `blocks.py` document and confirms
before replacing a different dirty editor buffer; text edits never round-trip
to Blocks. The initial toolbox is the standard, MicroPython-compatible language
subset (logic, loops, math, text, lists, variables, functions), with no board
profile, hardware mapping/default, copied catalog, or pedagogy. All runtime
assets are local and pinned; only the exact bundled main-frame asset is admitted
and external navigation/network is denied. Workspace JSON is retained across
in-process view recreation; durable project persistence remains the explicit
A-24 hook and is not claimed by this increment.

**A-31 responsive placement — FROZEN (`[docs]` 2026-07-28,
[ADR-0014](../../decisions/0014-focused-blocks-landscape-workspace.md)).**
Blocks is a first-class destination in both landscape rail and stacked
navigation. In landscape, selecting it replaces the Files, Editor/Console, and
Pin Reference panes with a focused workspace while retaining the application
toolbar. The toolbar's editor-targeted Run is hidden; the feature action strip
exposes the single Blocks Run beside Preview, Open in editor, and Save. Global
Stop and Soft-reboot remain available. The generated-Python inspector is
360–420 dp wide and appears only when Blockly still receives at least 720 dp
and 60% of usable focused width; otherwise it is omitted. Notices and action
state remain outside the editable canvas. The Blocks console is collapsed/on
demand and expands after Run or new output. Serialized workspace state survives
navigation, platform-view recreation, and rotation between the focused
landscape and stacked portrait surfaces. These requirements are fresh PyBLE
layout behavior only; no third-party product source, asset, styling
implementation, identifier, or block catalog is copied.

**A-31 generic digital GPIO, extended by A-38 named pins — FROZEN (`[docs]`
2026-08-12, [ADR-0015](../../decisions/0015-generic-micropython-gpio-blocks.md),
[ADR-0031](../../decisions/0031-explicit-named-micropython-pins.md)).**
The GPIO category contains three stable, composable block types:
`pyble_gpio_pin` is a `Pin`-valued constructor with required `GPIO` input
accepting `Number|String`, `MODE` = `IN|OUT`, and
`PULL` = `NONE|UP|DOWN`;
`pyble_gpio_write` is a statement with required `Pin` input `PIN` and
`LEVEL` = `LOW|HIGH`; and `pyble_gpio_read` is a `Number` value with required
`Pin` input `PIN`. Standard variable set/get blocks own storage and reuse. A
workspace with one or more constructors emits exactly one
`from machine import Pin` before executable code and reserves `Pin` against
user-name collision. `NONE` emits an explicit `None` pull argument,
`UP`/`DOWN` emit `Pin.PULL_UP`/`Pin.PULL_DOWN`, write emits `.value(0|1)`, and read emits
`.value()`. Output construction does not imply an initial level; deterministic
level changes require an explicit write. Missing inputs, an invalid GPIO
identity, or unknown enum tokens are generator errors using the existing
editable-workspace/stale-actions-disabled recovery boundary. If the workspace
serialized successfully, that error payload MUST retain its current JSON and
next monotonic revision so a recreated host restores the invalid-but-repairable
workspace. An integer identity remains bare; a name matching
`^[A-Za-z][A-Za-z0-9_]{0,15}$` is generated as a double-quoted string, so the
standard forms include `Pin(2, Pin.OUT, None)` and
`Pin("LED", Pin.OUT, None)`. A valid workspace-bearing error, including the first result from a
restored host, MUST stop the host watchdog and keep the editor repairable while
actions stay disabled until the active host publishes a later valid snapshot.
No toolbox shadow, pin default, name suggestion, or pin catalog is supplied,
and the app does not
validate physical pin/mode/pull suitability from `DeviceInfo`; standard
MicroPython on the board is authoritative. GPIO source remains ordinary
`/blocks.py` content using the same Preview/Open/Save/Run path, with no new
WebView-to-board, PBLE/1, or firmware operation.

**A-31 beginner examples and Time block, extended by A-38 named pins — FROZEN
(`[docs]` 2026-08-12,
[ADR-0016](../../decisions/0016-offline-beginner-blockly-examples.md),
[ADR-0031](../../decisions/0031-explicit-named-micropython-pins.md)).**
A fresh **Time** category adds `pyble_time_sleep_ms`, a statement with a
required `Number` input `MILLISECONDS`, no shadow/default, exact-once
`from time import sleep_ms`, reserved-name protection, and
`sleep_ms(<milliseconds>)` generation. The literal must be finite,
non-negative, and integral; invalid/tampered input follows the normal
editable-workspace generator-error boundary.

The local catalog at `app/assets/blockly/examples/catalog.json` is version 3 and
contains exactly `hello-pyble`, `count-repeatedly`, `blink-led`,
`blink-neopixel`, `read-button`, `button-controls-led`, and
`reusable-function`, followed by `waveshare-esp32-s3-lcd-147b`, in that order.
Each fixture is
ordinary Blockly serialization plus stable technical metadata and ARB keys.
The catalog does not duplicate generated Python. Opening, browsing, selecting,
or editing a GPIO draft does not invoke the platform view or production
generator. Only an explicit **Preview**, **Create copy**, or **Replace
workspace** action restores a deep clone and invokes the production generator
for the selectable, read-only source preview. Before that action, the preview
surface MUST state that generation awaits an action; it MUST show a loading
state only while generation is actually in progress. A GPIO fixture contains
disconnected constructor sockets and role bindings only; the user must provide
each pin identity as either a non-negative exact-safe integer or a name matching
FR-BLOCKS-1B before source is previewed or copied, and canonical values for
separate roles must be pairwise distinct. A repeated integer or exact
case-sensitive name produces a localized field error; this does not claim
physical board validity.
While a required GPIO is absent or invalid, the source surface describes that
entering every required GPIO enables generation; it does not promise automatic
generation.
Materialization connects an ordinary `math_number` block for an integer or
ordinary `text` block for a name in the clone and leaves no role placeholder or
metadata in the active workspace. No board/chip default, named-component
suggestion, remembered pin, or claimed safe value is supplied.
Wiring notes identify the roles, an external LED/resistor or button/pull
behavior where relevant, and direct the user to their board documentation.
The eighth fixture is the only named-board example. It contains the exact
`ESP32-S3-LCD-1.47B` spelling and six disconnected GPIO roles for SCLK, MOSI,
CS, D/C, reset, and backlight. Its ordinary visible values configure SPI bus
1 at 40 MHz with polarity 0 and phase 0, 172 × 320 geometry, offsets 34 and 0,
BGR order, and inversion. The localized wiring note states the documented
B-board GPIO values 40, 45, 42, 41, 39, and 46 respectively, warns that the
non-B board differs, and still requires the user to enter all six values.
Selecting, previewing, or loading this example never reads `DeviceInfo`, checks
a chip/capability, chooses a pin, gates a connection, or implies that another
board has a display. Localized compatibility copy states that exact
`waveshare-esp32-s3-lcd-147b` firmware bundles the runtime, lean
`esp32-s3-n16r8` does not, and a user-installed API-compatible module is an
alternative.

Preview is non-mutating. **Create copy** is available for a semantically empty
workspace. A workspace containing any block, variable, or procedure—including
an incomplete graph—offers **Replace workspace** instead and requires
confirmation. Cancel and catalog/materialization/generator/load/restore failure
preserve or restore the existing workspace. Loading never invokes Connection,
Run, Save, editor hand-off, or board I/O. The app announces loaded success only
after the active host accepts the restored candidate snapshot. The resulting
copy then uses the standard retained workspace/revision, invalid-state recovery,
host-epoch restore, rotation, and future A-24 durable persistence paths; catalog
fixtures remain immutable.

A prominent empty-canvas Examples action, a persistent Examples action in the
Flutter Blocks strip, and an Examples toolbox category open the same catalog
chooser. At constrained widths Examples moves first into a labelled, keyboard-
and screen-reader-reachable overflow rather than scrolling or shrinking the
canvas; further non-Run actions may join it if needed. Below 600 dp the chooser
is a scroll-controlled modal bottom sheet; at 600 dp and wider it is a dialog.
Catalog titles, summaries, concepts, role labels, wiring notes, warnings,
confirmations, validation/errors, buttons, and semantic labels are ARB-sourced.
Controls are keyboard reachable, expose their state, use ≥ 48 dp targets,
preserve focus on validation failure, announce each completed preview once and
loaded success only at the active-host acknowledgement boundary, and scroll
rather than clip under large text. These are fresh generic onboarding templates,
not a copied block catalog, curriculum, grading flow, domain-specific exercise,
or proprietary pedagogy.

**A-31 standard NeoPixel — FROZEN (`[docs]` 2026-07-28,
[ADR-0018](../../decisions/0018-standard-micropython-neopixel.md)).**
The NeoPixel category contains five stable blocks. `pyble_neopixel_create`
returns `NeoPixel` from required `PIN: Pin` and `PIXELS: Number` inputs;
`pyble_neopixel_rgb` returns `NeoPixelColor` from required
`RED/GREEN/BLUE: Number` inputs; `pyble_neopixel_set_pixel` assigns a required
colour to a required index on a required strip; `pyble_neopixel_fill` fills a
strip buffer; and `pyble_neopixel_write` transmits that buffer. The constructor
requires a finite positive integral literal count, owns one
`from neopixel import NeoPixel` definition, and reserves `NeoPixel`; the
existing GPIO constructor remains the sole owner of `Pin` and its import.
Disconnected receivers/values, multiline generation, or an invalid count
produce the same workspace-bearing repairable generator error used by GPIO.
RGB component/index expressions remain ordinary connected numeric expressions,
whose dynamic type/range errors belong to MicroPython.

Set/fill never call `write` implicitly. Off is an explicit `(0, 0, 0)` buffer
change followed by write; blink is composed from those blocks, a finite loop,
and Time. The toolbox contains no board or onboard-LED name, pin/count/colour
default, brightness transform, RGBW/timing extension, PBLE/1 operation, or
network path. Catalog version 2 introduced the ordinary `blink-neopixel` workspace
after `blink-led`: one pixel, index zero, dim colour/off, explicit writes,
finite delays/repeats, and one disconnected user-supplied GPIO role.

The bounded importer additionally admits only the exact unaliased,
use-dependent `from neopixel import NeoPixel`, a definitely bound NeoPixel
variable created as `NeoPixel(Pin(...), positive_count)`, three-item RGB tuples,
indexed colour assignment, `.fill(tuple)`, and `.write()`. Aliases, keywords,
RGBW/timing arguments, malformed arity, invalid counts, and calls on a receiver
not definitely bound to a NeoPixel variable reject the complete conversion.
Semantic round-trip equality includes the NeoPixel import, binding, operations,
indices, and tuple expressions.

**A-31 explicit ST7789 TFT — FROZEN (`[docs]` 2026-08-01,
[ADR-0023](../../decisions/0023-explicit-st7789-user-runtime.md)).**
The TFT Display category contains the eight stable types in FR-BLOCKS-14.
It is a target-neutral authoring surface, not proof that the connected runtime
supplies its import. The exact `waveshare-esp32-s3-lcd-147b` firmware freezes
`pyble_st7789`; lean `esp32-s3-n16r8` does not. A user MAY install a compatible
module separately. No connection, category, or example visibility may be gated
by that provisioning distinction.
`pyble_tft_create` returns `ST7789` and has required Number inputs
`SPI_ID`, `BAUDRATE`, `POLARITY`, `PHASE`, `WIDTH`, `HEIGHT`, `X_OFFSET`, and
`Y_OFFSET`; required Pin inputs `SCK`, `MOSI`, `CS`, `DC`, `RESET`, and
`BACKLIGHT`; and required Boolean inputs `BGR` and `INVERSION`. It emits the
16 values in exactly that order as one positional `ST7789(...)` call. The
constructor owns exactly one `from pyble_st7789 import ST7789`; the colour block
owns exactly one `from pyble_st7789 import rgb565`; when both are used the two
lines occur once each in deterministic `ST7789`-then-`rgb565` definition order.
Nested GPIO constructors alone own `from machine import Pin`.

`pyble_tft_rgb565` returns `TFTColor` from `RED`, `GREEN`, and `BLUE` Number
inputs. `pyble_tft_fill`, `pyble_tft_pixel`, `pyble_tft_rect`, and
`pyble_tft_text` mutate only the display framebuffer through the exact
`fill`, `pixel`, `rect`/`fill_rect`, and `text` methods. The rectangle block has
an explicit `OUTLINE|FILLED` field; the latter is the only path that emits
`fill_rect`. `pyble_tft_show` is the sole framebuffer-transfer block, and
`pyble_tft_backlight` passes its required Boolean `ON` input to
`display.backlight(on)`. All required inputs have no shadow/default. The
constructor validates literal SPI ID, frequency, mode, geometry, and offsets;
the ordinary connected expressions for coordinates, text, and colour remain
runtime values. A failure is the existing workspace-bearing repairable
generator error. No block performs board detection, imports `machine.SPI`,
turns on the backlight during construction, implies `show` after mutation, or
contains Waveshare wiring.

The bounded importer accepts only the exact unaliased, use-dependent leading
imports above; the exact positional 16-argument constructor; `rgb565` with
three arguments; and the listed methods on a definitely bound `ST7789`
receiver. The six constructor pin arguments must be explicit `Pin` values;
numeric/mode/geometry/offset and Boolean arguments must preserve the same
block-representable semantics. Keyword arguments, aliases, wrong order/arity,
an unsupported method, or a receiver that is not definitely bound reject the
complete conversion. Semantic round-trip equality includes both TFT imports,
the complete constructor configuration, RGB conversion, receiver bindings,
every draw operation, explicit show, and backlight state.

**A-31 exact sidecar reopen and bounded Python import — FROZEN (`[docs]`
2026-07-28,
[ADR-0017](../../decisions/0017-blocks-sidecar-and-bounded-python-import.md)).**
For active source target `P`, the companion is exactly
`P + '.pyble-blocks.json'`; the default pair is `/blocks.py` and
`/blocks.py.pyble-blocks.json`. The ≤1 MiB UTF-8 version-1 envelope has
`format: "pyble-blocks"`, `version: 1`, exact source
`{path, encoding, byteLength, crc32, text}`, supported generator
`{id, version, blockly}`, and ordinary `workspace`. CRC is the existing
IEEE/zlib algorithm rendered as eight lowercase hexadecimal digits and is only
an accidental-corruption/torn-pair fingerprint. Exact source equality is
required.

Save/Run freeze one acknowledged snapshot, upload its exact Python first, then
upload the matching sidecar as the pair commit record; both full UTF-8 paths are
preflighted against PBLE/1's 128-byte limit before either PUT. Run follows only
when both verified writes succeed. The coordinator pins the facade's local
session before the first PUT and revalidates it before the sidecar PUT and Run;
any attach/detach causes a typed refusal before the next verb, so an action
cannot cross boards. This opaque in-memory stamp is neither board identity nor
authentication/wire data. Reopen validates schema/path/version/bounds, requires
exact adjacent source bytes/text/length/CRC, round-trips the workspace through a
disposable host without structural loss, and requires production generation to
equal the embedded source byte-for-byte. Failure leaves Python available as
text and does not touch the live workspace. A text-editor change simply makes
an older sidecar stale; the editor neither silently rewrites nor deletes it.

The v1 importer accepts at most 256 KiB/4,096 lines/20,000 nodes/32 indentation
levels of spaces-indented UTF-8. It admits only ADR-0017's enumerated literals,
names, unary/arithmetic/Boolean/single-comparison expressions, simple
assignment/`+=`, one-argument `print`, conditionals, `while`, non-empty
literal `range`, bounded top-level procedures (≤16, ≤8 positional parameters),
explicit standard `Pin` with either its existing non-negative decimal integer
or FR-BLOCKS-1B's single-/double-quoted name, and literal `sleep_ms`. Canonical
imports are exact, unaliased, and use-dependent. Numeric literals fit JavaScript's exact
safe-integer bound where Blockly needs integral values; `range` has a non-zero
literal step and a direction that makes it non-empty. Integral-valued decimal
float syntax and raw U+0000 strings are rejected because ordinary Blockly
number/text generation cannot preserve them as valid, type-equivalent Python.
Unsupported syntax and comments/docstrings are errors, not omissions.

Conversion is
tokenize/validate → typed subset model → ordinary workspace → scratch restore
and production generation → reparse → semantic-model equality. Any error
produces diagnostics and no candidate; no recognized fragment is retained
alone, no raw-code block exists, and Python is never evaluated. Warnings may
describe visible formatting/layout normalization only. Diagnostics use stable
technical codes plus one-based end-exclusive source ranges and ARB message
keys.

The editor's explicit **Convert Python to Blocks** captures the entire immutable
editor document and adopts `boardPathForDocument(capturedDocument)` as `P`.
That action and a valid pair's **Open as Blocks** action lead to one
non-mutating adaptive Preview. The complete
generated source and both target paths are visible. A conversion candidate is
bound to the captured document identity/content/name/board path and becomes
stale on any change. Exact reopen adopts the validated sidecar source path;
workspaces without either origin retain the `/blocks.py` default. Structurally
empty Blocks offers Create;
otherwise confirmed Replace uses ADR-0016's exact rollback and active-host
acknowledgement. Below 600 dp the shared surface is a scroll-controlled bottom
sheet; at wider sizes it is a dialog. It retains ≥48 dp controls, keyboard/focus
and screen-reader semantics, one-shot announcements, and scrolling under large
text/keyboard insets. Parsing/validation/Preview/Create/Replace/cancel call no
Connection, Save, Run, editor replacement, console, board-write, or network
operation. Only an explicit file-open may read the selected pair, and only the
existing explicit Blocks Save/Run writes it or executes Python.

**A-38 explicit named MicroPython pins — FROZEN (`[docs]` 2026-08-12,
[ADR-0031](../../decisions/0031-explicit-named-micropython-pins.md)).**

**Story.** As a user of a compatible MicroPython board whose hardware is
addressed by a standard named `machine.Pin` rather than a numeric GPIO, I want
to enter the exact documented name in the existing Blocks GPIO surfaces so
that I can preview, save, and run truthful Python without PyBLE carrying a
board profile. The concrete validated case is the Pico 2 W onboard LED,
addressed as `Pin("LED")`; the story is capability-defined and is not a
Pico-only UI feature.

**Scope.** A-38 extends only the pin-identity value accepted by
`pyble_gpio_pin`, example GPIO roles, and ADR-0017's bounded importer. It does
not add a block type, firmware/PBLE operation, board/name registry, default,
suggestion, device gate, automatic example choice, or physical-validity claim.
All existing one-way workspace, error retention, explicit example action,
atomic replacement, exact sidecar, file-backed Save/Run, localization,
offline, and no-leak boundaries remain in force.

The acceptance criteria test authors MUST convert to `[red]` before the A-38
implementation:

- **A38-AC-1 (identity grammar)** — Each affected surface MUST preserve its
  existing non-negative integer semantics and additionally accept only a
  case-sensitive ASCII name matching `^[A-Za-z][A-Za-z0-9_]{0,15}$`. The
  one- and sixteen-character boundaries MUST pass; empty, digit-led,
  digits-only, spaced, hyphenated, non-ASCII, escaped, overlength, variable,
  and arbitrary-expression forms MUST fail through the existing invalid-pin
  path. MUST
- **A38-AC-2 (ordinary Blocks and deterministic source)** — The GPIO input
  MUST accept only ordinary Blockly `Number|String` values with no
  shadow/default. Integers MUST use `math_number` and generate bare; names MUST
  use `text` and generate as a quoted literal. A composed workspace containing
  `LED` MUST generate `Pin("LED", ...)`, retain exact-once `machine.Pin`
  import/name reservation, and remain repairable after an invalid identity.
  MUST
- **A38-AC-3 (examples)** — The native chooser MUST accept integer and named
  roles, allow mixed forms, use a full text keyboard with suggestions and
  autocorrection disabled, and materialize a deep clone with the matching
  ordinary value-block type. Distinctness MUST compare canonical typed values;
  duplicate integers or exact case-sensitive names MUST show localized errors.
  No fixture, selection, or reopening MAY supply or remember a pin. MUST
- **A38-AC-4 (bounded import)** — `Pin(2, ...)`, `Pin("LED", ...)`, and
  `Pin('WL_GPIO0', ...)` MUST import to the corresponding ordinary value
  blocks and pass generate→reparse semantic equality, including identity kind
  and value. One invalid identity MUST yield `invalid_gpio` and no partial
  candidate. Quote spelling MAY normalize; exact sidecar reopen remains
  byte-exact. MUST
- **A38-AC-5 (target neutrality and action safety)** — Validation/generation
  MUST NOT read `DeviceInfo`, a provisioning profile, connection state, or a
  pin catalog; Preview/Create/Replace MUST perform no Connection, Save, Run,
  board, or network operation. MicroPython MUST remain the physical-validity
  authority and its exception MUST remain visible. MUST
- **A38-AC-6 (regression and hardware evidence)** — Unit, asset, widget, real
  WebView, locale, offline/CSP, license, no-leak, and integration gates MUST
  cover both identity branches without regressing numeric ESP32,
  NeoPixel/TFT composition, or exact reopen. On the validated Pico 2 W, the
  existing Blink example with user-entered `LED` MUST run through the ordinary
  file-backed path and blink the physical onboard LED; that evidence MUST NOT
  be converted into an app-side Pico profile. MUST

- **FR-PLOTS-1** — The app MUST provide live plots (`fl_chart`, `lib/plots/`) over CSV/streamed values printed by the running program to the console stream. MUST (*source: PRD §9.8, §16.1; verify: widget/integration; story: A-32*)
- **FR-PLOTS-2** — Plotting MUST be derived purely from program console output (no special data-event opcode); the app SHOULD let the user configure how console output is parsed into series. MUST/SHOULD (*source: PRD §9.8; verify: unit/widget; story: A-32*)
- **FR-PLOTS-3** — Plots MUST bind to `Connection`/`ConsoleEvent` neutral types and carry no board-specific profile or pedagogy. MUST (*source: PRD §9.8, app.md §6; verify: unit; story: A-32*)

### 4.11 Beginner-Friendly Error Explanation — FR-ERR

- **FR-ERR-1** — The app MUST detect common MicroPython errors from the `stderr` traceback stream and present a plain-language explanation alongside the raw traceback. MUST (*source: PRD §9.9; verify: unit/widget; story: A-21*)
- **FR-ERR-2** — The explanation layer MUST NOT replace or hide the original traceback — it annotates it. MUST (*source: PRD §9.9, §2; verify: widget; story: A-21*)
- **FR-ERR-3** — The app MUST cover at least common beginner cases (e.g. `NameError` from a missing `from machine import …`, `IndentationError`, `ImportError` for a module absent from `/lib`, `OSError: ENOENT`, `MemoryError`) with a one-line suggested fix each. MUST (*source: PRD §9.9; verify: unit; story: A-21*)
- **FR-ERR-4** — Error mappings MUST be data-driven so new mappings can be added without code changes, and MUST be localizable (sourced from ARB per §4.12). MUST (*source: PRD §9.9, §9.10; verify: unit/locale; story: A-21*)

### 4.12 Localization (`lib/localization/`) — FR-I18N

- **FR-I18N-1** — The app MUST ship English (`en`) ARB strings from day one, and any user-facing string added in a commit MUST ship its `en` entry in the same commit. MUST (*source: PRD §9.10, §13.7; verify: locale; story: X-12*)
- **FR-I18N-2** — Any additional shipped language MUST meet enforced ARB key parity with `en`; a CI/test check MUST fail on missing or orphaned keys (and MUST block the merge). MUST (*source: PRD §9.10, §13.7, §21.1; verify: locale; story: X-12*)
- **FR-I18N-3** — All user-facing strings — including error explanations (§4.11), connection diagnostics (§4.3), and file-operation messages (§4.5) — MUST be sourced from ARB, with no hard-coded display text. MUST (*source: PRD §9.10; verify: locale/unit; story: X-12*)
- **FR-I18N-4** — Technical identifiers (including opaque `DeviceInfo.chip` values such as `esp32`/`esp32-s3`/`esp32-c3`, paths, opcode/capability names, and PBLE/1 status names) MUST remain ASCII/verbatim and MUST NOT be localized. MUST (*source: PRD §13.7; verify: locale; story: X-12*)
- **FR-I18N-5** — The app SHOULD respect the platform locale by default and MAY let the user override the language in settings. SHOULD/MAY (*source: PRD §9.10; verify: widget; story: X-12*)

### 4.13 UI Layout & Responsiveness — FR-UI

- **FR-UI-1** — The connected tablet **landscape** shell MUST retain its top toolbar and NavigationRail. Its default text workbench MAY remain Files | Editor/Console | Pin Reference, but Blocks MUST be a first-class rail destination whose selection replaces those panes with one focused Blocks workspace. In Blocks focus, the toolbar's editor Run MUST be hidden and the feature action strip MUST expose exactly one Blocks Run; notices MUST stay outside the editable canvas; the console MUST be collapsed/on demand and expand after Run or new output; and the 360–420 dp generated-Python inspector MUST be omitted unless Blockly retains both ≥ 720 dp and ≥ 60% of usable focused width. The serialized Blocks workspace MUST survive rotation into and back from the stacked layout. MUST (*source: PRD §19.1; verify: widget/golden/integration; story: A-31/A-26*)
- **FR-UI-2** — The app MUST provide a tablet **portrait** stacked layout (toolbar, editor primary, bottom tab bar swapping Console/Files/Plot/Blocks) per [PRD §19.2](../prd.md), keeping the editor the primary surface. MUST (*source: PRD §19.2; verify: golden; story: A-20*)
- **FR-UI-3** — The application toolbar MUST expose the active connection action, Stop, and Soft-reboot mapped to the corresponding `Connection` methods. It MUST expose the editor-targeted Run in the text workbench and stacked Editor surface, but MUST hide that Run in Blocks focus, where FR-UI-1 assigns the sole generated-source Run to the Blocks action strip. MUST (*source: PRD §19.1; verify: widget; story: A-11/A-31/A-26*)
- **FR-UI-4** — The text workbench's right pane MUST host the read-only **target-keyed pin reference** selected by the opaque `chip` value from DEVICE_INFO; it MUST be informational warnings only and MUST NOT be an enforced or stored profile. An unknown target MUST render generic guidance to consult the exact board documentation and MUST NOT block the connection or imply that every pin is safe. MUST (*source: PRD §19.1, §11.3, hardware.md §3; verify: widget; story: A-22*)
- **FR-UI-5** — The layout MUST be tablet-first but MUST NOT break on a phone (phone is best-effort). MUST (*source: PRD §13.2, §19, app.md §5; verify: golden; story: A-20*)
- **FR-UI-6** — Interactive controls MUST use large touch targets and MUST clearly communicate connection and run state (disconnected/connecting/ready/running/error). MUST (*source: PRD §13.2; verify: golden; story: A-22*)
- **FR-UI-7** — No UI panel MUST bind to BLE directly; every panel binds to `Connection`. MUST (*source: PRD §19, app.md §1; verify: unit; story: all A-2x/3x*)

### 4.14 Scan/Connect Flow UI (`lib/connect/`) — FR-CONNECT

- **FR-CONNECT-1** — The connect screen MUST present a scan **filtered to the PyBLE service UUID**, listing each board by its **advertised name with RSSI** — the user-set device **label** when one is set, otherwise the default `PyBLE-XXXX` ([protocol.md §2](../protocol.md#2-ble-transport-gatt)) — and MUST NOT present a raw, unfiltered BLE device list. MUST (*source: PRD §9.6, §19.3, §8.1, protocol.md §2; verify: widget; story: A-22*)
- **FR-CONNECT-2** — On Connect, the app MUST open GATT, subscribe to TX notify, request MTU 247, read INFO / send HELLO, and display `DeviceInfo` (chip, MicroPython version, free memory) before enabling editor/console/file actions. MUST (*source: PRD §9.6, §19.3, §8.1; verify: integration; story: A-22*)
- **FR-CONNECT-3** — The screen MUST surface BLE permission and adapter state with localized rationale (iOS `NSBluetoothAlwaysUsageDescription`; Android `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` + older-Android location). MUST (*source: PRD §9.6, §19.3, app.md §5; verify: widget/integration; story: A-04/A-22*)
- **FR-CONNECT-4** — The screen MUST list **saved boards** and reconnect them by remembered identifier; on link loss the app MUST auto-reattempt and in-flight transfers MUST resume per [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core). MUST (*source: PRD §8.1, §19.3, §13.1; verify: integration; story: A-03/A-22*)
- **FR-CONNECT-5** — The flow MUST be scan → connect → use only: no pairing-code step, no account, no session-lock/heartbeat, and no board-identity gating (the non-goals of [PRD §4.3](../prd.md)). MUST (*source: PRD §8.1, §9.6, §19.3, §4.3; verify: widget; story: A-22*)
- **FR-CONNECT-6** — The connect flow MUST refuse a board with an unsupported `proto_version` and prompt to update the firmware/app rather than failing silently. MUST (*source: PRD §18.3; verify: widget/integration; story: A-10/A-22*)

### 4.15 About & Open-Source Information (`lib/app/`) — FR-ABOUT

**FROZEN (X-11 About-page subset · `[docs]` 2026-07-28).** This subset makes
the already-required Open-Source Notices surface reachable without claiming
that X-11's release pipeline or complete mechanically generated notice set is
finished.

- **FR-ABOUT-1** — A localized About action MUST be reachable from the global toolbar while disconnected, connecting, ready, or running and in every responsive layout. It MUST open a full route, require no board, perform no `Connection` verb or network request, and Back MUST restore the prior IDE surface and session state. MUST (*source: PRD §13.2, §15.1, §19; verify: widget/integration; story: X-11*)
- **FR-ABOUT-2** — The About page MUST identify PyBLE as a free, MIT, tablet-first MicroPython IDE designed for compatible MicroPython + BLE boards; it MUST distinguish the initial `esp32`/`esp32-s3`/`esp32-c3` firmware targets from the broader platform scope, show `pyble.dev`, and MUST NOT introduce a board profile, proprietary product identity, managed-teaching copy, or invented contributor credit. MUST (*source: PRD §1A, §2, §4.3, §15.1; verify: widget/no-leak; story: X-11*)
- **FR-ABOUT-3** — The page MUST display the installed package's runtime version and build number, localizing only the label/format. Loading, a blank build number, and metadata failure MUST each render truthfully; the static ASCII `kAppVersion` remains the PBLE/1 HELLO identifier and MUST NOT be reused as display metadata. MUST (*source: PRD §13.7, §18.1; verify: unit/widget; story: X-11*)
- **FR-ABOUT-4** — A clearly labelled Open-source licenses action MUST open Flutter's offline `LicenseRegistry` surface with PyBLE legalese and registered bundled-asset attribution. It MUST remain usable with no network and MUST NOT imply that X-11's full release notice-generation work is complete. MUST (*source: PRD §15.1, §15.2; verify: widget/unit; story: X-11*)
- **FR-ABOUT-5** — The page MUST state the frozen privacy posture: no account, no telemetry by default, user work remains on the tablet/connected board unless explicitly exported, and user-started public GitHub import is the sole optional network workflow. MUST (*source: PRD §13.5, §14.2; verify: widget/locale; story: A-28/X-11*)
- **FR-ABOUT-6** — Every display and semantics string MUST come from ARB; technical identifiers, versions, and URLs remain ASCII. MUST (*source: PRD §9.10, §13.7; verify: locale; story: X-12/X-11*)
- **FR-ABOUT-7** — The route MUST use `SafeArea`, bounded scrollable content, semantic headings, labelled ≥48 dp actions, standard keyboard/Back navigation, and MUST NOT overflow at phone, iPad, or Android-tablet portrait/landscape sizes through 2× text scale and high contrast. MUST (*source: PRD §13.2, §13.6, §13.7, §19; verify: widget/golden; story: A-26/X-11*)
- **FR-ABOUT-8** — Opening About or Open-source licenses MUST preserve the current editor/Blocks document, selected surface, console state, and live board session. MUST (*source: PRD §13.1, §19; verify: widget/integration; story: X-11*)

## 5. Non-Functional Requirements

### 5.1 Reliability — NFR-REL

- **NFR-REL-1** — The app MUST automatically attempt to reconnect on BLE link loss; in-flight file transfers MUST resume from the verified offset and MUST never silently corrupt or duplicate data. MUST (*source: PRD §13.1; verify: integration; story: A-03/A-13*)
- **NFR-REL-2** — A transfer MUST be reported successful only after a whole-file CRC match; partial transfers MUST be resumable, not restarted-from-zero by default. MUST (*source: PRD §13.1; verify: conformance/integration; story: A-13*)
- **NFR-REL-3** — On disconnect the app MUST preserve open editor buffers, project files, and run/console state locally so nothing is lost across a dropped link. MUST (*source: PRD §13.1; verify: integration; story: A-20*)
- **NFR-REL-4** — The app MUST remain in a coherent, non-crashing state when the board reports any PBLE/1 error status or when the link drops mid-operation. MUST (*source: PRD §13.1, §13.2; verify: integration; story: A-11/A-13*)

### 5.2 Performance — NFR-PERF

- **NFR-PERF-1** — The app MUST request MTU 247 and MUST use windowed chunks
  (`W` from HELLO; the current reference agent advertises `W=8`, and the
  conservative missing-cap compatibility fallback is `W=4`; chunk sized to
  one MTU) with cumulative-offset ACKs for file transfer. MUST (*source: PRD
  §13.4; verify: conformance; story: A-13*)
- **NFR-PERF-2** — File transfer MUST report progress to the UI continuously during a transfer. MUST (*source: PRD §9.2, §13.4; verify: widget; story: A-30*)
- **NFR-PERF-3** — Interactive console latency (keystroke/`CONSOLE_INPUT` → echo, and `stdout` → display) MUST stay low enough to feel live; concrete ceilings MUST be measured on HIL and frozen alongside [PRD §10.13](../prd.md). MUST (*source: PRD §13.4; verify: integration; story: A-21*)
- **NFR-PERF-4** — Time-to-connect SHOULD be < 10 s on first connect and < 5 s for a saved board (validated on HIL per [PRD §20](../prd.md)). SHOULD (*source: PRD §20; verify: integration; story: A-22*)

### 5.3 Usability — NFR-USE

- **NFR-USE-1** — Connect MUST present named PyBLE boards (filtered to the service UUID) and MUST NOT show a raw, unfiltered BLE device list. MUST (*source: PRD §13.2, §9.6; verify: widget; story: A-22*)
- **NFR-USE-2** — Interactive controls MUST use large touch targets and MUST clearly communicate connection and run state. MUST (*source: PRD §13.2; verify: golden; story: A-22*)
- **NFR-USE-3** — Errors (BLE failures, flash/`ENOSPC`, run tracebacks) MUST be surfaced honestly and in beginner-readable form, mapping PBLE/1 status codes to clear messages rather than hiding failures. MUST (*source: PRD §13.2, §2; verify: widget; story: A-21/A-30*)
- **NFR-USE-4** — The UI MUST be tablet-first with a responsive split layout that MUST NOT break on a phone. MUST (*source: PRD §13.2, §19; verify: golden; story: A-20*)

### 5.4 Offline-first — NFR-OFF

- **NFR-OFF-1** — Projects, files, snapshots, run sessions, and console logs MUST be fully usable with no internet connection. MUST (*source: PRD §13.5, §12.1; verify: integration; story: A-20*)
- **NFR-OFF-2** — The only network-dependent feature is GitHub import; its absence MUST NOT block any other workflow. MUST (*source: PRD §13.5; verify: integration; story: A-33*)
- **NFR-OFF-3** — The app MUST NOT require an account, cloud sync, or any server to edit, run, or manage code on a board. MUST (*source: PRD §13.5, §15.1; verify: integration; story: A-20*)

### 5.5 Platform Compatibility / Parity — NFR-COMPAT

- **NFR-COMPAT-1** — iPadOS and Android tablet MUST ship at feature parity at every milestone; neither platform may lag the other for a released capability. MUST (*source: PRD §13.6, §15.3; verify: integration; story: X-11*)
- **NFR-COMPAT-2** — BLE permissions MUST be handled per platform (iOS `NSBluetoothAlwaysUsageDescription`; Android 12+ `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` + older-Android location). MUST (*source: PRD §13.6, app.md §5; verify: integration; story: A-04*)
- **NFR-COMPAT-3** — The app MUST NOT depend on USB serial or Wi-Fi onboarding as a runtime path; BLE is the only v1.0 transport. MUST (*source: PRD §13.6, §1A.3; verify: unit; story: A-02*)
- **NFR-COMPAT-4 — Android renderer fallback (FROZEN · X-11 · `[docs]`
  2026-08-07).** Until the pinned Flutter engine renders correctly through
  Impeller/Vulkan on the validated Lenovo TB-J616X/MediaTek Android 12 device,
  the Android manifest MUST disable Impeller so Flutter uses its supported
  legacy OpenGL renderer. A real-device cold-launch check MUST show the first
  application frame and the BLE connect surface; a blank foreground activity
  fails the Android gate. This temporary opt-out MUST be re-evaluated whenever
  Flutter is upgraded because Flutter has deprecated permanent opt-out.
  MUST (*source: PRD §13.6, §15.3; verify: unit/build/manual; story: X-11*)

### 5.6 Accessibility & Localization — NFR-A11Y

- **NFR-A11Y-1** — English MUST ship day-one; any new UI string MUST land with its `en` ARB entry in the same change. MUST (*source: PRD §13.7, §9.10; verify: locale; story: X-12*)
- **NFR-A11Y-2** — Any added locale MUST reach full string parity before release; partial translations MUST NOT ship as a shipped locale. MUST (*source: PRD §13.7; verify: locale; story: X-12*)
- **NFR-A11Y-3** — The app SHOULD support large-font and high-contrast modes and keyboard navigation so editor/console/files remain operable for accessibility users. SHOULD (*source: PRD §13.7; verify: widget/golden; story: A-20/A-21*)
- **NFR-A11Y-4** — Technical identifiers MUST remain ASCII and MUST NOT be localized. MUST (*source: PRD §13.7; verify: locale; story: X-12*)

### 5.7 Maintainability — NFR-MAINT

- **NFR-MAINT-1** — The strict layering (UI → `lib/pble` → `lib/ble`) MUST be preserved; an import-boundary check SHOULD enforce that widgets never import `lib/ble/`. MUST/SHOULD (*source: PRD §16.1, app.md §1; verify: unit; story: A-02*)
- **NFR-MAINT-2** — A single declarative state-management approach MUST be chosen (recorded as an ADR) and applied consistently across the app. MUST (*source: PRD §16.1, §25; verify: unit; story: A-20*)
- **NFR-MAINT-3** — Every shipped behaviour MUST have an automated test; no behaviour ships without a test (TDD). MUST (*source: PRD §1B.2, §21.1; verify: unit/widget/conformance/integration; story: all*)
- **NFR-MAINT-4** — The PBLE/1 client and BLE adapter MUST be re-usable and mockable so the two ends agree on the wire and platform differences stay isolated. MUST (*source: PRD §23, app.md §7; verify: conformance/unit; story: A-13*)

## 6. Constraints — CON

- **CON-1** — The app MUST NOT present a raw, unfiltered BLE device list; scanning is always filtered to the PyBLE service UUID. MUST (*source: PRD §9.6, §13.2, §8.1; verify: widget; story: A-01/A-22*)
- **CON-2** — The app MUST NOT use USB serial or Wi-Fi as a runtime transport; BLE is the only v1.0 transport (a future desktop serial transport is post-v1, behind the same `Connection`). MUST (*source: PRD §1A.3, §4.3, §13.6; verify: unit; story: A-02*)
- **CON-3** — File transfer MUST be `.py`/plain-data only; the app MUST NOT produce, transfer, or depend on `.mpy`/`.pyc`. MUST (*source: PRD §4.3, §10.14; verify: unit; story: A-30/A-33*)
- **CON-4** — The app MUST NOT require accounts, cloud sync, or telemetry-by-default; no feature may require a login or network round-trip to function (GitHub import excepted, and never blocking other workflows). MUST (*source: PRD §1A.3, §4.3, §13.5; verify: integration; story: A-20*)
- **CON-5** — The app MUST be tablet-first (iPad + Android); the phone layout is best-effort and MUST NOT break. MUST (*source: PRD §13.2, §19; verify: golden; story: A-20*)
- **CON-6** — Every shippable source file MUST be MIT-licensed and clean-room;
  the no-leak gate MUST pass over the app source (no proprietary protocol,
  opcodes, UUIDs, board-specific hardware profiles, copied catalog/curriculum,
  domain-specific lesson flow, or proprietary/classroom pedagogy, per
  [PRD §1A.2](../prd.md)). MUST (*source: PRD §1A.1, §1A.2; verify: unit
  (no-leak gate); story: X-01/X-02*)
- **CON-7** — The app MUST NOT implement any board-specific hardware profile, science-lab feature, or managed-teaching/multi-device mechanism (the permanent non-goals of [PRD §4.3](../prd.md)); the pin reference is read-only informational only. Website/build provisioning-profile IDs identify independently flashed bytes and MUST NOT become app connection, capability, routing, toolbox-visibility, or automatic-example-selection state. Example guidance MAY name an exact firmware prerequisite but MUST NOT store or enforce it. MUST (*source: PRD §4.3, §11.3; verify: unit; story: A-22*)
- **CON-8** — Every widget MUST bind only to the `Connection` API (or callbacks derived from it) and MUST NOT import `lib/ble/`; only `lib/pble/` knows the wire format. MUST (*source: PRD §6.1, §16.1, app.md §1; verify: unit; story: all A*)
- **CON-9** — Every new user-facing string MUST ship with at least its `en` ARB entry in the same commit; locale parity gates merges. MUST (*source: PRD §9.10, §13.7; verify: locale; story: X-12*)

## 7. External Interfaces — IF

- **IF-1** — **BLE GATT to the board** carrying PBLE/1: one primary service on the PyBLE-owned UUID base with RX (Write), TX (Notify), and INFO (Read) characteristics, advertised name prefix `PyBLE-`, MTU 247. The app consumes this per [protocol.md §2](../protocol.md#2-ble-transport-gatt)/[§3](../protocol.md#3-framing) via `lib/ble/`. MUST (*source: PRD §6.3, protocol.md §2/§3; verify: integration; story: A-01/A-02*)
- **IF-2** — The **`Connection` API** is the internal seam between UI and transport ([app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to)); all widget↔board interaction crosses it. MUST (*source: PRD §6.1, app.md §3; verify: unit; story: A-10*)
- **IF-3** — **Local database** via Drift (SQLite) for projects, settings, saved boards, snapshots, run/console logs, import provenance (offline-first; see §8). MUST (*source: PRD §12, §16.1; verify: unit; story: A-20*)
- **IF-4** — **GitHub over HTTPS** (public, unauthenticated) for importing a folder of `.py` files (`lib/github_import/`). MUST (*source: PRD §9.7; verify: integration; story: A-33*)
- **IF-5** — **Platform BLE permission APIs** on iOS and Android, invoked with localized rationale. MUST (*source: PRD §9.6, §13.6, app.md §5; verify: integration; story: A-04*)
- **IF-6** — **In-app Open-Source Notices** screen sourcing the generated third-party notice set on both platforms (see §9), reachable offline from the global About route. MUST (*source: PRD §15.2; verify: widget; story: X-11*)

## 8. Data Model — DAT

The local Drift database ([PRD §12.1](../prd.md), `lib/data/`) MUST model exactly the following user-content tables (offline CRUD, no network dependency) and no managed-fleet/lab tables.

- **DAT-1** — `projects` — a named bundle of files. Fields: `id`, `name`, `description`, `created_at`, `updated_at`, `last_opened_at`. MUST (*source: PRD §12.1; verify: unit; story: A-20*)
- **DAT-2** — `project_files` — the `.py`/data files mirroring the workspace shape. Fields: `id`, `project_id` (FK), `path`, `content`/blob, `size`, `content_hash`, `updated_at`; `.py`/data only. MUST (*source: PRD §12.1, §10.14; verify: unit; story: A-20*)
- **DAT-3** — `code_snapshots` — point-in-time file versions for local history/restore. Fields: `id`, `project_id` (FK), `path`, `content`, `label`, `trigger` (manual/pre-run), `created_at`. MUST (*source: PRD §12.1; verify: unit; story: A-20*)
- **DAT-4** — `run_sessions` — one run (RUN → terminal `RUN_STATE`). Fields: `id`, `project_id` (FK), `board_ref`, `chip`, `entry` (file/source), `started_at`, `ended_at`, `final_state` (idle/done/error). MUST (*source: PRD §12.1; verify: unit; story: A-11*)
- **DAT-5** — `console_logs` — captured output for a run session. Fields: `id`, `run_session_id` (FK), `seq`, `timestamp`, `stream` (stdout/stderr/system), `text`; capture MUST be local and MUST NOT be transmitted off-device. MUST (*source: PRD §12.1, §14.2; verify: unit; story: A-21*)
- **DAT-6** — `github_imports` — provenance of an import. Fields: `id`, `project_id` (FK), `repo_url`, `ref`, `subpath`, `commit_sha`, `file_count`, `imported_at`; `.py`/data only. MUST (*source: PRD §12.1; verify: unit; story: A-33*)
- **DAT-7** — Saved-board reconnect MUST be stored as a lightweight app setting / `board_ref`, NOT a relational board-profile or fleet table. MUST (*source: PRD §12.1; verify: unit; story: A-20*)
- **DAT-8** — The data model MUST NOT contain any managed-fleet, multi-user cohort, lab/experiment-dataset, or hardware-calibration tables — the concretely-excluded tables enumerated in [PRD §12.1](../prd.md) (explicit non-goals). MUST (*source: PRD §12.1, §4.3; verify: unit; story: A-20*)

## 9. Build, Versioning & Distribution — BLD

- **BLD-1** — The app MUST be a single Flutter codebase targeting iPadOS and Android tablets (one package, [app.md §2](../app.md#2-packages--directories)). MUST (*source: PRD §6.1, §16.1; verify: integration; story: A-20*)
- **BLD-2** — App dependencies MUST be governed by `pubspec.yaml` with an approved-entry record (rationale, license, minimum version) per dependency; each MUST be MIT/Apache-2.0/BSD-compatible; a committed `pubspec.lock` MUST pin versions and CI MUST build against the lock. MUST (*source: PRD §17.2; verify: unit/integration; story: X-03*)
- **BLD-3** — The app MUST follow SemVer; v1.0 is the first production release and a breaking change bumps MAJOR. MUST (*source: PRD §18.1; verify: unit; story: X-11*)
- **BLD-4** — The app MUST be distributed free on the App Store and Google Play, submitted **at parity** (neither store ahead of the other); no account, paywall, or in-app purchase. MUST (*source: PRD §15.3, §18.2; verify: integration; story: X-11*)
- **BLD-5** — The locale-parity check MUST block any merge that breaks ARB parity. MUST (*source: PRD §9.10, §21.1; verify: locale; story: X-12*)
- **BLD-6** — The build MUST ship a `THIRD_PARTY_LICENSES`/notices set generated mechanically, and the app MUST present an in-app Open-Source Notices screen reachable from About on both platforms. The earlier delivery of a reachable `LicenseRegistry` page is an incremental surface and does not close the complete generated-notices requirement. MUST (*source: PRD §15.2; verify: widget/integration; story: X-11*)
- **BLD-7** — Each app release MUST declare a minimum supported PBLE/1 capability baseline and minimum agent version it interoperates with; a mismatch MUST surface as an update prompt, never a silent failure. MUST (*source: PRD §18.3; verify: integration; story: A-10*)
  - **Frozen baseline (A-10 · `[docs]` 2026-07-02).** The declared PBLE/1 baseline is **PBLE/1 v1** — `proto_version = 1`, wire `VER = 0x01` ([protocol.md §9](../protocol.md#9-versioning-policy), FROZEN). HELLO offers `proto_versions = [1]`; a board whose negotiated `proto_version` is not `1` MUST be refused with a typed `UnsupportedProtocolException` and surfaced as an update prompt (FR-PBLE-5/6, FR-CONNECT-6), never a silent failure. Capabilities are additive within v1 (an older client ignores unknown caps, [protocol.md §7](../protocol.md#7-hello--capabilities)/[§9](../protocol.md#9-versioning-policy)). The **minimum interoperable agent version** is a release-time declaration (X-11/S10), not frozen here.
- **BLD-8** — Every source file MUST carry an `SPDX-License-Identifier: MIT` header; CI SHOULD reject any added source file lacking one. MUST/SHOULD (*source: PRD §15.1; verify: unit; story: X-01*)
- **BLD-9** — If a future backward-incompatible **PBLE/2** ships, the app MUST continue to interoperate with the previous protocol major version for a stated compatibility window so that already-deployed boards are not bricked by an app update; the version actually used MUST be selected through HELLO negotiation (FR-PBLE-5/6) rather than assumed. MUST (*source: PRD §18.4; verify: integration; story: X-11*)
- **BLD-10 — Launcher identity (FROZEN · X-11 · `[docs]` 2026-07-29).** iPadOS and Android MUST ship the same original PyBLE **Prompt Chip** identity from an MIT, grid-defined vector source: a full-bleed flat deep-navy `#081B35` field; one electric-blue `#2F8CFF` rounded microcontroller frame with exactly two pins on its top, bottom, and left edges and no right-edge pins; one large near-white `#F4F7FF` terminal prompt; and one subordinate blue radio arc on the right. The complete foreground MUST stay inside Android's 66×66 dp guaranteed safe zone. The production artwork MUST NOT contain text, a connection-status indicator, the Bluetooth or Python figure mark, extra radio arcs, generated lighting, a baked platform mask, or platform-specific geometry. Repeatable exports MUST provide an opaque 1024×1024 iOS default icon plus deliberate dark and grayscale-tinted appearances; opaque Android legacy density icons plus adaptive background/foreground and monochrome layers; and a 512×512 RGBA Google Play listing icon. Unit tests MUST verify catalog/resource linkage, canonical vector parity, formats, and dimensions; release builds plus 20 px and circle/squircle/rounded-square visual checks verify compilation, legibility, and mask safety. MUST (*source: PRD §13.6, §15.3, §18.2; verify: unit/build/manual; story: X-11*)
- **BLD-11 — Store-signable embedded assets (FROZEN · X-11 · `[docs]` 2026-07-29).** Every non-Mach-O file embedded in an iOS distribution archive MUST remain a sealed data resource and MUST NOT be classifiable as an unsigned nested executable. In particular, generated Blockly JavaScript that contains multiline Python templates MUST be transformed deterministically at vendoring time so the packaged file is ordinary JavaScript/data rather than a Python script while preserving byte-for-byte generated Python at runtime. The asset-policy unit gate MUST pin that transform; the vendoring build and exported-IPA gate MUST reject any Flutter asset identified as `script text executable`; and any correction MUST be followed by a clean archive/export rather than mutation of a signed bundle. MUST (*source: PRD §18.2; Apple Code Signing Guide / TN2206; verify: unit/build/manual; story: X-11*)
- **BLD-12 — Android release signing (FROZEN · X-11 · `[docs]` 2026-08-07).** Every Android `release` variant MUST fail closed unless an explicit non-debug signing identity is supplied through the four secret-manager environment variables `PYBLE_ANDROID_KEYSTORE_PATH`, `PYBLE_ANDROID_KEYSTORE_PASSWORD`, `PYBLE_ANDROID_KEY_ALIAS`, and `PYBLE_ANDROID_KEY_PASSWORD`; it MUST never fall back to the Android debug key or an unsigned artifact. The production Play artifact MUST be an upload-key-signed Android App Bundle for `dev.pyble.pyble`. Public CI MUST exercise this exact release-signing path with a disposable CI-only key, build both the production APK and AAB, verify the AAB JAR signature, and never receive the production upload key. The final release gate MUST compare the AAB signer SHA-256 fingerprint with the owner-controlled upload certificate and record the AAB SHA-256 plus source commit and version. MUST (*source: PRD §15.3, §18.2; Android app-signing requirements; verify: unit/build/manual; story: X-11*)

## 10. Security & Privacy — SEC

- **SEC-1** — v1.0 MUST rely on **BLE link-layer pairing/encryption** as the baseline and MUST NOT add application-layer authentication; a connected client is trusted at the application layer. MUST (*source: PRD §14.1, protocol.md §10; verify: integration; story: A-02*)
- **SEC-2** — The app MUST be a **single active writer** to one board: it is one client to one board, with run/file operations serialized so it cannot corrupt workspace state, surfacing `EBUSY` when the board is busy. MUST (*source: PRD §14.1, §10.6; verify: integration; story: A-11/A-12*)
- **SEC-3** — The app MUST have no accounts and no telemetry by default. MUST (*source: PRD §14.2, §1A.3; verify: integration; story: A-20*)
- **SEC-4** — No PII MUST be included in the app↔board exchange or in any advertisement the app relies on (only the PyBLE service UUID and short `PyBLE-XXXX` name); the app MUST NOT depend on or transmit user-identifying data. MUST (*source: PRD §14.2, protocol.md §2; verify: unit; story: A-01*)
- **SEC-5** — All user content (projects, files, snapshots, run/console logs) MUST stay on-device unless the user explicitly exports it; nothing is transmitted off-device by default. MUST (*source: PRD §13.5, §14.2; verify: integration; story: A-20*)
- **SEC-6** — The app MUST NOT gate access by board identity or MAC and MUST NOT build a remote registry of users or boards. MUST (*source: PRD §14.2, §11.1; verify: unit; story: A-22*)
- **SEC-7** — The app MUST NOT attempt to write the agent control plane or board overlay via PBLE/1 file commands; it treats those as forbidden paths (the agent enforces `EACCES`). MUST (*source: PRD §10.4, §14.1; verify: integration; story: A-30*)
- **SEC-8** — Because a user-set device **label is broadcast** in the BLE advertisement ([protocol.md §2](../protocol.md#2-ble-transport-gatt)/[§10](../protocol.md#10-security-note-v1)), the rename-board UI (FR-CONN-10) MUST warn the user that the label is publicly visible to anyone scanning, MUST nudge against entering personal data (PII), and MUST bound the label length in the UI to the board's limit; the default `PyBLE-XXXX` carries no PII. MUST (*source: PRD §14.2, protocol.md §10; verify: widget; story: A-22*)
- **SEC-9** — The label and identify-LED are per-device configuration the board owns for its own screenless UX; the app MUST NOT use `device_id`, MAC, or `label` to gate access or build any remote registry of boards (extends SEC-6 to the new identity fields). MUST (*source: PRD §14.2, §11.1, §4.3, protocol.md §10; verify: unit; story: A-22*)

## 11. Traceability Matrix

| Requirement family | Apex PRD source | Stories | Verification |
|---|---|---|---|
| FR-BLE-* | §9.6, §8.1, §16.1, §13.6 | A-01, A-02, A-03, A-04 | unit, integration |
| FR-PBLE-* | §6.3, §9, §18.3 | P-01..P-04, A-10, A-13 | conformance |
| FR-CONN-* | §9 (all), §4.3, app.md §3, protocol.md §7 | A-10, A-11, A-12, A-22 | unit (FakeConnection), widget |
| FR-PROJ-* | §9.1, §12, §13.1, §13.5 | A-20 | unit, integration |
| FR-FILES-* | §9.2, §8.4 | A-30 | widget, integration |
| FR-EDIT-* | §9.3, §16.1 | A-20 | widget, golden |
| FR-CONSOLE-* | §9.4 | A-21 | widget, golden |
| FR-RUN-* | §9.5, §8.2, §8.3, §13.3 | A-11 | widget, integration |
| FR-IMPORT-* | §9.7, §12.1 | A-33 | integration |
| FR-BLOCKS-*/FR-PLOTS-* | §9.8, §16.1 | A-31, A-32, A-38 | unit, asset, widget, integration, HIL |
| FR-ERR-* | §9.9 | A-21 | unit, widget |
| FR-I18N-* | §9.10, §13.7 | X-12 | locale |
| FR-UI-* | §19 | A-20, A-22 | golden, widget |
| FR-CONNECT-* | §9.6, §19.3, §8.1, §18.3, protocol.md §2 | A-22, A-04, A-10 | widget, integration |
| FR-ABOUT-* | §1A, §13.1/2/5/6/7, §14.2, §15.1/2, §18.1, §19 | X-11, A-26, A-28, X-12 | unit, widget, golden, locale, integration |
| NFR-REL-* | §13.1 | A-03, A-13, A-20 | integration, conformance |
| NFR-PERF-* | §13.4, §20 | A-13, A-21, A-30, A-22 | conformance, integration |
| NFR-USE-* | §13.2, §9.6 | A-21, A-22, A-30 | widget, golden |
| NFR-OFF-* | §13.5, §12.1 | A-20, A-33 | integration |
| NFR-COMPAT-* | §13.6, §15.3 | X-11, A-04, A-02 | integration |
| NFR-A11Y-* | §13.7, §9.10 | X-12, A-20, A-21 | locale, golden |
| NFR-MAINT-* | §16.1, §1B.2, §23 | A-02, A-20, all | unit, conformance |
| CON-* | §1A.3, §4.3, §9.6, §13.x | A-01, A-02, A-20, X-02 | unit, golden |
| IF-* | §6.3, §12, §9.7, §15.2 | A-01, A-20, A-33, X-11 | integration |
| DAT-* | §12.1 | A-20, A-11, A-21, A-33 | unit |
| BLD-* | §13.6, §15, §17.2, §18 | X-11, X-12, X-03, X-01 | unit, build, integration, locale |
| SEC-* | §14, §10.4, §11.1, §4.3, protocol.md §10 | A-02, A-20, A-22, A-30 | integration, unit, widget |

## 12. Open Items

- **OI-1 — Flutter Python-editor widget choice.** `flutter_code_editor` tablet-keyboard maturity is a tracked risk; a WebView-hosted editor (Monaco/CodeMirror) behind the same editor interface is the documented fallback. Decision is pending evaluation (see [PRD §16.1](../prd.md), [§23](../prd.md), [§25](../prd.md)). Affects FR-EDIT-1.
- **OI-2 — State-management library. CLOSED (2026-07-02) by [ADR-0007](../../decisions/0007-riverpod-state-management.md).** The single declarative approach is fixed as **Riverpod** (`flutter_riverpod`), with Bloc the documented alternative (App [TDD.md §2.3](TDD.md#23-single-declarative-state-management-riverpod), D3). NFR-MAINT-2 is satisfied; the shell/A-05 provider set (`connectionProvider`, derived `connStateProvider`) wires `Connection` at the `ProviderScope` root, overridable with `FakeConnection` in tests.
- **OI-3 — PBLE/1 freeze dependency. RESOLVED (2026-07-01).** [protocol.md](../protocol.md) **§2–§10 are FROZEN for v1.0** (§2 GATT/UUIDs + §3 framing at G0; §4 opcodes + §8 status + §5/§6/§7/§9/§10 at G1, all `[docs]` 2026-07-01) — see the protocol.md per-section freeze ledger. The UUID base (`7079626c-…`), the frame/fragmentation bytes, and the opcode/status numbers are now **stable inputs**; the FR-PBLE-* client dependency on §2/§4 being frozen first (per SDD, [PRD §1B.1](../prd.md)) is **met**. (The residual label / identify **payload encodings** — `SET_LABEL` max byte-length, `SET_IDENTIFY_LED` GPIO+active-level, `IDENTIFY` blink bound — are tracked by protocol.md **OI-6** and freeze before their S3/S4 identity stories, not needed for S1/S2.)
- **OI-4 — HIL-frozen performance ceilings.** Concrete console-latency and throughput ceilings (NFR-PERF-3, NFR-PERF-4) and time-to-connect targets MUST be measured on hardware and frozen alongside [PRD §10.13](../prd.md)/[§20](../prd.md).
- **OI-5 — Plot parsing configuration.** The exact user-facing model for configuring how console output parses into plot series (FR-PLOTS-2) is to be detailed in [TDD.md](TDD.md).
