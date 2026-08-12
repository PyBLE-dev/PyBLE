# PyBLE — Product Requirements Document

Status: **DRAFT** · Owner: project maintainer · Last updated: 2026-08-03

Project phase: **Implementation**. This is the apex requirements document; where it overlaps a deeper spec (protocol.md, firmware.md, app.md, hardware.md, architecture.md), the more specific spec wins on its own topic.

## Contents

- §1 Executive Summary
- §1A Non-Negotiable Design Constraints
- §1B Development Methodology: SDD + TDD
- §2 Product Vision
- §3 Problem Statement
- §4 Goals and Non-Goals
- §5 Target Users & Personas
- §6 Product Components
- §7 Product Scope
- §8 Core User Workflows
- §9 Functional Requirements: App
- §10 Functional Requirements: Agent Firmware
- §11 Hardware Requirements
- §12 Data Model
- §13 Non-Functional Requirements
- §14 Security & Privacy Requirements
- §15 Open-Source Posture, License & Distribution
- §16 Technical Architecture
- §17 Dependency Governance
- §18 Release & Versioning
- §19 UI Requirements
- §20 Success Metrics
- §21 Acceptance Criteria
- §22 Development Roadmap
- §23 Risks & Mitigations
- §24 Future Product Line / Post-v1
- §25 Open Questions
- §26 Glossary

---

## §1 Executive Summary

**PyBLE** ("Python over BLE") is a free, open-source ([MIT](../../LICENSE)) MicroPython IDE that edits, runs, and manages code on compatible microcontroller boards over **Bluetooth Low Energy**, from a tablet, with no everyday cable. Its platform scope is any board able to run MicroPython and host a conforming PBLE/1 BLE peripheral agent. Classic **ESP32**, **ESP32-S3**, and **ESP32-C3** are the initial v1 firmware targets, not the permanent product boundary. PyBLE is the wireless, tablet-native counterpart to desktop tools like Thonny and Mu: simple and beginner-friendly, while remaining useful to experienced makers. It is distributed free via `pyble.dev` (web flasher + docs) and the App Store / Google Play (app). The canonical firmware binaries are versioned at `pyble.dev`; v1.0 and later additionally mirror them through GitHub Releases.

**The gap it closes.** Upstream MicroPython ships **no built-in Bluetooth REPL**, so there is no standard way to edit and run code on a MicroPython board over BLE. On iPadOS, arbitrary USB serial is not available to apps, which rules out the cable-based workflow desktop tools assume. PyBLE supplies the two missing pieces and the contract that joins them. See §2.

**Three components, one contract.** PyBLE is delivered as exactly three deliverables bound by one open protocol:

1. **App** (`app/`) — a Flutter, iPad + Android tablet IDE: editor, console, file explorer, Blockly blocks, live plots, GitHub import. Layered as BLE adapter → PBLE/1 client → UI, per [app.md](app.md).
2. **Agent firmware** (`firmware/`) — a protected PBLE/1 agent built on **upstream MicroPython** (pinned source, never forked). The initial reference port uses ESP-IDF/NimBLE and builds `esp32`, `esp32-s3`, and `esp32-c3`; future platforms keep their BLE/runtime/storage differences behind a target adapter, per [firmware.md](firmware.md).
3. **PBLE/1** — the clean-room, versioned BLE wire protocol carried over a PyBLE-owned GATT service (RX/TX/INFO characteristics), per [protocol.md](protocol.md).

The seam between app and firmware is a byte stream over two GATT characteristics, framed by [PBLE/1](protocol.md). Everything above that seam is transport-agnostic and speaks only to the protocol client, which keeps the IDE testable against a fake board and lets the community re-implement either half against the open contract.

**Licensing & sustainability.** Every source file is MIT. There is no paywall, no account, no telemetry-by-default, and no closed module. Sustainability is via donations / GitHub Sponsors, not sales (see [ADR-0003](../decisions/0003-license-mit.md)).

**Project phase: Implementation.** This PRD governs the production build-out of PyBLE across phased releases — **v1.0** (first production release), then **v1.x** (breadth), then **post-v1** (community). It is not a prototype plan and not a feasibility study; it converts the frozen specifications into testable, story-sized requirements.

---

## §1A Non-Negotiable Design Constraints

These constraints are binding on every story, commit, and release. A change that violates one of them is rejected regardless of its other merits. They restate, in requirements voice, the posture fixed by [`AGENTS.md`](../../AGENTS.md) and [`CLAUDE.md`](../../CLAUDE.md).

### §1A.1 Open-source & MIT

