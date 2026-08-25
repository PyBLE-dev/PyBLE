# PyBLE — System Architecture

Status: **DRAFT** · Last updated: 2026-08-25

## 1. The three pieces

```
┌──────────────────────────────┐        BLE GATT (PBLE/1)        ┌──────────────────────────────────┐
│  PyBLE app  (app/)            │  ───────────────────────────▶  │  MicroPython board + agent        │
│  Flutter · iPad + Android     │   write → RX char               │                                  │
│                               │                                 │  ┌────────────────────────────┐  │
│  ┌─────────────────────────┐  │   notify ← TX char              │  │ Layer 4: user MicroPython   │  │
│  │ UI: editor · console ·  │  │  ◀───────────────────────────   │  │   /main.py, /lib, /data     │  │
│  │ files · blocks · plots  │  │   read   ← INFO char            │  └────────────────────────────┘  │
│  ├─────────────────────────┤  │                                 │  ┌────────────────────────────┐  │
│  │ PBLE/1 client (lib/pble)│  │                                 │  │ Layer 3: PyBLE agent        │  │
│  ├─────────────────────────┤  │                                 │  │   pyble_ble / _runner / _fs │  │
│  │ BLE adapter (lib/ble)   │  │                                 │  ├────────────────────────────┤  │
│  └─────────────────────────┘  │                                 │  │ Layer 2: target adapter     │  │
└──────────────────────────────┘                                 │  │   v1: esp32 / -s3 / -c3     │  │
                                                                  │  ├────────────────────────────┤  │
                                                                  │  │ Layer 1: upstream uPython   │  │
                                                                  │  └────────────────────────────┘  │
                                                                  └──────────────────────────────────┘
```

1. **App** (`app/`) — a Flutter tablet app. Layers: BLE adapter → PBLE/1 client → UI widgets.
2. **Agent firmware** (`firmware/`) — upstream MicroPython + a PyBLE agent, layered so the VM stays a clean submodule (see [firmware.md](firmware.md)).
3. **PBLE/1** (`docs/specifications/protocol.md`) — the open wire protocol carried over a BLE GATT service.

The seam between app and firmware is a **byte stream over two GATT characteristics** (RX/TX), framed by PBLE/1. Everything above that seam (the editor, file explorer, console, plots) is transport-agnostic and speaks only to the PBLE/1 client.

### 1.1 Companion example source collection

The official user-facing runnable-example collection is maintained separately
at <https://github.com/PyBLE-dev/examples>. It is content consumed through the
generic public-GitHub import boundary, not a fourth runtime subsystem, package,
submodule, build input, or privileged source. Repository existence alone makes
no runnable or validated-example claim; those claims belong to versioned
catalog and validation evidence in that repository.

The current primary-maintainer sibling checkout is
`/Users/vyv/Working/SciLabPro/PyBLE-Examples`. That path is non-portable
operational information only; contributors and releases identify source by the
public repository plus immutable commits/tags. Official example source,
catalogs, example-specific tests, and example HIL evidence are implemented in
that separate checkout and history. This PyBLE worktree retains app/importer,
PBLE/1, firmware, and cross-repository compatibility contracts, plus its small
GitHub-import integration fixtures and bundled offline Blocks examples. See
[ADR-0041](../decisions/0041-separate-official-examples-repository.md).

## 2. App architecture (summary)

- **`lib/ble/`** — a thin `flutter_blue_plus` wrapper: scan (filtered to the PyBLE service UUID), connect, MTU negotiation, and a `Stream<List<int>>` in / `write(bytes)` out byte boundary. Knows nothing about PBLE/1.
- **`lib/pble/`** — the PBLE/1 client: frame codec, request/response correlation, file-transfer state machine, console stream, error mapping. Exposes a clean `Connection` API (`deviceInfo`, `runFile`, `stop`, `console`, `listDir`, `getFile`, `putFile`, `delete`, `mkdir`).
- **UI** (`lib/editor`, `lib/console`, `lib/files`, `lib/blocks`, `lib/plots`) — widgets that bind to the `Connection` API through callbacks. No widget imports `lib/ble` directly.

Full detail: [app.md](app.md).

## 3. Firmware architecture (summary)

Four layers, strict separation:

1. **Upstream MicroPython** — pinned submodule, never edited in place.
2. **Target adapter / board overlay** — isolates MicroPython-port, BLE-host,
   build, storage, and board differences. The v1 reference chip targets are
   `esp32`, `esp32-s3`, and `esp32-c3`. A build variant may narrow one target
   to an explicitly selected physical board without changing target identity;
   the initial such variant is `waveshare-esp32-s3-lcd-147b`.
3. **PyBLE agent** — the protected native/frozen modules that own BLE, the runner, and the filesystem bridge.
4. **User workspace** — the student's own `.py` files; never the control plane.

