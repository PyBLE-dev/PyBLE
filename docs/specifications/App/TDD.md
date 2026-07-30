# PyBLE App — Technical Design Document (TDD)

Status: **DRAFT** · Owner: project maintainer · Last updated: 2026-07-30

## 0. Naming note (acronym clash)

In **this** document, **TDD = Technical Design Document** — the engineering design of the PyBLE Flutter app. The project's *development methodology* is also abbreviated "TDD", meaning **Test-Driven Development** (`red → green → refactor`), defined in [PRD §1B](../prd.md). Where this document says "TDD" it means *this design document*; where it discusses the methodology it spells out "Test-Driven Development". [§15](#15-test-design) is where the two meet: this Technical Design is delivered through Test-Driven Development.

## 1. Purpose & scope

### 1.1 Purpose

This document specifies **how** the PyBLE app is engineered to satisfy the requirements in [specs.md](specs.md) (the app requirements specification). specs.md owns *what/why* (requirement IDs `FR-*`, `NFR-*`, `CON-*`, `IF-*`, `DAT-*`, `BLD-*`, `SEC-*`); this document owns *how* (packages, public APIs, data structures, state machines, data flow, test strategy) and traces every design element back to those IDs ([§16](#16-traceability)).

### 1.2 Scope

The design covers the **entire Flutter app**: the BLE adapter (`lib/ble/`), the PBLE/1 client and the `Connection` implementation (`lib/pble/`), the `Connection`/`FakeConnection` seam, the persistence layer (`lib/data/`), the GitHub import path (`lib/github_import/`), the localization layer (`lib/localization/`), and every UI surface (`lib/editor`, `lib/console`, `lib/files`, `lib/connect`, `lib/blocks`, `lib/plots`). Out of scope: the wire protocol itself (owned by [protocol.md](../protocol.md)), the agent firmware (owned by [firmware.md](../firmware.md) and [../firmware/TDD.md](../firmware/TDD.md)), and the board hardware contract (owned by [hardware.md](../hardware.md)) — except where the app shares an in-memory fake-transport conformance corpus with the firmware so both ends honor the same wire ([§8.8](#88-shared-conformance-corpus-with-the-firmware), [§15.4](#154-pble1-conformance)).

### 1.3 Relationship to other documents

- [specs.md](specs.md) — the requirements this design satisfies; the authority on *what*.
- [PRD §9](../prd.md) — apex app requirement set; specs.md and this TDD both flow from it (with §5, §6.1, §12–§19 contributing app-facing obligations).
- [app.md](../app.md) — the app **overview**; it **owns** the package/directory layout ([app.md §2](../app.md#2-packages--directories)) and the `Connection`/`FakeConnection` seam ([app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to)). This TDD references those and does **not** restate the directory list.
- [protocol.md (PBLE/1)](../protocol.md) — **owns** the wire format. This document maps the wire format to in-app structures and **never redefines** frame bytes, opcodes, UUIDs, or status codes; it cites the relevant `§`.
- [architecture.md](../architecture.md) — three-piece system view ([§2 app architecture](../architecture.md#2-app-architecture-summary)), the [clean-room boundary (§5)](../architecture.md#5-clean-room--ip-boundary), and [technology choices (§6)](../architecture.md#6-technology-choices) this design adopts.
- [../firmware/TDD.md](../firmware/TDD.md) — the firmware engineering design; the **other end** of PBLE/1. The two TDDs agree on the wire via a shared conformance corpus ([§15.4](#154-pble1-conformance)).
- ADRs under [../../decisions/](../../decisions/) — e.g. [ADR-0002 (fresh protocol)](../../decisions/0002-fresh-protocol.md), [ADR-0003 (MIT)](../../decisions/0003-license-mit.md). The state-management and editor-widget choices are tracked as forthcoming ADRs ([§2.3](#23-single-declarative-state-management-riverpod), [§17](#17-risks--open-questions)).

## 2. Design goals & key decisions

The decisions below are the load-bearing choices the rest of the design rests on. Each cites the requirement(s) it serves.

### 2.1 The `Connection` API is the single seam

**Decision (D1):** every UI widget binds **only** to the abstract `Connection` interface ([app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to), [§5](#5-the-connection-api-design)) or to narrow callbacks derived from it. The wire format lives **only** in `lib/pble/`; no widget imports `lib/ble/`. This is enforced by an import-boundary lint ([§15.6](#156-import-boundary--no-leak-gates)). — *(satisfies FR-CONN-*, FR-PBLE-14, FR-BLE-8, NFR-MAINT-1, CON-8; the whole-document binding principle of [specs.md §1.4](specs.md).)*

Rationale: a single seam makes every functional requirement testable against a `FakeConnection` with no BLE dependency, keeps the editor/console/files transport-agnostic, and is the structural precondition for the Test-Driven Development workflow ([§15](#15-test-design)).

### 2.2 Transport-agnostic widgets over neutral types

**Decision (D2):** widgets speak only PyBLE's **neutral types** — `Connection`, `DeviceInfo`, `ConsoleEvent`, `RemoteEntry`, `ConnState`, `TransferProgress`, and the typed `PbleException` hierarchy ([§5.2](#52-shared-types)). No widget sees a raw frame, opcode, status byte, MTU, or `flutter_blue_plus` type. This is also the clean-room retyping boundary (D6). — *(satisfies FR-PBLE-14, FR-BLOCKS-4, FR-PLOTS-3, CON-8.)*

### 2.3 Single declarative state management (Riverpod)

**Decision (D3):** the app uses **one** declarative state-management approach across all surfaces, recorded in an ADR before broad adoption ([architecture.md §6](../architecture.md#6-technology-choices); the working choice is **Riverpod**, Bloc the documented alternative). `Connection` is exposed as a provider; UI reads derived providers (connection state, console buffer, file listing, run state) and never holds transport handles directly. — *(satisfies NFR-MAINT-2; tracked by [OI-2](specs.md) / [§17](#17-risks--open-questions).)*

Rationale: a single approach keeps the strict layering observable (state flows down from `Connection`, intents flow up through it) and makes widget/golden tests deterministic by overriding one provider with a `FakeConnection`.

### 2.4 Offline-first via Drift

**Decision (D4):** the local Drift (SQLite) database in `lib/data/` is the **source of truth** for all user content; the board filesystem is a *target*, not the store. Every editor/project workflow is fully usable with no board and no network; the only network-dependent feature is GitHub import, which never blocks another workflow. — *(satisfies FR-PROJ-1..7, NFR-OFF-1..3, DAT-1..8, IF-3, CON-4, SEC-5.)*

### 2.5 FakeConnection-driven testability

**Decision (D5):** `FakeConnection` is a **first-class, shipped test artifact** implementing the full `Connection` interface in memory (scriptable device info, console scripts, file tree, error injection, progress simulation). Every FR that binds to `Connection` is exercised against it in widget/unit tests; the production `PbleConnection` is exercised separately by conformance tests over a fake byte transport. — *(satisfies FR-CONN-7, NFR-MAINT-3/4; the testing model of [app.md §7](../app.md#7-testing).)*

### 2.6 Reuse provenance — relicense-MIT at copy time, retype onto neutral types

**Decision (D6):** board-agnostic widgets that derive from the maintainer's own prior art (editor scaffold, console view, file explorer, plots, Blockly bridge, GitHub import, tablet scaffold, localization plumbing) are **re-implemented or relicensed MIT by the author at copy time** and **retyped onto PyBLE's neutral types** ([app.md §6](../app.md#6-reuse-provenance-clean-room-note)). They carry **no** closed-source protocol client, board profiles, UUIDs, copied catalog/curriculum, domain-specific lesson flow, or proprietary/classroom pedagogy. The PBLE/1 client (`lib/pble/`), BLE adapter (`lib/ble/`), and ADR-0016's bounded generic starter workspaces are written **fresh** for PyBLE. The no-leak gate runs over all app source. — *(satisfies CON-6, FR-PBLE-15, FR-BLOCKS-4, FR-PLOTS-3, BLD-8; [architecture.md §5](../architecture.md#5-clean-room--ip-boundary), [ADR-0002](../../decisions/0002-fresh-protocol.md).)*

### 2.7 Wire format is referenced, never redefined

**Decision (D7):** `lib/pble/` mirrors [protocol.md §2](../protocol.md#2-ble-transport-gatt)/[§3](../protocol.md#3-framing)/[§4](../protocol.md#4-opcodes)/[§8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) into a **single generated constants table** (UUIDs, opcodes, status codes, frag-header bits), so a protocol freeze updates exactly one Dart file — the symmetric counterpart of the firmware's mirror ([../firmware/TDD.md §2.6](../firmware/TDD.md)). — *(satisfies FR-PBLE-1/13, IF-1; manages [OI-3](specs.md).)*

## 3. Architecture overview

### 3.1 Layering

```text
+----------------------------------------------------------------------+
| UI WIDGETS  lib/connect lib/editor lib/console lib/files             |
|             lib/blocks  lib/plots  lib/github_import                 |
|             (bind to Connection / narrow callbacks — D1/D2)          |
+-----------------------------+----------------------------------------+
            state (down)      |   intents (up)
                              v
+----------------------------------------------------------------------+
| STATE  Riverpod providers (D3): connState, console, files, runState  |
+-----------------------------+----------------------------------------+
                              |  Connection (abstract)        FakeConnection (tests)
                              v
+----------------------------------------------------------------------+
| lib/pble/   PBLE/1 client  ── implements Connection                  |
|   codec+CRC32 · fragment/reassemble · ID correlation ·               |
|   file-transfer state machine (window+resume) · console stream ·     |
|   HELLO/caps · status-byte -> typed PbleException                    |
+-----------------------------+----------------------------------------+
            Stream<List<int>> in   |   write(bytes) out
                              v
+----------------------------------------------------------------------+
| lib/ble/    BLE adapter  ── scan(filter UUID) · connect · MTU 247 ·  |
|             notify->stream · write · reconnect · permissions         |
+-----------------------------+----------------------------------------+
                              v
+----------------------------------------------------------------------+
| flutter_blue_plus  ── BLE radio (iOS/Android)                        |
+----------------------------------------------------------------------+

side: lib/data/ (Drift, offline-first, D4)  ·  lib/localization/ (intl/ARB)
```

Strict rule (NFR-MAINT-1, CON-8): UI widgets never import `lib/ble/`; only `lib/pble/` knows the wire format. The package map is **owned by [app.md §2](../app.md#2-packages--directories)** and not restated here.

### 3.2 Data-flow example — Run a file

Mirrors [architecture.md §4](../architecture.md#4-data-flow-examples):

```text
editor "Run"
  -> save buffer to Drift project_files            (FR-EDIT-7, D4)
  -> Connection.putFile("/main.py", bytes)         [PBLE/1 FILE_PUT_*, §5]  (FR-CONN-4)
       lib/pble: PUT_BEGIN -> windowed PUT_DATA -> PUT_END (whole-file CRC)
  -> Connection.runFile("/main.py")                [PBLE/1 RUN, §6]         (FR-CONN-2)
  <- RUN_STATE(running) event   -> runState provider -> toolbar disables Run (FR-RUN-3)
  <- CONSOLE_DATA(stdout/stderr) events -> console stream -> console view   (FR-CONSOLE-1)
  <- RUN_STATE(done|error)      -> runState provider; on error, stderr      (FR-CONSOLE-3)
                                   traceback annotated by error explainer   (FR-ERR-1)
```

### 3.3 Data-flow example — Stop

```text
toolbar "Stop" -> Connection.stop()  [PBLE/1 STOP, §6]   (FR-RUN-2)
  <- RSP(OK) then RUN_STATE(idle) -> runState provider -> UI returns to idle
Stop is presented as authoritative even against a tight loop (firmware §5.2 lands it).
```

### 3.4 Data-flow example — File mirroring (download)

```text
files "Download" -> Connection.getFile(path, onProgress)  [PBLE/1 FILE_GET_*, §5] (FR-CONN-9)
  lib/pble: GET_BEGIN -> GET_DATA events -> GET_END; verify size + whole-file CRC
  onProgress -> TransferProgress -> progress UI                              (FR-FILES-4)
  success only on full-file CRC match                                        (NFR-REL-2)
```

## 4. Package / module design

Each subsection states **responsibility · public API/type sketch · key data structures/state · dependencies · the FR IDs it satisfies**. API sketches are illustrative Dart, not the frozen interface; the frozen interface is whatever the `[red]` tests pin down ([§15](#15-test-design)). The directory list itself is owned by [app.md §2](../app.md#2-packages--directories).

### 4.1 `lib/ble/` — BLE adapter

**Responsibility:** the thin, mockable `flutter_blue_plus` seam: scan filtered to the PyBLE service UUID, connect, MTU negotiation to 247, a byte-stream boundary (`Stream<List<int>>` in / `write(bytes)` out), connection-state transitions, reconnect, and platform permission/adapter-state handling. It knows **nothing** about PBLE/1.

**Public interface (sketch):**

```dart
abstract interface class BleTransport {
  Stream<BleScanResult> scan();                 // filtered to the PyBLE service UUID (FR-BLE-1)
  Future<void> stopScan();                      // before connect (FR-BLE-5)
  Future<BleSession> connect(BleDeviceId id);   // GATT + subscribe TX + request MTU 247 (FR-BLE-2)
  ValueListenable<BlePermissionState> get permissions; // (FR-BLE-6)
}
abstract interface class BleSession {
  Stream<List<int>> get inbound;                // TX notifications (FR-BLE-3)
  Future<void> write(List<int> bytes);          // RX Write / Write-Without-Response (FR-BLE-3)
  int get mtu;                                   // negotiated, down to default (FR-BLE-2)
  ValueListenable<BleLinkState> get link;        // up/down transitions (FR-BLE-4)
  Future<void> reconnect();                      // by remembered id (FR-BLE-4)
  Future<void> close();
}
```

**Key data structures / state:** the PyBLE Service/RX/TX/INFO UUIDs (from the [protocol.md §2](../protocol.md#2-ble-transport-gatt) constants mirror, D7); negotiated MTU; remembered device identifier for reconnect; permission/adapter state enum carrying enough detail for a localized rationale.

**Dependencies:** `flutter_blue_plus` only. Hands bytes up to `lib/pble/` via `inbound`/`write`. Nothing imports it except `lib/pble/`.

**Satisfies:** FR-BLE-1..8, IF-1, IF-5, NFR-COMPAT-2/3, CON-1/2, SEC-4.

### 4.2 `lib/pble/` — PBLE/1 client + `Connection` implementation

**Responsibility:** the only layer that knows the wire. It encodes/decodes [protocol.md §3.1](../protocol.md#3-framing) frames with IEEE CRC-32, fragments/reassembles across `MTU − 4` ([protocol.md §3.2](../protocol.md#3-framing)), correlates `CMD`↔`RSP` by `ID`, routes `EVT`s, runs the file-transfer window+resume state machine ([protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core)), exposes the console stream, performs HELLO/caps negotiation ([protocol.md §7](../protocol.md#7-hello--capabilities)), and maps each [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) status byte to a typed exception. It implements the `Connection` interface ([§5](#5-the-connection-api-design)).

**Public interface (sketch):** internal codec types (`Frame`, `Fragmenter`, `Reassembler`, `Crc32`, `Correlator`, `FileTransfer`, `HelloNegotiator`) plus the public `PbleConnection implements Connection` ([§5.1](#51-the-connection-interface)).

**Key data structures / state:** the protocol constants mirror (D7); the pending-request table keyed by `ID` (1–255) with completers and timeouts; the inbound reassembly accumulator (FIRST/LAST/index-mod-64); negotiated `caps` from HELLO (chip, mpy_version, fs_root, max_file_size, put_window `W`, chunk_size, has_sd, free_mem); the active upload/download context ([§8.4](#84-file-transfer-state-machine)); the console `StreamController<ConsoleEvent>` and run-state `ValueNotifier<ConnState>`.

**Dependencies:** `lib/ble/` (byte transport) below; presents `Connection` (neutral types) above. Authored fresh, clean-room (FR-PBLE-15).

**Satisfies:** FR-PBLE-1..15, FR-CONN-1..9 (implementation), IF-1, IF-2, SEC-1/2/7.

### 4.3 `lib/editor/` — code editor

**Responsibility:** Python/MicroPython syntax highlighting, line numbers, auto-indent, multi-file tabs, Save/Run/Stop actions, find (and find/replace), external-keyboard shortcuts, tablet-friendly touch targets. The editor widget is `flutter_code_editor`, behind an `EditorSurface` interface with a WebView-hosted editor (Monaco/CodeMirror) as the documented fallback ([PRD §16.1](../prd.md), [OI-1](specs.md)).

**Public API (sketch):** `EditorSurface { String get text; set text; Stream<EditEvent> edits; void applyFind(...); }`; an `EditorTabs` controller backed by Drift `project_files`.

**Key state:** open buffers (dirty flags), active tab, find/replace state. Save persists to Drift (D4); Run uploads then runs through `Connection` (the §8.2 loop).

**Dependencies:** `Connection` (run/save), `lib/data/` (persist), `lib/localization/`. No `lib/ble/`.

**Satisfies:** FR-EDIT-1..7, FR-RUN-1/4, NFR-A11Y-3.

### 4.4 `lib/console/` — console panel

**Responsibility:** render the live `Connection.console` stream, visually distinguishing `stdout`/`stderr`/`system`; render Python tracebacks legibly; reflect run state and connection state; feed stdin via `sendInput`; copy/clear; host the beginner error explainer's annotations ([§11.4](#114-console--error-explanation)). Switching tabs must not drop the stream or an in-flight transfer.

**Public API (sketch):** `ConsoleController` subscribing to `console` and `runState` providers; a bounded ring buffer of `ConsoleLine` with stream tags; mirrors to Drift `console_logs` for the active run session.

**Key state:** the line ring buffer (bounded, with backpressure), the input field, scroll-follow flag. The subscription lives in a provider (D3) so tab switches do not tear it down (FR-CONSOLE-7).

**Dependencies:** `Connection` (console/sendInput/runState), `lib/data/` (log capture), `lib/localization/`. No `lib/ble/`.

**Satisfies:** FR-CONSOLE-1..7, FR-ERR-2, DAT-5.

### 4.5 `lib/files/` — workspace file explorer

**Responsibility:** display the board filesystem from `listDir` rooted at `fs_root`; open/upload/download/rename/delete/mkdir; multi-select bulk ops; progress for transfers; surface PBLE/1 status codes as actionable localized messages; mark the agent control plane non-editable; `.py`/data only.

**Public API (sketch):** `FileExplorerController` over `Connection.listDir/getFile/putFile/delete/mkdir/rename`; a `RemoteEntry` tree model; a forbidden/non-editable predicate for control-plane paths.

**Key state:** current path, expanded nodes, selection set, per-transfer `TransferProgress`.

**Dependencies:** `Connection`, `lib/localization/`, `lib/data/` (mirror to project). No `lib/ble/`.

**Satisfies:** FR-FILES-1..8, FR-CONN-4/9, CON-3, SEC-7.

### 4.6 `lib/blocks/` — Blockly block editor

**Responsibility:** host Blockly in a WebView, generating MicroPython for
an inspectable, board-neutral subset with no board-specific defaults, including
the current numeric-GPIO `machine.Pin` and NeoPixel surface initially validated
on ESP32-family firmware, plus paced programs through standard
`time.sleep_ms`; expose generated code as inspectable plain `.py`; route it
through the same upload/run/save path as the text editor; and load editable
copies of the bundled beginner examples without automatic execution. Numeric
pin identifiers and NeoPixel availability are not claimed for every
MicroPython port; broader target support requires an explicit capability and
block contract.
Persist an exact Blocks-origin reopen record beside generated Python, and
convert only ADR-0017's bounded beginner Python subset into a new workspace,
offline and all-or-nothing.

**Public API:** a WebView-only `BlocksBridge` publishes versioned
`GeneratedProgram { source, workspaceJson, revision }` snapshots and accepts a
serialized workspace for restoration. A workspace-bearing generator error
publishes `{message, workspaceJson, revision}` without actionable source so
invalid intermediate edits remain restorable. `BlocksController` owns
loading/error/busy state, serializes all fresh-source consumers, and delegates
Save/Run to the shared Connection-only `ProgramActions`; no board action exists
on the bridge. `BlocksExampleCatalog` decodes the local version-1 manifest into
immutable example/role records. An example-candidate service deep-clones and
materializes a fixture, asks the pinned production generator for source in an
isolated scratch workspace, and commits that candidate only after an explicit
Create-copy or confirmed Replace-workspace action.
`BlocksSidecarCodec` encodes/validates the ≤1 MiB version-1 `pyble-blocks`
envelope at `P + '.pyble-blocks.json'`; `BlocksPairActions` preflights both
UTF-8 paths against PBLE/1's 128-byte limit, freezes one
acknowledged snapshot and performs verified source-first/sidecar-last Save/Run.
`PythonBlocksImporter` is a pure-Dart, resource-bounded tokenizer/parser and
typed subset model returning either a complete `BlocksImportCandidate` or
`List<PythonBlocksDiagnostic>`; it never evaluates Python. The existing scratch
host is generalized to restore, reserialize, production-generate, and return a
candidate for exact structural/source or normalized-semantic verification.

**Key state:** Blockly JSON (not XML), the last generated source and monotonic
revision, an active normalized source target `P` (default `/blocks.py`) and
derived companion `P + '.pyble-blocks.json'`, load/busy/error state, and an
ephemeral import preview bound to the complete captured editor document,
resolved target, exact text, UTF-8 length, and CRC fingerprint. The
provider retains
the snapshot across in-process platform-view recreation. Drift project
persistence remains the A-24 hook and is a recorded deviation in this bounded
increment. A confirmed Start fresh clears incompatible retained JSON without
touching the board. The example chooser owns only its selected example and
ephemeral GPIO-role drafts; these never become device settings. Carries no
board profile, copied parser/converter/catalog/curriculum, domain-specific
lesson flow, or proprietary/classroom pedagogy (D6).

**Dependencies:** `webview_flutter`, `Connection`, `lib/data/`. No `lib/ble/`.

**Vendoring:** Blockly is a **pinned upstream submodule** at
`app/upstream/blockly` (`RaspberryPiFoundation/blockly`, the owner declared by
the pinned v13.1.0 source; Apache-2.0; pristine — never edited in place; pin +
rationale in `app/DEPENDENCIES.md`), mirroring the firmware's
`firmware/upstream/micropython` discipline. The WebView asset bundle is built
from that pin when A-31 starts; attribution ships in `THIRD_PARTY_LICENSES`
(X-11). The upstream Python generator embeds multiline Python inside
JavaScript template literals. Its raw line-leading `try:` tokens cause Apple's
distribution classifier to treat that otherwise sealed data file as an
unsigned Python executable inside `App.framework`. The deterministic vendor
step therefore writes each such token as the JavaScript template interpolation
`${"try"}:`. Evaluation still emits the exact Python token `try:` while the
packaged file remains ordinary data. The build refuses any vendored asset that
the host `file` classifier reports as `script text executable` (BLD-11).

**Satisfies:** FR-BLOCKS-1..13, CON-6/7.

### 4.7 `lib/plots/` — live plots

**Responsibility:** render live plots (`fl_chart`) derived **purely** from program console output (CSV/streamed values), with a user-configurable parse model (which columns/series, delimiter, regex) — no special data-event opcode.

**Public API (sketch):** `PlotController` subscribing to `ConsoleEvent`; a `SeriesParser` (configurable) producing `List<DataPoint>` per series; bound, downsampled series buffers.

**Key state:** parser config (persisted per project), series ring buffers, axis/window settings. The configuration UI detail is tracked by [OI-5](specs.md) and specified in [§11.3](#113-plots).

**Dependencies:** `Connection.console`/`ConsoleEvent` (neutral types only), `fl_chart`. No `lib/ble/`.

**Satisfies:** FR-PLOTS-1..3, CON-7.

### 4.8 `lib/connect/` — scan/connect flow UI

**Responsibility:** present a scan filtered to the PyBLE service UUID, listing each board by its **advertised name + RSSI** — the user-set device **label** when set, otherwise the default `PyBLE-XXXX` ([§7.1](#71-scan--connect)) — never a raw list; drive connect (GATT → TX subscribe → MTU 247 → INFO/HELLO → show `DeviceInfo` incl. `deviceId`/`label`) before enabling editor/console/file actions; surface permission/adapter state with localized rationale; list and reconnect saved boards; refuse an unsupported `proto_version` with an update prompt; scan→connect→use with no pairing-code/account/lease. It also hosts the post-connect **screenless-identity** UX: a **rename-board** action ([§11.5](#115-screenless-identity--rename--identify)) and a cap-gated **Identify** action.

**Screenless-identity UX (FR-CONN-10/11/12, SEC-8/9):**

- **Rename board.** A rename action calls `Connection.setLabel(label)`; an empty value clears back to `PyBLE-XXXX`. Because the label is **broadcast** in the advertisement, the rename UI MUST warn that the name is publicly visible to anyone scanning, nudge against entering personal data (PII), and **bound the input length** to the board's limit (default `PyBLE-XXXX` is non-PII) — SEC-8, [protocol.md §10](../protocol.md#10-security-note-v1). On success the new label becomes the scan-list/diagnostics name on next advertisement and `DEVICE_INFO.label`.
- **Identify.** The Identify button is shown **only** when `caps.hasIdentify` is set ([§8.6](#86-hello--capabilities)); when the board has no identify LED yet (`caps.identifyLed == null`) the action first **prompts the user to configure it** via `Connection.setIdentifyLed({gpio, activeLevel})`, then calls `Connection.identify()` to blink it. An `EUnsupported` from `identify()` (no LED configured) is surfaced as a clear localized typed error ([§14](#14-error-handling--mapping)), never a silent failure.
- **Not a profile / not a gate.** The configured identify-LED GPIO is device UX config for the IDENTIFY blink only — it maps no hardware for user code and is not a routing/pin profile or capability map. The flow MUST NOT use `deviceId`, MAC, or `label` to authorize anything or build a remote board registry (SEC-9, extending SEC-6).

**Runtime connection session — FROZEN (A-22 · `[docs]` 2026-07-02, [ADR-0009](../../decisions/0009-runtime-connection-manager.md)).** The active `Connection` **changes at runtime** (launch → scan → pick → GATT+HELLO → live board → disconnect). Because building a live board from a scan result is transport-facing (`BleAdapter.connect(id) → BleLink → PbleConnection.fromLink(...)`), the session orchestration lives **in `lib/pble`** (the sole importer of `lib/ble`, CON-8 / FR-BLE-8) — **never** in `lib/connect`, `lib/app`, or `main.dart`. The connect UI binds only to the neutral types below.

- **Neutral scan seam (`lib/pble`).** `class ScanHit { final String id; final String name; final int rssi; }` — the advertised board, retyped 1:1 off `BleScanResult` (`name` is the advertised name **verbatim**: the user-set label, else `PyBLE-XXXX`; value equality by `id`). `abstract interface class Scanner { Stream<List<ScanHit>> scan({Duration? timeout}); Future<void> stopScan(); }` — emits an **accumulating, deduped-by-`id`, latest-RSSI snapshot list** (accumulation lives in `lib/pble`, not the UI). A shipped `FakeScanner implements Scanner` scripts snapshots for tests. **This supersedes the illustrative `DiscoveredBoard`/`Scanner`-in-`lib/connect` sketch** — the seam is a neutral `lib/pble` type, exported through the `pble` barrel.
- **Readiness seam.** `BleReadinessSource` (`BleReadiness current` + `Stream<BleReadiness> readiness`, [§7.4](#74-permissions--platform-quirks)) is **re-exported through the `pble` barrel** (the enum already is), so the connect UI observes adapter/permission transitions without importing `lib/ble`.
- **`ConnectionManager` (neutral, `lib/pble`).** Holds the session; composes a `Scanner`, a `BleReadinessSource`, and a `ConnectionFactory` (`typedef ConnectionFactory = Future<Connection> Function(String deviceId)`). Surface: `Connection get connection` (the **stable facade**, [§6.2](#62-binding-pattern)); `Stream<List<ScanHit>> get scanResults`; `BleReadinessSource get readiness`; `ValueListenable<ConnectPhase> get phase`; `ScanHit? get selected`; `Object? get lastError`; and `startScan({Duration? timeout})` / `stopScan()` / `connect(String id)` / `disconnect()` / `dispose()`. `enum ConnectPhase { idle, scanning, connecting, connected, failed }` is the **connect-flow session phase — distinct from `ConnState`** (`scanning`/`connected` are deliberately not `ConnState` members, [§5.2](#52-shared-types)). `connect(id)` calls the `ConnectionFactory`, publishes the resulting `Connection`, and lets `PbleConnection.fromLink`'s link observation drive `connecting → ready`. The production `PbleConnectionManager.production({required String appName, required String appVersion})` wires the real `flutter_blue_plus` stack (`FbpBleAdapter` as scan source **and** connector, `FbpBleReadinessSource`) **internally**, so `main.dart` names no `lib/ble` type ([§6.2](#62-binding-pattern)).
- **Connect controller + view (`lib/connect`).** A `ConnectController` (Riverpod `Notifier`, ADR-0007) projects the manager into an immutable `ConnectState { ConnectPhase phase, BleReadiness readiness, List<ScanHit> hits, ScanHit? selected, DeviceInfo? deviceInfo, Object? error }` (with `int get hitCount`), exposing `startScan`/`stopScan`/`connect(id)`/`disconnect`. On reaching `connected` it reads `connection.deviceInfo()` and stores it — the **DeviceInfo proof** the UI shows. `ConnectScreen` (the surface, hosted by `lib/app/pages/connect_page.dart` as a thin delegator) renders: the readiness banner (adapter-off / unauthorized / unsupported with localized rationale, FR-CONNECT-3); the scan CTA → live `ScanHit` list (name + RSSI, FR-CONNECT-1) → connecting indicator → connected `DeviceInfo` card (chip / mpy / free-mem, FR-CONNECT-2) → disconnect; the unsupported-`proto_version` update prompt (FR-CONNECT-6); and a **live diagnostics panel** (adapter state, scanning yes/no, hit count, last-error detail) for on-hardware debugging (FR-CONN-6).
- **Scope of this freeze.** Delivers FR-CONNECT-1/2/3/5/6 + FR-CONN-6. **Saved-boards persistence** (FR-CONNECT-4 list/reconnect-by-remembered-id) depends on Drift `board_ref` (`lib/data`, A-24) which does not exist yet — auto-reattempt on an *unexpected* drop works today (A-03 `ReconnectingBleLink` + re-HELLO), but the persisted saved-board **list** is A-24/S5. The **screenless-identity UX** (rename / Identify, `setLabel`/`setIdentifyLed`/`identify`) is A-36/A-37/S7 and is **not** in this increment.

**Public API (sketch):** `ConnectController` (Riverpod `Notifier`) over the neutral `ConnectionManager` above; plus (A-36/A-37) `renameBoard(String label)`, `configureIdentifyLed(IdentifyLed)`, and `identify()` delegating to `Connection`.

**Key state:** scan results (advertised name + RSSI), selected board, connect phase, saved-board list (from Drift `board_ref`), diagnostics (state/RSSI/MTU/caps incl. `deviceId`/`label`/`hasIdentify`/`identifyLed`), pending rename input (bounded), pending identify-LED config.

**Dependencies:** the neutral `ConnectionManager` seam (`Connection` + `Scanner`/`ScanHit` + `BleReadinessSource`, all via the `pble` barrel), `lib/data/` (saved boards, A-24), `lib/localization/`. Never `lib/ble` (CON-8).

**Satisfies:** FR-CONNECT-1..6, FR-CONN-1/5/6/10/11/12, FR-UI-3, CON-1/5, SEC-6/8/9, NFR-USE-1.

### 4.9 `lib/github_import/` — public-repo import

**Responsibility:** fetch a folder of `.py` files from a **public** GitHub repo over HTTPS (no account/token), let the user pick subpath/branch and preview, write via `Connection.putFile`, store locally as the source of truth, and record provenance.

**Public API (sketch):** `GithubImporter { Future<RepoTree> browse(repoUrl, ref); Future<ImportResult> import(selection, Connection c, ProgressCb); }`.

**Key state:** repo URL/ref/subpath, fetched file list (`.py`/data only filter), conflict set vs existing board files, provenance record for `github_imports`.

**Dependencies:** `http`/`dio` (HTTPS), `Connection.putFile`, `lib/data/`, `lib/localization/`. No `lib/ble/`.

**Satisfies:** FR-IMPORT-1..6, IF-4, DAT-6, NFR-OFF-2, CON-3.

### 4.10 `lib/data/` — persistence (Drift)

**Responsibility:** the offline-first Drift (SQLite) database and DAOs for the six content tables plus saved-board settings; migrations; hydration on launch. Source of truth for user content (D4).

**Public API (sketch):** typed DAOs — `ProjectsDao`, `ProjectFilesDao`, `SnapshotsDao`, `RunSessionsDao`, `ConsoleLogsDao`, `GithubImportsDao`, and a `SettingsStore` for `board_ref`/locale override.

**Key data structures:** the six tables of [§9](#9-persistence-design-libdata) ([specs.md §8](specs.md) / [PRD §12.1](../prd.md)). No managed-fleet/lab/calibration tables (DAT-8).

**Dependencies:** `drift`, `sqlite3`. Used by editor/console/files/connect/import controllers.

**Satisfies:** FR-PROJ-1..7, DAT-1..8, IF-3, NFR-OFF-1..3, SEC-3/5.

### 4.11 `lib/localization/` — i18n

**Responsibility:** `intl`/ARB strings with `en` day-one; the parity gate; platform-locale default with optional override; ASCII technical identifiers left unlocalized; data-driven error-explanation strings.

**Public API (sketch):** generated `AppLocalizations`; an `Arb` key registry; a `LocaleController` (platform default + user override).

**Dependencies:** `flutter_localizations`, `intl`. Consumed everywhere user-facing text appears.

**Satisfies:** FR-I18N-1..5, NFR-A11Y-1/2/4, BLD-5, CON-9.

### 4.12 `lib/app/` — About and open-source information

**Responsibility:** a board-independent About route reachable from the global
toolbar, runtime package metadata, the product's frozen MIT/privacy identity,
and an explicit offline path into Flutter's `LicenseRegistry`.

**Public API:** `AboutPage(buildInfoLoader:)`; immutable `AppBuildInfo`; and a
single `AppBuildInfoLoader` seam whose production implementation calls
`PackageInfo.fromPlatform()` once. Tests inject pending, success, blank-build,
and failure futures without a platform channel.

The static `kAppName`/`kAppVersion` constants remain ASCII PBLE/1 HELLO wire
identifiers. They are not the About page's display metadata. The page obtains
the installed package version/build at runtime, localizes only the
label/format, and degrades truthfully while pending or unavailable.

The route owns no provider and imports neither `lib/ble` nor `lib/pble`.
Opening it or the nested licenses route cannot call `Connection`, mutate the
selected IDE surface/document, or require network access. Wide toolbars expose
a direct About action; compact toolbars retain their bounded action count by
placing Soft-reboot and About in a labelled More menu. The page is
`SafeArea` + scrollable, uses a centered bounded responsive layout, semantic
headings, Signal tokens, and ≥48 dp actions.

**Dependencies:** `package_info_plus` (BSD-3-Clause; admitted solely for actual
installed version/build metadata), Flutter `LicenseRegistry`.

**Satisfies:** FR-ABOUT-1..8, IF-6, NFR-OFF-1..3, NFR-A11Y-3, CON-5/8/9,
SEC-3/5.

## 5. The Connection API design

`Connection` is the single seam (D1). It is owned in shape by [app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to); this section is the engineering detail and the `FakeConnection` design. — *(satisfies FR-CONN-1..9.)*

### 5.1 The `Connection` interface

```dart
abstract interface class Connection {
  ValueListenable<ConnState> get state;        // disconnected/connecting/ready/running (FR-CONN-5)
  Diagnostics get diagnostics;                 // state, rssi, mtu, caps (FR-CONN-6)
  Future<DeviceInfo> deviceInfo();             // chip, mpyVersion, freeMem, fsRoot (FR-CONN-1)

  // run / console
  Future<void> runFile(String path);           // (FR-CONN-2)
  Future<void> runSource(String source);       // (FR-CONN-2)
  Future<void> stop();                         // (FR-CONN-2)
  Future<void> softReboot();                   // (FR-CONN-2); fire-then-expect-disconnect (protocol.md §6)
  Stream<RunState> get runState;               // idle/running/done/error from RUN_STATE 0x40 (FR-PBLE-11)
  Stream<ConsoleEvent> get console;            // {stream, bytes} (FR-CONN-3)
  Future<void> sendInput(String text);         // (FR-CONN-3)

  // files (progress via onProgress -> FR-CONN-9)
  Future<List<RemoteEntry>> listDir(String path);          // (FR-CONN-4)
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress});
  Future<void> putFile(String path, Uint8List bytes, {ProgressCb? onProgress});
  Future<void> delete(String path);
  Future<void> mkdir(String path);
  Future<void> rename(String from, String to);

  // screenless identity & identify (per-device UX config, NOT a profile/gate)
  Future<void> setLabel(String label);                     // SET_LABEL 0x50; "" clears to PyBLE-XXXX (FR-CONN-10)
  Future<void> setIdentifyLed(IdentifyLed config);         // SET_IDENTIFY_LED 0x51; {gpio, activeLevel} (FR-CONN-11)
  Future<void> identify();                                 // IDENTIFY 0x52; EUNSUPPORTED if unconfigured (FR-CONN-12)
}
```

The surface exposes **only** the board-control verbs in scope. It MUST NOT expose any session-lock/heartbeat, board-identity gating, pairing-token, or managed-fleet operation (FR-CONN-8; the non-goals of [PRD §4.3](../prd.md)). Single-active-writer semantics ([§6.3](#63-single-active-writer--serialization)) and `EBUSY` surfacing live behind these methods (SEC-2).

`setLabel`/`setIdentifyLed`/`identify` are the board's **own per-device UX configuration**, persisted on the board ([protocol.md §4](../protocol.md#4-opcodes) `0x50`–`0x52`). They are **not** a routing/pin profile, board-capability map, or access-gating mechanism: `setIdentifyLed` maps no hardware for user code (it configures only the single optional identify status-LED), and the app MUST NOT use `device_id`, MAC, or `label` to authorize anything or to build a remote board registry (FR-CONN-10/11, SEC-9; distinct from and not weakening the [PRD §4.3](../prd.md) rejection of routing/pin profiles and MAC gating). The Identify action is offered **only** when the board advertised `has_identify` ([§8.6](#86-hello--capabilities), FR-CONN-12).

**Run-state stream & `ConnState` derivation (S3 A-11 · `[docs]` 2026-07-02, additive to [app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to)).** `runState` is a broadcast `Stream<RunState>` fed by `RUN_STATE` (`0x40` EVT, `[state:u8]` 0=idle / 1=running / 2=done / 3=error — [protocol.md §6](../protocol.md#6-run--stop--console)). It carries the full four-value run lifecycle the console (FR-CONSOLE-3) and run toolbar (FR-RUN-3) need; the four-value `ConnState` (FR-CONN-5) is **derived** from it — `ConnState.running` while `runState == running`, otherwise `ConnState.ready` once the session is up — so `ConnState` never has to distinguish idle/done/error. `runFile`/`runSource` complete on the RUN `RSP` (throwing `EBusy`/`EBadReq`/`ERange` on a non-OK status); a program-level failure (missing file, uncaught exception) is **not** a `RSP` error — it arrives asynchronously as a `stderr` `ConsoleEvent` + `runState == error`, and the run Future still completed OK. `softReboot()` is **fire-then-expect-disconnect**: it sends `SOFT_REBOOT` (`0x22`) and returns without awaiting a guaranteed `RSP` (the reset may preempt it), after which the link drops and the A-03 reconnect path drives `ConnState` back through `connecting → ready`. `runState`/`RunState` are additive to the minimal [app.md §3](../app.md#3-the-connection-api-the-seam-every-widget-binds-to) surface (as `dispose()` and the S2 caps fields were) and fold into the A-14 full freeze; the identity verbs `setLabel`/`setIdentifyLed`/`identify` are added to the surface at A-14 and driven by UI at A-22/A-36/A-37 — **not** S3.

### 5.2 Shared types

`ConnState { disconnected, connecting, ready, running }`; `RunState { idle, running, done, error }` (mirrors `RUN_STATE` `0x40` `[state:u8]`; the source for `Connection.runState` and the derived `ConnState.running` — S3 A-11 `[docs]`); `DeviceInfo { chip, mpyVersion, freeMem, fsRoot, deviceId, label, protoVersion, agentVersion, mtu, window, chunk, hasSd, hasIdentify, identifyLed, autoRun }` (the S2 caps fields `protoVersion`/`agentVersion`/`mtu`/`window`/`chunk`/`hasSd`/`hasIdentify`/`identifyLed`/`autoRun` are **additive** and frozen A-10 `[docs]` 2026-07-02: they are parsed from the single HELLO / `DEVICE_INFO` / INFO caps payload — one payload feeds all three ([protocol.md §4](../protocol.md#4-opcodes) `0x02`, [§7](../protocol.md#7-hello--capabilities)) — and are default-valued so pre-S2 construction is unaffected; `identifyLed` is the GPIO as `int?` (null when the caps byte is `255`/none). At S2 the `Connection` seam exposes caps only through `deviceInfo()` (there is no `diagnostics` getter until A-14/S4, at which point `Diagnostics.caps` reads this same negotiated `DeviceInfo`). The screenless-identity fields `deviceId` = the stable MAC-derived suffix and `label` = the user-set device label, or empty, from DEVICE_INFO / the INFO read — [protocol.md §2](../protocol.md#2-ble-transport-gatt)/[§4](../protocol.md#4-opcodes) `0x02`; `deviceId` is display-only, never authorization — FR-CONN-1, SEC-9); `Diagnostics { state, rssi, mtu, caps }` (where `caps` carries `deviceId`, `label`, `hasIdentify`, `identifyLed` per [§8.6](#86-hello--capabilities) — FR-CONN-6); `IdentifyLed { int gpio, int activeLevel /* 0 active-low | 1 active-high */ }`; `ConsoleEvent { ConsoleStream stream /* stdout|stderr|system */, Uint8List bytes }` (the wire `CONSOLE_DATA` `0x30` carries only `stdout`=0/`stderr`=1; the `system` tag is **client-synthesized** by `lib/pble` for app-side notices — e.g. run finished, link dropped — and never comes off the wire, S3 A-11 `[docs]`); `RemoteEntry { name, isDir, size }` (the **leaf entry name** from `FILE_LIST` [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core) `{[etype][esize][nlen][name]}`, **not** a full path — the caller composes the path from the `listDir` argument; frozen S3 A-12 `[docs]` 2026-07-02, superseding the earlier `path` field to match the HIL-frozen wire); `TransferProgress { sent, total }`; `ProgressCb = void Function(TransferProgress)`; the `PbleException` hierarchy ([§14](#14-error-handling--mapping)). The connect-flow seam adds `ScanHit { String id, String name, int rssi }` (the advertised board, retyped 1:1 off `BleScanResult`; `name` verbatim = label or `PyBLE-XXXX`; equality by `id`) and `ConnectPhase { idle, scanning, connecting, connected, failed }` (the runtime **session** phase held by `ConnectionManager`, [§4.8](#48-libconnect--scanconnect-flow-ui) / [ADR-0009](../../decisions/0009-runtime-connection-manager.md)) — **distinct from `ConnState`**: `scanning`/`connected` are session phases, **never** `ConnState` members (`ConnState` stays the frozen four-value `{ disconnected, connecting, ready, running }`). All ASCII technical names (FR-I18N-4).

### 5.3 `FakeConnection` design

`FakeConnection implements Connection` (D5) with no BLE dependency: a scriptable `DeviceInfo`/`caps` (including `deviceId`, `label`, `hasIdentify`, `identifyLed`); a programmable console script (push `ConsoleEvent`s on a timer to simulate `stdout`/`stderr`/tracebacks); an in-memory file tree for `listDir/getFile/putFile/delete/mkdir/rename`; `ProgressCb` driven on a synthetic schedule; an **error-injection** hook to make any method throw a chosen `PbleException` (e.g. `Enospc`, `Ebusy`); and a `ConnState`/`Diagnostics` it can drive through transitions. For the screenless-identity seam it also holds an in-memory `label`/`identifyLed`/`hasIdentify`: `setLabel` updates the scriptable `DeviceInfo.label` (empty resets it to the synthetic `PyBLE-XXXX` derived from `deviceId`, so the rename round-trip is testable); `setIdentifyLed` updates the held `identifyLed` (and lets `hasIdentify` flip true); and `identify()` records the call but **throws the injected `EUnsupported`** when `hasIdentify` is false or `identifyLed` is null, so the cap-gated UI and the EUNSUPPORTED path ([§14](#14-error-handling--mapping)) are exercised without a board. It is the default injection for widget/golden/unit tests (FR-CONN-7, FR-CONN-10/11/12), overriding the `Connection` provider (D3).

## 6. State management & data flow

### 6.1 Where state lives

- **Connection-derived runtime state** (connState, diagnostics, console buffer, run state, transfer progress) is exposed through Riverpod providers (D3) sourced from the injected `Connection`. UI watches; it does not poll (FR-CONN-5).
- **Durable user state** (projects, files, snapshots, run sessions, console logs, imports, `board_ref`, locale) lives in Drift (`lib/data/`, D4) and is the source of truth (NFR-OFF-1).
- **Ephemeral UI state** (active tab, selection, scroll) lives in widget/controller scope.

### 6.2 Binding pattern

UI reads down (watch providers) and writes up (call `Connection` methods / DAO mutations). A single `connectionProvider` yields the active `Connection`; tests override it with `FakeConnection`. Streams (`console`) and `ValueListenable`s (`state`) are adapted into providers so a tab switch never tears down a subscription (FR-CONSOLE-7).

**Runtime session — FROZEN (A-22 · `[docs]` 2026-07-02, [ADR-0009](../../decisions/0009-runtime-connection-manager.md)).** The active `Connection` changes at runtime, so the seam is preserved as a **stable facade** rather than a swapped root value:

- **Root injection moves up to `connectionManagerProvider`** (`Provider<ConnectionManager>`, throws until overridden). `main.dart` overrides it with `PbleConnectionManager.production(appName: kAppName, appVersion: kAppVersion)` — importing `package:pyble/pble/…` only, so `main.dart` names no `lib/ble` type (the import-boundary gate scans `main.dart`). `kAppName` (`"PyBLE"`) / `kAppVersion` are ASCII HELLO `app_name`/`app_version` constants ([protocol.md §7](../protocol.md#7-hello--capabilities)) held in `lib/app/` and kept in sync with the `pubspec` base version by hand. No runtime metadata dependency crosses into `lib/pble`; `package_info_plus` is confined to the About-page adapter ([§4.12](#412-libapp--about-and-open-source-information)) and never supplies a wire value. The constants are wire identifiers, not display text (FR-I18N-4, FR-ABOUT-3).
- **`connectionProvider` is preserved, now derived:** `Provider<Connection>((ref) => ref.watch(connectionManagerProvider).connection)`. `ConnectionManager.connection` is a **stable facade** whose identity never changes: its `state` reflects the whole session (`disconnected` while idle/scanning/failed, `connecting` during GATT+HELLO, then the live board's `ready`/`running`), and its verbs delegate to the live board when connected and throw a **typed not-connected error** otherwise (never a silent success). `connStateProvider` is **unchanged** (`connectionProvider.state`). Every S1–S3 widget (`ConnectionStatusPill`, `PinReferencePage` `FutureBuilder`, `FilesPage`) keeps compiling and now shows real state.
- **Test compatibility:** a test overriding `connectionProvider` directly with a `FakeConnection` still **wins** (the override replaces the derived body), so the existing widget/golden suite (`shell_harness.pumpShell`) is untouched. New connect-flow tests inject `FakeScanner` + a `ConnectionFactory` returning `FakeConnection` + a fake `BleReadinessSource` through a `PbleConnectionManager`, or override `connectionManagerProvider` with a fake manager — no fake radio / fake `BleLink` needed (FR-CONN-7, D5).
- The `ConnectController` (`Notifier`) projecting the manager into `ConnectState` for the connect surface lives in `lib/connect` ([§4.8](#48-libconnect--scanconnect-flow-ui)); it is the one place with the connect-flow intents.

### 6.3 Single active writer / serialization

The app is one client to one board (SEC-2). `PbleConnection` serializes mutating operations (`runFile`/`runSource`/`putFile`/`delete`/`mkdir`/`rename`/`softReboot`) through an internal queue so commands cannot interleave; a `RUN` while running surfaces `EBUSY` as `EBusy` ([§14](#14-error-handling--mapping)) rather than corrupting state (FR-RUN-3). Read-only ops (`listDir`, `deviceInfo`) and `stop` are not blocked behind a long transfer beyond correctness.

## 7. BLE transport design (`lib/ble/`)

Implements the byte boundary; references [protocol.md §2](../protocol.md#2-ble-transport-gatt) for UUIDs/MTU. — *(satisfies FR-BLE-1..8, IF-1/5, NFR-COMPAT-2/3.)*

### 7.1 Scan & connect

`scan()` uses `flutter_blue_plus` **filtered to the PyBLE service UUID** (FR-BLE-1, CON-1) and emits `BleScanResult { id, name, rssi }`, where `name` is the **advertised name** verbatim — the board's user-set device **label** when one is set, otherwise the default `PyBLE-XXXX` ([protocol.md §2](../protocol.md#2-ble-transport-gatt); the label replaces the default name in the advertisement so it is visible pre-connect). The adapter does not interpret or rewrite the name; it passes the advertised string up for `lib/connect` to render alongside RSSI ([§4.8](#48-libconnect--scanconnect-flow-ui)). A raw unfiltered list is never produced. `stopScan()` is called before `connect()` (FR-BLE-5). `connect()` opens GATT, subscribes to the TX (Notify) characteristic, and requests **MTU 247**, accepting any negotiated value down to the BLE default and reporting it via `mtu` (FR-BLE-2). `lib/ble` emits individual `BleScanResult`s; the neutral **`Scanner`** seam and its accumulation into a deduped, latest-RSSI `Stream<List<ScanHit>>` live in **`lib/pble`** ([§4.8](#48-libconnect--scanconnect-flow-ui), [ADR-0009](../../decisions/0009-runtime-connection-manager.md)) so no widget imports `lib/ble` (CON-8).

### 7.2 Byte boundary

`inbound` is a `Stream<List<int>>` of raw TX notification payloads; `write(bytes)` writes to RX (Write / Write-Without-Response). The adapter never interprets frame contents (FR-BLE-3) — fragmentation/reassembly is entirely `lib/pble/`'s job ([§8.2](#82-fragmentation--reassembly)).

### 7.3 Reconnect

`linkState` exposes up/down transitions; on link loss the adapter auto-reattempts and can reconnect a saved board by remembered identifier (FR-BLE-4). In-flight transfers resume at the `lib/pble/` layer ([§8.4](#84-file-transfer-state-machine)) — the adapter only restores the byte pipe.

**Frozen reconnect contract (S3 A-03 · `[docs]` 2026-07-02).**

- **`BleLinkState` (extended, additive to the S2 two-value enum):** `{ disconnected, connecting, connected, reconnecting }`. `connecting` = first establishment; `connected` = link up (TX subscribed, MTU negotiated); `reconnecting` = auto-reattempt in progress after an *unexpected* drop; `disconnected` = down, or the backoff policy is exhausted, or a user-initiated `disconnect()`.
- **Bounded backoff (`BleBackoff`, frozen values):** `initial = 500 ms`, `factor = 2.0`, `maxInterval = 8 s`, `maxAttempts = 6` → attempt intervals `0.5, 1, 2, 4, 8, 8 s`, then give up and settle on `disconnected` surfacing a neutral `BleLinkException` ([§14.1](#141-status-byte--typed-exception--localized-message)). **No jitter** in v1 (deterministic conformance/unit tests); jitter is a post-v1 option. The policy is injectable so the mocked transport can shrink it.
- **Reconnect target:** the `BleLink` remembers the `id` it bound to and auto-reattempts to it; `BleAdapter.connect(id)` is the reconnect-by-remembered-id entry the saved-board flow reuses later (the `board_ref` persistence is A-24/S5 — S3 only takes an `id`). A **user-initiated** `disconnect()` disables auto-reattempt (no reconnect after intentional teardown).
- **`lib/pble` maps `BleLinkState → ConnState` (FR-CONN-5):** `connecting`/`reconnecting` → `ConnState.connecting`; `connected` → run HELLO (re-negotiate on every (re)connect) and, on success, → `ConnState.ready` (or `running` if `runState == running`); `disconnected` → `ConnState.disconnected`. **S3 scope = link restoration + re-HELLO + `ConnState` transitions only.** In-flight **transfer resume** (`FILE_STAT` → verified offset → resume `BEGIN`, FR-PBLE-10 / NFR-REL-1) and offline buffer preservation (NFR-REL-3) are **A-13/S4 + A-20/A-24**, not S3.

### 7.4 Permissions & platform quirks

`permissions` surfaces enough detail for a localized rationale (FR-BLE-6, IF-5). iOS requires `NSBluetoothAlwaysUsageDescription`; Android 12+ requires `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT`, and older Android needs location handling. Known quirks isolated here (FR-BLE-7): iOS does not expose the device MAC (use the platform-assigned identifier for `board_ref`); Android MTU negotiation timing differs and may return a lower MTU; adapter-off and permission-denied states are surfaced upward, never swallowed. No USB/Wi-Fi runtime path exists (CON-2, NFR-COMPAT-3).

**Frozen permission / readiness contract (S3 A-04 · `[docs]` 2026-07-02).**

- **Typed, mockable readiness seam (surfaced through `lib/pble` ONLY, FR-BLE-8):** `enum BleReadiness { ready, adapterOff, unauthorized, unsupported }` plus a `Stream<BleReadiness>` of transitions (a reasons stream) so the layer above can render a localized rationale *later*. `lib/ble` derives it from `FlutterBluePlus.adapterState` (`on → ready`, `off → adapterOff`, `unauthorized → unauthorized`, `unavailable → unsupported`); `lib/pble` re-exposes it as a neutral type — **no widget imports `lib/ble/`** and no `flutter_blue_plus` enum crosses the seam (CON-8).
- **Platform manifest keys (A-04 content, owned by app-ble-engineer; app-build-smith owns the surrounding skeleton):** iOS `ios/Runner/Info.plist` → `NSBluetoothAlwaysUsageDescription`. Android `android/app/src/main/AndroidManifest.xml` → `BLUETOOTH_SCAN` (`android:usesPermissionFlags="neverForLocation"`) + `BLUETOOTH_CONNECT`, and legacy `ACCESS_FINE_LOCATION` with `android:maxSdkVersion="30"` (Android ≤ 11 only). The `flutter_blue_plus_android` plugin manifest is intentionally blank, so the app MUST declare these itself; `startScan(androidUsesFineLocation: false)` since the scan is service-UUID-filtered and derives no location.
- **Dependency decision — NO new dependency (prefer-zero, BLD-2):** the pinned `flutter_blue_plus` (1.36.8) already (a) exposes `adapterState` covering on/off/`unauthorized`/`unavailable`, and (b) requests the Android 12+ runtime BLE permissions at `startScan`; iOS surfaces authorization denial as `adapterState == unauthorized` off the Info.plist string. `permission_handler` is **not** required and MUST NOT be added.
- **No user-facing strings at S3:** A-04 ships the seam + manifest keys only; the localized rationale UI and its ARB entries are **A-22/S5**. S3 therefore adds no ARB keys and the locale-parity gate stays trivially green.

## 8. PBLE/1 client design (`lib/pble/`)

References [protocol.md](../protocol.md) throughout; redefines nothing. — *(satisfies FR-PBLE-1..15.)*

### 8.1 Frame codec

Encode/decode the [protocol.md §3.1](../protocol.md#3-framing) message (`VER`/`TYPE`/`OPCODE`/`ID`/`LEN`/`PAYLOAD`/`CRC32`); `LEN` little-endian `uint16`; compute/verify IEEE CRC-32 over `VER…PAYLOAD` little-endian (FR-PBLE-1). A reassembled frame whose CRC fails is dropped and surfaced as `ECRC`, never delivered upward (FR-PBLE-3).

### 8.2 Fragmentation / reassembly

Outbound messages are split across `MTU − 4` boundaries with the [protocol.md §3.2](../protocol.md#3-framing) `FRAG_HDR` (`bit7 FIRST`, `bit6 LAST`, `bits5..0 index mod 64`); inbound packets are concatenated from FIRST through LAST to reproduce the original message byte-identically (FR-PBLE-2). The per-fragment payload tracks the negotiated MTU from `lib/ble/`.

### 8.3 Request/response correlation & event routing

A pending-request table keyed by the 1-byte `ID` (1–255, app-chosen) matches each `CMD` to its `RSP`; `EVT` frames (`ID = 0`) route by opcode to the console stream, run-state notifier, or file-transfer ack/data handlers (FR-PBLE-4). Each pending request carries a completer + timeout.

### 8.4 File-transfer state machine

Implements [protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core):

```text
UPLOAD (putFile)
  PUT_BEGIN{path,total_size,crc32} -> RSP{status, resume_offset}    (FR-PBLE-8)
     resume_offset>0 -> start window at resume_offset (resume, FR-PBLE-10)
  loop: PUT_DATA{offset,bytes}, window <= W unacked (W from HELLO;   (NFR-PERF-1)
        current ref 8, missing-cap fallback 4; chunk = one MTU)
        on PUT_ACK{ack_offset}: advance window; retransmit gaps
  PUT_END{crc32} -> RSP{status}; success ONLY on whole-file CRC match (NFR-REL-2)
  onProgress(sent,total) throughout                                  (FR-CONN-9, NFR-PERF-2)

DOWNLOAD (getFile)
  GET_BEGIN{path,offset} -> RSP{status,total_size,crc32}             (FR-PBLE-9)
  GET_DATA{offset,bytes} events -> GET_END{crc32}; verify size+CRC
RESUME (on reconnect)
  FILE_STAT{path} -> verified partial offset -> resume BEGIN at offset (FR-PBLE-10, NFR-REL-1)
```

State: active-transfer context (path, total, expected/running CRC, ack_offset, window bookkeeping). Only one transfer active at a time (serialized, [§6.3](#63-single-active-writer--serialization)); a second `*_BEGIN` while one is active is refused client-side and by the board as `EBusy` ([protocol.md §5](../protocol.md#5-file-transfer-the-reliability-core)).

**S3 (A-12) vs S4 (A-13) boundary (`[docs]` 2026-07-02; window wording reconciled 2026-07-29).** A-12/S3 ships the **wire-correct simple** paths: `getFile` (BEGIN → collect `GET_DATA` events → `GET_END`, verifying assembled length `== total_size` **and** whole-file CRC before success) and `putFile` as a **sequential send-then-await-ACK upload** (effective window depth 1: send one `PUT_DATA` chunk of `caps.chunk` bytes, await `FILE_PUT_ACK` advancing the watermark, resend from the watermark on a gap/duplicate, then `PUT_END{crc32}` — success only on `RSP OK`). `putFile` honours the `FILE_PUT_BEGIN` `resume_offset` when the board reports one (`0` at S5, so S3 always starts at offset 0). The true **W-deep sliding window (`W` advertised by HELLO; current reference agent 8, missing-cap compatibility fallback 4; unacked pipelining and Go-Back-N retransmit)** and **resume-on-reconnect via `FILE_STAT`** (FR-PBLE-8/-10, NFR-REL-2, NFR-PERF-1) land at **A-13/S4** — the state machine above is the A-13 target, of which A-12 implements the depth-1 subset. `listDir` reads exactly `count` entries from the single `FILE_LIST` `RSP`; the wire defines **no continuation cursor**, so `more == 1` is a **truncation indicator only** (the listing exceeded the board worker buffer), never a re-issue — A-12 parses `count` entries and does not over-read; surfacing the truncation to the user is the explorer's concern (A-30/S7).

### 8.5 Console stream

`CONSOLE_DATA` events become `ConsoleEvent { stream: stdout|stderr|system, bytes }` on the `console` stream; `sendInput(text)` issues `CONSOLE_INPUT` (FR-PBLE-12). Observe-anywhere: output is delivered regardless of which client triggered the run (FR-CONSOLE-5).

### 8.6 HELLO / capabilities

HELLO is the first exchange after connect ([protocol.md §7](../protocol.md#7-hello--capabilities)): send `proto_versions[]` + `app_name`/`app_version`, receive `proto_version` + `caps` (FR-PBLE-5). Beyond the transfer/runtime fields, `caps` carries the screenless-identity fields `device_id` (the stable MAC-derived suffix), `label` (the user-set label, or empty), `has_identify` (the board supports `IDENTIFY`), and `identify_led` (the configured identify-LED GPIO, or null) — these are **additive within PBLE/1** and an older client simply ignores them. The client never issues a request for a capability the board did not advertise (FR-PBLE-7): in particular it offers the Identify action **only** when `has_identify` is set ([§4.8](#48-libconnect--scanconnect-flow-ui), FR-CONN-12), and treats `device_id`/`label` as display-only, never authorization (SEC-9). An unsupported chosen `proto_version` is refused with a typed error (FR-PBLE-6, surfaced by the connect flow, FR-CONNECT-6, BLD-7).

### 8.7 Status byte → typed exception

Each [protocol.md §8](../protocol.md#8-status--error-codes-1-byte-status-in-rsp) status maps to a distinct `PbleException` subtype so callers branch on failure (FR-PBLE-13) — see [§14](#14-error-handling--mapping).

### 8.8 Shared conformance corpus with the firmware

`lib/pble/` and the firmware's `pyble_proto` ([../firmware/TDD.md §14.2](../firmware/TDD.md)) run a **shared conformance corpus** — the same byte sequences (frame round-trips, fragmentation across an MTU matrix, window/resume, error mapping) against an **in-memory fake transport** — so both ends agree on the wire (FR-PBLE-1, NFR-MAINT-4). The corpus is the cross-language guard that protocol changes do not silently diverge ([§15.4](#154-pble1-conformance)). The corpus also covers the screenless-identity opcodes ([§8.9](#89-screenless-identity--identify-control-commands)) — `SET_LABEL`/`SET_IDENTIFY_LED` round-trips and the `IDENTIFY` → `EUNSUPPORTED` mapping — so app and firmware stay byte-consistent on the additive control commands.

### 8.9 Screenless-identity & identify control commands

Implements the additive [protocol.md §4](../protocol.md#4-opcodes) opcodes `0x50`–`0x52` as ordinary `CMD`/`RSP` exchanges behind the `Connection` methods ([§5.1](#51-the-connection-interface)). These are control commands under the v1 connected-client trust model ([protocol.md §10](../protocol.md#10-security-note-v1)); the client adds no app-layer auth and never gates by `device_id`/MAC/`label` (SEC-9).

```text
setLabel(label)        -> SET_LABEL{utf8 label}        -> RSP{status}   (FR-CONN-10)
   client bounds length before send; "" clears to PyBLE-XXXX; on OK the
   board's advertised name + DEVICE_INFO.label change (refreshed via deviceInfo()/INFO)
setIdentifyLed(cfg)    -> SET_IDENTIFY_LED{gpio,active} -> RSP{status}   (FR-CONN-11)
   persists the single optional identify LED; device config only, never exposed to user code
identify()             -> IDENTIFY{}                    -> RSP{status}   (FR-CONN-12)
   OK -> board blinks the configured LED for a bounded duration
   EUNSUPPORTED(0x0A) when no identify LED is configured -> EUnsupported ([§14](#14-error-handling--mapping))
```

The label is UTF-8 and **bounded** — the client enforces a length cap before sending (the UI also bounds input, SEC-8) and surfaces an over-bound or rejected label as a typed error rather than truncating silently. `setIdentifyLed` configures **only** the single identify status-LED (GPIO + active level); it maps no hardware for user code and carries no routing/pin profile or board-capability map. The client issues `identify()` only when HELLO advertised `has_identify` ([§8.6](#86-hello--capabilities)); a board that nonetheless returns `EUNSUPPORTED` (LED unconfigured) is mapped to `EUnsupported` so the UI can prompt to configure the LED (FR-CONN-12). — *(satisfies FR-CONN-10/11/12, FR-PBLE-7/13, SEC-8/9.)*

## 9. Persistence design (`lib/data/`)

The Drift schema models exactly the six content tables of [specs.md §8](specs.md) / [PRD §12.1](../prd.md), plus a lightweight settings store. No managed-fleet/lab/calibration tables (DAT-8, CON-7). — *(satisfies DAT-1..8, FR-PROJ-1..7, IF-3.)*

### 9.1 Schema

| Table | Key fields | DAT |
|---|---|---|
| `projects` | id, name, description, created_at, updated_at, last_opened_at | DAT-1 |
| `project_files` | id, project_id (FK), path, content/blob, size, content_hash, updated_at; `.py`/data only | DAT-2 |
| `code_snapshots` | id, project_id (FK), path, content, label, trigger (manual/pre-run), created_at | DAT-3 |
| `run_sessions` | id, project_id (FK), board_ref, chip, entry (file/source), started_at, ended_at, final_state | DAT-4 |
| `console_logs` | id, run_session_id (FK), seq, timestamp, stream (stdout/stderr/system), text; on-device only | DAT-5 |
| `github_imports` | id, project_id (FK), repo_url, ref, subpath, commit_sha, file_count, imported_at | DAT-6 |

Saved-board reconnect is a lightweight `board_ref` app setting, **not** a relational board-profile/fleet table (DAT-7). `console_logs` capture is local and never transmitted off-device (DAT-5, SEC-5).

### 9.2 Migrations & hydration

Drift schema versions with explicit `MigrationStrategy` step migrations (forward-only); a schema-version test guards every bump. On launch the app hydrates the last-opened project and `board_ref` from Drift before any network/board activity (offline-first, NFR-OFF-1). Project export/import is a local archive (zip of files + metadata), no cloud (FR-PROJ-5, NFR-OFF-3). On disconnect, open buffers / files / run-and-console state are already in Drift, so nothing is lost across a dropped link (FR-PROJ-6, NFR-REL-3).

## 10. GitHub import design (`lib/github_import/`)

— *(satisfies FR-IMPORT-1..6, IF-4, DAT-6.)*

`browse(repoUrl, ref)` uses the **public, unauthenticated** GitHub HTTPS API (repo contents / raw) — no account, token, or auth, and no Git push (FR-IMPORT-2). The user selects a subpath/branch (ref) and SHOULD preview the file list, warned on conflicts with existing board files (FR-IMPORT-3). `import(...)` filters to `.py`/data (never `.mpy`/`.pyc`, FR-IMPORT-5, CON-3), writes each via `Connection.putFile` (FR-IMPORT-1), stores files locally so work continues offline with the local project as source of truth (FR-IMPORT-4, NFR-OFF-2), and records provenance — repo URL, ref, subpath, commit SHA, file count, timestamp — in `github_imports` (FR-IMPORT-6, DAT-6). Import failures never block other workflows (NFR-OFF-2).

## 11. Editor / blocks / plots / console design

### 11.1 Editor

`flutter_code_editor` behind the `EditorSurface` interface ([§4.3](#43-libeditor--code-editor)), with a WebView-hosted editor (Monaco/CodeMirror) as the documented fallback selectable behind the same interface ([PRD §16.1](../prd.md), [OI-1](specs.md)). Python highlighting, line numbers, auto-indent (FR-EDIT-1); tabs + Save/Run (FR-EDIT-2); find, optional find/replace (FR-EDIT-3); external-keyboard shortcuts for Save/Run/Stop/comment/find (FR-EDIT-4); large touch targets, no phone breakage (FR-EDIT-5). Save persists to Drift; Run uploads then runs through `Connection` (FR-EDIT-7).

**Working-loop increment — FROZEN (A-20 subset · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md)).** The first shippable editor is a **monospace editable surface** (a `SignalCodeColors`-styled text field, line numbers if cheap — no `flutter_code_editor`, no `google_fonts`, NFR-OFF dep hygiene) over a **single volatile in-memory current document** ([§11.6](#116-working-loop-provider-contract-frozen)). It offers **New** and (when connected) **Run**. **Deferred to A-24 / OI-1:** syntax highlighting, multi-file tabs, find/replace, external-keyboard shortcuts (FR-EDIT-1/2/3/4), and Drift persistence — Save-to-project (FR-EDIT-7) and buffers-survive-restart (NFR-REL-3/FR-PROJ-6) are **carried, not dropped**, and re-freeze at A-24. The document provider's `openFromBoard`/`markSaved` are the persistence hooks A-24 rebinds onto Drift without a widget rewrite.

### 11.2 Blocks

Blockly in a `webview_flutter` WebView, generating an inspectable,
board-neutral MicroPython subset with no board-specific defaults
(FR-BLOCKS-1), including the current numeric digital `machine.Pin`
construction/read/write surface initially validated on ESP32-family firmware
(FR-BLOCKS-5). Generated code is inspectable plain `.py` and flows through the
same upload/run/save path as the editor (FR-BLOCKS-2/3) via the `Connection`.
The JS-channel bridge carries only neutral types and no board profile, copied
curriculum/catalog, domain-specific lesson flow, or proprietary/classroom
pedagogy (FR-BLOCKS-4, D6).

**A-31 increment — FROZEN (`[docs]` 2026-07-27,
[ADR-0013](../../decisions/0013-clean-room-blockly-one-way-file-backed.md)).**
The workspace publishes immutable `{source, workspaceJson, revision}` snapshots
and is the visual source of truth in the baseline workflow; ordinary visual
editing remains one-way. ADR-0017 adds an exact verified sidecar reopen and an
explicit bounded import, not live synchronization. The view shows the
exact source in a selectable read-only preview. Each WebView generation has a
Dart host epoch and begins in loading: messages from disposed epochs are ignored
and restore must publish a newer revision before actions re-enable. Preview,
Open in editor, Save, and Run share one action lock; each requests and awaits
one fresh acknowledged non-empty snapshot, revalidates and freezes it, then
Preview/Open consume it locally while Save/Run delegate to
`ProgramActions.saveSource(path: '/blocks.py', source: snapshot.source)` (Run
continues with `runFile('/blocks.py')`). Each action request carries a
Dart-generated per-host request ID; only a snapshot/error echoing that ID can
complete the waiter, while unsolicited change snapshots only refresh retained
state. Bridge/host lifecycle changes never
clear the single-writer busy state; only the action's `finally` does.
Generator/serialization errors remain over the editable workspace, while
all source actions stay disabled until a valid repair snapshot. Errors before
the first accepted epoch snapshot and main-frame/startup failures are retryable
host errors guarded by a first-message watchdog; stale retained revisions do
not stop that watchdog. The action timeout covers both the JavaScript request
and its bridge acknowledgement. Retry retains valid JSON, while confirmed Start
fresh clears an unrecoverable retained workspace and recreates an empty host.
The text editor delegates to the same file-backed actions, replacing
its interim primary `runSource` path. “Open in editor” is the only operation
that mutates the current editor document and resolves a dirty-buffer conflict
first. PyBLE's fresh MIT wrapper loads only the minimal bundle built from the
pristine pinned Blockly upstream, admits only the exact local main-frame asset,
denies external navigation/network, and exposes the standard
logic/loops/math/text/lists/variables/functions toolbox. The platform host is
lazy and fakeable; Dart bridge decoding/controller/action behavior is covered
without a platform view, while the real restore → generate → Save → Run flow is
exercised on both iPadOS and Android.

ADR-0017's source-first/sidecar-last pair action supersedes only the
source-only Save/Run sequence in this baseline paragraph. Fresh-snapshot
acknowledgement, request correlation, the action lock, and the final `runFile`
boundary remain unchanged. `/blocks.py` remains the default target; an
explicitly converted editor document or exact sidecar reopen may bind the active
workspace to its validated Python path.

**A-31 responsive placement — FROZEN (`[docs]` 2026-07-28,
[ADR-0014](../../decisions/0014-focused-blocks-landscape-workspace.md)).**
Landscape selection of the first-class Blocks rail destination replaces the
three text-workbench panes with a focused Blocks host while the application
toolbar stays mounted. That toolbar hides its editor-targeted Run; the
Flutter-owned Blocks action strip supplies exactly one generated-source Run
beside Preview, Open in editor, and Save. It also owns loading, generator,
recovery, and action notices in bands outside the WebView so no overlay covers
the editable canvas. Let `W` be usable focused content width after the
NavigationRail and outer/divider chrome. For an inspector width
`P ∈ [360 dp, 420 dp]` and its divider/gutter `G`, it is mounted only if the
remaining Blockly width `B = W − P − G` satisfies both `B ≥ 720 dp` and
`B / W ≥ 0.60`; otherwise Blockly receives the full `W` and the inspector is
omitted. The Blocks console defaults to its
collapsed header, can be expanded on demand, and expands after Run begins or
the next console event. The console buffer is never recreated. Orientation
changes retain the Blocks destination and provider snapshot; if Flutter
recreates the platform view, the existing host-epoch restore handshake must
publish a fresh revision before source actions re-enable.

**A-31 generic digital GPIO — FROZEN (`[docs]` 2026-07-28,
[ADR-0015](../../decisions/0015-generic-micropython-gpio-blocks.md)).**
The fresh MIT GPIO extension registers its custom blocks and Python generators
before workspace injection, then adds one GPIO category to the local toolbox:

| Type | Shape | Generated MicroPython |
|---|---|---|
| `pyble_gpio_pin` | output `Pin`; required `GPIO` input checked `Number`; `MODE` field `IN|OUT`; `PULL` field `NONE|UP|DOWN` | `Pin(gpio, Pin.IN|Pin.OUT, None|Pin.PULL_UP|Pin.PULL_DOWN)`; explicit `None` disables any prior pull |
| `pyble_gpio_write` | statement; required `PIN` input checked `Pin`; `LEVEL` field `LOW|HIGH` | `pin.value(0|1)` |
| `pyble_gpio_read` | output `Number`; required `PIN` input checked `Pin` | `pin.value()` |

The constructor has no GPIO shadow/default. Users connect an explicit
non-negative integral numeric literal and may store the returned object with
standard variable set/get blocks. The Python generator installs
`from machine import Pin` in its definitions/preamble map under one stable key
and reserves `Pin` before name allocation; therefore any number of constructors
produce one import and a user variable/procedure cannot shadow it. A workspace
without a constructor produces no GPIO import. Constructor generation returns
function-call precedence, read returns function-call precedence, and write
terminates as a statement, so constructor and variable receivers remain safely
composable. Constructing `Pin.OUT` does not choose an initial level; a
deterministic level requires an explicit write.

Definitions enforce the declared Blockly connection checks. Generators also
reject disconnected sockets, non-finite/fractional/negative GPIO literals, and
unknown restored enum tokens; they never substitute GPIO 0, a level, or a pull.
Such failures publish the normal correlated generator error, retain the
editable/serializable workspace, and disable Preview/Open/Save/Run until a
fresh repaired snapshot arrives. Concretely, snapshot publication serializes
the workspace before code generation; if generation fails, the versioned error
message carries
`{type: 'error', message, workspace, revision, requestId?}` (plus the existing
bridge `version`): that serialized workspace, its next monotonic revision, and
the request ID when correlated. Dart accepts the JSON/revision for retention but
never treats it as source. A valid workspace-bearing error transitions the host
from loading to ready-but-invalid and stops its first-message watchdog, even
when that error is the first restore result. A recreated host therefore keeps
the platform view mounted, restores the retained JSON, remains editable, and
publishes a newer error or valid snapshot; only the latter re-enables actions.
A serialization failure cannot carry invalid JSON and follows ADR-0013's
existing host-recovery path. The generator does not compare against
`DeviceInfo.chip`, an allowed-pin table, or the informational pin reference:
MicroPython on the board is the only authority for physical pin availability
and mode/pull support, and its original exception remains visible in the
console. `Pin` is deliberately one connection check: standard variable get is
untyped and does not preserve constructor mode, so read/write do not claim a
static `IN`/`OUT` proof. The generated text remains ordinary `/blocks.py`; the
bridge, shared file-backed actions, firmware, and PBLE/1 are unchanged.

Node/unit tests execute the actual custom definitions and generators for every
mode/pull/level branch, exact-once/no-import behavior, reserved-name
sanitization, variable composition, required-input failures, invalid restored
state, and workspace/revision retention across a generator-error host
recreation. Asset-policy tests pin the IDs/category and exclude a pin catalog. A
real WebView integration test serializes the GPIO workspace,
recreates/restores it (including rotation), compares generated source before and
after, then exercises Preview/Save/Run through the existing acknowledged
snapshot path on iPadOS and Android.

**A-31 standard NeoPixel — FROZEN (`[docs]` 2026-07-28,
[ADR-0018](../../decisions/0018-standard-micropython-neopixel.md)).**
The fresh MIT extension adds one local NeoPixel category without a new runtime
dependency in Flutter:

| Type | Shape | Generated MicroPython |
|---|---|---|
| `pyble_neopixel_create` | output `NeoPixel`; required `PIN: Pin`; required `PIXELS: Number` | `NeoPixel(pin, pixels)` with exact-once `from neopixel import NeoPixel` |
| `pyble_neopixel_rgb` | output `NeoPixelColor`; required `RED/GREEN/BLUE: Number` | `(red, green, blue)` |
| `pyble_neopixel_set_pixel` | statement; required `STRIP: NeoPixel`, `INDEX: Number`, `COLOR: NeoPixelColor` | `strip[index] = color` |
| `pyble_neopixel_fill` | statement; required `STRIP: NeoPixel`, `COLOR: NeoPixelColor` | `strip.fill(color)` |
| `pyble_neopixel_write` | statement; required `STRIP: NeoPixel` | `strip.write()` |

The constructor reserves `NeoPixel` and installs its unaliased import under one
stable definitions-map key. Its pixel count is a finite positive integral
literal; no socket has a shadow/default. RGB components and index remain
composable single-line expressions and the runtime owns their dynamic
type/range checks. The constructor consumes the `Pin` value but does not own or
duplicate the `machine.Pin` import. Set/fill mutate only the standard driver
buffer and explicit write transmits it. Required-input, multiline, invalid
count, or tampered-state errors use the workspace-bearing recovery contract in
lines 692–707; no generator substitutes a pin, count, colour, brightness,
RGBW/timing option, or write.

Asset/runtime tests pin all five IDs and Blockly connection checks; exact-once
and no-unused-import behavior; `NeoPixel` name reservation; constructor,
variable, RGB/index, fill/write composition; invalid workspace retention; and
the absence of board profiles/defaults/custom driver or network access. A real
WebView test restores and generates the new catalog fixture on both platforms.

**A-31 beginner examples and Time block — FROZEN (`[docs]` 2026-07-28,
[ADR-0016](../../decisions/0016-offline-beginner-blockly-examples.md)).**

The PyBLE extension registers one additional statement before workspace
injection:

| Type | Shape | Generated MicroPython |
|---|---|---|
| `pyble_time_sleep_ms` | statement; required `MILLISECONDS` input checked `Number`; no shadow/default | `sleep_ms(milliseconds)` with exact-once `from time import sleep_ms` |

The generator reserves `sleep_ms` before Blockly allocates variable/procedure
names and installs the import under one stable definitions-map key. It accepts
only a finite, non-negative integral numeric literal. Missing, negative,
fractional, non-finite, multiline, or tampered input publishes the same
workspace-bearing generator error as GPIO. The block lives in a **Time**
category; it is ordinary generated MicroPython and adds no runtime or bridge
escape hatch.

`app/assets/blockly/examples/catalog.json` is a bounded, local-only manifest:

```text
{
  "version": 2,
  "examples": [{
    "id": stable-id,
    "titleKey": ARB-key,
    "summaryKey": ARB-key,
    "conceptKeys": [ARB-key, ...],
    "wiringNotesKey": ARB-key,
    "workspace": ordinary-Blockly-serialization,
    "gpioRoles": [{
      "role": stable-role,
      "labelKey": ARB-key,
      "blockId": target-constructor-id,
      "input": "GPIO"
    }]
  }]
}
```

Catalog order and IDs are fixed as `hello-pyble`, `count-repeatedly`,
`blink-led`, `blink-neopixel`, `read-button`, `button-controls-led`, and
`reusable-function`.
The decoder rejects an unknown catalog version, duplicate/unknown IDs or roles,
missing ARB keys, non-object workspaces, duplicate block IDs, role bindings that
do not resolve to a disconnected `pyble_gpio_pin.GPIO`, extra GPIO constructor
sockets without a role, and catalog GPIO number blocks connected to those
sockets. It never treats catalog text as executable source. The manifest does
not contain `source` or `sourceTemplate`; tests pin expected output while the
production generator remains the runtime source authority.

The first two examples progress from `print` to a finite paced count with a
variable. Blink configures one user-selected output and visibly alternates
explicit LOW/HIGH writes with delay blocks. Blink-NeoPixel creates one pixel
from a disconnected user-selected Pin role, alternates a dim RGB tuple and off
at index zero, and makes every buffer transmission visible with an explicit
write. Read-button uses a user-selected pulled input and paced console reads.
Button-controls-LED composes separate user-selected input/output Pin objects, a
condition, explicit writes, and a short pacing delay. Reusable-function defines
and calls a procedure with a parameter. A repeating example's localized summary
says that it continues until Stop. No program is run merely by choosing or
loading it.

The candidate pipeline is isolated from the active workspace:

```text
catalog entry + ephemeral role values
  → schema/role validation
  → deep-cloned ordinary workspace
  → connect ordinary math_number blocks for every GPIO role
  → load into disposable scratch Blockly.Workspace
  → production Python generator
  → immutable {workspaceJson, source} candidate
  → Preview only, or explicit commit to the rendered workspace
```

Role values are decimal finite, non-negative integers and are pairwise distinct
when an example declares multiple roles. The UI supplies no
initial/suggested/remembered value and consults neither `DeviceInfo` nor a board
profile. A duplicate numeric value shows a localized error on the conflicting
role fields and keeps/returns focus to the first conflict; it is not presented
as physical board-pin validation. The same validated candidate supplies both
the read-only Python shown in the chooser and the subsequent copy, so the
display cannot describe a different program. Disposing the scratch workspace
and changing/closing a preview do not publish an active revision. A commit
submits the candidate to the rendered workspace and lets the existing
change/snapshot path publish the next monotonic revision; only that accepted
active-host snapshot completes the load and authorizes the one-shot success
announcement. No commit calls a source action.

Workspace emptiness is structural: no blocks, variables, or procedures. Only
that state presents **Create copy**. Every other state—including an incomplete
GPIO graph with no actionable source—presents **Replace workspace**, followed
by a localized confirmation. Before commit the active serialized JSON/revision
is retained as the rollback value. Cancel changes nothing. Any load, restore, or
candidate-generation failure before the candidate's acknowledged snapshot
restores the rollback JSON, program, and revision and emits no loaded-success
announcement; catalog/materialization/preview-generation failure happens before
commit. The catalog fixture is never returned by reference and cannot be
mutated by edits to the loaded copy.

There are three entry events but one Flutter-owned chooser/controller:

- the WebView shows a prominent empty-workspace Examples call to action until
  structural emptiness becomes false;
- the Flutter Blocks action strip always exposes Examples, moving it first to a
  labelled keyboard/screen-reader-accessible overflow when width is constrained
  (and moving further non-Run actions there if needed rather than scrolling,
  clipping, or shrinking the canvas); and
- an Examples toolbox category contains catalog buttons that send only a
  versioned `openExamples` host event (optionally with a stable example ID).

The event carries no source, workspace, board data, transport object, or
callback. An absent or null optional `exampleId` opens the chooser at its default
selection. A non-string or unknown ID is ignored without changing the host or
document readiness; it never becomes a host error. Host recreation restores
only the ordinary active workspace and does not reopen the chooser. Once loaded,
an example follows the existing host-epoch, invalid-workspace, rotation, and
A-24 persistence paths exactly like hand-built blocks.

The chooser uses ARB keys for all visible and semantic text and displays
localized title, summary, concept chips, wiring notes, role fields, generated
source, and the state-appropriate action. At an available width below 600 dp the
shared controller is presented in a scroll-controlled modal bottom sheet; at
600 dp and wider it is presented in a dialog. Hardware notes explain external
LED/current-limiting-resistor or button/pull/active-level wiring and tell users
to verify GPIO/voltage against their own board documentation; they do not claim
that a pin or circuit is universally safe. Controls are ≥ 48 dp, keyboard and
screen-reader reachable, expose disabled/selected/error state, return focus to
the invalid role, announce one preview result and one host-acknowledged load
result, and scroll at large text. Preview, Create copy, Replace workspace, and
chooser cancellation invoke no `Connection`, `ProgramActions`, Run, Save,
editor hand-off, or console method.

**A-31 exact sidecar reopen and bounded Python import — FROZEN (`[docs]`
2026-07-28,
[ADR-0017](../../decisions/0017-blocks-sidecar-and-bounded-python-import.md)).**

#### Exact Blocks pair

Let `P` be the normalized absolute `.py` source path in the user workspace.
`blocksSidecarPath(P)` validates the same path/jail rules as file operations and
returns exactly `P + '.pyble-blocks.json'`. Both complete UTF-8 paths must fit
PBLE/1's 128-byte path limit. For a workspace with no imported/paired origin the
default is:

```text
P = /blocks.py
S = /blocks.py.pyble-blocks.json
```

`BlocksSidecarCodec` admits at most 1 MiB of UTF-8 and owns this strict required
shape (additional fields do not change v1 semantics):

```text
{
  format: "pyble-blocks",
  version: 1,
  source: {
    path: P,
    encoding: "utf-8",
    byteLength: unsigned bounded integer,
    crc32: exactly /[0-9a-f]{8}/,
    text: exact generated source
  },
  generator: {
    id: "pyble-blockly-python",
    version: 1,
    blockly: "13.1.0"
  },
  workspace: ordinary-Blockly-object
}
```

The encoder emits fields in that order for deterministic fixtures. CRC is
IEEE/zlib CRC-32 over the exact UTF-8 `source.text` bytes, formatted as eight
lowercase hexadecimal digits. It reuses the already-conformance-tested
algorithm (`"123456789"` → `cbf43926`) but is not treated as a signature or
security boundary. `byteLength`, CRC, and the embedded text must all agree;
validation finally compares the adjacent source bytes exactly, so a CRC
collision cannot authorize a workspace.

`BlocksPairActions.save/run` execute under the existing fresh-snapshot action
lock. They capture the stable facade and its opaque local session stamp before
preflight, derive `S` from the active `P`, and validate both path byte lengths:

```text
snapshot = await requestFreshSnapshot(activeHost)
sourceBytes = exact UTF-8 bytes acted on by ProgramActions
sidecarBytes = encode(snapshot.workspaceJson, sourceBytes, versions)
session = capture(connection facade, local session stamp)
preflight(P, S)
await putFile(P, sourceBytes)       # existing verified single-file upload
requireCurrent(session)             # fail before crossing board sessions
await putFile(S, sidecarBytes)      # sidecar-last pair commit
if run:
  requireCurrent(session)           # fail before crossing board sessions
  await runFile(P)
```

Neither Save nor Run reports success after only the first write. A source-write
failure makes zero sidecar/run calls. A sidecar-write failure makes zero run
calls and surfaces the specific torn-pair state: the Python may be new while any
old sidecar is stale. A `runFile` failure occurs after a valid saved pair and is
reported as execution failure, not pair failure. This is deliberately not
described as a multi-file atomic transaction. The manager's stable
`Connection` facade replaces the local stamp on every attach and detach,
including reconnecting the same board. A changed facade or stamp produces a
typed refusal before the next sidecar/Run verb. The stamp is in-memory action
consistency only—not board identity, authentication, pairing state, persisted
metadata, or PBLE/1 wire data.

Exact reopen accepts bytes supplied by the explicit file-open layer and runs:

```text
decode + schema/path/version/bounds validation
  → adjacent Python == embedded source bytes/text/length/CRC
  → scratch restore(workspace)
  → scratch serialize deep-equals stored workspace
  → production generate == embedded source byte-for-byte
  → immutable exact-reopen candidate
```

Deep JSON equality ignores object-key order and JSON whitespace only; array
order, IDs, coordinates, fields, comments, `extraState`, variables/procedures,
disabled/collapsed state, and all supported serialized values must survive.
There is no best-effort restore. Any failure returns a typed diagnostic and
keeps the Python editor and active Blocks document unchanged. Text-editor Save
does not couple itself to, update, or delete a sidecar; exact mismatch safely
invalidates it. An acknowledged exact-reopen candidate adopts validated `P` as
its active source target; rollback restores the prior target with the prior
workspace.

#### Bounded Python importer

`PythonBlocksImporter` is a fresh MIT pure-Dart tokenizer, recursive-descent
parser, validator, and typed v1 subset model. It accepts only source within
256 KiB, 4,096 physical lines, 20,000 model nodes, and 32 indentation levels.
Indentation uses spaces, source contains no semicolon statement packing,
identifiers are non-keyword ASCII Python identifiers, and integral Blockly
literals fit `±9007199254740991`. Decimal float syntax is admitted only when
its finite value is non-integral; integer-only `range`/GPIO/Time positions
require decimal integer syntax, and raw U+0000 string content is rejected.

Only the exact, unaliased, use-dependent leading imports
`from machine import Pin`, `from time import sleep_ms`, and
`from neopixel import NeoPixel` are admitted. The statement/expression/function/
range grammar and complete rejection list are normative in ADR-0017 §5 as
extended by ADR-0018. The key mappings are:

| Python subset node | Ordinary Blockly representation |
|---|---|
| `name = expression` / numeric `name += expression` | `variables_set`; `+=` becomes `variables_set(name, math_arithmetic(ADD, variables_get(name), expression))` |
| decimal/string/Boolean/`None`/name | `math_number`, `text`, `logic_boolean`, `logic_null`, `variables_get` |
| unary/arithmetic/Boolean/single comparison | standard math/logic blocks with precedence-preserving connections |
| `print(expression)` | `text_print` |
| `if`/`elif`/`else` | one `controls_if` with the required mutation/extra state |
| `while condition` | `controls_whileUntil` in `WHILE` mode |
| literal `range(start, stop, step)` | `controls_for`, positive endpoint `stop - 1` or negative endpoint `stop + 1`, positive `BY = abs(step)` |
| top-level function/call/final return | standard `procedures_defnoreturn`/`procedures_defreturn` and matching call block |
| `Pin(...)`, `.value(0\|1)`, `.value()` | `pyble_gpio_pin`, `pyble_gpio_write`, `pyble_gpio_read` |
| `sleep_ms(N)` | `pyble_time_sleep_ms` |
| `NeoPixel(Pin(...), count)` | nested `pyble_neopixel_create` + `pyble_gpio_pin` |
| `(red, green, blue)` in a NeoPixel colour position | `pyble_neopixel_rgb` |
| `strip[index] = rgb`, `strip.fill(rgb)`, `strip.write()` | `pyble_neopixel_set_pixel`, `pyble_neopixel_fill`, `pyble_neopixel_write` |
| sole `pass` in a suite | empty statement connection; no placeholder block |

Range values are literal, exact-safe, non-zero-step, direction-consistent, and
non-empty. Functions are top-level, precede executable statements, number at
most 16, have at most eight unique positional parameters, use no
free/local-variable state, have no call cycle, and contain either no return or
one final value return. The importer validates call kind and arity before
workspace construction. These restrictions prevent standard Blockly generators
from inserting range/global semantics that differ from the input.

Definite binding is a control-flow property, not a first-iteration shortcut.
Branch exits are intersected; loop bodies and conditions are revalidated across
their backedges until the assigned, `Pin`, and `NeoPixel` binding sets stabilize.
A `while` may execute zero times, so its post-loop state is the intersection of
entry and stabilized body exit. A literal non-empty `range` executes at least
once, but a multi-iteration range still validates its backedge before exporting
the final body-exit state. A receiver that may cease to be a `Pin` or
`NeoPixel` therefore rejects the complete conversion.

Construction assigns fresh unique block/variable/procedure IDs and a
deterministic non-overlapping top-level layout. Those visual choices are not
claimed to reproduce a handwritten file's nonexistent layout. The resulting
workspace contains no source string, AST payload, unsupported-line list,
disabled fallback, or raw-code block.

The importer captures one immutable `EditorDocument` and resolves
`P = boardPathForDocument(capturedDocument)` before parsing. A non-`.py`,
non-user-workspace, or source/companion path above 128 UTF-8 bytes is a
diagnostic and yields no candidate. This target is displayed in Preview and is
adopted only with the acknowledged workspace commit; `/blocks.py` is not
substituted for an explicitly captured document.

Conversion is all-or-nothing:

```text
captured source
  → complete typed subset model OR diagnostics
  → candidate ordinary workspace
  → scratch restore + production generation
  → generated source reparsed by the same bounded parser
  → normalized semantic-model equality
  → candidate OR internal-conversion diagnostic
```

Model equality includes imports, literal values, identifiers, operators,
statement/branch order, adjusted range semantics, function signatures/call
kind, GPIO/Time choices, and definite NeoPixel bindings/indices/RGB operations;
it ignores only disclosed formatting, redundant parentheses/blank lines, quote
spelling, and visual layout. Any error at any
stage discards the whole workspace. Comments/docstrings and every unsupported
construct are errors, never warnings or silently dropped material. The input
fingerprint retains the complete captured document identity/name/content/board
path, resolved target, exact text, UTF-8 byte length, and CRC; a final exact
editor-document comparison invalidates a stale preview regardless of
fingerprint collision.

`PythonBlocksDiagnostic` is immutable:

```text
{
  code: stable ASCII identifier,
  severity: warning | error,
  startLine/startColumn: one-based Unicode-scalar position,
  endLine/endColumn: one-based, end-exclusive position,
  messageKey: ARB lookup key,
  args: typed interpolation arguments
}
```

Errors yield no candidate and disable Create/Replace. Warnings are limited to
visible non-semantic normalization. Parser/host exception text is logged only
under the app's normal diagnostic policy; it never becomes an unlocalized user
message.

#### Candidate UI and action boundary

The editor's **Convert Python to Blocks** and a valid pair's **Open as Blocks**
use one controller. It owns only the captured source, diagnostics, generated
preview, candidate target paths, and candidate workspace. Below 600 dp it
presents a scroll-controlled modal bottom sheet; otherwise a dialog. It shows
the full selectable generated Python, source/companion paths, and
source-range-linked diagnostics. Error conversion focuses the first
diagnostic; screen readers receive one error-count or completion announcement.
All visible/semantic copy is ARB-sourced, controls are ≥48 dp, and content
scrolls at 1×–3× text and with a software-keyboard inset.

The controller reuses the example candidate commit state machine: structural
empty → Create workspace; all other graphs, including invalid ones → confirmed
Replace workspace; exact rollback on cancel/load/restore/generation/source
staleness, including the active source target; success only after the active
host's matching candidate snapshot.
No validation, Preview, Create, Replace, or cancel call may reach
`Connection`, `ProgramActions`, Save, Run, editor mutation, console, or
network. Explicit File Explorer open may read only the selected pair through its
existing operation. Explicit Blocks Save/Run remains the sole pair writer and
Run remains the sole executor.

### 11.3 Plots

`fl_chart` over values printed to the console stream — derived **purely** from program output, no special data-event opcode (FR-PLOTS-1/2). A configurable `SeriesParser` ([OI-5](specs.md)) lets the user choose delimiter/columns/labels; config persists per project. Bound to `ConsoleEvent` neutral types only (FR-PLOTS-3).

### 11.4 Console & error explanation

The console renders the live stream with per-stream styling (FR-CONSOLE-1), legible tracebacks (FR-CONSOLE-2), run/connection state (FR-CONSOLE-3), stdin via `sendInput` (FR-CONSOLE-4), copy/clear (FR-CONSOLE-6). The **error explainer** ([§14](#14-error-handling--mapping)) watches the `stderr` stream, detects common MicroPython errors from the traceback, and renders a one-line localized suggestion **alongside** the raw traceback (it annotates, never hides — FR-ERR-1/2). Mappings are **data-driven** (a table keyed by error signature → ARB key) so new cases need no code change and are localizable (FR-ERR-4); the day-one set covers at least `NameError` (missing `from machine import …`), `IndentationError`, `ImportError` (module absent from `/lib`), `OSError: ENOENT`, and `MemoryError` (FR-ERR-3).

**Working-loop increment — FROZEN (A-21 subset · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md)).** The first shippable console renders the live `Connection.console` stream into a **capped ring buffer held in `consoleBufferProvider`** ([§11.6](#116-working-loop-provider-contract-frozen)) so output **survives tab/navigation switches** and observe-anywhere (FR-CONSOLE-5/7): `stdout`/`stderr`/`system` differentiated via `SignalCodeColors.streamColor` (FR-CONSOLE-1/2); a **stdin input row** → `sendInput` (FR-CONSOLE-4); **clear**, optional **copy** (FR-CONSOLE-6); **auto-scroll with scroll-lock** on manual scroll-up (a console-widget-local flag, not provider state — TDD §6.1); and a **RunState indicator** (idle/running/done/error) from `runStateProvider` (FR-CONSOLE-3). The buffer renders in both the landscape bottom strip and the Console surface off the **same** provider. **Deferred:** the data-driven beginner **error explainer** (FR-ERR-1..4) and `console_logs` Drift capture (DAT-5) land at **A-25 / A-24** — the raw `stderr` traceback still renders legibly in this increment (never hidden, FR-ERR-2).

### 11.5 Screenless identity — rename & identify

Many supported boards are screenless, so identity is established in the app's
connect surface ([§4.8](#48-libconnect--scanconnect-flow-ui)), not on a required
board display. Two UX surfaces:

- **Rename board.** A rename control (in the scan list per-board and in the connected diagnostics view) edits the device **label** through `Connection.setLabel` (FR-CONN-10). The input is **length-bounded** to the board's limit and shows an inline **privacy warning**: the label is broadcast in the advertisement and visible to anyone scanning, so it MUST NOT contain personal data (PII); clearing the field restores the non-PII default `PyBLE-XXXX` (SEC-8, [protocol.md §10](../protocol.md#10-security-note-v1)). All warning/label/error text is ARB-sourced ([§12](#12-localization-design-liblocalization)).
- **Identify.** An Identify button appears **only** when `caps.hasIdentify` ([§8.6](#86-hello--capabilities), FR-CONN-12). Pressing it blinks the board's configured identify LED via `Connection.identify()` so the user can spot the physical board. When `caps.identifyLed == null`, the button first opens a small **configure-LED** prompt (`Connection.setIdentifyLed({gpio, activeLevel})`, FR-CONN-11) then identifies. An `EUnsupported` result (LED unconfigured) renders a clear localized message ([§14](#14-error-handling--mapping)), never a silent no-op. The configured GPIO is **device UX config only** — it maps no hardware for user code and is not a routing/pin profile or capability map (SEC-9).

— *(satisfies FR-CONN-10/11/12, SEC-8/9, FR-CONNECT-1.)*

### 11.6 Working-loop provider contract (frozen)

**FROZEN (working-loop increment · `[docs]` 2026-07-02, [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md)).** This is the shared Riverpod contract the edit→run→watch→manage loop implements to, across A-20 (editor), A-21 (console), A-16 (run-control toolbar) and A-30 (files). Ownership is **disjoint** so the feature engineers work in parallel. Every provider binds only to the neutral `Connection` seam + neutral types ([§5](#5-the-connection-api-design)) — **no UI package imports `lib/ble`** (CON-8, FR-UI-7); app-layer packages MAY cross-import each other's **public** providers (`files → editor`, shell → run-control). API sketches are illustrative; the frozen interface is whatever the `[red]` tests pin ([§15](#15-test-design)).

**(a) Current document — `lib/editor` (owner: app-editor-console-engineer).** A single volatile in-memory document; survives navigation, not restart (persistence deferred to A-24, [§11.1](#111-editor)):

```dart
@immutable
class EditorDocument {                 // value type; ASCII field names (FR-I18N-4)
  final String name;                   // display filename, e.g. "main.py" (technical id, not localized)
  final String content;                // the buffer text
  final bool dirty;                    // edits since last new/openFromBoard/markSaved
  final String? boardPath;             // absolute board path this buffer maps to, or null (never on board)
}
// editorDocumentProvider = NotifierProvider<EditorDocumentController, EditorDocument>
//   newDocument()                              -> fresh untitled empty buffer (dirty=false, boardPath=null)
//   setContent(String content)                 -> update content; dirty=true if changed
//   openFromBoard({required String path, required String content})
//                                              -> name=leaf(path), content, boardPath=path, dirty=false
//   markSaved({String? boardPath})             -> dirty=false; adopt boardPath if given  [A-24 persistence hook]
```

The default filename (`untitled.py`) is a **technical identifier**, an ASCII constant in `lib/editor` — never an ARB string (FR-I18N-4). `openFromBoard`/`markSaved` are the hooks A-24 rebinds onto Drift. Save captures one normalized document snapshot and, after its verified upload, calls `markSaved` only if the live document still equals that snapshot; edits or a replacement document made during transfer remain dirty and unbound.

**(b) Run-control — `lib/editor` (owner: app-editor-console-engineer; shell wires the buttons).** Derives availability from `ConnState` + `RunState`; runs the current buffer:

```dart
@immutable
class RunAvailability { final bool canRun, canStop, canSoftReboot, isRunning; }
// runAvailabilityProvider = Provider<RunAvailability>  (watches connStateProvider + runStateProvider)
//   canRun        = ConnState.ready                     (connected & idle; false while running/connecting/disconnected)
//   canStop       = ConnState.running
//   canSoftReboot = ConnState.ready || ConnState.running
//   isRunning     = ConnState.running (RunState.running)
// runControllerProvider = Provider<RunController>
class RunController {                   // reads connectionProvider + editorDocumentProvider via ref
  Future<void> run();                  // shared putFile(path, content) → runFile(path)
  Future<void> runFile(String path);   // runFile(path) — run a board file directly (from files)
  Future<void> stop();                 // stop()  (idempotent-OK)
  Future<void> softReboot();           // softReboot()  (fire-then-expect-disconnect)
}
```

ADR-0013 supersedes the interim primary `runSource(currentDocument.content)`
implementation: `ProgramActions` now owns normalization, UTF-8 upload, and the
verified file-backed run shared by Editor and Blocks. `runSource` remains on the
Connection API for deliberately bounded snippets. After the upload/run succeeds,
the controller marks the editor saved and binds its board path only when the
current document still equals the captured normalized upload snapshot. Edits or
a different document opened during the transfer remain dirty and unbound.

`EBusy` from `run()`/`runFile()` (board already running) is surfaced as a localized notice (`runBusyMessage`), never swallowed (FR-RUN-3). `NotConnectedException` cannot occur behind an enabled button (availability gates it); if a verb is reached while disconnected it surfaces `runDisconnectedHint`. **Focusing the console on Run is the shell's job** (it knows the layout): in the stacked layout the Run handler sets `selectedSurfaceProvider = console`; in landscape the strip is always visible, so no nav. The controller stays layout-agnostic.

**(c) Console buffer — `lib/console` (owner: app-editor-console-engineer).** A capped ring subscribed to `Connection.console`, alive independent of the console widget (observe-anywhere / survive-nav, FR-CONSOLE-5/7):

```dart
// consoleBufferProvider = NotifierProvider<ConsoleBufferController, List<ConsoleEvent>>
//   build(): subscribes ref.watch(connectionProvider).console; appends; caps at kConsoleMaxEvents
//            (frozen default 4000, oldest-dropped ring); re-subscribes when the seam identity changes.
//   clear()               -> empties the ring
//   sendInput(String)     -> ref.read(connectionProvider).sendInput(text)  (fire-and-forget passthrough)
// const int kConsoleMaxEvents = 4000;   // tunable; documented cap
```

Rendering (line-splitting, `SignalCodeColors.streamColor` per `ConsoleStream`, traceback legibility) is the widget's job. **Scroll-follow/scroll-lock is console-widget-local ephemeral state** (a `ScrollController` + follow flag), not provider state (TDD §6.1). The `RunState` indicator reads `runStateProvider`. The buffer MUST be kept alive from an always-mounted point (the shell reads it once) so it captures output even before the Console surface is first opened.

**(d) File explorer — `lib/files` (owner: app-files-engineer).** A controller over the `Connection` file verbs, rooted at `DeviceInfo.fsRoot`:

```dart
enum FileErrorKind {                    // typed PbleException -> kind; widget maps kind -> ARB (FR-I18N-3)
  notFound, permission, storageFull, io, crc, busy, unsupported, range, badRequest, notConnected, generic }
@immutable
class FileExplorerState {
  final String cwd; final List<RemoteEntry> entries; final bool loading;
  final TransferProgress? progress; final FileErrorKind? error; final String? errorPath;
}
// fileExplorerProvider = NotifierProvider<FileExplorerController, FileExplorerState>
//   refresh()                     -> listDir(cwd)
//   into(String dirName)          -> cwd = cwd/dirName; refresh
//   up()                          -> cwd = parent(cwd), bounded at fsRoot; refresh
//   openInEditor(String fileName) -> getFile(path, onProgress) -> utf8 decode
//                                    -> editorDocumentProvider.notifier.openFromBoard(path, content)
//                                    -> selectedSurfaceProvider = editor        [cross-import: files->editor, app]
//   uploadCurrentBuffer()         -> putFile(cwd/name, utf8(currentDocument.content), onProgress)
//                                    -> on success editorDocumentProvider.notifier.markSaved(boardPath: path)
//   newFile(String name)          -> putFile(cwd/name, empty, onProgress) -> openInEditor(name)
//   mkdir(String name)            -> mkdir(cwd/name); refresh
//   delete(String name)           -> delete(path); refresh
//   rename(String from,String to) -> rename(cwd/from, cwd/to); refresh
```

Every verb wraps the typed `PbleException` ([§14.1](#141-status-byte--typed-exception--localized-message)) into a `FileErrorKind` the widget renders as an actionable, localized message (FR-FILES-3). Transfers report `progress` continuously and succeed only on the seam's whole-file CRC/size verification (FR-FILES-4, already enforced in `lib/pble`). File ops are enabled only while the session is up (`ConnState.ready`/`running`); disconnected shows the existing `folder_off` guidance with no destructive action. **Deferred:** multi-select bulk ops (FR-FILES-5), the control-plane non-editable predicate (FR-FILES-6 — the board still enforces `EACCES`, SEC-7), and a true export-to-device-storage **Download** (needs local persistence + a `path_provider`-class dep, out of scope) — **open-in-editor is the read-into-app path** for this increment. `.py`/data-only holds (CON-3): the workspace never produces `.mpy`/`.pyc`.

**(e) Seam providers — `lib/app/providers.dart` (owner: app-architect).** Adds one Connection-derived provider beside `connectionProvider`/`connStateProvider`:

```dart
// runStateProvider = StreamProvider<RunState>  ((ref) => ref.watch(connectionProvider).runState)
```

Shared by run-control (b) and the console indicator (c). This is seam wiring (like `connStateProvider`), not feature code.

**File ownership (disjoint):**

| Agent | Creates / edits |
|---|---|
| app-editor-console-engineer | `lib/editor/editor_document.dart`, `lib/editor/run_controller.dart`, `lib/editor/editor_view.dart`, `lib/editor/editor.dart` (barrel); `lib/console/console_controller.dart`, `lib/console/console_view.dart`, `lib/console/console.dart` (barrel) |
| app-files-engineer | `lib/files/file_explorer_controller.dart`, `lib/files/files_view.dart`, `lib/files/files.dart` (barrel) |
| app-architect (shell + seam) | `lib/app/providers.dart` (add `runStateProvider`); `lib/app/shell.dart` (wire toolbar Run/Stop/Soft-reboot to run-control; host `ConsoleView` in the strip; focus-console-on-run in stacked; keep-alive read of `consoleBufferProvider`); `lib/app/pages/{editor,console,files}_page.dart` (delegate to the feature `*_View`) |
| app-test-author | all `[red]` (unit/widget/golden) + `test/support` scripting; **all new `en` ARB keys** in `lib/localization/arb/app_en.arb` (one place) + `gen-l10n`; golden reseed; extends `FakeConnection` scripting if needed |

## 12. Localization design (`lib/localization/`)

— *(satisfies FR-I18N-1..5, NFR-A11Y-1/2/4, BLD-5, CON-9.)*

`intl` + ARB; `en` ships day-one and any new user-facing string lands with its `en` entry in the same commit (FR-I18N-1, CON-9). A **parity check** fails CI on any missing or orphaned key against `en` and blocks the merge (FR-I18N-2, BLD-5). All user-facing text — including error explanations, connection diagnostics, and file-operation messages — is sourced from ARB; no hard-coded display strings (FR-I18N-3). Opaque target identifiers (including the initial `esp32`/`-s3`/`-c3` examples), paths, and opcode/capability/status names remain ASCII/verbatim and are never localized (FR-I18N-4, NFR-A11Y-4). The app respects the platform locale by default with an optional in-settings override persisted in `SettingsStore` (FR-I18N-5).

## 13. Platform design

— *(satisfies NFR-COMPAT-1..3, FR-UI-1..7, CON-5.)*

### 13.1 Feature parity

iPadOS and Android tablet ship at **feature parity at every milestone**; no released capability lags one platform (NFR-COMPAT-1). Platform-specific code is confined to `lib/ble/` (permissions, identifiers, MTU quirks — [§7.4](#74-permissions--platform-quirks)) and the OS notice/store plumbing; all UI is shared. CI builds both targets each milestone.

### 13.2 Responsive layout

Tablet-first, responsive (CON-5, FR-UI-5). The shell is **connection-gated** ([ADR-0011](../../decisions/0011-connection-gated-shell.md)): with no board connected (`ConnState` `disconnected`/`connecting`) the app is a **full-screen Connect surface** with no IDE chrome; the landscape / stacked IDE below appears only once a board is `ready`/`running`. **Connect is therefore not an IDE navigation destination** — the IDE navigation is Editor / Console / Files / Blocks, and the toolbar carries an active **Disconnect** action (returning to the Connect surface) whenever a board is connected.

- **Landscape text workbench.** The default content MAY remain Files |
  Editor/Console | Pin Reference beneath the persistent top toolbar, with the
  live console strip at rest (FR-UI-1, [PRD §19.1](../prd.md)). The left
  **Files** pane is a persistent, **collapsible** sidebar: its destination
  toggles that sidebar rather than duplicating Files in the center. Editor and
  Console select the center work surface; the right pane defaults to the
  read-only pin reference and may add Plots only when A-32 provides a live view.
  State lives in `filesPaneCollapsedProvider`.
- **Landscape Blocks focus.** Blocks is a first-class NavigationRail
  destination. Selecting it replaces all Files, Editor/Console, and Pin
  Reference panes with the focused host frozen in [§11.2](#112-blocks); the
  application toolbar and rail remain. The toolbar's editor-targeted Run is
  hidden, while the feature action strip owns the sole Blocks Run. Blockly owns
  all focused width at narrower landscape sizes. Only when its remaining width
  stays ≥ 720 dp and ≥ 60% may a 360–420 dp generated-Python inspector appear.
  Host notices sit outside the canvas. The console is collapsed/on demand and
  expands after Run or new output.
- **Portrait / stacked tablet** layout uses a bottom bar to swap the full-width
  Editor, Console, Files, and Blocks work surfaces (FR-UI-2,
  [PRD §19.2](../prd.md)); editor remains the default primary surface. Blocks is
  created lazily while selected and its provider snapshot restores the workspace
  after view recreation. Rotation preserves both the selected Blocks destination
  and its serialized workspace; a recreated host completes restoration before
  actions re-enable. Plots joins this host with A-32.
- **Phone** best-effort, must not break (FR-UI-5).

A `LayoutBuilder`/breakpoint scaffold selects the landscape shell only when
width is at least 900 dp **and** width exceeds height; the selected destination
then chooses the text workbench or focused Blocks body. Portrait remains stacked
even on a 1024 dp-wide iPad. The application toolbar maps
Disconnect/Stop/Soft-reboot to the corresponding `Connection` methods and
includes the editor-targeted Run only outside Blocks focus (FR-UI-3). The text
workbench's right pane hosts the read-only **target-keyed pin reference**
selected by the opaque `chip` value from `DeviceInfo` — informational warnings
only, never an enforced/stored profile. An unknown value renders generic
guidance to consult the exact board documentation and never blocks connection
or implies pin safety (FR-UI-4, CON-7). Large touch targets clearly
communicate connection/run state (FR-UI-6, NFR-USE-2). No panel binds to BLE
directly (FR-UI-7, CON-8).

**Global About route — FROZEN (X-11 subset · `[docs]` 2026-07-28).** About is
not an `AppSurface` or board-gated IDE destination. The toolbar pushes it above
the shell from every connection state, preserving all providers and platform
views behind the route. Below 600 dp, Soft-reboot moves into a labelled More
menu beside About so the phone toolbar keeps the same bounded action count; at
wider sizes Soft-reboot and a direct About action remain visible. The route
uses a single-column bounded scroll at narrow widths and a balanced two-column
card layout at wide landscape widths. It remains scrollable through 2× text,
and standard Back returns to the exact prior shell state (FR-ABOUT-1/7/8).

## 14. Error handling & mapping

— *(satisfies FR-PBLE-13, FR-ERR-1..4, FR-FILES-3, NFR-USE-3, NFR-REL-4.)*

### 14.1 Status byte → typed exception → localized message

```text
PBLE/1 status (protocol.md §8)  ->  PbleException subtype  ->  ARB key -> localized text
0x01 EBADREQ      -> EBadReq        0x06 ENOMEM   -> ENoMem
0x02 ENOENT       -> ENoEnt         0x07 EBUSY    -> EBusy
0x03 EACCES       -> EAcces         0x08 ECRC     -> ECrc
0x04 ENOSPC       -> ENoSpc         0x09 ERANGE   -> ERange
0x05 EIO          -> EIo            0x0A EUNSUPPORTED -> EUnsupported
                                    0xFF EINTERNAL    -> EInternal
link/transport failures            -> BleLinkException / BleTimeoutException
unsupported proto_version          -> UnsupportedProtocolException
```

`lib/pble/` raises the typed exception (FR-PBLE-13); UI catches it and renders the localized, beginner-readable message from ARB (FR-FILES-3, NFR-USE-3) — e.g. `ENoSpc` → "the board's storage is full". The app stays coherent and non-crashing on any error or mid-operation drop (NFR-REL-4).

### 14.2 Traceback annotation (beginner errors)

Run-time Python errors arrive as `stderr` `ConsoleEvent`s, not status bytes. The data-driven error explainer ([§11.4](#114-console--error-explanation)) matches the traceback against signature → ARB suggestion and renders the suggestion **alongside** the raw traceback (annotate, never hide — FR-ERR-2). Honest surfacing at each recovery rung (STOP → soft-reboot → physical power cycle) per FR-RUN-5; there is no app-level hard-reset/safe-mode (FR-RUN-1).

## 15. Test design

This is where the Technical Design meets **Test-Driven Development** ([§0](#0-naming-note-acronym-clash), [PRD §1B.3](../prd.md)). The verification methods of [specs.md §2.2](specs.md) — *widget*, *golden*, *unit*, *conformance*, *integration*, *locale* — map onto the packages below. Each behaviour is pinned by a `[red]` test before code (NFR-MAINT-3).

### 15.1 Per-package verification approach

| Package | unit | widget | golden | conformance | integration | locale |
|---|---|---|---|---|---|---|
| `lib/ble/` | scan filter, connect, MTU, reconnect (mocked transport) | — | — | — | on-device scan/connect/MTU per chip | — |
| `lib/pble/` | codec, CRC32, correlation, error mapping | — | — | frame round-trip, fragmentation matrix, window+resume vs fake transport | resume across simulated drop | — |
| `Connection`/`FakeConnection` | every method against FakeConnection | — | — | both ends of shared corpus | — | — |
| `lib/data/` | DAO CRUD, migrations, schema version | — | — | — | offline create→run→log | — |
| `lib/editor/` | EditorSurface, tabs, save | tabs/find/run actions (FakeConnection) | landscape/portrait/phone | — | save→upload→run loop | strings from ARB |
| `lib/console/` | line buffer, error explainer table | stream render, stdin, tab-switch persistence | stdout/stderr/system + traceback | — | observe-anywhere | explainer strings |
| `lib/files/` | path/forbidden predicate, `.py` filter | list/upload/download/rename/delete (FakeConnection) | — | — | progress + CRC success | status-code messages |
| `lib/connect/` | saved-board store | scan list (label/PyBLE-XXXX + RSSI), diagnostics, unsupported-version prompt, rename privacy-warn + length bound, Identify shown iff has_identify, configure-LED prompt when identify_led null, EUNSUPPORTED surfaced | — | — | scan→connect→HELLO→DeviceInfo; setLabel/setIdentifyLed/identify round-trips | permission rationale, rename warning |
| `lib/blocks/` | bridge decode/limits, host epochs, fresh-snapshot correlation, action lock, restore state; GPIO/Time/NeoPixel definitions, codegen, validation, imports, and name safety; catalog schema/IDs/distinct-role materialization; production-generation of all seven fixtures (no pin/default/profile); target adoption/path derivation/128-byte preflight, sidecar v1 codec/CRC/exact-source and scratch-round-trip validation; bounded tokenizer/parser/model precedence, imports, names, numeric/range/function/NeoPixel/resource limits, supported/rejected grammar, all-or-nothing and semantic reparse equality | focused layout, sole Run ownership, off-canvas notices, inspector threshold, console expansion; shared adaptive example/import chooser; Preview non-mutation; empty Create; confirmed/cancelled/failed Replace with workspace+target rollback and host-acknowledged success; duplicate-role/diagnostic/stale-document errors; non-destructive optional/invalid toolbox IDs; no implicit board action; keyboard/semantics | wide landscape with inspector; narrower landscape without; stacked portrait; empty Examples state; exact-reopen/import diagnostics, target paths, and source preview; compact bottom sheet, wider dialog, constrained action overflow, large text, and keyboard inset | source-first/sidecar-last write ordering, no-PUT overlength preflight, local-session stamp lifecycle, board-swap/disconnect refusal before the next sidecar/Run verb, and CRC anchor reuse | every catalog workspace restore→generate; exact pair reopen preserving serialization/target; composed bound-document Python subset→workspace→generate→semantic reparse; torn-pair failures; GPIO/NeoPixel workspace pair Save→Run on iPadOS + Android | all Blocks/example/import/actions/wiring/diagnostic/validation/semantics labels |
| `lib/plots/` | SeriesParser | plot render | plot golden | — | live plot from console | — |
| `lib/github_import/` | `.py` filter, provenance | preview/conflict | — | — | fetch→putFile→record | — |
| `lib/localization/` | key registry | — | — | — | — | parity gate (en vs locale) |
| `lib/app/` About | runtime build-info adapter + blank/failure formatting | global disconnected/connected entry, full-route/back preservation, offline `LicenseRegistry` navigation, semantics, zero `Connection` calls | phone + iPadOS/Android portrait/landscape, 2× text/high contrast | — | installed version/build smoke on iPadOS + Android | every About/action/privacy/version string |

### 15.2 Widget + golden across en + iPad + Android

Golden tests render each layout at iPad and Android tablet form factors
(landscape, portrait) plus a phone breakpoint, in `en`, all against
`FakeConnection` (FR-UI-1/2/5, NFR-COMPAT-1, NFR-USE-2/4). Blocks-specific
goldens cover a wide focused landscape with the bounded inspector, a narrower
landscape with Blockly full-width and no inspector, the collapsed and expanded
console states, and stacked portrait. Widget assertions prove exactly one
Blocks Run and that notices are siblings outside the platform-view canvas.
Example variants cover the empty-workspace call to action, chooser/source
preview, explicit GPIO fields, non-empty replacement confirmation, and
constrained-width action overflow. Sidecar/import variants cover a valid exact
reopen, source/version mismatch diagnostics, an all-or-nothing unsupported
Python error, a complete converted-source preview, stale-editor invalidation,
and empty Create versus confirmed Replace. A11y golden variants cover
large-font/high-contrast (NFR-A11Y-3); widget/semantics tests cover focus
recovery, keyboard activation, and one-shot announcements.
About variants cover phone plus iPadOS/Android tablet portrait and landscape,
2× text/high contrast, wide two-column versus compact single-column layout,
the compact toolbar overflow, and route restoration. Widget tests inject
pending/success/blank/failing package metadata, prove the licenses route is
offline/reachable, and assert that neither route calls `Connection`
(FR-ABOUT-1..8).

### 15.3 FakeConnection / mocked transport

Widget/unit suites inject `FakeConnection` (D5, FR-CONN-7); `lib/ble/` uses a mocked `flutter_blue_plus` transport (FR-BLE-7); `lib/pble/` uses an in-memory fake byte transport (FR-PBLE-* conformance).

### 15.4 PBLE/1 conformance

The shared corpus ([§8.8](#88-shared-conformance-corpus-with-the-firmware)) runs the same byte sequences on the Dart client and the firmware `pyble_proto`, validating frame/fragmentation/window/resume/error parity once for both ends (FR-PBLE-1..13, NFR-MAINT-4). DRAFT-protocol dependency tracked by [OI-3](specs.md).

### 15.5 Locale parity & integration

The locale parity check fails on any missing/orphaned ARB key and blocks merges
(FR-I18N-2, BLD-5). The real
`integration_test/android_smoke_test.dart` platform boundary registers the
About and Blockly scenarios from non-entrypoint suite modules, so Flutter
has one integration application entrypoint and installs one bundle containing
both scenarios. It runs in CI on a fresh Android 14 / API 34 Google APIs x86_64
AVD with the pinned Flutter
toolchain and NDK, 2 GiB RAM, one virtual CPU, KVM acceleration, a software
GPU, a bounded `sys.boot_completed` wait, and always-uploaded bounded
emulator/logcat diagnostics. The runner reclaims only unused side-by-side NDK
revisions before creating the API 34 emulator's required 6 GiB userdata image.

The checked-in Android Gradle configuration bounds the build JVM to a 3 GiB
heap, 1 GiB metaspace, and 256 MiB code cache. The hosted integration job
additionally disables the persistent Gradle daemon and permits one Gradle
worker. It prebuilds the sole integration entrypoint before starting the AVD,
then stops the build daemon; the device-backed `flutter test` reuses that
artifact cache for its build/install boundary. Prebuild and device test are
separately time-bounded and write directly to retained diagnostic logs, so a
failed timeout cannot be hidden behind a still-open shell pipeline. This keeps
the compiler and emulator peak allocations sequential on the smallest
supported hosted runner while preserving the single-entrypoint integration
contract.

The Blockly suite verifies the offline asset, JavaScript channel,
restore/recreation, source generation, examples, sidecar reopen, bounded Python
import, and fake-Connection Save/Run flow in Android's actual WebView rather
than a host widget substitute. The About suite verifies actual installed
version/build metadata and the offline PyBLE license asset through the platform
plugin boundary (FR-ABOUT-3/4). Integration suites also run end-to-end against a
fake board and on-device smoke per chip (run/stop, multi-file upload,
dropped-link resume, observe-anywhere console) — NFR-REL-1..4, NFR-PERF-* (HIL
ceilings frozen later, [OI-4](specs.md)).

### 15.6 Import-boundary & no-leak gates

A static check (custom lint / dependency rule) fails the build if any widget imports `lib/ble/` (NFR-MAINT-1, CON-8). The no-leak gate ([CLAUDE.md](../../../CLAUDE.md), [AGENTS.md](../../../AGENTS.md)) runs over app source — zero proprietary tokens (CON-6, FR-PBLE-15, BLD-8). An SPDX-header lint enforces `SPDX-License-Identifier: MIT` on every source file (BLD-8).

### 15.7 Launcher identity and platform assets

The launcher source of truth is the flat, grid-defined
`assets/branding/pyble-prompt-chip.svg`; generated PNGs are never edited
independently. The deep-navy field and electric-blue Prompt Chip preserve the
user-authored microcontroller-plus-radio composition while removing its
unscalable wordmark, third-party figure mark, generated lighting, and baked
mask. `tools/generate_app_icons.sh` exports the 1024 px master, the iOS
default/dark/grayscale-tinted appearances, legacy platform sizes, and the
Google Play listing image. Android's adaptive background, foreground, and
monochrome vector resources mirror the SVG path data on the same 108 dp grid
and keep the complete mark inside the guaranteed 66×66 dp core.

`app_identity_manifest_test.dart` parses the iOS catalog and Android adaptive
resource references and verifies PNG dimensions/color types. Both release
builds are required because asset-catalog and Android-resource compilation are
part of the contract. A fixed visual strip at 20/29/40/48/76/180 px and masked
circle/squircle/rounded-square previews catches optical regressions that file
metadata cannot (BLD-10).

The iOS distribution gate additionally enumerates every regular file under
`App.framework/flutter_assets`, rejects any non-Mach-O payload reported as
`script text executable`, and verifies the extracted IPA after ZIP metadata has
been applied. This is deliberately stricter than `codesign --deep --strict`,
which can validate the enclosing framework while Apple's server independently
reclassifies a script-like resource as nested code (BLD-11).

## 16. Traceability

Design element → satisfied requirement IDs. Each `FR-*`/`NFR-*`/`CON-*`/`DAT-*` family has at least one design home.

| Design element (section) | Package(s) | Requirement IDs |
|---|---|---|
| BLE adapter, scan filter, MTU, reconnect, permissions ([§4.1](#41-libble--ble-adapter), [§7](#7-ble-transport-design-libble)) | lib/ble | FR-BLE-1..8, IF-1/5, NFR-COMPAT-2/3, CON-1/2 |
| PBLE/1 codec, fragmentation, correlation, transfer, HELLO, errors ([§4.2](#42-libpble--pble1-client--connection-implementation), [§8](#8-pble1-client-design-libpble)) | lib/pble | FR-PBLE-1..15, IF-1/2 |
| Connection interface + FakeConnection ([§5](#5-the-connection-api-design)) | lib/pble, test | FR-CONN-1..12, NFR-MAINT-3/4, CON-8 |
| State management & data flow, single-writer, runtime connection session ([§6](#6-state-management--data-flow), [ADR-0009](../../decisions/0009-runtime-connection-manager.md)) | (app-wide), lib/pble | FR-CONN-5, FR-RUN-3, NFR-MAINT-1/2, CON-8, SEC-2 |
| Editor ([§4.3](#43-libeditor--code-editor), [§11.1](#111-editor)) | lib/editor | FR-EDIT-1..7, FR-RUN-1/4, NFR-A11Y-3 |
| Console + error explanation ([§4.4](#44-libconsole--console-panel), [§11.4](#114-console--error-explanation), [§14.2](#142-traceback-annotation-beginner-errors)) | lib/console | FR-CONSOLE-1..7, FR-ERR-1..4, DAT-5 |
| File explorer ([§4.5](#45-libfiles--workspace-file-explorer)) | lib/files | FR-FILES-1..8, FR-CONN-4/9, CON-3, SEC-7 |
| Blocks ([§4.6](#46-libblocks--blockly-block-editor), [§11.2](#112-blocks)) | lib/blocks | FR-BLOCKS-1..13, CON-6/7 |
| Plots ([§4.7](#47-libplots--live-plots), [§11.3](#113-plots)) | lib/plots | FR-PLOTS-1..3, CON-7, OI-5 |
| Connect flow + runtime `ConnectionManager` session ([§4.8](#48-libconnect--scanconnect-flow-ui), [ADR-0009](../../decisions/0009-runtime-connection-manager.md)) | lib/connect, lib/pble | FR-CONNECT-1..6, FR-CONN-6, FR-UI-3, FR-BLE-8, CON-8, SEC-6, NFR-USE-1 |
| Screenless identity — label/identify caps, scan-list name, rename + Identify UI, privacy ([§4.8](#48-libconnect--scanconnect-flow-ui), [§7.1](#71-scan--connect), [§8.6](#86-hello--capabilities), [§8.9](#89-screenless-identity--identify-control-commands), [§11.5](#115-screenless-identity--rename--identify)) | lib/connect, lib/pble | FR-CONN-10/11/12, FR-CONNECT-1, FR-CONN-1/6, SEC-8/9 |
| GitHub import ([§4.9](#49-libgithub_import--public-repo-import), [§10](#10-github-import-design-libgithub_import)) | lib/github_import | FR-IMPORT-1..6, IF-4, DAT-6, NFR-OFF-2 |
| Persistence ([§4.10](#410-libdata--persistence-drift), [§9](#9-persistence-design-libdata)) | lib/data | FR-PROJ-1..7, DAT-1..8, IF-3, NFR-OFF-1..3, CON-4 |
| Localization ([§4.11](#411-liblocalization--i18n), [§12](#12-localization-design-liblocalization)) | lib/localization | FR-I18N-1..5, NFR-A11Y-1/2/4, BLD-5, CON-9 |
| About, runtime metadata, and offline notices entry ([§4.12](#412-libapp--about-and-open-source-information), [§13.2](#132-responsive-layout)) | lib/app | FR-ABOUT-1..8, IF-6, NFR-OFF-1..3, NFR-A11Y-3, CON-5/8/9, SEC-3/5 |
| Platform & responsive layout ([§13](#13-platform-design)) | (app-wide) | FR-UI-1..7, NFR-COMPAT-1..3, NFR-USE-2/4, CON-5 |
| Run control & data flow ([§3.2](#32-data-flow-example--run-a-file)–[§3.4](#34-data-flow-example--file-mirroring-download)) | lib/pble + UI | FR-RUN-1..5, FR-CONN-2 |
| Error handling & mapping ([§14](#14-error-handling--mapping)) | lib/pble + UI | FR-PBLE-13, FR-ERR-*, FR-FILES-3, NFR-USE-3, NFR-REL-4 |
| Reliability (resume, CRC, preserve-on-drop) ([§8.4](#84-file-transfer-state-machine), [§9.2](#92-migrations--hydration)) | lib/pble, lib/data | NFR-REL-1..4, NFR-PERF-1/2, FR-PROJ-6 |
| Test design, shared corpus, gates ([§15](#15-test-design)) | all | NFR-MAINT-1/3/4, BLD-5/8, CON-6/8 |
| Build/versioning/distribution ([§15.6](#156-import-boundary--no-leak-gates), [§15.7](#157-launcher-identity-and-platform-assets), [§8.6](#86-hello--capabilities)) | all | BLD-1..11, IF-6, NFR-COMPAT-1 |
| Security & privacy ([§5.1](#51-the-connection-interface), [§6.3](#63-single-active-writer--serialization), [§8.9](#89-screenless-identity--identify-control-commands), [§9.1](#91-schema), [§11.5](#115-screenless-identity--rename--identify)) | lib/pble, lib/connect, lib/data | SEC-1..9 |

**Requirements with no dedicated design element:** none functional. Notes:

- **NFR-PERF-3/4** and **OI-4** have design *levers* (MTU 247, window `W`, bounded console buffer, time-to-connect via saved `board_ref`) but the concrete ceilings are HIL-frozen later — by intent, not a gap.
- **BLD-1/2/3/4/6/10/11** (single Flutter codebase, `pubspec` governance + lock, SemVer, free dual-store-at-parity distribution, generated notices + in-app Open-Source Notices screen / IF-6, platform launcher packaging, and store-signable embedded data) are project/build-pipeline obligations: this TDD honors them (single codebase, ASCII identifiers, notices screen surfaced in UI, shared vector launcher source, deterministic Blockly asset transform) but the release pipeline is owned by the build/infra stories (X-03/X-11). Flagged here for completeness.
- **BLD-9** (previous-protocol-major compatibility window) is forward-looking: no PBLE/2 exists yet, but its design home is the version-negotiation seam ([§8.6](#86-hello--capabilities)) — the same HELLO `proto_versions[]` exchange that refuses an unsupported version (FR-PBLE-5/6) is where a future app would select a previous major, so deployed boards are never bricked by an app update.
- **OI-1** (editor widget) and **OI-2** (state-management ADR) are reflected as D3 and the `EditorSurface` fallback ([§11.1](#111-editor)); both await their ADRs ([§17](#17-risks--open-questions)).

## 17. Risks & open questions

- **R1 — Flutter Python-editor widget maturity (OI-1).** `flutter_code_editor` tablet/external-keyboard maturity is unproven. Mitigation: the `EditorSurface` interface lets a WebView-hosted Monaco/CodeMirror editor drop in without touching callers ([§11.1](#111-editor)); decision pending evaluation and an ADR.
- **R2 — State-management choice (OI-2).** D3 fixes a single approach (working choice Riverpod); must be ratified by an ADR before broad adoption (NFR-MAINT-2).
- **R3 — iOS vs Android BLE behavior.** MTU negotiation timing/results differ; iOS hides the MAC (use the platform identifier for `board_ref`); permission models diverge. Isolated in `lib/ble/` ([§7.4](#74-permissions--platform-quirks)) and tested with a mocked transport (FR-BLE-7) plus per-chip on-device smoke.
- **R4 — Blockly-in-WebView.** WebView/JS-channel performance and offline asset bundling on tablets are a risk; the bridge stays behind `Connection` so a failure is contained to `lib/blocks/` ([§11.2](#112-blocks)).
- **R5 — Large-file transfer UX.** Long uploads over BLE need continuous progress and graceful resume across drops; covered by the window+resume state machine ([§8.4](#84-file-transfer-state-machine)) and progress callbacks, but real-link throughput/latency ceilings are HIL-frozen later (OI-4, NFR-PERF-3/4).
- **R6 — PBLE/1 still DRAFT (OI-3).** UUIDs/opcodes/status numbers are provisional until [protocol.md](../protocol.md) §2/§4 freeze; the single constants mirror (D7) localizes the churn, and the shared corpus ([§8.8](#88-shared-conformance-corpus-with-the-firmware)) keeps app and firmware in lockstep.
- **R7 — Plot-parsing configuration model (OI-5).** The exact user-facing model for mapping console output to series ([§11.3](#113-plots)) is to be detailed; the `SeriesParser` seam keeps it changeable without touching `fl_chart` rendering.