- Every source file in the repository **MUST** be MIT-licensed. The repository **MUST** carry a single top-level [`LICENSE`](../../LICENSE) (MIT) and the product **MUST** be distributed free of charge on all applicable channels (App Store, Google Play, web flasher, and the GitHub Releases mirror required from v1.0).
- No file **MAY** carry a proprietary, "all rights reserved", or non-OSI header. No module, build variant, or feature **MAY** be closed-source, paywalled, or gated behind an account or paid tier.
- Third-party components **MUST** be MIT/Apache/BSD-compatible; their notices **MUST** ship in `THIRD_PARTY_LICENSES`. The currently-planned stack (Flutter, `flutter_blue_plus`, `flutter_code_editor`, Blockly, `fl_chart`, upstream MicroPython, ESP-IDF, NimBLE) satisfies this; see [architecture.md §6](architecture.md#6-technology-choices).
- Contributions **MUST** be made under the DCO (sign-off, see §1B.6). Prior art a contributor owns **MAY** be relicensed MIT and re-implemented, but proprietary code **MUST NOT** be pasted (see §1A.2).
- Telemetry **MUST** be off by default; any future opt-in analytics **MUST** be local-first, disclosed, and shipped as MIT source — never a precondition of use.

### §1A.2 Clean-room / no-leak rule

PyBLE is an independent, clean-room project. Its shippable source **MUST** contain **none** of any closed-source product's intellectual property: no closed wire protocol, opcodes, or frame format; no proprietary board or routing profiles; no proprietary BLE UUIDs or advertising prefixes; no lab/chemistry/calibration code, content, or pedagogy. Where a maintainer holds prior art they own, they **MUST** re-implement it under MIT rather than copy it. See [architecture.md §5](architecture.md#5-clean-room--ip-boundary) and [ADR-0002](../decisions/0002-fresh-protocol.md).

This requirement is enforced mechanically. CI **MUST** run the canonical
no-leak gate on every push and **MUST** reject the push if it finds a forbidden
proprietary identifier in shippable source. The tested implementation is the
single source of truth:

```sh
tools/ci/no_leak.sh
```

PyBLE keeps its identifiers independent: the protocol is **PBLE/1**, codec
files are `pble_*`, agent modules are `pyble_*`, the GATT base is a
PyBLE-owned 128-bit UUID encoding `pybl`, and the advertising prefix is
`PyBLE-`. A passing no-leak gate is part of the Definition of Done (§1B.5).

### §1A.3 Architectural Rejection List

The following are vetoed as core mechanisms. Each is stated as **Rejected: X — because Y**; a story that reintroduces any of them fails review.

1. **Rejected: a USB-serial-first workflow — because** iPadOS cannot offer arbitrary USB serial to apps, so a cable-first path would make the first-class platform second-class. BLE is the primary and only v1 transport. (See [app.md §5](app.md#5-platform-notes).)
2. **Rejected: a Wi-Fi-first workflow — because** network onboarding (SSID/password, captive portals, AP mode) is exactly the friction PyBLE removes for classrooms and walk-up use; Wi-Fi is not a v1 transport.
3. **Rejected: board-specific product or generalized routing/pin profiles — because** PyBLE targets compatible MicroPython + BLE platforms and exposes ordinary hardware to user code via standard MicroPython APIs, not via an agent-owned product profile; the in-app pin reference is informational only and **MUST NOT** become an enforced or stored profile (see [hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware)). An open target adapter needed to run PBLE/1 on a MicroPython port is implementation support, not a user hardware profile. Carve-outs (do not weaken this): a persisted **device label** and a **single optional identify-LED GPIO** are permitted per-device agent configuration for screenless UX; and ADR-0024/ADR-0029 permit one module named for the exact Waveshare ESP32-S3-LCD-1.47B to drive only its published display pins for a bounded, cosmetic, BLE-ready app-discovery frame. That frame is factory-enabled only after an erased installation of the explicitly chosen exact-board image and remains persistently disableable. Per [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md), that driver and splash machinery **MUST** ship only in the explicit `waveshare-esp32-s3-lcd-147b` provisioning image and **MUST NOT** be accumulated in the lean `esp32-s3-n16r8` chip-family image. Neither exception routes hardware for user code, exposes a lookup/capability profile, detects or selects a board, or gates access by device identifier or label (see §11.3, §10.7, [ADR-0029](../decisions/0029-enable-waveshare-splash-after-erased-install.md)).
4. **Rejected: forking MicroPython — because** a fork is unmaintainable and breaks the clean-submodule rule; PyBLE builds on upstream MicroPython as a pinned submodule and adds an agent around it (see [firmware/upstream/README.md](../../firmware/upstream/README.md)). Upstream **MUST NOT** be edited in place; any unavoidable patch is isolated under `firmware/patches/micropython-<tag>/` with a written reason, default **zero**.
5. **Rejected: an editable control plane — because** the agent is the control plane and user code is just a program it runs; user code (including a frozen `while True: pass`) **MUST NOT** be able to wedge BLE or block `STOP`. The agent **MUST** keep servicing the link while user code runs, and **MUST NOT** depend on editable `boot.py`/`main.py` for its own operation (see [firmware.md §1](firmware.md#1-four-layer-rule), [firmware.md §5](firmware.md#5-runtime-rules)).
6. **Rejected: `.mpy`/`.pyc` in the workspace or transfer — because** byte-compiled artifacts are mpy-cross-version-fragile and opaque to learners; examples and file transfer are `.py` only.
7. **Rejected: unpinned upstream — because** reproducibility requires that one MicroPython tag + one ESP-IDF version drive all three chips. The build **MUST** verify the checked-out submodule SHA against [`firmware/versions.lock`](../../firmware/versions.lock) and refuse to proceed on mismatch; upgrades go only through the controlled workflow, never by hand during a build.
8. **Rejected: accounts, cloud sync, or telemetry-by-default — because** PyBLE is local-first and offline-capable; a connected client on a personal board is the trust model (see [protocol.md §10](protocol.md#10-security-note-v1)). No feature **MAY** require a login or a network round-trip to function.
9. **Rejected: instructor/classroom/lab/actuator features — because** PyBLE is a general MicroPython IDE, not a managed teaching platform or a science-lab controller. No group/lease/pairing-token/grading/safety-guard/calibration mechanism is in scope; these are permanent boundaries, not deferrals (see §4.3).

### §1A.4 Correct firmware principle

The production firmware **MUST** follow the four-layer rule from [firmware.md §1](firmware.md#1-four-layer-rule), with strict separation between layers:

```text
Layer 1  Upstream MicroPython port           — pinned source, never edited in place
Layer 2  Target adapter / board overlay      — port, BLE host, storage, build, chip config
Layer 3  PyBLE agent (pyble_*)               — the protected control plane (BLE, runner, fs, console, info)
Layer 4  User workspace                      — /main.py, /lib/*.py, /data/*  (never the control plane)
```

Requirements:

- The PBLE/1 agent core **MUST** be platform-neutral; MicroPython-port, BLE-host,
  scheduler/interrupt, storage, identity, build, and chip differences **MUST**
  remain behind the **target adapter / board overlay (Layer 2)**. Within the
  initial ESP32 port, per-chip overlays are copied into the upstream port tree
  at build prep so the submodule stays pristine.
- The agent **MAY** ship first as **frozen-Python** modules (fastest path to nail PBLE/1 and reliability) and **MAY** later move hot paths (BLE I/O, framing, file chunking) to a native `USER_C_MODULE` where the chip budget demands it — **without** changing the PBLE/1 wire contract (see [firmware.md §2](firmware.md#2-agent-base-native-vs-frozen)).
- For the initial v1 ESP32 port, the single MicroPython + ESP-IDF pin in [`firmware/versions.lock`](../../firmware/versions.lock) **MUST** build all three ESP-IDF targets (`esp32`, `esp32s3`, `esp32c3`). The agent **MUST** fit the tightest target; **ESP32-C3** is the initial footprint constraint and **MUST** be validated early. Every future port owns an equivalent pinned, reproducible build and per-target resource gate.
- Cold boot **MUST** be safe: on boot the board advertises and waits; it **MUST NOT** auto-run user `main.py` unless explicitly enabled via a capability flag, so a bad `main.py` cannot lock a user out of the board.
- A separately built exact-board Layer-2 companion **MAY** render one
  cosmetic boot frame only after actual BLE readiness. It **MUST** be
  factory-enabled only after an erased exact-board installation, persistently
  disableable, bounded, fail-open, independent of
  user autorun and the PBLE/1 capability/trust model, and release its display
  resources before ordinary startup continues. It **MUST** be absent from the
  generic chip-family image and confined to its explicitly named provisioning
  profile ([ADR-0024](../decisions/0024-opt-in-waveshare-boot-splash.md),
  [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).

---

## §1B Development Methodology: SDD + TDD

PyBLE's two development approaches are **Spec-Driven Development (SDD)** and **Test-Driven Development (TDD)**. PyBLE is built **spec-first and test-first**: the two disciplines interlock — the specification fixes the contract, the test encodes the acceptance criterion, and the code is the minimum that turns the test green.

### §1B.1 Spec-Driven Development (SDD)

- The documents under `docs/specifications/` are the **single source of truth**. A contract section it depends on **MUST** be agreed and **frozen** before the code that depends on it is written. PBLE/1 is frozen one section at a time (e.g. §2 transport and §3 framing freeze first, in M0).
- A spec change **MUST** precede the code change and **MUST** land in its own commit tagged `[docs]`. Code **MUST NOT** silently diverge from a frozen spec; if reality forces a change, the spec is amended first.
- Every story **MUST** cite a **Spec ref** (file + `§` anchor) for the behaviour it implements. Where two specs touch a topic, the deeper spec wins on its own topic (e.g. [protocol.md](protocol.md) wins on wire format; [firmware.md](firmware.md) wins on module internals).
- Cross-references between specs **MUST** stay live; `prd.md` / `architecture.md` / `protocol.md` **MUST** be kept mutually consistent.

### §1B.2 Test-Driven Development (TDD)

- All behaviour **MUST** be developed **red → green → refactor**: author the test from the story's acceptance criteria and commit it failing (`[red]`); write the **minimum** code to pass (`[green]`); refactor while green (`[refactor]`).
- Tests **are** the acceptance criteria. A behaviour that works in a manual run but has no automated test **MUST NOT** be considered done.
- Code **MUST NOT** add capability beyond what a failing test requires (minimum viable code); speculative generality is rejected.

### §1B.3 Test categories

Each story selects the applicable categories; the protocol and firmware stories typically span several.

- **Native / unit tests** — host-side logic: PBLE/1 codec, CRC32, fragmentation/reassembly, file-transfer window/resume state machine, error→exception mapping; runs without hardware.
- **PBLE/1 protocol conformance** — frame round-trips, fragmentation across `MTU − 4` boundaries, CRC failure handling (`EVT ERROR(ECRC)`), opcode/status coverage, HELLO capability negotiation — exercised on **both** ends (Dart client in `lib/pble/` and the firmware `pyble_proto`) against an in-memory fake transport, so the two implementations agree on the wire.
- **Build sanity** — each maintained logical build target builds from the pinned
  base. The current matrix is `esp32`, `esp32-s3`,
  `waveshare-esp32-s3-lcd-147b`, and `esp32-c3` over the three ESP-IDF chip
  targets; the build **MUST** verify the submodule SHA against
  [`firmware/versions.lock`](../../firmware/versions.lock) and emit
  `firmware.bin` + `manifest.json`.
- **Resource gates** — total shipped application-image size/headroom is a
  static build/candidate gate; Python GC and internal-IDF heap floors,
  reset-to-advertising latency, transfer goodput floors, and reliability are
  candidate HIL gates. The numeric values in
  [firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target) are
  derived from real-hardware baseline samples by a method frozen before
  measurement, not asserted up front.
- **Hardware-in-the-loop (HIL)** — on every exact profile claimed by the
  release: connect, `DEVICE_INFO`, run/stop, console streaming, and a clean
  multi-file upload without dropping the link, plus resume-on-reconnect and
  the resource measurements above. The current v0.4.2 public-beta profile set
  is exactly `esp32-4mb` plus `esp32-s3-n16r8`; production-browser installation
  and interrupted-flash recovery passed, but the other formal HIL rows remain
  pending. The earlier v0.5.1 source-candidate matrix was exactly
  `esp32-4mb`, `esp32-s3-n16r8`, and
  `waveshare-esp32-s3-lcd-147b`; no exact-byte qualification was completed for
  it. The current v0.6.0 source retains those prospective public profiles,
  while C3 remains engineering-only and v1.0 additionally requires
  `esp32-c3-4mb`. The two S3 profiles require independent evidence because
  their candidate contracts produce different immutable bytes. No v0.6.0
  exact-byte qualification is asserted here. A milestone is gated by a working
  HIL demo, not by merged code alone.

### §1B.4 SDD+TDD interlock

The lockstep order for every story is fixed:

1. **Spec** — confirm or freeze the relevant `docs/specifications/` section (commit `[docs]`).
2. **Red** — translate acceptance criteria into named failing tests (commit `[red]`).
3. **Green** — write the minimum code to pass (commit `[green]`).
4. **Refactor** — clean up while green (commit `[refactor]`).
5. **Gate** — no-leak gate, locale parity, static application-image checks
   and (where relevant) runtime HIL resource checks pass before merge.

A story **MUST NOT** skip ahead: no `[red]` before the spec is frozen, no `[green]` before a failing `[red]`, no merge before the gates of §1B.5.

### §1B.5 Definition of Ready / Definition of Done

**Definition of Ready (DoR)** — a story **MUST NOT** start until:

- the spec section it depends on is **frozen** and cited as its Spec ref;
- its acceptance criteria are written as concrete, **testable** statements (MUST/SHOULD/MAY);
- its test categories (§1B.3) and target chips (if firmware) are identified.

**Definition of Done (DoD)** — a story is done only when:

- red → green → refactor is complete and all its tests pass in CI;
- the **no-leak gate** (§1A.2) passes;
- **locale parity** holds — any new user-facing string ships with at least its `en` ARB entry in the same commit, and added languages keep parity;
- applicable static **application-image** and runtime **HIL resource** gates
  pass for firmware stories;
- every commit is **signed off** (DCO) and correctly tagged (§1B.6);
- spec cross-references remain live and consistent.

### §1B.6 Commit tagging + DCO

- Commits **MUST** be prefixed with one of `[red]`, `[green]`, `[refactor]`, `[docs]`, `[build]`, `[chore]`, reflecting the actual change (per [`AGENTS.md`](../../AGENTS.md)).
- Every commit **MUST** be signed off under the Developer Certificate of Origin via `git commit -s`. CI **MUST** reject unsigned commits and **MAY** reject commits whose tag does not match the change class.

### §1B.7 Acceptance gates G0..Gn mapped to roadmap milestones M0–M4

Each milestone in the [public roadmap](../ROADMAP.md) is gated by a production
acceptance gate; a milestone is reached only when its gate is demonstrably green
on real hardware where applicable. The gates restate the milestone **exit**
criteria as pass/fail conditions.

| Gate | Milestone | Pass condition (all MUST hold) |
|---|---|---|
| **G0** | **M0 — Foundations** | Public repo is contributable (MIT `LICENSE`, `CONTRIBUTING`, CI with the no-leak grep gate live); an **empty agent builds for all three chips** (`esp32`/`-s3`/`-c3`) from the pinned base; **PBLE/1 §2 (transport) and §3 (framing) are frozen**. |
| **G1** | **M1 — Agent on classic ESP32** | From a test client on a classic **ESP32**: HELLO + `DEVICE_INFO`, `put`/`get`/`list`/`delete`, `RUN`, `STOP`, and live console are all green, including a **clean multi-file upload with CRC + resume and no link drop**. |
| **G2** | **M2 — App spine** | On **iPad and Android**: open a `.py`, **Run** it on a classic ESP32, watch the console, **Stop** a loop, and save back — through the `Connection` API with passing `lib/pble/` conformance tests. |
| **G3** | **M3 — Multi-chip + breadth** | The core edit-run-console loop passes on **esp32 / -s3 / -c3** with per-chip heap/MTU/**footprint validated (C3 first)**; file explorer, CSV plots, and Blockly—including the eight offline editable beginner examples with explicit GPIO roles and no autorun—are usable. |
| **G4** | **M4 — Public release (v1.0)** | The **esp-web-tools** flasher at `pyble.dev/flash` flashes a per-chip manifest; firmware bins are on GitHub Releases with `THIRD_PARTY_LICENSES`; the free app is submitted to the App Store and Google Play; a donation / Sponsors link and docs site are live. Anyone can flash an agent and use the free app on the initial supported ESP32-family targets. |

Gates are cumulative: a later gate **MUST NOT** be declared green if an earlier gate has regressed. Additional sub-gates (G3a per-chip, etc.) **MAY** be introduced per story without renumbering the milestone gates.

---

## §2 Product Vision

**Vision.** PyBLE lets anyone **edit, run, and manage MicroPython on a compatible Bluetooth Low Energy board — from a tablet, without an everyday cable.** Its platform scope spans microcontroller vendors and CPU families wherever MicroPython and a conforming PBLE/1 agent can run. The initial firmware targets are classic ESP32, ESP32-S3, and ESP32-C3. PyBLE is the wireless, tablet-native counterpart to desktop tools like Thonny and Mu: simple, free, open-source, and friendly to beginners, while remaining useful to experienced makers.

**Positioning.** PyBLE is a **Thonny-style wireless MicroPython IDE** for tablets. Where Thonny/Mu assume a laptop and a USB cable, PyBLE assumes an iPad or Android tablet and a BLE radio. It is not a science-lab platform, not a classroom-management product, and not tied to a silicon vendor or board product — it is a general-purpose IDE for compatible MicroPython boards, joined to the board by an open protocol anyone can implement.

**Scope versus support.** A board having MicroPython and Bluetooth hardware is
not, by itself, a compatibility claim. Current support requires a released
PyBLE agent port that can host the PBLE/1 GATT service, preserve BLE/STOP
responsiveness while user code runs, provide sufficient storage/resources, and
pass conformance plus HIL gates. See
[ADR-0021](../decisions/0021-capability-defined-board-scope.md).

**Product pillars.** The whole product reduces to four verbs, each backed by a spec:

- **Edit** — a full Python text editor and a beginner-friendly Blockly block mode that generates MicroPython; `.py` files, on the tablet and on the board ([app.md §2](app.md#2-packages--directories)).
- **Connect** — scan filtered to the PyBLE service UUID, lightweight BLE connect, MTU 247, HELLO capability negotiation; no QR, no account ([app.md §4](app.md#4-connect-flow), [protocol.md §2](protocol.md#2-ble-transport-gatt)).
- **Run** — execute a file or snippet on the board, **Stop** it instantly, and watch a live `stdout`/`stderr` console — with `STOP` authoritative even against a runaway loop ([protocol.md §6](protocol.md#6-run--stop--console)).
- **Capture** — manage the board filesystem (list/open/upload/download/rename/delete/mkdir), import a folder of `.py` from a public GitHub repo, and plot live values from CSV/streamed output ([app.md §2](app.md#2-packages--directories), [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)).

**Guiding principles** (binding on design decisions): beginner-first but not dumbed down; honest about hardware (surface real BLE/flash errors, don't hide them); open by default (open protocol, open code, open to contributions); and small and sharp (the non-goals in §4.3 are load-bearing).

---

## §3 Problem Statement

PyBLE exists because the simplest thing a learner wants to do — write a few lines of Python and run them on an accessible MicroPython board from the tablet in front of them — has no good path today. ESP32-family boards are the first implementation targets, not the endpoint.

- **MicroPython has no BLE REPL.** Upstream MicroPython provides a serial REPL and an experimental WebREPL over Wi-Fi, but **no standard Bluetooth REPL** and no standard way to edit/run/manage files over BLE. There is no off-the-shelf wire contract for "run this file and stream me the console over Bluetooth." PyBLE defines that contract as [PBLE/1](protocol.md) and implements both ends.
- **iPad cannot do USB serial, so BLE is required.** iPadOS does not expose arbitrary USB serial to third-party apps. For the first-class target — learners and classrooms on iPads — the cable-based workflow that Thonny/Mu rely on is simply unavailable. BLE is the only transport that makes the iPad a first-class citizen, which is **why PyBLE is BLE-first by design**, not by preference (§13.6).
- **Laptop and driver friction.** The desktop path carries real friction even where USB is available: installing an IDE, USB-UART drivers (CP210x/CH340), per-OS permission quirks, and finding the right cable. For a classroom or a walk-up workshop, "install drivers on every machine" is a non-starter. A zero-install, zero-account tool that "just connects" removes that barrier.
- **Wi-Fi onboarding is its own friction.** A Wi-Fi-first workflow trades the cable for SSID/password entry, AP-mode juggling, and captive-portal failures — exactly the setup pain PyBLE aims to eliminate. BLE pairs to a nearby personal board with no network configuration.

**Why BLE-first + tablet-first.** Choosing BLE as the primary and only v1 transport is what unlocks the iPad, removes drivers and network setup, and keeps the board approachable on a workbench. Choosing tablet-first (iPad + Android at parity, phones best-effort) matches where beginners and classrooms actually are. The cost — BLE's lossy, MTU-bounded link — is met head-on by designing reliable, windowed, resumable file transfer into [PBLE/1](protocol.md#5-file-transfer-the-reliability-core) from the start, which the architecture flags as the part to get right early ([architecture.md §4](architecture.md#4-data-flow-examples)).

---

## §4 Goals and Non-Goals

### §4.1 Primary goals (v1.0)

For the first production release, PyBLE **MUST** deliver the core edit-run-console loop end-to-end on real hardware:

1. **Connect over BLE** — scan filtered to the PyBLE service UUID, connect, negotiate MTU 247, and complete HELLO + `DEVICE_INFO` (chip, MicroPython version, free memory, fs root) ([protocol.md §7](protocol.md#7-hello--capabilities)).
2. **Edit `.py`** — a full Python text editor with Run/Save, plus a Blockly block mode that generates MicroPython ([app.md §2](app.md#2-packages--directories)).
3. **Run / Stop / Console** — run a file or snippet, see live `stdout`/`stderr`, and stop a runaway loop instantly, with `STOP` authoritative ([protocol.md §6](protocol.md#6-run--stop--console)).
4. **Reliable files** — `list`/`stat`/`get`/`put`/`delete`/`mkdir`/`rename`, with windowed upload, whole-file CRC verification, and **resume-on-reconnect**; a multi-file upload **MUST** complete without dropping the link ([protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)).
5. **Multi-chip parity** — the loop **MUST** pass on classic **ESP32**, **ESP32-S3**, and **ESP32-C3**, with the C3 footprint validated ([firmware.md §4](firmware.md#4-chip-targets-and-release-profiles)).
6. **Free, flashable, installable** — the agent is flashable from `pyble.dev/flash` (esp-web-tools) and GitHub Releases; the app is free on the App Store and Google Play; iPad and Android ship at feature parity.

These restate the success criteria of §21.1 in production terms.

### §4.2 Secondary goals (post-v1)

The following are planned for **v1.x / post-v1** and **SHOULD** be built on the same frozen contract without breaking it:

- **Breadth IDE features** — file explorer multi-select, CSV/streamed **live plots**, and richer Blockly coverage hardened across all three chips ([public roadmap](../ROADMAP.md)).
- **GitHub import** — pull a folder of `.py` from a public GitHub repo onto the board ([app.md §2](app.md#2-packages--directories)).
- **Saved-board UX and reliability hardening** — remembered boards, reconnect polish, and stress-tested transfers ([public roadmap](../ROADMAP.md)).
- **Additional validated MicroPython + BLE platform ports** — later ESP32
  variants and non-Espressif microcontrollers under the same PBLE/1 contract;
  each port supplies the target-specific BLE/runtime/storage/build adapter and
  passes conformance, resource, recovery, and HIL gates
  ([hardware.md §2](hardware.md#2-requirements-for-a-board-to-work-with-pyble)).
- **Desktop port with a serial transport** behind the same `Connection` API and PBLE/1 client (§13.6).
- **Application-layer pairing token** — an optional PBLE capability negotiated in HELLO, explicitly out of v1 scope ([protocol.md §10](protocol.md#10-security-note-v1)).
- **More languages** — additional ARB locales, kept at parity with `en` (translations are community-friendly from day one).

### §4.3 Explicit non-goals

The following are **permanent product boundaries, not deferrals.** They define what PyBLE is by defining what it refuses to become; they **MUST NOT** creep in, and the no-leak gate (§1A.2) and rejection list (§1A.3) enforce several of them. They are the canonical, complete list:

- **No chemistry / lab / titration / calibration features.** PyBLE is a general MicroPython IDE, not a science-lab platform. It drives no actuators, manages no calibration, and contains no hardware safety guard — those belong to the user's own code ([hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware)). *Permanent: adding a lab domain would make PyBLE a different product.*
- **No board-specific product profiles.** Compatible MicroPython + BLE platform
  ports only; no proprietary routing/pin profiles. An open agent port adapts
  runtime mechanics but does not describe or mediate the user's hardware. The
  in-app pin reference is informational, never an enforced or stored profile,
  and PyBLE never gates by MAC or board identity
  ([hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware)). An
  explicitly selected exact-board provisioning image is permitted only as a
  bounded Layer-2 dependency set; it is not a runtime product profile and MUST
  NOT cause its drivers to be bundled into a generic chip-family image
  ([ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- **No proprietary protocol.** PyBLE speaks only its clean-room [PBLE/1](protocol.md); it carries no closed-source wire format, opcodes, or UUIDs ([architecture.md §5](architecture.md#5-clean-room--ip-boundary)).
- **No USB-serial-first or Wi-Fi-first workflow.** BLE is the primary and only v1 transport; a future desktop serial transport is a community add-on behind the same client, not a shift away from BLE-first.
- **No custom MicroPython fork.** PyBLE uses upstream MicroPython plus an add-on agent; it does not fork the VM ([firmware/upstream/README.md](../../firmware/upstream/README.md)).
- **No `.mpy` in examples or transfer.** `.py` only.
- **No accounts, cloud sync, or automatic grading.** Local-first, offline-capable. *Permanent: no PyBLE feature may require a login or network round-trip to function.*
- **No paid tiers, closed modules, or telemetry-by-default.** Every file is MIT and free; sustainability is via donations / Sponsors.
- **No instructor / classroom / lab management.** No groups, leases, QR-pairing, dashboards, or distribution packages. A connected client on a personal board is the trust model ([protocol.md §10](protocol.md#10-security-note-v1)). *Permanent: PyBLE is a single-user IDE, not a managed teaching platform.*

These boundaries are load-bearing: they are what keep PyBLE small, safe to open-source, and clean-room. Relaxing any of them is a product change requiring a new ADR, not a story.

---

## §5 Target Users & Personas

PyBLE serves individuals and small groups who want to edit and run MicroPython on a compatible BLE-capable board, from a tablet, without an everyday cable or network setup. The product is deliberately narrow (see §4.3): there is **no** classroom-management, fleet-provisioning, curriculum-authoring, or administrator persona. PyBLE is a personal IDE that one person points at one board at a time, and every persona below interacts with the product through the same single app — there is no separate console or management surface.

### §5.1 Persona: The Learner

**Who.** A beginner picking up MicroPython, often on an iPad in a setting where laptops, USB drivers, and serial-port setup are unavailable or unwelcome.

**Goals.**
- Connect to a board and run a first program within minutes, with zero install and zero account.
- See errors explained in plain language rather than raw tracebacks (see §9.9).
- Build logic visually with blocks before committing to text (see §9.8).

**Frustrations PyBLE removes.** No cables on a tablet; no driver hunt; no command line; no confusing raw BLE device list (the scanner is filtered to the PyBLE service UUID — see §9.6).

**Top requirements.** §8.1 (connect), §8.2 (edit→run→console→stop), §9.3 (editor), §9.8 (blocks), §9.9 (error explanation).

### §5.2 Persona: The Educator / Workshop Runner

**Who.** Someone teaching or demonstrating MicroPython to a small group and who needs a tool that "just connects" with no provisioning step, no logins, and nothing to administer mid-session.

> Scope note: PyBLE gives this persona a dependable single-board IDE. It is **not** a classroom-management product — there is no roster, no group/device binding, no monitoring dashboard, and no remote board administration. These are explicit non-goals (see §4.3). An educator runs the same app a learner runs.

**Goals.**
- Stand up a session on any currently supported board with its matching agent
  firmware installed (the initial ESP32 targets use `pyble.dev/flash`), then
  hand the same flow to learners.
- Distribute starter code by pointing the app at a public GitHub repository (see §9.7), with no per-learner accounts.
- Recover a board from bad code quickly so a frozen program never derails a session (see §8.3).

**Top requirements.** §8.3 (bad-code recovery), §9.5 (run control), §9.7 (GitHub import), §9.10 (localization).

### §5.3 Persona: The Maker / Hobbyist

**Who.** An intermediate-to-advanced user iterating on a deployed MicroPython board — a project already installed somewhere awkward, where unplugging it to reach a provisioning or debug port is the main friction.

**Goals.**
- Tweak and re-run code on a board in place over BLE, without finding a cable.
- Manage the board filesystem directly: list, upload, download, rename, delete, mkdir, and round-trip files with verified content (see §8.4, §9.2).
- Use the board's hardware from standard MicroPython (`machine`), with the in-app pin reference as a guardrail against common footguns (see [hardware.md §3](hardware.md#3-generic-pin-reference-shown-in-app-read-only)).

**Frustrations PyBLE removes.** No teardown to re-flash a tweak; reliable file transfer over a lossy link with resume-on-reconnect (see [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)); honest surfacing of BLE/flash failures rather than silent retries.

**Top requirements.** §8.4 (file transfer/sync), §9.1 (projects), §9.2 (file explorer), §9.6 (connection manager).

---

## §6 Product Components

PyBLE is three components joined at one seam: a Flutter **app**, the board-side **agent firmware**, and the **PBLE/1** wire protocol that connects them over a BLE GATT service (see [architecture.md §1](architecture.md#1-the-three-pieces)). The seam between app and firmware is a byte stream over two GATT characteristics (RX/TX), framed by PBLE/1; everything above that seam is transport-agnostic.

### §6.1 App

A single Flutter application, tablet-first for iPadOS and Android tablets at feature parity, distributed free on the App Store and Google Play. There is exactly **one** app — no separate management or console build (contrast the personas in §5; all of them run this app).

- The app MUST be layered BLE adapter (`lib/ble/`) → PBLE/1 client (`lib/pble/`) → UI widgets, and UI widgets MUST NOT import `lib/ble/` directly. Only `lib/pble/` knows the wire format. See [app.md §1](app.md#1-layering).
- Every widget MUST bind to the `Connection` interface (or narrow callbacks derived from it), so the editor, console, files, blocks, and plots are testable against a `FakeConnection`. See [app.md §3](app.md#3-the-connection-api-the-seam-every-widget-binds-to).
- The app MUST be iPadOS-first by design: because iPadOS cannot do arbitrary USB serial, BLE is the primary and only v1 transport (see §13.6). It MUST remain usable, not broken, on a phone, but the layout is optimized for tablets.
- The app MUST be offline-first: projects, settings, and saved boards persist locally (`lib/data/`) with no account and no telemetry-by-default.

Functional requirements for the app are specified in §9; full module breakdown is in [app.md §2](app.md#2-packages--directories).

### §6.2 Agent Firmware

A protected agent port that turns a supported MicroPython + BLE board into a
PyBLE-speaking board. It is built on **upstream MicroPython as pinned source —
never a fork, never edited in place** (see
[firmware.md §1](firmware.md#1-four-layer-rule) and
[`firmware/upstream/README.md`](../../firmware/upstream/README.md)).

- The firmware MUST follow the four-layer rule: Layer 1 upstream MicroPython
  (pinned), Layer 2 per-build board overlay, Layer 3 the PyBLE agent, Layer 4
  the user workspace. A chip-family overlay stays lean; an exact-board overlay
  owns only the dependencies required by that named board image. The agent is
  the control plane and MUST NOT be editable by user code; a frozen
  `while True: pass` in user code MUST NOT be able to wedge BLE or block
  `STOP` (see [firmware.md §1](firmware.md#1-four-layer-rule),
  [firmware.md §5](firmware.md#5-runtime-rules), and
  [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- The agent is the `pyble_*` module set: `pyble_ble` (NimBLE peripheral, advertising, GATT, MTU, fragmentation), `pyble_proto` (PBLE/1 codec, CRC32, dispatch), `pyble_runner` (run/stop/soft-reboot, `RUN_STATE`), `pyble_fs` (filesystem bridge with windowed upload + resume), `pyble_console` (tee `stdout`/`stderr` to BLE), and `pyble_info` (`DEVICE_INFO`/HELLO caps). See [firmware.md §3](firmware.md#3-modules).
- The initial v1 port MUST build one shared agent core for three ESP-IDF
  targets — `esp32`, `esp32s3`, `esp32c3` — all using NimBLE, with per-chip
  differences confined to Layer 2. The pinned base is MicroPython `v1.28.0` +
  ESP-IDF `v5.5.1` per
  [`firmware/versions.lock`](../../firmware/versions.lock). Those exact lock
  bytes are candidate-frozen for v0.4.2; this is not complete hardware
  approval. The exact candidate still requires the remaining formal
  exact-profile HIL and resource gates before qualification. Future
  MicroPython ports MAY use different platform adapters while preserving the
  same agent/PBLE contract. See [firmware.md §4](firmware.md#4-chip-targets-and-release-profiles).
- The agent MUST start frozen-Python to nail PBLE/1 and reliability, then port hot paths to native C where the chip budget demands it (especially ESP32-C3); the wire contract MUST NOT change across that move. See [firmware.md §2](firmware.md#2-agent-base-native-vs-frozen).
- The Layer-3 agent and generic chip-family images MUST NOT accumulate any
  GPIO-routing, actuator-safety, display, calibration, or board-profile module.
  The dedicated `waveshare-esp32-s3-lcd-147b` Layer-2 image is the sole current
  exception: it owns its clean-room TFT runtime and factory-enabled-after-erase,
  persistently disableable cosmetic splash;
  the lean `esp32-s3-n16r8` image owns neither. Board hardware remains exposed
  to **user code** through standard MicroPython (`machine`), not through the
  agent (see [firmware.md §3](firmware.md#3-modules),
  [hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware), and
  [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- Footprint budget is provisional and MUST be measured and frozen per target on real hardware — ESP32-C3 flash overhead is the hard constraint and MUST be validated early. The numbers in [firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target) are placeholders to be pinned after hardware-in-the-loop measurement, not asserted up front.

The initial ESP32 builds emit `firmware.bin` plus a `manifest.json` for the
esp-web-tools flasher at `pyble.dev/flash`, published via GitHub Releases.
Every future port MUST publish its matching artifacts and documented
provisioning path (see
[firmware.md §6](firmware.md#6-build--distribution)).

### §6.3 PBLE/1 Protocol

The open, clean-room wire protocol that carries PyBLE's app↔board messages over a BLE GATT service. PBLE/1 is the contract both other components implement; it is authored fresh for PyBLE and reuses no closed-source wire format, opcodes, or UUIDs (see [PBLE/1](protocol.md) and [architecture.md §5](architecture.md#5-clean-room--ip-boundary)).

- The transport MUST be one primary GATT service on a PyBLE-owned 128-bit UUID base (`7079626c-…`, encoding ASCII `pybl`), with RX (app→board, Write), TX (board→app, Notify), and INFO (board→app, Read) characteristics. The board MUST advertise the Service UUID and a name beginning with `PyBLE-`; the app MUST scan filtered to the Service UUID. See [protocol.md §2](protocol.md#2-ble-transport-gatt).
- The app MUST request MTU 247; messages MUST be framed per [protocol.md §3](protocol.md#3-framing) (VER/TYPE/OPCODE/ID/LEN/PAYLOAD/CRC32) with the 1-byte fragmentation header for multi-packet messages, and a CRC failure MUST be dropped and answered with `EVT ERROR(ECRC)`.
- PBLE/1 MUST cover the full PyBLE feature set through its opcode table (HELLO, DEVICE_INFO, the FILE_* family, RUN/STOP/SOFT_REBOOT, CONSOLE_DATA/CONSOLE_INPUT, RUN_STATE) — see [protocol.md §4](protocol.md#4-opcodes). The app MUST NOT use a feature the board did not advertise in HELLO caps (see [protocol.md §7](protocol.md#7-hello--capabilities)).
- File transfer is the reliability core: windowed upload with cumulative-offset acks, full-file CRC verification, and resume-on-reconnect via `FILE_STAT`. It MUST be correct over a lossy, MTU-bounded link before higher-level features are built on it (see [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)).
- PBLE/1 MUST be versioned and capability-negotiated from day one: `VER` plus the HELLO `proto_versions[]` exchange let either side refuse or downgrade gracefully; backward-incompatible changes bump to PBLE/2, additive opcodes are gated behind capability flags, and there MUST be no silent wire-format change within version 1 (see [protocol.md §9](protocol.md#9-versioning-policy)).
- Several PBLE/1 sections are DRAFT (not frozen); each MUST be frozen before code that depends on it is written. UUID and opcode numbers are provisional until [protocol.md §2](protocol.md#2-ble-transport-gatt) and [protocol.md §4](protocol.md#4-opcodes) freeze.

---

## §7 Product Scope

Scope is delivered as phased production releases. **v1.0** is the first production release — a complete, dependable single-board IDE — not a trial or a reduced "minimum" tier. **v1.x** adds breadth on the same foundation. **post-v1** is the future product line. Every tier honors the non-goals in §4.3: no chemistry/lab features, no board-specific profiles, no proprietary protocol, no USB/Wi-Fi-first workflow, no MicroPython fork, no accounts/cloud/telemetry, no paid tiers.

### §7.1 v1.0 — First Production Release

The initial v1.0 release MUST deliver the complete wireless MicroPython IDE
loop on the three ESP32-family reference targets. This release matrix does not
limit PyBLE's broader platform scope.

**In scope for v1.0:**
1. BLE connect: scan filtered to the PyBLE service UUID, connect, MTU 247, HELLO/DEVICE_INFO, show chip, MicroPython version, and free memory (§8.1, §9.6).
2. Edit→upload→run→console→stop loop with live `stdout`/`stderr` and the ability to stop a runaway loop instantly (§8.2, §9.3, §9.4, §9.5).
3. Bad-code recovery ladder: STOP → soft reboot → cold-boot-safe (§8.3).
4. Full board filesystem operations — list/open/upload/download/rename/delete/mkdir — with verified content and size, multi-file upload without dropping the link, and resume-on-reconnect (§8.4, §9.2; [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)).
5. Project & file management with local, offline-first persistence (§9.1).
6. GitHub public-repo import over HTTPS: pull a folder of `.py` files onto the board (§9.7).
7. Blocks (Blockly→MicroPython) and live plots from CSV/streamed values (§9.8).
8. Beginner-friendly error explanation (§9.9).
9. Localization with English on day one and parity enforced for any added language (§9.10).
10. Multi-chip parity across classic **ESP32**, **ESP32-S3**, **ESP32-C3** (see [hardware.md §1](hardware.md#1-supported-chip-families-v1)).

**v1.0 release gate (MUST all pass on classic ESP32, then on ESP32-S3 and ESP32-C3):** connect and show `device_info`; write→upload→Run→see console→Stop a runaway loop; files round-trip (`put`/`get`/`list`/`delete`) with verified content and size; a multi-file upload completes reliably without dropping the connection. These mirror the criteria in §21.1. The provisional firmware footprint figures in [firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target) MUST be measured on hardware and frozen per target before the v1.0 tag.

### §7.2 v1.x — Incremental Production Releases

v1.x adds breadth on the v1.0 foundation without touching the non-goals and without a backward-incompatible protocol break (additive PBLE/1 opcodes only, gated behind HELLO capability flags per [protocol.md §9](protocol.md#9-versioning-policy)). Candidate items (each promoted to a release when specified and tested):

- Best-effort phone layout hardening beyond the tablet-first baseline.
- Richer console: search, copy, and a clearer traceback renderer linked to the error-explanation layer (§9.9).
- Richer plots: multi-series, export of captured plot data, and configurable CSV parsing (§9.8).
- File explorer enhancements: multi-select bulk operations, local↔board diff/compare before sync (§9.2).
- Additional shipped localizations beyond `en`, each meeting enforced ARB parity (§9.10).
- Expanded in-app per-chip pin references keyed by the `chip` reported in DEVICE_INFO (see [hardware.md §3](hardware.md#3-generic-pin-reference-shown-in-app-read-only)).
- Native-C agent hot paths where a chip budget requires it, behind the unchanged PBLE/1 contract (see [firmware.md §2](firmware.md#2-agent-base-native-vs-frozen)).

### §7.3 post-v1 — Future Product Line

Longer-horizon directions, explicitly outside v1.x and subject to the same non-goals. These are candidates, not commitments:

- **Validated agent ports for additional MicroPython + BLE MCU families** —
  including later ESP32 variants and non-Espressif targets — using the same
  PBLE/1 contract with a target-specific Layer-2 adapter and the same
  conformance/resource/recovery/HIL gates (see
  [hardware.md §2](hardware.md#2-requirements-for-a-board-to-work-with-pyble)).
- **A desktop port** that adds a serial transport behind the same PBLE/1 client (`lib/pble/`), keeping the wire contract unchanged (see §13.6).
- **An application-layer pairing token**, negotiated in HELLO, layered on top of the BLE link-layer baseline — intentionally out of v1 scope (see [protocol.md §10](protocol.md#10-security-note-v1)).
- **A PBLE/2 protocol revision** if and only if a backward-incompatible change is justified, following the versioning policy (see [protocol.md §9](protocol.md#9-versioning-policy)).

Out of scope across all tiers (restating §4.3): chemistry/lab/calibration
features, generalized board-specific routing profiles (the narrow ADR-0024
cosmetic companion is not one), any proprietary wire format, a USB- or
Wi-Fi-first primary workflow, a MicroPython fork, `.mpy` in examples or
transfer, accounts/cloud-sync/automatic-grading, and any paid tier, closed
module, or telemetry-by-default.

---

## §8 Core User Workflows

These are the end-to-end flows v1.0 MUST support. Each maps to PBLE/1 opcodes and to the `Connection` API in [app.md §3](app.md#3-the-connection-api-the-seam-every-widget-binds-to). There are no classroom, group, pairing-token, or experiment-capture flows — those are non-goals.

### §8.1 Connect to a PyBLE Board

1. **Scan.** The app scans with `flutter_blue_plus` **filtered to the PyBLE service UUID** and lists advertised names with RSSI — the default `PyBLE-XXXX` (the `XXXX` suffix derives from the board's BLE MAC), or the user-set **device label** when one is configured, since the label replaces the advertised name and so distinguishes boards pre-connect. The app MUST NOT present a raw, unfiltered BLE device list (see [app.md §4](app.md#4-connect-flow) and §9.6).
2. **Identify before connect (optional).** A read of the INFO characteristic returns the same payload as a `DEVICE_INFO` response (now including `device_id` and `label`), so the app MAY show chip, MicroPython version, and label before subscribing (see [protocol.md §2](protocol.md#2-ble-transport-gatt)).
3. **Connect.** The app opens GATT, subscribes to TX notify, requests MTU 247, and exchanges HELLO/DEVICE_INFO, then displays `DeviceInfo` (chip, MicroPython version, free memory, fs root). The app MUST NOT use any feature the board did not advertise in HELLO caps.
4. **Use.** The editor, console, and file explorer bind to the live `Connection`.
5. **Rename / Identify (optional, screenless).** Because many supported boards
   are screenless, the app MAY help disambiguate boards once connected: it MAY
   set a persisted **device label** (`SET_LABEL`) — which becomes the advertised
   name and `DEVICE_INFO.label` — and, **only when HELLO caps report
   `has_identify`**, MAY offer an **Identify** action (`IDENTIFY`) that briefly
   blinks the board's single optional status LED. Setting an empty label clears
   it back to `PyBLE-XXXX`. The app MUST warn the user that a label is broadcast
   and MUST NOT contain personal data (see §14.2).
6. **Reconnect.** On link loss the app MUST auto-reattempt and reconnect saved boards by remembered identifier; any in-flight file transfer MUST resume per [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core).

Pairing is **screenless**: there is no QR pairing, pairing code,
lease/heartbeat, or board-identity gate — just scan, connect, use (see
[app.md §3](app.md#3-the-connection-api-the-seam-every-widget-binds-to)).
The optional exact-board QR in ADR-0024 is only an app-download URL displayed
after BLE is ready; it carries no pairing or board-identity data.

### §8.2 Edit → Upload → Run → Console → Stop

1. **Edit** a `.py` file in the editor (§9.3), or generate one from blocks (§9.8).
2. **Upload** the file to the board with `putFile` (`FILE_PUT_*`), using windowed chunks with CRC verification (see [architecture.md §4](architecture.md#4-data-flow-examples)).
3. **Run** it with `runFile(path)` (or `runSource` for a snippet) → `RUN { mode: file|source }` → `RSP` then `RUN_STATE(running)` (see [protocol.md §6](protocol.md#6-run--stop--console)).
4. **Console.** `stdout`/`stderr` stream back as `CONSOLE_DATA` events into the console panel (§9.4); the console is observe-anywhere regardless of which client triggered the run. A program blocked on `input()` MUST be feedable via `sendInput` (`CONSOLE_INPUT`).
5. **Completion / error.** Normal completion → `RUN_STATE(done)`; an uncaught exception → `CONSOLE_DATA(stderr, traceback)` then `RUN_STATE(error)`, which the error-explanation layer (§9.9) MAY annotate.
6. **Stop.** **Stop** issues `stop()` → `STOP`, which raises `KeyboardInterrupt` in the runner, ensures clean teardown, and returns `RUN_STATE(idle)`. STOP MUST always land even while user code runs, because the BLE/agent task is independent of the runner task (see [firmware.md §5](firmware.md#5-runtime-rules)).

### §8.3 Bad-Code Recovery: STOP → Soft Reboot → Cold-Boot Safe

A three-rung ladder, escalating only as needed. There is no "hard reset" or "safe mode" management surface — recovery is local and physical at the top rung.

1. **STOP (cooperative interrupt).** `stop()` → `STOP` raises `KeyboardInterrupt` in the runner and tears down cleanly → `RUN_STATE(idle)`. Because the runner executes user code on its own task while the BLE/agent task keeps servicing the link, STOP MUST land even against a tight loop (see [firmware.md §5](firmware.md#5-runtime-rules)). This rung handles the common runaway-loop case.
2. **Soft reboot (VM reset).** If STOP is not enough, `softReboot()` → `SOFT_REBOOT` soft-resets the MicroPython VM, clearing interpreter state without dropping the BLE link where possible (see [protocol.md §4](protocol.md#4-opcodes) and §9.5).
3. **Cold boot (power cycle) is always safe.** If the board is wedged beyond BLE reach, a physical power cycle MUST recover it: on cold boot the board advertises and waits and MUST NOT auto-run user `main.py` unless explicitly enabled via a HELLO/`DEVICE_INFO` capability flag. A bad `main.py` therefore cannot lock the user out of the board (see [firmware.md §5](firmware.md#5-runtime-rules)). After reconnecting (§8.1), the user can fix or replace the offending file (§8.4).

The app MUST surface real BLE/run failures honestly at each rung rather than hiding them (see §2).

### §8.4 File Transfer / Sync

1. **Browse.** `listDir(path)` (`FILE_LIST`) populates the board file explorer (§9.2).
2. **Round-trip.** `putFile` / `getFile` (`FILE_PUT_*` / `FILE_GET_*`) upload and download with full-file CRC verification; uploads use temp-write-then-rename on the board so a file is never corrupted mid-transfer (see [firmware.md §5](firmware.md#5-runtime-rules)). A transfer is reported `OK` only after a full-file CRC match.
3. **Manage.** `delete`, `mkdir`, and `rename` (`FILE_DELETE`/`MKDIR`/`FILE_RENAME`) MUST be supported.
4. **Reliable multi-file upload.** A multi-file upload MUST complete without dropping the connection; uploads use a sliding window of up to `W` unacknowledged chunks (`W` advertised in HELLO; the current reference agent advertises 8, while a conservative missing-cap compatibility fallback is 4) with cumulative-offset acks and gap retransmission (see [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)).
5. **Resume on reconnect.** On a dropped link the app MUST issue `FILE_STAT { path }`, learn the verified partial size, and resume `FILE_PUT_BEGIN`/`FILE_GET_BEGIN` from that offset.

This is plain board file management and project sync — there is no experiment-data capture, calibration record, or notebook flow (those are non-goals).

---

## §9 Functional Requirements: App

These requirements specify app behavior and become story acceptance criteria. They reference the app architecture rather than restating it; every requirement binds to the `Connection` interface and MUST be testable against a `FakeConnection` (see [app.md §3](app.md#3-the-connection-api-the-seam-every-widget-binds-to) and [app.md §7](app.md#7-testing)). Module homes are in [app.md §2](app.md#2-packages--directories). The app's detailed, individually-traceable requirements and engineering design are derived from this section into [App/specs.md](App/specs.md) and [App/TDD.md](App/TDD.md) (Technical Design Document).

### §9.1 Project & File Management

- The app MUST let a user create, open, and duplicate local projects, and MUST persist projects, settings, and saved boards locally and offline-first (`lib/data/`).
- A project MUST be usable with no account and no network connection.
- The app MUST associate a project with a saved board identifier so it reconnects without re-scanning (see §8.1), and MUST NOT require any class/group/device binding.
- The app SHOULD support exporting and importing a project as a local archive for backup or hand-off; it MUST NOT require a cloud service to do so.

### §9.2 Workspace File Explorer

- The explorer MUST display the board filesystem from `listDir` (`FILE_LIST`) rooted at the `fs_root` reported in DEVICE_INFO.
- It MUST support open, upload (`putFile`), download (`getFile`), rename (`rename`), delete (`delete`), and mkdir (`mkdir`), each surfacing PBLE/1 status codes (e.g. `ENOENT`, `ENOSPC`, `EACCES`) as actionable messages (see [protocol.md §8](protocol.md#8-status--error-codes-1-byte-status-in-rsp)).
- Uploads and downloads MUST report progress and MUST be reported successful only on full-file CRC match (see §8.4).
- The explorer SHOULD support multi-select for bulk operations and SHOULD distinguish the user workspace (`/main.py`, `/lib/*.py`, `/data/*`) from the agent control plane, which it MUST NOT expose as editable (see [firmware.md §1](firmware.md#1-four-layer-rule)).
- Transfers MUST be `.py`/data files only; the app MUST NOT produce or transfer `.mpy` (non-goal, see §4.3).

### §9.3 MicroPython Code Editor

- The editor MUST provide Python/MicroPython syntax highlighting, line numbers, and auto-indentation (`flutter_code_editor`).
- It MUST offer Save and Run actions and support multiple open files via tabs.
- It MUST provide find (and SHOULD provide find/replace), and SHOULD support an external keyboard with common shortcuts (Save, Run, Stop, comment/uncomment, find).
- Touch targets MUST be tablet-friendly; the editor MUST remain usable on a phone without layout breakage.
- The editor MUST bind only to the `Connection` API for board actions and MUST NOT import `lib/ble/` (see [app.md §1](app.md#1-layering)).

### §9.4 Console Panel

- The console MUST render the live `console` stream (`CONSOLE_DATA`) and MUST visually distinguish `stdout`, `stderr`, and `system` streams.
- It MUST render Python tracebacks legibly and MUST reflect run state from `RUN_STATE` (idle/running/done/error) and connection state.
- It MUST support feeding `stdin` via `sendInput` (`CONSOLE_INPUT`) for programs blocked on `input()`.
- It MUST display output regardless of which client triggered the run (observe-anywhere, see [protocol.md §6](protocol.md#6-run--stop--console)).
- It SHOULD support copying console text and clearing the view.

### §9.5 Run Control (Run / Stop / Soft-Reboot)

- The app MUST expose **Run** (`runFile` / `runSource`), **Stop** (`stop`), and **Soft-Reboot** (`softReboot`) — and only these board-control verbs; there is no app-level hard-reset or safe-mode command (recovery beyond soft-reboot is a physical power cycle, see §8.3).
- **Stop** MUST interrupt a running program promptly even under a tight loop, and MUST return the board to `idle` (see [firmware.md §5](firmware.md#5-runtime-rules)).
- The app MUST reflect the run lifecycle from `RUN_STATE` events and MUST disable Run while a program is already running (surfacing `EBUSY` if the board reports it).
- Run actions MUST be driven by the `Connection` API so they are exercisable against a `FakeConnection`.

### §9.6 BLE Connection Manager

- The scanner MUST be filtered to the PyBLE service UUID and MUST present advertised names with RSSI — the default `PyBLE-XXXX` or the user-set **device label** when one is configured, since the label replaces the advertised name and so shows in the scan list; it MUST NOT present a raw, unfiltered BLE device list (see [app.md §4](app.md#4-connect-flow)).
- It MUST request MTU 247, subscribe to TX notify, and complete HELLO/DEVICE_INFO before enabling editor/console/file actions.
- It MAY let the user **rename** the connected board by setting a persisted device label (`SET_LABEL`; empty clears back to `PyBLE-XXXX`), and MAY offer an **Identify** action (`IDENTIFY`, which blinks the board's single optional status LED) **only when HELLO caps report `has_identify`**. The label is broadcast, so the app MUST warn against personal data (see §14.2); neither action is board-identity gating.
- It MUST auto-reconnect on link loss, reconnect saved boards by remembered identifier, and resume in-flight file transfers (see §8.1, §8.4).
- It MUST show connection diagnostics (state, signal/RSSI, MTU, negotiated caps) and surface BLE permission and adapter-off conditions with actionable guidance (iOS `NSBluetoothAlwaysUsageDescription`; Android `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` and older-version location handling, see [app.md §5](app.md#5-platform-notes)).
- It MUST stop scanning before connecting and MUST NOT implement any lease/heartbeat or board-identity gating.

### §9.7 GitHub Public-Repo Import (HTTPS)

- The app MUST import a folder of `.py` files from a **public** GitHub repository over HTTPS and write them to the board via `Connection.putFile` (`lib/github_import/`).
- Import MUST require no GitHub account, token, or authentication, and the app MUST NOT support Git push in v1.0.
- The app MUST let the user select a subfolder/branch to import and SHOULD preview the file list before writing, warning on conflicts with existing board files.
- Imported files MUST be stored locally so work continues offline after import; the local project remains the source of truth (the import is a project source, not the storage model).
- Import MUST be `.py`/data only and MUST NOT fetch or write `.mpy`.

### §9.8 Blocks & Plots

- The app MUST provide a Blockly block editor (WebView, `lib/blocks/`) that generates MicroPython and MUST allow running or saving the generated code through the `Connection` API.
- Generated code MUST be inspectable as plain `.py` and MUST flow through the same upload/run path as the text editor (§8.2).
- The Blocks GPIO category MUST compose a generic `machine.Pin` constructor
  with digital write/read blocks. GPIO number, `IN`/`OUT`, pull
  (`NONE`/`UP`/`DOWN`), and output level (`LOW`/`HIGH`) are explicit program
  choices; generated code MUST own one `from machine import Pin` import and use
  standard `Pin(...).value(...)` calls. It MUST NOT contain a board pin map,
  named onboard component, routing profile, or claimed default/safe GPIO;
  physical validity remains the connected board's MicroPython responsibility.
- A **Time** category MUST provide an explicit non-negative integral
  millisecond delay block that generates standard `time.sleep_ms` use with one
  import and no raw-code or board-control escape hatch.
- A **NeoPixel** category MUST expose composable construction, RGB colour,
  indexed buffer assignment, fill, and explicit write blocks over the standard
  MicroPython `neopixel.NeoPixel` API. Pin and pixel count are explicit program
  values, generated imports are deterministic, buffer mutation MUST NOT imply a
  write, and neither app nor firmware may choose an onboard LED or GPIO.
- A **TFT Display** category MUST expose exactly eight composable operations:
  construct, RGB565 colour, fill, pixel, outline/filled rectangle, text,
  explicit show, and explicit Boolean backlight. It MUST generate the frozen
  `pyble_st7789` API with separate use-dependent `ST7789`/`rgb565` imports and
  the exact positional constructor
  `ST7789(spi_id, baudrate, polarity, phase, sck, mosi, cs, dc, reset,
  backlight, width, height, x_offset, y_offset, bgr, inversion)`. All values and
  six `Pin` objects are explicit, with no shadow/default, board detection, pin
  map, implicit show, or implicit backlight-on.
- The app MUST bundle an offline beginner library containing **Hello PyBLE,
  Count repeatedly, Blink an LED, Blink a NeoPixel, Read a button, Button
  controls LED, Reusable function, and ESP32-S3-LCD-1.47B TFT display** as
  editable ordinary Blockly workspaces. It MUST generate the displayed Python
  with the production generator rather than store a second source
  representation. The eighth example's six GPIO roles MUST be disconnected;
  its explicit non-pin values MUST show SPI ID 1, 40 MHz, mode 0, 172 × 320,
  offsets 34/0, BGR, and inversion. Localized guidance may state the exact
  B-board wiring but MUST warn that the non-B board differs and MUST NOT
  materialize those GPIOs or gate the example by the connected device.
- Example Preview MUST be non-mutating; creating an editable copy over an empty
  workspace MUST be explicit; replacing any non-empty/incomplete workspace MUST
  require confirmation and preserve the prior workspace until the replacement
  is acknowledged. GPIO examples MUST require user-entered pin roles before
  preview/copy, require distinct numeric GPIOs for separate roles with a
  localized duplicate error, and contain no supplied, remembered, named-board,
  or claimed-safe GPIO. Browsing/loading MUST never automatically Run, Save,
  write a board file, or replace the text-editor document; loaded success MUST
  wait for the active host's acknowledged candidate snapshot.
- The same localized, accessible chooser MUST be reachable from the empty
  workspace, the persistent Blocks action strip, and an Examples toolbox
  category. At constrained widths the action strip MUST use a labelled
  accessible overflow rather than horizontal scrolling, and the chooser MUST use
  a compact bottom sheet below 600 dp and a dialog at wider widths. Loaded copies
  MUST use the normal revision, restore, rotation, and persistence/recovery path.
  Hardware examples MUST include generic wiring notes and direct users to verify
  pins and voltage against their own board.
- Convert Python to Blocks MUST remain offline and all-or-nothing. Its bounded
  subset MUST additionally accept only the exact unaliased, use-dependent
  `pyble_st7789` imports; exact positional 16-argument constructor; `rgb565`;
  fill/pixel/rect/fill_rect/text/show/backlight calls on a definitely bound
  display; and the same six explicit `Pin` values. Any alias, keyword argument,
  wrong order/arity, unsupported display call, invalid configuration, or
  uncertain receiver binding MUST reject the complete conversion with no
  partial workspace or raw-code escape.
- The app MUST provide live plots (`fl_chart`, `lib/plots/`) over CSV/streamed values printed by the running program to the console stream.
- Plotting MUST be derived purely from program output (no special data-event opcode is required); the app SHOULD let the user configure how console output is parsed into series.
- The block bridge and plots MUST bind to `Connection`/`ConsoleEvent` neutral
  types and carry no board-specific profile, copied catalog/curriculum,
  domain-specific lesson flow, or proprietary/classroom pedagogy. The eight
  bounded onboarding workspaces are fresh PyBLE content under
  [ADR-0016](../decisions/0016-offline-beginner-blockly-examples.md) and
  [ADR-0018](../decisions/0018-standard-micropython-neopixel.md), with the
  manually selected named-board fixture bounded by
  [ADR-0023](../decisions/0023-explicit-st7789-user-runtime.md) (see
  [app.md §6](app.md#6-reuse-provenance-clean-room-note)).

### §9.9 Beginner-Friendly Error Explanation

- The app MUST detect common MicroPython errors from the `stderr` traceback stream and present a plain-language explanation alongside the raw traceback.
- The explanation layer MUST NOT replace or hide the original traceback — it annotates it (honest about hardware/errors, see §2).
- It MUST cover at least common beginner cases (e.g. `NameError` for a missing `from machine import …`, `IndentationError`, `ImportError` for a module absent from `/lib`, `OSError: ENOENT`, `MemoryError`) with a one-line suggested fix each.
- Mappings MUST be localizable (see §9.10) and MUST be data-driven so new mappings can be added without code changes.

### §9.10 Localization

- The app MUST ship English (`en`) ARB strings from day one, and any user-facing string added in a commit MUST ship its `en` entry in the same commit (`lib/localization/`, `intl`/ARB).
- Any additional shipped language MUST meet enforced ARB key parity with `en`; a CI/test check MUST fail on missing or orphaned keys (see [app.md §7](app.md#7-testing)).
- All user-facing strings — including error explanations (§9.9), connection diagnostics (§9.6), and file-operation messages (§9.2) — MUST be sourced from ARB, with no hard-coded display text.
- The app SHOULD respect the platform locale by default and MAY let the user override the language in settings.

---

## §10 Functional Requirements: Agent Firmware

The PyBLE agent is board-side firmware that turns a supported MicroPython + BLE
target into a PyBLE-speaking device: it advertises the BLE service, accepts
[PBLE/1](protocol.md) commands, runs and stops MicroPython, and bridges the
filesystem and console. It is built on **upstream MicroPython** (pinned source),
not a fork. The concrete requirements below govern the initial ESP32 v1 port;
future MCU families implement the same portable agent/PBLE contract behind
their own target adapter and must pass equivalent gates. This section elevates
[firmware.md](firmware.md) to testable production requirements; it references
the deep spec and does not restate module internals or wire formats. The
firmware's detailed, individually-traceable requirements and engineering design
are derived from this section into [firmware/specs.md](firmware/specs.md) and
[firmware/TDD.md](firmware/TDD.md) (Technical Design Document).

### §10.1 Initial v1 reference targets (esp32 / esp32-s3 / esp32-c3)

v1.0 MUST ship one initial ESP32-port agent core that builds for all three chip
families below, with chip facts taken from
[hardware.md §1](hardware.md#1-supported-chip-families-v1) and
[firmware.md §4](firmware.md#4-chip-targets-and-release-profiles). Within this port, per-chip
differences are confined to the Layer 2 board overlay (see §10.2); future
cross-port differences belong behind the broader target-adapter boundary.

| PyBLE target | IDF target | Cores | RAM (typical) | BLE | Role in v1.0 |
|---|---|---|---|---|---|
| `esp32` | `esp32` | 2 (Xtensa) | ~520 KB SRAM | NimBLE | Conservative baseline; tightest heap. |
| `esp32-s3` | `esp32s3` | 2 (Xtensa) | ~512 KB SRAM (+PSRAM common) | NimBLE | Most headroom; native USB. |
| `esp32-c3` | `esp32c3` | 1 (RISC-V) | ~400 KB SRAM | NimBLE | Smallest footprint — the hard constraint (see §10.13). |

Requirements:

- The firmware MUST use **NimBLE** on all three targets.
- A board MUST have flash large enough for MicroPython plus the PyBLE agent; **4 MB is the comfortable reference** (see [hardware.md §2](hardware.md#2-requirements-for-a-board-to-work-with-pyble)).
- The ESP32-C3 MUST be validated on real hardware early; it is the footprint gate that the other two targets are not.
- v1.0 success on a given target means the §21.1 criteria pass on that chip: connect + `DEVICE_INFO`, write/upload/run/observe/stop, file round-trip with verification, and a reliable multi-file upload without dropping the link. v1.0 MUST pass these on `esp32` first, then `esp32-s3` and `esp32-c3`.
- All targets beyond the initial three — including later ESP32 variants and
  other MicroPython + BLE MCU families — are **post-v1 ports** under the same
  protocol and are NOT a v1.0 requirement. Another ESP32 target may need only a
  board overlay; another MicroPython port may need a complete Layer-2 adapter.

### §10.2 Firmware architecture (the four-layer rule)

The firmware MUST follow the four-layer separation defined in [firmware.md §1](firmware.md#1-four-layer-rule):

1. **Layer 1 — Upstream MicroPython** (ESP32 port): a pinned submodule that MUST NOT be edited in place (see §10.9, §10.10).
2. **Layer 2 — Board overlay**: per-build config (pins, flash size, USB and only
   explicitly required board dependencies), copied into the upstream
   `ports/esp32/boards/` tree at build prep so the submodule stays pristine.
   `esp32-s3-n16r8` is the lean generic S3 overlay;
   `waveshare-esp32-s3-lcd-147b` is a distinct exact-board overlay on the same
   `esp32s3` IDF target ([ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
3. **Layer 3 — PyBLE agent**: the protected modules (§10.3) that own BLE, the runner, and the filesystem bridge. This is the **control plane**.
4. **Layer 4 — User workspace**: the user's own `.py` files (§10.4); never the control plane.

Non-negotiable control-plane requirements:

- The agent (Layer 3) MUST NOT be editable or replaceable by user code (Layer 4).
- A wedged user program (e.g. `while True: pass`) MUST NOT be able to block BLE servicing or prevent `STOP` from landing (see §10.6, §13.3).
- v1.0 MAY implement the agent as **frozen-Python modules** baked into the firmware; hot paths (BLE I/O, framing, file chunking) MAY later be ported to a native `USER_C_MODULE` for throughput/RAM headroom. The PBLE/1 wire contract MUST NOT change across that migration ([firmware.md §2](firmware.md#2-agent-base-native-vs-frozen)).

### §10.3 Agent modules (pyble_ble / pyble_proto / pyble_runner / pyble_fs / pyble_console / pyble_info)

The agent MUST be organized as the six modules defined in [firmware.md §3](firmware.md#3-modules), each owning one responsibility:

| Module | Responsibility (requirements altitude) |
|---|---|
| `pyble_ble` | NimBLE peripheral: advertising (`PyBLE-XXXX`), the GATT service (RX/TX/INFO), MTU, and fragmentation. |
| `pyble_proto` | PBLE/1 frame encode/decode, CRC32, request/response correlation, and dispatch. |
| `pyble_runner` | Run a file or inline source on a separate task; capture `stdout`/`stderr`; implement `STOP` (KeyboardInterrupt) and `SOFT_REBOOT`; emit `RUN_STATE`. |
| `pyble_fs` | Filesystem bridge: list/stat/get/put/delete/mkdir/rename with windowed upload, CRC, and resume. |
| `pyble_console` | Tee `stdout`/`stderr` to BLE as console events (and to USB-serial if present, for local debugging only). |
| `pyble_info` | Assemble `DEVICE_INFO`/HELLO capabilities: chip, MicroPython version, free memory, fs root, MTU, SD presence. |

Hard exclusions (restating the non-goals): the Layer-3 agent MUST NOT contain
GPIO-routing, actuator-safety, display/branding, calibration, or board-profile
logic. A generic chip-family image MUST NOT collect board drivers. The only
current display carve-out is the dedicated exact-board Layer-2 image in
[ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md);
it does not change PBLE/1 or mediate user hardware. PyBLE otherwise exposes the
board's hardware to **user code** via standard MicroPython (`machine`), not via
the agent (see §11.3).

### §10.4 User workspace jail (/main.py, /lib/*.py, /data/*, project.json; forbidden paths; NO .mpy/.pyc)

The user workspace is Layer 4 and MUST be the only filesystem region the app reads and writes through PBLE/1 file commands.

- The agent MUST expose a writable workspace root reported as `fs_root` in `DEVICE_INFO`/HELLO. The conventional workspace shape is `/main.py`, `/lib/*.py`, `/data/*`, and an optional `/project.json` manifest.
- File operations MUST be confined to the workspace root. The agent MUST reject any path that escapes the root (e.g. `..` traversal, absolute paths outside the root, or paths targeting the agent's own protected modules) with `EACCES` (see [PBLE/1 §8](protocol.md#8-status--error-codes-1-byte-status-in-rsp)).
- The agent's control-plane code (Layer 3) and the board overlay (Layer 2) MUST NOT be writable via PBLE/1 file commands. They are forbidden paths.
- Uploads MUST use temp-write-then-rename so a file is never corrupted mid-transfer ([firmware.md §5](firmware.md#5-runtime-rules)).
- The workspace is **`.py` only**. The agent MUST NOT require, generate, or depend on `.mpy`/`.pyc` artifacts in the workspace (see §10.14).
- User code MAY itself touch the filesystem normally at runtime; the jail constrains the **PBLE/1 file bridge**, not the MicroPython runtime's own `os`/`vfs` access.

### §10.5 Boot flow + cold-boot safety (advertise and wait)

Cold boot MUST be safe so a bad `main.py` can never lock a user out of the board ([firmware.md §5](firmware.md#5-runtime-rules)):

- On power-up the agent MUST initialize, start BLE advertising, and **wait for a connection**. It MUST NOT auto-run the user's `main.py` by default.
- Auto-run MUST be **opt-in only**, gated behind an explicit capability flag surfaced in `DEVICE_INFO`/HELLO. When disabled (the default), the board boots into agent mode (§10.6) regardless of workspace contents.
- The agent MUST reach the advertising state independently of user-workspace validity; a syntactically broken or infinite-loop `main.py` MUST NOT prevent advertising or connection.
- After connect, HELLO MUST be the first exchange (version + capability negotiation) per [PBLE/1 §7](protocol.md#7-hello--capabilities).

### §10.6 Execution modes (agent mode; run mode)

The agent MUST operate in two observable modes, reflected in `RUN_STATE`:

- **Agent mode (idle):** advertising and/or connected, servicing PBLE/1 (file, info, console-input) commands, with no user program executing. `RUN_STATE` reports `idle`.
- **Run mode:** a user program (file or inline source) is executing on the **runner task** while the BLE/agent task continues to service the link. `RUN_STATE` reports `running`, then `done` on normal completion or `error` on an uncaught exception.

Requirements:

- The runner MUST execute user code on a task separate from the BLE/agent task so that `STOP` always lands and the link stays responsive ([firmware.md §5](firmware.md#5-runtime-rules)).
- Only one user program MUST run at a time; a `RUN` issued while running MUST be answered with `EBUSY`.
- Mode transitions MUST be emitted as `RUN_STATE` events so the app can drive UI state without polling (see [PBLE/1 §6](protocol.md#6-run--stop--console)).

### §10.7 BLE GATT service (RX / TX / INFO characteristics; MTU up to 247)

The agent MUST expose exactly one primary GATT service using the PyBLE-owned 128-bit UUID base, with UUID and transport facts taken from [PBLE/1 §2](protocol.md#2-ble-transport-gatt):

| Role | Properties (required) |
|---|---|
| **Service** | Primary service on the PyBLE-owned UUID base (`7079626c-…`, encoding ASCII `pybl`). |
| **RX** (app → board) | Write, Write-Without-Response. |
| **TX** (board → app) | Notify. |
| **INFO** (board → app) | Read; returns the same payload as a `DEVICE_INFO` response. |

- The board MUST advertise the Service UUID and, by default, a name beginning with the `PyBLE-` prefix followed by a short MAC-derived device suffix (e.g. `PyBLE-9F3A`), so the app can scan **filtered to the Service UUID** rather than a raw device list. When a device label is set (`SET_LABEL`), the label MUST replace the advertised name so it shows pre-connect; an empty label MUST restore the default `PyBLE-XXXX`.
- The agent MUST treat the device **label**, the single optional **identify-LED** configuration (`SET_IDENTIFY_LED`), and **IDENTIFY** as control commands under the v1 connected-client trust model (see §14.1, [protocol.md §10](protocol.md#10-security-note-v1)). The board MUST bound the persisted label length; `IDENTIFY` MUST return `EUNSUPPORTED` when no identify LED is configured. These are per-device agent configuration only — never exposed to user code, never a routing/pin profile, and never used to gate access (see §11.3).
- The agent MUST accept an MTU request of **247** and MUST handle the negotiated MTU correctly down to the BLE default; usable per-packet payload is `MTU − 3` (ATT) minus the 1-byte fragmentation header.
- The agent MUST implement PBLE/1 fragmentation/reassembly over RX/TX and MUST validate the per-message CRC32, dropping and reporting (`EVT ERROR(ECRC)`) any frame that fails.
- A read of INFO MUST let a client identify a board before subscribing to TX.

### §10.8 PBLE/1 v1.0 command set

v1.0 firmware MUST implement the full PBLE/1 opcode set defined in [PBLE/1 §4](protocol.md#4-opcodes) — none are optional in v1.0. At requirements altitude (the wire format is owned by the protocol spec, not restated here), the required commands are:

- **Session / identity:** `HELLO`, `DEVICE_INFO`.
- **Filesystem:** `FILE_LIST`, `FILE_STAT`, `FILE_GET_BEGIN` / `FILE_GET_DATA` / `FILE_GET_END`, `FILE_PUT_BEGIN` / `FILE_PUT_DATA` / `FILE_PUT_END`, `FILE_DELETE`, `MKDIR`, `FILE_RENAME`, with `FILE_PUT_ACK` for windowed, resumable transfer.
- **Execution:** `RUN` (file or inline source), `STOP`, `SOFT_REBOOT`.
- **Console:** `CONSOLE_DATA` (stdout/stderr stream), `CONSOLE_INPUT` (feed `stdin`), `RUN_STATE` (state transitions).

Conformance requirements:

- The agent MUST return the correct PBLE/1 status code ([PBLE/1 §8](protocol.md#8-status--error-codes-1-byte-status-in-rsp)) for every command, including the error cases (`ENOENT`, `EACCES`, `ENOSPC`, `EBUSY`, `ECRC`, `ERANGE`, `EUNSUPPORTED`, etc.).
- File transfer MUST implement the windowed-upload + CRC + resume model and download streaming + whole-file CRC verification from [PBLE/1 §5](protocol.md#5-file-transfer-the-reliability-core). A transfer MUST be reported `OK` only after a full-file CRC match.
- The console MUST be **observe-anywhere**: `stdout`/`stderr` MUST stream regardless of which client triggered the run.
- The agent MUST advertise its capabilities in HELLO (`chip`, `mpy_version`, `fs_root`, `max_file_size`, `put_window`, `chunk_size`, `has_sd`, `free_mem`) and MUST reject use of any feature it did not advertise.

### §10.9 Version pinning

Firmware reproducibility MUST be enforced by the version-pin file [`firmware/versions.lock`](../../firmware/versions.lock), with the rationale in [`firmware/upstream/README.md`](../../firmware/upstream/README.md) and [firmware.md §6](firmware.md#6-build--distribution):

Pin selection and pin approval are separate lifecycle states:

- **Proposed** pins may still change while the firmware base is evaluated.
- **Candidate-frozen** pins are the exact committed `versions.lock` bytes
  selected as immutable inputs to one release candidate. They MUST be
  candidate-frozen before the two clean release builds, license audit,
  candidate packaging, protected-site staging, or HIL. Candidate-freezing is
  not a claim of hardware compatibility and is not public-release approval.
- The candidate's pins become approved for public release only when that exact
  hash-locked candidate passes the required HIL on every exact release
  profile. Any upstream pin change creates a new source state and candidate and
  requires the build, audit, deployment, and complete HIL matrix to restart.

- `versions.lock` is the **single source of truth** for the pinned upstream MicroPython tag + commit and the ESP-IDF version + commit. MicroPython `v1.28.0` and ESP-IDF `v5.5.1` are candidate-frozen for v0.4.2; a future release selects its own exact committed lock state.
- One MicroPython + ESP-IDF pin MUST drive all three chip targets; per-chip differences live in the board overlays, not in the lock.
- The build MUST refuse to proceed if the checked-out upstream submodule SHA does not match the SHA recorded in `versions.lock` (**SHA-drift gate**).
- Upgrades MUST go through the controlled workflow (`firmware/scripts/upgrade_micropython.sh`), never by hand-editing during a build. ESP-IDF MUST be installed from the pin into a gitignored directory (it is not an outer submodule); `mpy-cross` MUST be rebuilt from the pinned MicroPython.

### §10.10 Patch policy

The default MUST be **zero** upstream patches.

- Upstream MicroPython MUST NEVER be edited in place.
- Any genuinely unavoidable upstream change MUST be isolated as a patch under `firmware/patches/micropython-<tag>/`, carry a written reason, and apply only at build prep ([firmware.md §6](firmware.md#6-build--distribution)).
- Each patch MUST be re-reviewed for retirement at every upstream upgrade.
- PyBLE-specific code MUST live outside the submodule tree: the agent in `pyble_*` modules (Layer 3) and per-chip config in the board overlays (Layer 2).

### §10.11 Logical build targets

- `firmware/scripts/build.sh <target>` MUST build exactly one maintained logical
  target (`esp32` | `esp32-s3` | `waveshare-esp32-s3-lcd-147b` |
  `esp32-c3`); `build_all.sh` MUST build all four logical targets
  ([firmware.md §6](firmware.md#6-build--distribution)).
- All targets MUST build from the **single** MicroPython + ESP-IDF pin in `versions.lock`; the build MUST NOT silently substitute a different toolchain version.
- The build MUST map each PyBLE target name to its IDF target
  (`esp32`→`esp32`, `esp32-s3`→`esp32s3`,
  `waveshare-esp32-s3-lcd-147b`→`esp32s3`,
  `esp32-c3`→`esp32c3`) and apply the matching independent board overlay before
  invoking the port build. The generic S3 build MUST exclude the Waveshare
  display driver, board companion, splash assets, and splash-only native seam;
  only the exact-board target MAY include them
  ([ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- Builds MUST be reproducible from a clean checkout given the pinned versions (see §13.1).

### §10.12 Build artifacts & manifest

Each successful per-target build MUST emit a flashable artifact set ([firmware.md §6](firmware.md#6-build--distribution)):

- `firmware.bin` plus the bootloader and partition table for that chip.
- A `manifest.json` compatible with **esp-web-tools**, so users can flash from a browser at `pyble.dev/flash` with no local toolchain.
- Artifacts MUST be published at the canonical immutable
  `pyble.dev/firmware/v<version>/` path, versioned to a local annotated release
  tag and matched to the `versions.lock` pin used to build them. A v0.x mirror
  is optional and MUST be byte-identical if published; v1.0 and later
  additionally require the matching GitHub Release.
- A qualified pre-v1 release MAY publish only the exact profiles for which the
  maintainer owns matching hardware and has completed the full hash-locked HIL
  matrix. The narrowly digest-bound v0.4.2 exception in
  [browser-flashing §10](firmware/browser-flashing.md#10-activation-and-rollback)
  MAY instead expose its two exact images only as a hardware-tested beta after
  their supplemental production-browser installation and recovery run passes;
  it MUST say that complete qualification remains pending.
- An unqualified profile MUST be absent from release metadata, artifacts,
  selection, and recovery commands and shown as unavailable, never silently
  marked supported. The immutable v0.4.2 public-beta set remains exactly
  `esp32-4mb` plus `esp32-s3-n16r8` and MUST NOT be expanded.
- The current v0.6.0 source's prospective public set is exactly `esp32-4mb`,
  `esp32-s3-n16r8`, and `waveshare-esp32-s3-lcd-147b`, in that order. The
  earlier v0.5.1 candidate did not complete qualification;
  `esp32-c3-4mb` remains unavailable pending exact-profile
  real-hardware validation. Re-enabling it requires a new SemVer candidate and
  immutable bundle.
- The flasher manifest MUST select the correct artifact per released profile.
  The two S3 selections MUST reference different immutable bytes and require
  separate explicit compatibility consent. v1.0 MUST retain the three v0.5
  profiles and add `esp32-c3-4mb`, preserving parity across all three chips.

### §10.13 Resource and performance thresholds as REQUIREMENTS

[firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target) retains
the immutable v0.4.2 two-profile history; C3 remains provisional. The current
v0.6.0 source requires a controlled three-profile refresh using the
detailed method, exact workload, metric meanings, rounding formulas, and
evidence contract in
[firmware/specs.md §5.3](firmware/specs.md#53-footprint-gates-nfr-fp).

| Gate | Metric and direction | v0.6.0 prospective public profiles | ESP32-C3 / v1.0 |
|---|---|---|---|
| **FP-FLASH** | Total shipped application-image ceiling plus factory-partition headroom floor | Derive and freeze independently for all three profiles | Remains open for `esp32-c3-4mb`; C3 is the hard constraint |
| **FP-HEAP** | Python GC and internal-IDF current/largest/minimum heap floors after HELLO and transfer workloads | Derive and freeze all three profile floors; default-capability `free_mem` is diagnostic only | Must leave usable user-code and control-plane headroom |
| **FP-BOOT** | Controlled reset-release → first fresh service-advertisement ceiling, plus physical power-cycle pass | Apply the fixed SLO and verify all three profiles | Required before C3 enablement and v1.0 |
| **FP-TPUT** | Committed PUT and verified GET goodput floors at observed ATT MTU 247, plus exact reliability counts | Derive and freeze all three profile floors | Must remain usable and reliable on the binding target |

Requirements:

- The immutable v0.4.2 public-beta set is exactly the two profiles in §10.12.
  Its bounded exception does not satisfy or waive the remaining qualification
  gates. The current v0.6.0 source's prospective public set is exactly the
  three profiles in
  §10.12; fresh numeric policy and hash-locked final-candidate HIL are
  release-blocking for every one of them.
  Earlier v0.5.1 evidence cannot qualify it. `esp32-c3-4mb` MUST remain absent
  from a three-profile release's policy, HIL rows,
  artifacts, recovery, and installer selection.
- The split changes both S3 binaries. Pre-split v0.5 baseline, threshold,
  candidate, and HIL evidence MUST NOT qualify either new S3 image. A fresh
  source-bound baseline, independently derived threshold row, reproducible
  candidate, browser-install/recovery pass, physical power-cycle pass, and full
  HIL record are required for each of all three prospective profiles; one S3 board or
  binary MUST NOT stand in for the other.
- **ESP32-C3 remains the binding v1.0 constraint.** Its source target continues
  to build and participate in reproducibility and license audits. If its later
  exact-profile HIL does not meet flash/heap requirements with usable
  headroom, the design MUST change (for example native `USER_C_MODULE` hot
  paths per §10.2), not the constraint.
- The application-image ceiling/headroom floor MUST be enforced by automated
  build/candidate validation. Runtime heap, boot, goodput, and reliability
  thresholds MUST be evaluated from machine-readable final-candidate HIL.
- Thresholds MUST follow only the predeclared, metric-specific contracts in
  firmware/specs.md §5.3. Static build quantities remain exact; heap keeps its
  baseline-derived outward quantum; reset detection uses the fixed 3,000 ms
  end-to-end product SLO; and goodput receives the exact integer 5%
  baseline-derived repeatability allowance before outward quantization. A
  candidate result MUST NOT be used to fit, trim, or relax any threshold.
- A controlled refresh MUST retain earlier evidence, replace all three current
  profile threshold sets together, and rebuild and reverify the final
  candidate. Engineering-baseline observations do not qualify that candidate.
- A v0.5 qualification of all three current profiles closes only that release
  subset. The open C3 portion remains release-blocking for any C3 enablement
  and for v1.0; “to be measured on hardware” is not permission to claim C3.

### §10.14 .mpy / .pyc policy

- The user workspace and any future PyBLE package format MUST be **`.py` source only**. The firmware MUST NOT require `.mpy`/`.pyc` in the workspace, and the app MUST NOT transfer them (see §4.3 and [AGENTS.md](../../AGENTS.md)).
- Examples and imported content (see §12.1 `github_imports`) MUST be `.py`.
- This is independent of MicroPython's internal freezing of the **agent's own** modules into firmware (Layer 3), which is a build concern, not a workspace artifact.

---

## §11 Hardware Requirements

PyBLE's platform scope covers compatible microcontroller boards that can run
MicroPython and host a conforming PBLE/1 BLE peripheral agent. The initial v1
support matrix is the three ESP32-family targets below. Hardware eligibility
does not mean an image exists: actual support requires a released, validated
agent port. PyBLE makes no assumptions about wiring. The board-side hardware
contract is owned by [hardware.md](hardware.md); this section states it as
requirements.

### §11.1 Supported chip families & specs

v1.0 MUST support the three chip families in [hardware.md §1](hardware.md#1-supported-chip-families-v1):

| Family | IDF target | Cores | RAM (typical) | BLE | Notes |
|---|---|---|---|---|---|
| Classic **ESP32** | `esp32` | 2 (Xtensa) | ~520 KB SRAM | NimBLE | Conservative baseline; tightest heap. |
| **ESP32-S3** | `esp32s3` | 2 (Xtensa) | ~512 KB SRAM (+PSRAM common) | NimBLE | Most headroom; native USB. |
| **ESP32-C3** | `esp32c3` | 1 (RISC-V) | ~400 KB SRAM | NimBLE | Smallest footprint — the constraint to validate early (see §10.13). |

- A board is supported only when its board/firmware combination passes the
  published build, compatibility, recovery, resource, and HIL matrix. No
  user-authored routing profile is required.
- PyBLE MUST NOT gate by MAC address or board identity; any matching chip running the agent is acceptable ([hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware)).

### §11.2 What a board needs to work

A target MUST meet the requirements from
[hardware.md §2](hardware.md#2-requirements-for-a-board-to-work-with-pyble):

1. A maintained upstream MicroPython port.
2. A BLE peripheral/GATT stack able to host and advertise PBLE/1.
3. Sufficient flash/RAM plus filesystem/config storage for the protected agent
   and usable user-code headroom.
4. A runtime mechanism that preserves BLE and authoritative `STOP`
   responsiveness while user code runs.
5. A validated target adapter, versioned agent firmware, and documented
   provisioning path.

For the initial ESP32 v1 port, boards use the three families in §11.1, a
comfortable **4 MB** flash reference (with §10.13 governing the actual floor),
and USB provisioning through the **web flasher at `pyble.dev/flash`**
(esp-web-tools, §10.12) or a self-build. Another port may use its platform's
validated one-time provisioning method. USB is NOT a runtime transport: PyBLE
remains BLE-first, so iPadOS — which cannot do arbitrary USB serial — is a
first-class runtime platform (see §13.6). No specific GPIO wiring is required.

### §11.3 Ordinary hardware exposed through standard MicroPython `machine` — no generalized profiles/routing

Restating the non-goal from [hardware.md §4](hardware.md#4-what-pyble-does-not-do-with-hardware):

- The board's ordinary hardware MUST be exposed to user code **only** through
  standard MicroPython (`machine`, `os`, etc.). The agent MUST NOT mediate or
  abstract GPIO for user programs.
- PyBLE MUST NOT impose, store, or transmit a generalized board routing/pin
  profile. The agent MAY persist a **device label** and a **single optional
  identify-LED GPIO** as its own per-device UX configuration. ADR-0024 also
  permits the dedicated `waveshare-esp32-s3-lcd-147b` image alone to contain an
  exact-board Layer-2 companion with the
  Waveshare ESP32-S3-LCD-1.47B's published display wiring solely for a bounded
  cosmetic boot frame after BLE readiness. The frame is factory-enabled after
  erase only in this exact profile and remains persistently disableable. These
  exceptions are not user-code routing/capability maps, never detect/select a
  board, and never gate access by MAC or label. The generic
  `esp32-s3-n16r8` image MUST contain none of that display/splash machinery
  (see §10.7, §14.2 and
  [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- PyBLE MUST NOT drive actuators, manage calibration, or contain any hardware safety guard; those belong to the user's own code and project (see §13.3 for the distinction from generic software safety).
- The app MAY surface a **read-only, informational** per-target pin reference
  (keyed by the opaque `chip` identifier reported in `DEVICE_INFO`) to warn
  beginners about footguns such as flash-connected, input-only, or strapping
  pins ([hardware.md §3](hardware.md#3-generic-pin-reference-shown-in-app-read-only)).
  These are warnings only and MUST NOT be enforced restrictions on user code.
  An unknown target MUST fall back to generic board-documentation guidance and
  MUST NOT block connection.

---

## §12 Data Model

The app is **offline-first**: all persistent state lives on the tablet (`lib/data/`, see [app.md §2](app.md#2-packages--directories)). There is **no** server, no account, and no cloud store in v1.0.

### §12.1 Local database tables

The local database MUST model the following tables and no others related to user content. Each table MUST support offline create/read/update/delete with no network dependency.

| Table | Purpose | Key fields (illustrative; frozen during the data-layer story) |
|---|---|---|
| `projects` | A user's PyBLE project (a named bundle of files). | `id`, `name`, `description`, `created_at`, `updated_at`, `last_opened_at` |
| `project_files` | The `.py`/data files in a project, mirroring the workspace shape (`/main.py`, `/lib/*.py`, `/data/*`, `project.json`). | `id`, `project_id` (FK), `path`, `content` (or blob), `size`, `content_hash`, `updated_at` |
| `code_snapshots` | Point-in-time versions of project files for local history/restore. | `id`, `project_id` (FK), `path`, `content`, `label`, `trigger` (manual/pre-run), `created_at` |
| `run_sessions` | A single run on a board (from `RUN` to `RUN_STATE` terminal). | `id`, `project_id` (FK), `board_ref`, `chip`, `entry` (file/source), `started_at`, `ended_at`, `final_state` (idle/done/error) |
| `console_logs` | Captured `stdout`/`stderr`/system output for a run session. | `id`, `run_session_id` (FK), `seq`, `timestamp`, `stream` (stdout/stderr/system), `text` |
| `github_imports` | Provenance of a folder of `.py` pulled from a public GitHub repo (see [app.md §2](app.md#2-packages--directories), `lib/github_import/`). | `id`, `project_id` (FK), `repo_url`, `ref`, `subpath`, `commit_sha`, `file_count`, `imported_at` |

Requirements and exclusions:

- The data model MUST NOT contain tables for managed device fleets, multi-user grouping, lab/experiment datasets, or hardware calibration. Concretely: **no** `classes`, `groups`, `boards` (as a managed-fleet/profile table), `experiment_data`, or `calibration` tables. These concepts are explicit non-goals (see §4.3).
- Saved-board **reconnect** (remembering the last-used board identifier for auto-reconnect, per [app.md §4](app.md#4-connect-flow)) MUST be stored as a lightweight app setting / `board_ref` value, NOT as a relational board-profile or fleet table.
- `project_files` and `github_imports` MUST hold `.py` (and plain data) only — never `.mpy`/`.pyc` (see §10.14).
- Console capture MUST be local; v1.0 MUST NOT transmit console logs off-device.

---

## §13 Non-Functional Requirements

### §13.1 Reliability

- The app MUST automatically attempt to reconnect on BLE link loss, and in-flight file transfers MUST resume from the verified offset via [PBLE/1 §5](protocol.md#5-file-transfer-the-reliability-core) — never silently corrupt or duplicate data.
- A transfer MUST be reported successful only after a whole-file CRC match; partial transfers MUST be resumable, not restarted-from-zero by default.
- The agent (control plane) MUST stay alive and BLE-responsive even when user code crashes, loops, or exhausts its own resources (see §13.3); a control-plane fault MUST fail safe to the advertising state (see §10.5).
- On disconnect, the app MUST preserve the user's work locally (open editor buffers, project files, run/console state) so nothing is lost across a dropped link (see §12.1).
- Firmware builds MUST be **reproducible** from the pinned versions (see §10.9–§10.11): the same commit + `versions.lock` MUST yield equivalent artifacts.

### §13.2 Usability

- The UI MUST be **tablet-first** (iPad + Android tablet), with a responsive split layout (editor / console / files) that MUST NOT break on a phone (best-effort) ([app.md §5](app.md#5-platform-notes)).
- Connect MUST present **named PyBLE boards** (advertised `PyBLE-XXXX` + RSSI) filtered to the PyBLE service UUID; the app MUST NOT show users a raw, unfiltered BLE device list ([app.md §4](app.md#4-connect-flow)).
- Interactive controls MUST use large touch targets and clearly communicate connection and run state (disconnected / connecting / ready / running / error).
- Errors MUST be surfaced honestly and in beginner-readable form (BLE failures, flash/`ENOSPC`, run tracebacks), mapping PBLE/1 status codes to clear messages rather than hiding failures (§2).

### §13.3 Safety (generic software safety, not actuator safety)

This is software-level safety of the IDE/agent, NOT hardware/actuator safety (which is out of scope, see §11.3).

- Cold boot MUST be safe: the board MUST advertise and wait, and MUST NOT auto-run user `main.py` unless explicitly enabled (see §10.5).
- `STOP` MUST be **authoritative**: it MUST promptly interrupt the runner (KeyboardInterrupt), tear down cleanly, and report `RUN_STATE` ([PBLE/1 §6](protocol.md#6-run--stop--console)).
- User code MUST NOT be able to wedge BLE or the agent: the runner runs on a task separate from the BLE/agent task so the link and `STOP` remain serviceable under any user-code behavior (see §10.2, §10.6).
- The agent MUST NOT contain or imply any actuator, relay, motor, or other physical-safety guard; physical safety belongs to the user's own program.

### §13.4 Performance

- The app MUST request MTU **247** and the agent MUST support it; throughput MUST be **usable for file transfer** at that MTU on every supported chip, with the C3 figure validated and frozen per §10.13.
- File transfer MUST use windowed chunks (`W` from HELLO; current reference
  agent `W=8`, conservative missing-cap compatibility fallback `W=4`; chunk
  sized to one MTU) with cumulative-offset ACKs and per-chunk/whole-file CRC
  for reliability over a lossy link
  ([PBLE/1 §5](protocol.md#5-file-transfer-the-reliability-core)).
- Interactive console latency (keystroke/`CONSOLE_INPUT` → echo, and `stdout` → display) MUST stay low enough to feel live; concrete latency/throughput ceilings MUST be measured on HIL and frozen alongside §10.13.

### §13.5 Offline-first

- Projects, files, snapshots, run sessions, and console logs MUST be fully usable with **no internet connection** (see §12.1).
- The only network-dependent feature is `github_imports` (pulling public `.py` from GitHub); its absence MUST NOT block any other workflow.
- v1.0 MUST NOT require an account, cloud sync, or any server to edit, run, or manage code on a board (§15.1).

### §13.6 Platform compatibility

- **iPadOS and Android tablet MUST ship at feature parity at every milestone** — neither platform may lag the other for a released capability.
- BLE permissions MUST be handled per platform (iOS `NSBluetoothAlwaysUsageDescription`; Android 12+ `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT`, with location handling on older Android) ([app.md §5](app.md#5-platform-notes)).
- The app MUST NOT depend on USB serial or Wi-Fi onboarding as a runtime path; BLE is the only v1.0 transport.

### §13.7 Accessibility & Localization

- English (`en`) MUST ship day-one; any new UI string MUST land with its `en` ARB entry in the same change.
- Any added locale MUST reach **full string parity** before release; partial translations MUST NOT ship as a shipped locale (translation parity is enforced).
- Technical identifiers (chip names `esp32`/`esp32-s3`/`esp32-c3`, paths, opcode/capability names, PBLE/1 status names) MUST remain ASCII and MUST NOT be localized.
- The app SHOULD support large-font and high-contrast modes and keyboard navigation (external keyboards are common on tablets), so editor/console/files remain operable for accessibility users.

---

## §14 Security & Privacy Requirements

### §14.1 v1.0 model

- v1.0 MUST use **BLE link-layer pairing/encryption** as the baseline, matching the "personal board on a workbench" model ([PBLE/1 §10](protocol.md#10-security-note-v1)).
- v1.0 MUST NOT add application-layer authentication; a connected client is trusted at the application layer.
- The agent MUST enforce a **single active writer per connection**: only one user program runs at a time (`EBUSY` otherwise, see §10.6), and file/run operations are serialized so concurrent writers cannot corrupt workspace state.
- The agent MUST keep its control plane non-writable by user code (see §10.4), so "trusted client" never extends to overwriting the agent itself.

### §14.2 Privacy

- v1.0 MUST have **no accounts** and **no telemetry by default** (§15.1).
- The BLE advertisement MUST carry only the PyBLE service UUID and a short device name. The default name (the MAC-derived `PyBLE-XXXX` suffix) is non-PII. A user-set **device label** replaces that name and is therefore broadcast, so the app MUST warn the user against entering personal or user-identifying information and the board MUST bound the label length; the advertisement MUST NOT otherwise include personal data ([PBLE/1 §2](protocol.md#2-ble-transport-gatt)).
- All user content (projects, files, snapshots, run/console logs) MUST stay on-device unless the user explicitly exports it; nothing is transmitted off-device by default (see §13.5).
- PyBLE MUST NOT gate access by board identity or MAC, and MUST NOT build a remote registry of users or boards (see §11.1). The `device_id` (MAC-derived suffix) and label are for recognition and display only and MUST NOT be used for authorization.

### §14.3 Post-v1 security evolution

- An optional **application-layer pairing token / auth** is a candidate for a future release. It is **deferred and undecided** for v1.0.
- If added, it MUST be negotiated through HELLO capabilities so older clients keep working, and it MUST be additive (no backward-incompatible wire change within PBLE/1; a breaking change would bump to PBLE/2 per [PBLE/1 §9](protocol.md#9-versioning-policy)).
- Until that decision is made, no partial or implicit application-layer auth may ship; the v1.0 model in §14.1 is the committed baseline.

---

## §15 Open-Source Posture, License & Distribution

PyBLE is, by design, the inverse of a closed-source product: every shippable artifact is permissively licensed, the source is public, and external contribution is a first-class goal. This posture is load-bearing — it is what makes the project trustworthy for a tool that flashes firmware onto users' boards and runs their code, and it is enforced mechanically (see the no-leak gate referenced in §16.3 and the clean-room boundary in [architecture.md §5](architecture.md#5-clean-room--ip-boundary)).

### §15.1 Open-source policy

- The entire project — Flutter app (`app/`), agent firmware (`firmware/`), shared PBLE/1 bindings (`protocol/`), examples, tooling, and tests — MUST be released under the **MIT License**. Per [ADR-0003](../decisions/0003-license-mit.md), there is no open-core split, no paywalled feature, no closed module, and no telemetry-by-default.
- Every source file MUST carry an MIT SPDX header (`SPDX-License-Identifier: MIT`). CI SHOULD reject any added source file lacking one.
- The canonical repository MUST be a **public GitHub repository**. v1.0 ships with `LICENSE` (MIT), `README.md`, `CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md` at the repo root (the only files allowed there per §16.3).
- External contributions (issues and pull requests) MUST be welcome. Every commit MUST be **DCO-signed** (`git commit -s`); CI MUST reject unsigned commits. Contribution mechanics, commit-tag convention (`[red]`/`[green]`/`[refactor]`/`[docs]`/`[build]`/`[chore]`), and the SDD+TDD method are documented in `CONTRIBUTING.md` and [AGENTS.md](../../AGENTS.md).
- A **Code of Conduct** MUST be published and enforced for all project spaces.
- Re-used prior art the author owns (board-agnostic widgets — editor, console, file explorer, plots, Blockly bridge, GitHub import, tablet scaffold, localization) MUST be **relicensed MIT at copy time** with the header replaced; no proprietary protocol client, board profiles, UUIDs, or pedagogy is carried across (see [app.md §6](app.md#6-reuse-provenance-clean-room-note) and [ADR-0002](../decisions/0002-fresh-protocol.md)).
- Attribution MAY be given as "a SciLabPro open-source project" in `README`/About for brand credit only; the project is **not** hosted under any commercial domain (see [ADR-0005](../decisions/0005-standalone-domain.md)). PyBLE's canonical web home is `pyble.dev`.

### §15.2 Upstream license compliance

MIT licensing of PyBLE's own code does **not** discharge the obligations of its upstream dependencies. The build MUST preserve and ship the required notices for everything it links or bundles.

- The firmware build MUST emit a `THIRD_PARTY_LICENSES` artifact alongside each `firmware.bin` (see [firmware.md §6](firmware.md#6-build--distribution)).
- The app MUST present an in-app **Open-Source Notices** screen on **both iPadOS and Android**, surfacing the full upstream notice set (Flutter's generated license page is acceptable as the Dart/Flutter portion, augmented with the firmware and native notices).
- All bundled third-party components MUST remain MIT/Apache-2.0/BSD-compatible; a dependency under an incompatible license MUST NOT be added (see §17.2).

| Component | Where it ships | License | Obligation |
|---|---|---|---|
| MicroPython (ESP32 port) | firmware | MIT | Ship copyright + permission notice with `firmware.bin` and in the app notices screen. |
| ESP-IDF | firmware (build base) | Apache-2.0 | Ship attribution + `NOTICE`. |
| NimBLE (ESP-IDF BLE host) | firmware | Apache-2.0 | Ship Apache-2.0 attribution. |
| LittleFS / VFS (if linked) | firmware | BSD-3-Clause | Preserve copyright notice. |
| Flutter / Dart SDK | app | BSD-3-Clause | Flutter-generated license page. |
| `flutter_blue_plus` | app | BSD-3-Clause | Include in the notices screen. |
| `flutter_code_editor`, `fl_chart`, Drift, `intl` | app | MIT/BSD (per package) | Include in the auto-generated notices set. |
| Blockly (WebView asset) | app | Apache-2.0 | Ship Apache-2.0 attribution. |
| esp-web-tools | web flasher (`pyble.dev/flash`) | Apache-2.0 | Attribution on the flasher page. |

Exact per-package licenses MUST be generated mechanically at build time (not hand-maintained) so the shipped notice set is always complete and current; the table above is the minimum it MUST cover.

### §15.3 Distribution

- The app MUST be distributed **free** on the **Apple App Store** and **Google Play**, at feature parity across iPadOS and Android tablets (see §13.6 and §19). No account, no paywall, no in-app purchase.
- A browser-based **web flasher** MUST be hosted at `pyble.dev/flash`, built on **esp-web-tools**, with one profile-scoped, single-build manifest per exact profile included in that release (see [firmware.md §6](firmware.md#6-build--distribution)). It MUST allow a user to flash the agent from a supported desktop browser over USB without installing a toolchain, and MUST NOT give ESP Web Tools a multi-family manifest that could override the user's selected profile. The immutable v0.4.2 hardware-tested beta contains the two exact profiles in §10.12; complete release qualification remains pending. The earlier v0.5.1 source candidate completed no exact-byte qualification. Current v0.6.0 source authorizes no public bytes until every included profile qualifies. C3 is unavailable until separately qualified.
- Firmware binaries (`firmware.bin`, bootloader, partition table, profile-scoped
  `manifest.json` files, and `THIRD_PARTY_LICENSES`) MUST be published at the
  canonical immutable `pyble.dev/firmware/v<version>/` path, one set per exact
  listed profile and truthful release state. A v0.x mirror is optional and MUST
  be byte-identical if present; v1.0 and later additionally require the
  matching GitHub Release. Any pre-qualification publication MUST be an
  explicitly permitted beta, never described as qualified.
- Self-build from source MUST remain fully supported (`firmware/scripts/build.sh <target>`, `build_all.sh`) so no user depends on the hosted flasher.
- Sustainability is via **donations / GitHub Sponsors**, not sales ([ADR-0003](../decisions/0003-license-mit.md)); a Sponsors link MAY appear in `README`/About but MUST NOT gate any functionality.

---

## §16 Technical Architecture

This section is a production-level summary; the deep design wins on its own topic. See [architecture.md](architecture.md) for the three-piece system view, [app.md](app.md) for the Flutter layering, and [firmware.md](firmware.md) for the agent. The seam between app and board is a byte stream over two GATT characteristics (RX/TX), framed by **[PBLE/1](protocol.md)**; everything above that seam is transport-agnostic.

### §16.1 App stack

The app is a single Flutter package targeting iPad and Android tablets (see [app.md §2](app.md#2-packages--directories)).

- **Framework / language:** Flutter + Dart, one codebase for both platforms.
- **Layering (strict):** UI widgets → `lib/pble/` (PBLE/1 client, `Connection` API) → `lib/ble/` (`flutter_blue_plus` wrapper) → radio. **UI widgets MUST NOT import `lib/ble/`**, and only `lib/pble/` knows the wire format (see [app.md §1](app.md#1-layering)). This keeps the editor/console/files testable against a `FakeConnection`.
- **State management:** a single declarative state-management approach (e.g. Riverpod or Bloc) MUST be chosen and applied consistently across the app; the choice is recorded as an ADR before broad adoption.
- **BLE:** `flutter_blue_plus` — scan filtered to the PyBLE service UUID, connect, MTU **247**, byte-stream in/out, reconnect (see [app.md §4](app.md#4-connect-flow)).
- **Code editor:** `flutter_code_editor` (Python mode). The widget's tablet-keyboard maturity is a tracked risk (§23); a WebView-hosted editor is the documented fallback.
- **Blocks:** Blockly in a WebView, generating inspectable MicroPython
  (a board-neutral subset with no board-specific defaults or pin catalog).
  The current numeric-`machine.Pin`, NeoPixel, and explicit `pyble_st7789` TFT
  blocks are initially validated on ESP32-family firmware; they are not a claim
  that all MicroPython ports use the same pin identifier or ship either optional
  library.
- **Charts:** `fl_chart` over CSV/streamed values from the running program.
- **Persistence:** **Drift** (SQLite) for projects, settings, and saved boards — offline-first (see [app.md §2](app.md#2-packages--directories), `lib/data/`).
- **Localization:** `intl` + ARB. New user-facing strings MUST ship with at least `en` in the same commit; translation parity MUST be enforced in CI.

### §16.2 Firmware stack

The agent turns a supported MicroPython + BLE target into a PyBLE-speaking
board, built on **upstream MicroPython — never a fork** (see
[firmware.md §1](firmware.md#1-four-layer-rule)). The concrete stack below is
the initial ESP32 v1 port, not a cross-vendor implementation mandate.

- **Four-layer rule (strict separation):** Layer 1 upstream MicroPython (pinned
  source, never edited in place) → Layer 2 target adapter / board overlay
  (per logical build, including separate lean generic-S3 and exact Waveshare
  S3 overlays) → Layer 3 PyBLE agent (the
  control plane) → Layer 4 user workspace (`/main.py`, `/lib`, `/data`). User
  code MUST NOT be able to wedge BLE or block `STOP`.
- **Build base:** ESP-IDF toolchain (xtensa-esp for `esp32`/`-s3`, riscv32-esp for `-c3`), `mpy-cross` rebuilt from the pinned MicroPython.
- **BLE host:** **NimBLE** (Bluedroid not built), one host across all three chips.
- **Agent modules (Layer 3):** `pyble_ble`, `pyble_proto`, `pyble_runner`, `pyble_fs`, `pyble_console`, `pyble_info` (see [firmware.md §3](firmware.md#3-modules)). There is no GPIO-routing, board-profile, calibration, actuator, or display module in the agent. The exact-board TFT runtime and cosmetic splash are Layer-2 dependencies of `waveshare-esp32-s3-lcd-147b` only; hardware is otherwise exposed to user code via standard MicroPython `machine`, not via the agent ([ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).
- **Integration mechanism:** `USER_C_MODULES` for native hot paths. v1.0 starts as a **frozen-Python agent** to nail PBLE/1 and reliability, then ports hot paths (BLE I/O, framing, file chunking) to C where the chip budget demands it — most acutely on ESP32-C3. The wire contract is unchanged across that move.
- **Filesystem:** MicroPython VFS / LittleFS-style workspace; uploads use temp-write-then-rename to avoid mid-transfer corruption.
- **Protocol:** **[PBLE/1](protocol.md)** — framed messages with CRC-32, fragmentation over GATT, windowed file transfer with resume.

### §16.3 Repository structure

The repository MUST follow the GOLDEN RULE layout (see [CLAUDE.md](../../CLAUDE.md) and [AGENTS.md](../../AGENTS.md)). Only the whitelisted root files and directories are permitted; anything else lives inside a subdirectory, and scratch/local notes are gitignored, never committed at root.

```text
PyBLE/
├── README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  AGENTS.md  CLAUDE.md  .gitignore  (+ .gitmodules)
├── docs/
│   ├── specifications/   prd.md · product.md · architecture.md · protocol.md · firmware.md · app.md · hardware.md
│   ├── developments/     roadmap.md · stories.md
│   └── decisions/        NNNN-*.md  (ADRs)
├── app/                  Flutter app (one package, iPad + Android)
├── firmware/             upstream MicroPython submodule + pyble_* agent; board overlays esp32/-s3/-c3; scripts; versions.lock
├── protocol/             shared PBLE/1 bindings (Dart + C), generated/hand-written codecs (pble_*)
├── tools/                web-flasher manifests, provisioning, helpers
├── examples/             example MicroPython scripts (.py only)
└── tests/                host-side firmware tests, protocol conformance, app/integration runners
```

- The repo root MUST contain only the listed files plus the listed directories (plus tool-managed `.git/`, `.github/`, `.claude/`).
- A CI **no-leak gate** MUST reject any forbidden proprietary identifier in shippable source (`app/ firmware/ protocol/ examples/ tests/ tools/`, scanning `.dart`/`.c`/`.h`/`.py`); governance docs that define the rule are exempt. The canonical command is in [AGENTS.md](../../AGENTS.md). A push containing a fixture token MUST fail; a clean tree MUST pass.
- Upstream MicroPython is a clean submodule under `firmware/upstream/`; it MUST NOT be edited in place. Any unavoidable patch is isolated under `firmware/patches/micropython-<tag>/` with a written reason — default zero patches.

---

## §17 Dependency Governance

PyBLE depends on third-party code at two layers (firmware upstream and Flutter packages). Both MUST be pinned, reviewed, and upgraded only through a controlled path, so a build is reproducible and a supply-chain or footprint regression cannot land silently.

### §17.1 Upstream pins

- The single source of truth for upstream firmware versions is [`firmware/versions.lock`](../../firmware/versions.lock). It pins **MicroPython `v1.28.0`** (commit `e0e9fbb17ed6fd06bb76e266ae554784c9c80804`) and **ESP-IDF `v5.5.1`** (commit `fcae32885b0296b32044cb99ecbdc50d98dddb83`). One MicroPython + ESP-IDF pair drives all three chip targets; per-chip differences live only in the board overlays. These exact values are candidate-frozen for v0.4.2 under §10.9; later candidates must deliberately select their own committed lock state.
- Before release-candidate builds or HIL, the exact committed lock file MUST be
  **candidate-frozen**. This makes the selected input immutable; it does not
  approve the pins. Public-release approval still requires the same candidate
  to pass HIL on every exact profile included in that release. The current
  v0.6.0 source's prospective public set is the three profiles in §10.12; v1.0 retains them and adds the
  binding ESP32-C3 footprint profile (§10.13, §21.2). A pin change
  abandons that candidate and all evidence bound to it.
  The immutable v0.4.2 formal history remains its two-profile matrix and MUST
  NOT be reinterpreted as approval of the current candidate.
- A **SHA gate** MUST run in the build: the build prep verifies the checked-out submodule SHA against `versions.lock` and **refuses to proceed on mismatch**. CI MUST run this gate on every PR.
- ESP-IDF is **not** a submodule; it is installed from the pinned version into a gitignored directory by the build scripts. MicroPython's own `lib/` dependencies are fetched by the standard port build (`make … submodules`).
- Upgrades MUST go only through the **controlled upgrade workflow** (`firmware/scripts/upgrade_micropython.sh`) — never edited by hand during a build. An upgrade MUST: bump `versions.lock` (ref + resolved SHA) in its own commit; rebuild `mpy-cross`; pass the full host + protocol-conformance suite; pass the applicable per-profile resource gates (§10.13); candidate-freeze the updated lock before release-candidate generation; and validate that exact candidate on every profile included in the release. All three profiles are mandatory for v1.0. The default patch count against upstream is **zero**; any patch is re-reviewed for retirement at every upgrade.

### §17.2 App dependencies

- The app's dependencies are governed by `pubspec.yaml`. Each non-trivial dependency MUST have an **approved entry** (rationale, license, minimum version) recorded — a new dependency requires review before it lands, mirroring the firmware discipline.
- Every app dependency MUST be MIT/Apache-2.0/BSD-compatible (§15.2). A package under an incompatible or unknown license MUST NOT be added.
- Dependencies MUST be pinned to a **minimum version** with a reproducible lockfile (`pubspec.lock`) committed. CI MUST build against the locked versions.
- Native/transitive code that ships in the binary MUST be reflected in the generated `THIRD_PARTY_LICENSES`/notices set (§15.2).
- Dependency count SHOULD be kept small and sharp; prefer a smaller, well-maintained package over a heavy one, consistent with the project's "small and sharp" principle (§2).

### §17.3 Update cadence / end-of-life strategy

- Security-relevant updates to any dependency SHOULD be evaluated promptly; routine updates SHOULD be batched on a regular cadence (e.g. per minor release) rather than ad hoc.
- The project SHOULD track upstream MicroPython and ESP-IDF release lines and plan a controlled upgrade before its pinned line reaches end-of-life, so PyBLE is never stranded on an unsupported base.
- An upgrade MUST NOT be approved for a public candidate on the strength of CI
  alone: it requires the §17.1 HIL pass on every exact profile included in that
  release. The three v0.5 profiles plus `esp32-c3-4mb` remain mandatory for
  v1.0.
- When a dependency is abandoned upstream, the project MUST either vendor it under MIT/Apache/BSD terms (with the source pinned and recorded) or replace it; an unmaintained dependency MUST NOT be left as a silent liability.

---

## §18 Release & Versioning

### §18.1 Versioning scheme

- The **app** and the **firmware agent** each follow **SemVer** (`MAJOR.MINOR.PATCH`). v1.0 is the first production release; v1.x adds compatible features; a breaking change bumps MAJOR.
- The **wire protocol** is versioned independently as **PBLE/1**. Per [protocol.md §9](protocol.md#9-versioning-policy): a backward-incompatible wire change bumps the protocol to **PBLE/2**; **additive** changes (new opcodes/fields) MUST be gated behind **capability flags** negotiated in HELLO so older clients keep working. There MUST be no silent wire-format change within version 1.
- The `VER` byte in every frame is `0x01` for PBLE/1 (see [protocol.md §3](protocol.md#3-framing)); a PBLE/2 frame would carry `0x02`.
- Firmware releases SHOULD be tagged so the chip target, agent version, and protocol version are all recoverable from the tag and from `manifest.json`.

### §18.2 Release cadence & artifacts

- Releases are **milestone-gated by a working demo on real hardware**, not by a fixed calendar (see the [public roadmap](../ROADMAP.md)). v1.0 ships when the §21.1 gate passes; v1.x follows as features mature.
- Each qualified firmware release MUST publish, per exact profile, at the
  canonical immutable `pyble.dev/firmware/v<version>/` path:
  `firmware.bin`, bootloader, partition table, `manifest.json` (for the web
  flasher), and `THIRD_PARTY_LICENSES` (§15.3). A v0.x mirror is optional and
  byte-identical; v1.0 and later additionally require the matching GitHub
  Release. The exact v0.4.2 public-beta exception publishes the same immutable
  artifact shape and a matching GitHub pre-release while retaining its pending
  formal qualification state.
- Each app release MUST be submitted to the **App Store and Google Play** at parity; neither platform may ship a release ahead of the other.
- The web flasher at `pyble.dev/flash` MUST be updated to the matching per-chip manifests on each firmware release.
- Release notes MUST state the app version, agent version, protocol version, and the upstream pins in effect.

### §18.3 Firmware ↔ app ↔ protocol compatibility

Compatibility is negotiated on the wire, not assumed (see [protocol.md §7](protocol.md#7-hello--capabilities)).

- The first message after connect MUST be **HELLO**: the app sends `proto_versions[]` (the versions it supports) + `app_name`/`app_version`; the board replies with the chosen `proto_version` and a `caps` set (`chip`, `mpy_version`, `fs_root`, `max_file_size`, `put_window`, `chunk_size`, `has_sd`, `free_mem`).
- The app MUST refuse (with a clear message) a board whose `proto_version` it does not support, and MUST NOT use any feature the board did not advertise in `caps`.
- The **INFO characteristic** read MUST return a `DEVICE_INFO`-equivalent payload so a client can identify a board (chip, MicroPython version, free memory) before subscribing (see [protocol.md §2](protocol.md#2-ble-transport-gatt)).
- Each app release MUST declare a **minimum supported PBLE/1 capability baseline** and a minimum agent version it interoperates with; the agent likewise declares its minimum app expectations via capabilities. A mismatch surfaces as a "please update the firmware/app" prompt, never a silent failure.
- Additive protocol growth within v1 MUST be discoverable purely through `caps`, so a new app and an older board (or vice-versa) degrade gracefully to the common feature set.

### §18.4 Deprecation policy

- A capability or feature, once shipped in a released `caps` set, MUST NOT be removed within the same protocol major version without a deprecation window: it is first marked deprecated in release notes and remains functional for at least one subsequent MINOR release before removal is considered.
- Removing or changing the meaning of an existing opcode, field, or status code (see [protocol.md §8](protocol.md#8-status--error-codes-1-byte-status-in-rsp)) is a breaking change and MUST bump the protocol to PBLE/2.
- The app MUST continue to support the previous protocol major version for a stated window after a new major ships, so deployed boards are not bricked by an app update.
- Deprecations MUST be documented in `protocol.md` and the release notes, with the replacement named.

---

## §19 UI Requirements

The app is **tablet-first and responsive**: a split workspace in landscape, a stacked workspace in portrait, and a scan/connect entry flow. It MUST NOT break on a phone, but the phone is best-effort, not the design target (see [app.md §5](app.md#5-platform-notes)). All UI strings MUST be localized (≥ `en`). No widget binds to BLE directly — every panel binds to the `Connection` API (see [app.md §3](app.md#3-the-connection-api-the-seam-every-widget-binds-to)).

### §19.1 Tablet landscape layout

The connected landscape shell retains its top application toolbar and
NavigationRail. It has two mutually-exclusive workbench modes.

The default text workbench MAY remain a three-pane split:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ PyBLE | Board: PyBLE-9F3A ▾ | Disconnect  Run  Stop  Soft-reboot      │
├───────────────┬───────────────────────────────────┬──────────────────┤
│ Files         │ Code Editor / Console              │ Pin Reference     │
│ (board FS)    │                                    │                   │
│  main.py      │ from machine import Pin            │                   │
│  lib/         │ import time                        │ (chip-keyed pin   │
│  data/        │ led = Pin(2, Pin.OUT)              │  cautions, read-  │
│               │                                    │  only)            │
├───────────────┴───────────────────────────────────┴──────────────────┤
│ Console (stdout/stderr + stdin)  |  Plot  |  Problems                  │
└──────────────────────────────────────────────────────────────────────┘
```

Blocks MUST also be a first-class NavigationRail destination. Selecting it MUST
replace the Files, Editor/Console, and Pin Reference panes with one focused
Blocks workspace; Blocks MUST NOT be squeezed into the text workbench's
secondary pane:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ PyBLE | Board: PyBLE-9F3A ▾ | Disconnect  Stop  Soft-reboot          │
├─────────┬───────────────────────────────────────┬────────────────────┤
│ Rail    │ Blocks: Examples | Preview | Open      │ Generated Python†  │
│ Blocks ●│                                       │ (read-only)        │
│         │ Save | Run*                           │                    │
│         │                                       │                    │
│         │                                       │                    │
├─────────┴───────────────────────────────────────┴────────────────────┤
│ Console ▸  (collapsed/on demand; expands after Run or new output)    │
└──────────────────────────────────────────────────────────────────────┘
* the one feature-owned Blocks Run; † present only when width permits
```

- In the text workbench, Files MUST present the board filesystem through
  `Connection` file operations; the center hosts Editor or Console; and the
  right pane defaults to the read-only **chip-keyed pin reference** selected
  from DEVICE_INFO. Plots MAY join that secondary host when implemented.
- In Blocks focus, the retained top toolbar MUST hide its editor-targeted Run.
  The Blocks action strip owns the **only** Blocks Run beside Examples,
  Preview, Open in editor, and Save; it acts on a freshly acknowledged
  generated snapshot. At a constrained width Examples MUST move first into a
  labelled keyboard- and screen-reader-reachable overflow and MUST remain
  available; further non-Run actions MAY join it. The strip MUST NOT substitute
  horizontal scrolling, clipped targets, or canvas compression.
  Disconnect, Stop, and Soft-reboot remain available in the top chrome.
- A wide focused content area MUST show a selectable, read-only generated-Python
  inspector at a bounded **360–420 dp** width only when the remaining Blockly
  host is both at least **720 dp** wide and at least **60%** of usable focused
  content width. At narrower landscape widths the inspector MUST be omitted,
  not used to squeeze Blockly below either bound.
- Loading, generator, recovery, and action notices MUST live in Flutter-owned
  host chrome outside the Blockly canvas. No notice, banner, or action panel may
  cover the editable canvas.
- Blocks uses a collapsed/on-demand console so live output remains reachable
  without permanently consuming canvas height. It MUST expand when the user
  requests it, after Blocks Run starts, or when new console output arrives; its
  existing buffer MUST be preserved.
- Rotating between landscape and the §19.2 stacked layout MUST preserve the
  selected Blocks workspace and restore its serialized JSON if the platform
  view is recreated.
- A structurally empty workspace MUST offer a prominent Examples action while
  leaving the Blockly toolbox usable. Together with the persistent action-strip
  entry and Examples toolbox category, it opens one adaptive chooser controller:
  a scroll-controlled modal bottom sheet below 600 dp and a dialog at 600 dp and
  wider. It previews locally generated Python, gathers every required GPIO role
  without a default (and distinct values for separate roles), creates an
  editable copy, or confirms replacement of non-empty work. It MUST NOT execute
  or save merely because an example is browsed or loaded, and MUST NOT announce
  loaded success until the active host acknowledges the restored candidate.
- This is a clean-room contract for generic, high-level responsive behavior.
  It authorizes no copying of a third-party application's source, assets,
  styling implementation, identifiers, or block catalog.

### §19.2 Tablet portrait layout

A stacked layout: toolbar, editor, and a bottom tab bar that swaps the secondary panels.

```text
┌────────────────────────────────────────────┐
│ Top toolbar (Connect Run Stop Soft-reboot)  │
├────────────────────────────────────────────┤
│ Code editor                                 │
├────────────────────────────────────────────┤
│ Tabs: Console | Files | Plot | Blocks       │
└────────────────────────────────────────────┘
```

- The editor MUST remain the primary surface; secondary panels are reachable via the bottom tabs without leaving the editing context.
- Switching tabs MUST NOT drop the console stream or an in-flight file transfer.

### §19.3 Connection screen

The entry flow is scan → connect → use, with no QR pairing, no account, and no board-specific gating (see [app.md §4](app.md#4-connect-flow)).

```text
┌────────────────────────────────────────────┐
│ Connect a board                             │
│                                             │
│ Bluetooth: On     Permission: Granted       │
│                                             │
│ Nearby PyBLE boards:                        │
│   PyBLE-9F3A     ▂▄▆  -52 dBm   [Connect]   │
│   PyBLE-1C04     ▂▄    -71 dBm  [Connect]   │
│                                             │
│ Saved boards:  PyBLE-9F3A  (reconnect)      │
└────────────────────────────────────────────┘
```

- The scan MUST be **filtered to the PyBLE service UUID** — never a raw device list — and MUST show advertised `PyBLE-XXXX` names with RSSI.
- On Connect, the app MUST open GATT, subscribe to TX notify, request MTU **247**, read INFO / send HELLO, and display `DeviceInfo` (chip, MicroPython version, free memory) before enabling the editor.
- The screen MUST surface BLE permission and adapter state with localized rationale (iOS `NSBluetoothAlwaysUsageDescription`; Android `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT`, plus location handling on older Android).
- On link loss the app MUST auto-reattempt; in-flight file transfers MUST resume per [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core). Saved boards MUST reconnect by remembered identifier.

---

## §20 Success Metrics

These are the production targets the project measures itself against. Numeric
BLE/throughput targets are validated on hardware for every exact profile
included in a release and MUST be frozen per profile after measurement. The
immutable v0.4.2 formal matrix has two profiles. The current v0.6.0 source has
three prospective public profiles, and the v1.0 matrix retains them and
adds `esp32-c3-4mb`. Until a profile's values are frozen from retained evidence,
they are stated as intent, not asserted.

| Metric | Definition | v1.0 target | Status |
|---|---|---|---|
| **Time-to-connect** | Median wall-clock from "Connect" tap to editor-ready (TX subscribed, MTU negotiated, HELLO/DEVICE_INFO shown). | SHOULD be < 10 s on a first connect; < 5 s for a saved board. | Validate on HIL. |
| **BLE connection success rate** | Fraction of connect attempts to an in-range, advertising board that reach editor-ready without manual retry. | SHOULD be > 95%, measured separately on iOS and Android. | Validate on HIL. |
| **Upload/transfer reliability** | Fraction of file `put`/`get` operations that complete with a verified whole-file CRC match (no silent corruption). | MUST be > 99% for files up to the negotiated `max_file_size`. | Validate on HIL. |
| **Multi-file upload integrity** | A back-to-back multi-file upload completes with zero dropped connections and every file CRC-verified. | MUST pass the reliability bench with zero drops (story F-11). | Validate on HIL. |
| **Recovery success rate** | Fraction of cases where a runaway program (`while True`) is interrupted by **Stop** and the board returns to idle with BLE responsive throughout. | MUST be 100% barring hardware failure. | Validate on HIL. |
| **Resume-on-reconnect** | Fraction of transfers interrupted by a simulated link drop that resume from the verified offset and finish CRC-clean. | SHOULD be 100% (story F-10). | Validate on HIL. |
| **Cold-boot safety** | Board advertises on boot and does not auto-run user `main.py` unless the capability is explicitly enabled. | MUST hold on every chip (story F-12). | Validate on HIL. |

`STOP` correctness and BLE responsiveness during a run are non-negotiable (see [firmware.md §5](firmware.md#5-runtime-rules)); they are measured as the recovery metric above and gate the release in §21.

---

## §21 Acceptance Criteria

### §21.1 v1.0 release acceptance

v1.0 is accepted when **all** of the following pass. The first block folds in the former product success criteria (now owned by this document), reframed as production-release gates; the second block adds the open-source/distribution gates that a free public release requires.

**Core loop (on a classic ESP32 running the PyBLE agent):**

1. The app connects over BLE — scan filtered to the PyBLE service UUID, MTU 247 negotiated — and displays `DEVICE_INFO` (chip, MicroPython version, free memory).
2. A user can write a `.py`, upload it, **Run** it, see live `stdout`/`stderr` in the console, and **Stop** a runaway loop, with BLE staying responsive throughout.
3. Files round-trip — `put` / `get` / `list` / `delete` — with verified whole-file CRC and size.
4. A multi-file upload completes reliably with zero dropped connections (story F-11), and an interrupted transfer resumes CRC-clean on reconnect (story F-10).
5. Cold-boot safety holds: the board advertises on boot and does not auto-run user `main.py` unless explicitly enabled (story F-12).

**Breadth (v1.0 IDE surface):**

6. File explorer (multi-select), Blockly → MicroPython (including the eight
   offline editable examples with generated preview, explicit GPIO roles, and
   no autorun), `fl_chart` plots over streamed CSV, and public-GitHub `.py`
   folder import all work end-to-end against a real board.
7. The chip-keyed read-only pin reference renders for the connected chip.

**Open-source & distribution gates:**

8. The repository is public; `LICENSE` (MIT), `README`, `CONTRIBUTING` (DCO), and `CODE_OF_CONDUCT` are present; every source file is MIT-headed.
9. The **no-leak CI gate** is green on a clean tree and demonstrably fails on a fixture token (stories X-02).
10. `THIRD_PARTY_LICENSES` ships with each firmware artifact and the in-app Open-Source Notices screen renders on both iPadOS and Android (§15.2).
11. The **esp-web-tools** web flasher at `pyble.dev/flash` flashes each chip target from a supported browser (story X-10).
12. Free App Store + Play builds are submitted at parity, and firmware bins are published via GitHub Releases (story X-11).
13. **Localization parity** holds: `en` is complete and CI blocks any merge that breaks ARB parity (story X-12).
14. Every shipped behavior has a test (no behavior without a test); the PBLE/1 conformance suite (frame round-trip, CRC, fragmentation, window/resume, error mapping) is green.

### §21.2 Multi-chip acceptance

15. The full core loop (criteria 1–5) MUST pass on **`esp32`**, **`esp32-s3`**, and **`esp32-c3`** from one agent codebase (Layer-3 chip-agnostic; differences confined to the board overlay — see [firmware.md §4](firmware.md#4-chip-targets-and-release-profiles)).
16. The **ESP32-C3 resource profile** MUST be validated against §10.13
    (sourced from
    [firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target)):
    total application image/headroom within bounds, Python GC and internal-IDF
    heap above their floors after HELLO and transfer workloads,
    reset-to-advertising below its ceiling, and committed PUT plus verified GET
    goodput above their floors at observed MTU 247 with the reliability
    workload clean. The values MUST be measured and frozen on real
    `esp32-c3-4mb` hardware before v1.0 ships; C3 is the binding constraint.
17. The per-chip on-device smoke suite (per [app.md §7](app.md#7-testing)) MUST be green for all three chips.

---

## §22 Development Roadmap

The execution direction lives in the [public roadmap](../ROADMAP.md), while
accepted work is tracked through GitHub issues and milestones. This section
maps the production phases to those milestones and epics without duplicating
them. Each milestone is gated by a working demo on real hardware, not merged
code alone. Epics: **X** infra, **P** protocol/shared, **F** firmware,
**A** app.

| Phase / Milestone | Goal | Primary epics | Exit gate |
|---|---|---|---|
| **M0 — Foundations** | Project is contributable; an empty agent builds for all three chips. | X | Public repo with MIT license + DCO + **no-leak gate**; PBLE/1 §2 (transport) and §3 (framing) frozen; the 3 ESP-IDF targets build an empty agent. |
| **M1 — Firmware agent on classic ESP32** (the hard part) | A board speaks PBLE/1 well enough to edit-and-run. | F, P | From a test client on a classic ESP32: connect, device_info, put/get/list/delete, run, stop, console — all green, with a clean multi-file upload. |
| **M2 — App spine** | Edit, run, and watch the console wirelessly from a tablet. | A | Open a `.py` on iPad/Android, Run on a classic ESP32, watch the console, Stop a loop, save back; `lib/pble/` conformance tests green. |
| **M3 — Multi-chip + breadth** | All three chips; fuller IDE. | F, A | Core loop passes on `esp32`/`-s3`/`-c3` (C3 footprint validated, §21.2); file explorer + Blockly (including eight offline editable beginner examples with explicit GPIO roles and no autorun) + plots usable. |
| **M4 — Polish & release** | First public release. | X, A | esp-web-tools flasher at `pyble.dev/flash`; free App Store + Play submission; GitHub Releases for firmware; `THIRD_PARTY_LICENSES`; donation/Sponsors link; docs site. |

The agent is built **frozen-Python first** to nail PBLE/1 and reliability, then hot paths port to C where the chip budget demands it (most acutely on C3); the wire contract does not change across that move (see [firmware.md §2](firmware.md#2-agent-base-native-vs-frozen)).

**Non-deliverables (post-v1, not in any v1.0 milestone)** — listed so they cannot be quietly added; tracked in §24:

- Non-v1 agent ports beyond `esp32`/`-s3`/`-c3`, including later ESP32 and
  non-Espressif MicroPython + BLE targets.
- A desktop build with a serial transport behind the same `Connection`.
- Application-layer pairing/auth (a future PBLE capability; out of v1 scope per [protocol.md §10](protocol.md#10-security-note-v1)).
- Locales beyond `en` (translations are community-friendly from day one but not a v1.0 gate beyond `en` parity).
- `.mpy` in examples or transfer; accounts, cloud sync, or grading — explicit non-goals (§4.3).

---

## §23 Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **ESP32-C3 footprint** — single-core RISC-V, ~400 KB SRAM; the agent may not fit comfortably with NimBLE + the runner. | High | Validate C3 **first** (§21.2); hold the agent to the per-target budget in §10.13 / [firmware.md §7](firmware.md#7-footprint-budget-provisional-per-target); port hot paths (BLE I/O, framing, chunking) to C `USER_C_MODULES` where heap demands it; measure free heap after connect on real hardware before freezing the pin. |
| **Flutter Python-editor widget maturity** — no first-class Python editor widget exists; `flutter_code_editor` may fall short on tablet keyboards. | Medium | Budget an explicit evaluation against external + on-screen keyboard ergonomics; fall back to a WebView-hosted editor (Monaco/CodeMirror) behind the same editor interface if needed (see [app.md](app.md), §16.1). |
| **BLE reliability differs on iOS vs Android** — MTU behavior, scan/connect timing, background handling diverge. | Medium | Keep `lib/ble/` a thin, mockable adapter; measure connection-success and transfer-reliability metrics (§20) **separately per platform**; design PBLE/1 file transfer for a lossy, MTU-bounded link (windowed chunks + CRC + resume) from the start (see [protocol.md §5](protocol.md#5-file-transfer-the-reliability-core)). |
| **Maintaining clean-room / no-leak discipline** — accidental import of proprietary protocol, UUIDs, board profiles, or pedagogy. | High | The **no-leak CI gate** rejects forbidden tokens on every push (see [AGENTS.md](../../AGENTS.md)); PBLE/1 is authored fresh ([ADR-0002](../decisions/0002-fresh-protocol.md)); reused widgets are relicensed MIT and retyped onto neutral types; the boundary is public and documented ([architecture.md §5](architecture.md#5-clean-room--ip-boundary)). |
| **File-transfer reliability is the fragile core** — drops, MTU bounds, partial writes. | High | Get it right first (M1); windowed upload with cumulative ACK, whole-file CRC, temp-write-then-rename, and resume-on-reconnect; reliability bench (story F-11) as a release gate. |
| **STOP fails to land while user code runs** — a frozen `while True` wedges BLE. | High | Run user code on its own task; the BLE/agent task always services the link so `STOP` (KeyboardInterrupt) is authoritative (see [firmware.md §5](firmware.md#5-runtime-rules)); measured as the recovery metric (§20). |
| **Upstream MicroPython/ESP-IDF upgrade breaks a build or footprint.** | Medium | Upgrade only via the controlled workflow with the SHA gate, conformance suite, per-profile resource gates, and hardware validation on every included profile; v1.0 requires all four exact profiles (§17.1, §17.3). Default zero upstream patches. |
| **Store-distribution friction** (BLE permission rejections, review). | Medium | Localized BLE permission rationale on both platforms; tablet-first responsive layout that does not break on a phone; parity submission so neither store lags. |

---

## §24 Future Product Line / Post-v1

These are candidates for v1.x and post-v1, deferred from v1.0 and listed so they are not quietly pulled forward. All remain consistent with the project's non-goals (§4.3) and clean-room posture.

| Item | What it is | Trigger / condition |
|---|---|---|
| **Additional platform ports** (later ESP32 and non-Espressif MicroPython + BLE MCUs) | Same PBLE/1 plus a port-specific BLE/runtime/storage/build adapter; a new board overlay is sufficient only when the underlying MicroPython port is shared. | Community contribution after v1.0 is stable; gated by equivalent conformance, recovery, resource, and HIL acceptance. |
| **Desktop transport** | A serial transport behind the same `Connection` API, enabling a desktop build without changing the protocol client. | Post-v1; requires a serial adapter in `lib/ble/`-equivalent layer; iPad remains BLE-only by design. |
| **Application-layer auth** | An optional pairing token negotiated in HELLO, on top of BLE link-layer pairing. | A future PBLE capability flag; explicitly out of v1 scope ([protocol.md §10](protocol.md#10-security-note-v1)); additive, no PBLE/2 bump. |
| **Additional locales** | Languages beyond `en`, community-contributed. | Translations are community-friendly from day one; parity is CI-enforced for any added locale (§16.1, story X-12). |
| **Blocks / plots maturity** | Blocks beyond the v1.0 language + generic digital-GPIO set, and more capable plotting beyond the v1.0 CSV/streamed-value charts. | Post-v1 breadth; MUST stay board-neutral and capability-honest, with no board-specific defaults. |

PyBLE deliberately does **not** plan accounts, cloud sync, grading, paid tiers,
closed modules, generalized board-specific routing profiles, or a MicroPython
fork — these are permanent non-goals, not deferred features. The explicit,
exact-profile cosmetic display companion frozen by ADR-0024/ADR-0029 does not create a
user-code routing system or weaken that boundary.

---

## §25 Open Questions

The foundational product decisions are resolved and recorded as Architecture Decision Records under [docs/decisions/](../decisions/) (decided 2026-06-30). This section is the decision log plus the items still pending hardware measurement.

**Resolved (see ADRs):**

- **Separate project vs. extending a closed product** → build PyBLE as a new, separate, open-source project ([ADR-0001](../decisions/0001-separate-project-not-extend.md)).
- **Reuse a proprietary protocol vs. author fresh** → fresh clean-room **PBLE/1**, with its own framing, opcodes, and UUIDs ([ADR-0002](../decisions/0002-fresh-protocol.md)).
- **License / business model** → entirely **MIT**, free, donation/Sponsors-funded; no paywall, no telemetry-by-default ([ADR-0003](../decisions/0003-license-mit.md)).
- **Name / identifiers** → **PyBLE** ("Python over BLE"); protocol **PBLE/1**, modules `pyble_*`, BLE prefix `PyBLE-`, UUID base encoding `pybl` ([ADR-0004](../decisions/0004-name-pyble.md)).
- **Web home** → standalone `pyble.dev` (`.org` redirects), not a commercial subdomain ([ADR-0005](../decisions/0005-standalone-domain.md)).
- **Initial app platforms** → iPadOS and Android tablet at parity, released together (§13.6).
- **Wi-Fi / USB as primary transport** → no; BLE-first and BLE-only for v1 (this is what makes iPad first-class).
- **Board scope** → capability-defined MicroPython + BLE platform; ESP32,
  ESP32-S3, and ESP32-C3 are the initial build/reference targets. Current
  public compatibility remains exact-profile and evidence-gated
  ([ADR-0021](../decisions/0021-capability-defined-board-scope.md)).

**Pending (resolved by measurement, not debate):**

- **Upstream-pin approval and footprint gates on real hardware** — the exact
  MicroPython/ESP-IDF lock bytes are candidate-frozen for v0.4.2, but the
  per-target footprint budgets and formal approval (especially **ESP32-C3**)
  remain open under §10.13. Candidate-freezing is not approval. The same
  exact source-selected v0.6.0 lock file MUST be deliberately frozen as the
  immutable release-build/HIL input; historical v0.5.1 selection does not
  qualify a new candidate. The same candidate MUST then pass the
  complete exact-profile HIL matrix before its pins and resource gates are
  approved. The v0.6.0 prospective public subset is exactly the three profiles in
  §10.12; v1.0 retains them and adds C3 (§10.9, §17.1, §21.2). A pin
  change creates a new candidate. New ADRs are added if a pin or budget
  changes materially.
- **Agent base transition point** — frozen-Python first, then C `USER_C_MODULES` for hot paths; the exact point where the C port becomes necessary per chip is decided by HIL footprint/throughput data, not up front (see [firmware.md §2](firmware.md#2-agent-base-native-vs-frozen)).
- **State-management library choice** for the Flutter app (§16.1) — to be fixed by an ADR before broad adoption.

New significant decisions MUST be captured as additional ADRs (`docs/decisions/NNNN-*.md`); ADRs are immutable once accepted and are superseded, not edited.

---

## §26 Glossary

| Term | Definition |
|---|---|
| **PyBLE** | "Python over BLE" — the project: a free, open-source (MIT), tablet-first MicroPython IDE that edits and runs code on compatible MicroPython boards over Bluetooth Low Energy. ESP32 / ESP32-S3 / ESP32-C3 are its initial firmware targets. Wordmark **PyBLE**; repo `PyBLE`; domain `pyble.dev`. |
| **PBLE/1** | The PyBLE BLE wire protocol (version 1): clean-room, original framing + opcodes + file-transfer scheme carried over a PyBLE-owned GATT service. Authoritative spec: [protocol.md](protocol.md). |
| **Agent** | The board-side firmware (Layer 3) — the `pyble_*` modules (`pyble_ble`, `pyble_proto`, `pyble_runner`, `pyble_fs`, `pyble_console`, `pyble_info`) running on upstream MicroPython that advertise the service, speak PBLE/1, run/stop code, and bridge the filesystem and console. Built on upstream MicroPython, never a fork (see [firmware.md](firmware.md)). |
| **Control plane** | The agent's protected layer that owns BLE, the runner, and the filesystem bridge. It MUST NOT be editable by user code; a frozen `while True` in user code MUST NOT be able to wedge BLE or block `STOP`. |
| **Workspace** | The user's own files on the board — `/main.py`, `/lib/*.py`, `/data/*` (Layer 4). Just programs the agent runs; never the control plane. |
| **Platform port / target adapter** | Layer-2 integration for a MicroPython target: BLE host, scheduler/interrupt boundary, storage/config, identity, build, and provisioning. The initial ESP32 port uses per-chip board overlays for `esp32` / `esp32-s3` / `esp32-c3`, copied into the upstream tree at build prep so the submodule stays pristine. |
| **HIL** | Hardware-in-the-loop — validation and measurement performed on a real board (as opposed to host-side or fake-transport tests). Resource and BLE/goodput numbers are frozen only after HIL measurement for every exact profile claimed by a release. The immutable v0.4.2 matrix is `esp32-4mb` plus `esp32-s3-n16r8`; its supplemental browser rows passed while other formal rows remain pending. The v0.5.1 source-candidate matrix adds `waveshare-esp32-s3-lcd-147b`, and the two prospective S3 binaries require independent evidence. v1.0 additionally requires `esp32-c3-4mb`. |