Optional frozen user libraries such as `pyble_st7789` belong at the Layer-4
boundary: import is inert, construction is explicit user code, and no display
state or pin routing enters PBLE/1 or the Layer-3 agent. ADR-0028 requires such
a board-specific library to live only in the named board build that needs it;
the generic `esp32-s3-n16r8` image contains neither the display runtime nor
the exact-board companion or splash-only native seam.

ADR-0024, as amended by ADR-0029, adds one narrow Layer-2 exception for the
exact Waveshare ESP32-S3-LCD-1.47B: a named companion is factory-enabled after
an erased exact-board install, remains persistently disableable, and may render
one cosmetic app-discovery frame only after actual BLE
readiness. It neither detects a board nor changes the generic driver,
connection selection, PBLE/1 capabilities, user-code hardware access, or trust
model. Its failure boundary returns to ordinary boot, and it releases SPI and
framebuffer before making the retained panel visible. ADR-0028 confines that
exception to the independently built and provisioned
`waveshare-esp32-s3-lcd-147b` image. Its profile ID is release/install evidence,
not an app-visible runtime connection profile; both S3 variants still report
the target `esp32-s3` over PBLE/1.

Full detail: [firmware.md](firmware.md).

The app and PBLE/1 are not keyed to an ESP32 allowlist. A future MicroPython
target may use a different CPU, port, BLE host, storage backend, and
provisioning tool, provided its agent preserves this boundary and passes
PBLE/1 conformance. See
[ADR-0021](../decisions/0021-capability-defined-board-scope.md).

## 4. Data flow examples

**Run a file**

```
editor "Run" → Connection.putFile("/main.py", bytes)   [PBLE/1 FILE_PUT]
             → Connection.runFile("/main.py")           [PBLE/1 RUN]
agent: import/exec the file on a runner task
agent → console notifications (stdout/stderr)           [PBLE/1 CONSOLE events]
app: append to console view
```

**Stop**

```
console "Stop" → Connection.stop()                      [PBLE/1 STOP]
agent: raise KeyboardInterrupt into the runner; ensure clean teardown
```

**Reliability** — file transfer uses windowed chunks with acknowledgements and resume-on-reconnect, designed into PBLE/1 from the start (see [protocol.md](protocol.md#5-file-transfer-the-reliability-core)). This is the part to get right early.

## 5. Clean-room / IP boundary

PyBLE is an **independent, MIT, clean-room project.** It must contain **none** of any closed-source product's intellectual property:

- ❌ No closed-source wire protocol, opcodes, or frame format. PyBLE defines **PBLE/1** from scratch.
- ❌ No proprietary board or routing profiles, and no proprietary BLE UUIDs / advertising prefixes. PyBLE uses its **own** UUID base.
- ❌ No lab/chemistry/calibration content, copied catalog/curriculum,
  domain-specific lesson flow, or proprietary/classroom pedagogy. ADR-0016's
  eight small starter workspaces are authored fresh for PyBLE and are not a
  curriculum or grading system. A named hardware example remains explicit
  guidance with disconnected GPIO roles, never detection or routing state.

Where a maintainer holds prior art they own, they may **re-implement** it under
MIT — they do **not** copy proprietary code. A CI "no-leak" gate (see
[`AGENTS.md`](../../AGENTS.md#open-source-and-clean-room-boundary)) enforces
this on every push by rejecting forbidden tokens.

This boundary is what makes PyBLE safe to open-source. It is also why the protocol is fresh rather than reused — see [ADR-0002](../decisions/0002-fresh-protocol.md).

## 6. Technology choices

| Area | Choice | Why |
|---|---|---|
| App framework | Flutter | One codebase, iPad + Android, tablet-first |
| BLE | `flutter_blue_plus` | Mature cross-platform BLE; iOS + Android |
| Editor | `flutter_code_editor` | Syntax highlighting, Python mode |
| Blocks | Blockly in a WebView | Proven block→Python generation |
| Charts | `fl_chart` | Pure-Dart plotting |
| Firmware architecture | upstream MicroPython + protected PyBLE agent + target adapter | Vendor-neutral contract, no MicroPython fork |
| Firmware (v1 reference) | MicroPython ESP32 port + ESP-IDF | Initial `esp32` / `esp32-s3` / `esp32-c3` implementation |
| BLE stack (v1 reference) | NimBLE | ESP32-family implementation; future ports may use another conforming BLE peripheral stack |
| Persistence | local (sqlite/Drift or files) | Offline-first; project files & settings |

All third-party components are MIT/Apache/BSD-compatible; notices ship in `THIRD_PARTY_LICENSES`.

<!-- SPDX-License-Identifier: MIT -->
