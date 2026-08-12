# PyBLE — Agent Firmware

Status: **DRAFT** · Last updated: 2026-08-12

The PyBLE agent is small board-side firmware that turns a compatible
MicroPython target into a PyBLE-speaking board: it advertises the BLE service,
accepts PBLE/1 commands, runs/stops MicroPython, and bridges the filesystem and
console. PyBLE's platform scope includes any microcontroller board able to run
MicroPython and a conforming BLE peripheral agent. The current v1 reference
implementation is built for classic ESP32, ESP32-S3, and ESP32-C3 on
**upstream MicroPython** — not a fork.

> **Detailed firmware docs:** this page is the overview. The full requirements live in [`firmware/specs.md`](firmware/specs.md) and the technical design in [`firmware/TDD.md`](firmware/TDD.md) (Technical Design Document), both derived from [PRD §10](prd.md).

## 1. Four-layer rule

```
Layer 1  Upstream MicroPython port            — pinned source, never edited in place
Layer 2  Target adapter / board overlay       — port, BLE host, build, and chip config
Layer 3  PyBLE agent                           — the protected modules (this spec)
Layer 4  User workspace                        — /main.py, /lib/*.py, /data/*  (never the control plane)
```

The agent is the **control plane** and must not be editable by user code. The user's `main.py` is just a program the agent runs; a frozen `while True: pass` in user code must not be able to wedge BLE or block `STOP`.

## 2. Agent base: native vs frozen

Two viable implementations behind the same PBLE/1 contract:

- **Frozen-Python agent (recommended first):** the agent is frozen `.py` modules baked into the firmware, using MicroPython's `bluetooth` (NimBLE) and `os`/`vfs` APIs, plus `_thread`/`asyncio` for the runner. Fastest to prototype the protocol and iterate.
- **Native `USER_C_MODULE` agent (hardening target):** the hot paths (BLE I/O, framing, file chunking) move to C for throughput and RAM headroom, especially on ESP32-C3.

Decision (revised 2026-07-01 — see [ADR-0006](../decisions/0006-native-c-agent-from-day-one.md)): **the agent base is a native `USER_C_MODULE` (C) from day one.** The module boundaries and the PBLE/1 wire are unchanged; the agent's `pble_*.c` sources are byte-compatible with the wire and are built module-by-module, each byte-identical to (and sharing the conformance corpus of) any interim frozen `.py` scaffold it replaces. The wire contract does not change across this move.

Scoped deviation (2026-08-11 — see [ADR-0030](../decisions/0030-pico2w-portable-python-agent-first.md)): the `rpi-pico2-w` port ships the **portable frozen-Python agent first**, grown from the `firmware/pyble/` scaffolds and frozen into the image (embedded, never a user-deletable vfs file — that rule is not deviated). Each frozen module retires when its native BTstack `pble_*.c` twin reaches parity on the shared conformance corpus (port OI-P1). The PBLE/1 wire is invariant across the swap; the ESP32-family native agent is unchanged.

## 3. Modules

| Module | Owns |
|---|---|
| `pyble_ble` | NimBLE peripheral: advertising (`PyBLE-XXXX`), the GATT service (RX/TX/INFO), MTU, fragmentation (PBLE/1 §3.2). |
| `pyble_proto` | PBLE/1 frame encode/decode, CRC32, request/response correlation, dispatch. |
| `pyble_runner` | Run a file or source on a separate task; capture `stdout`/`stderr`; implement `STOP` (KeyboardInterrupt) and `SOFT_REBOOT`; emit `RUN_STATE`. |
| `pyble_fs` | Filesystem bridge: list/stat/get/put/delete/mkdir/rename; windowed upload with CRC + resume (PBLE/1 §5). |
| `pyble_console` | Tee `stdout`/`stderr` to BLE as `CONSOLE_DATA` events (and to USB-serial if present, for local debugging). |
| `pyble_info` | Assemble `DEVICE_INFO`/HELLO caps: chip, MicroPython version, free memory, fs root, MTU, SD presence. |

There is **no** GPIO-routing, actuator-safety, display-control, calibration, or
board-profile module in the agent. PyBLE exposes hardware to **user code**, not
through PBLE/1. Every initial ESP32-family target freezes the pinned upstream
`neopixel` package. The exact `waveshare-esp32-s3-lcd-147b` build additionally
freezes the clean-room MIT `pyble_st7789` user library; importing it has no side
effects, and the program must explicitly supply its SPI bus configuration,
pins, geometry, offsets, colour order, and inversion. The generic
`esp32-s3-n16r8` build intentionally omits it. This optional Layer-4 helper
neither claims that another board has a display nor changes agent capabilities. See
[ADR-0018](../decisions/0018-standard-micropython-neopixel.md) and
[ADR-0023](../decisions/0023-explicit-st7789-user-runtime.md), as narrowed by
[ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md).

The exact-board overlay alone contains the separately bounded companion
`pyble_waveshare_lcd147b`, its splash-aware boot hook, and the splash-only
native readiness seam. A freshly erased exact-board installation enables its
splash by default, while an explicit persisted disable remains authoritative;
it cannot detect/select hardware. When enabled, boot waits boundedly for actual
BLE availability, renders one private/offline app-discovery frame on the
published Waveshare ESP32-S3-LCD-1.47B wiring, releases display resources, and
continues. It adds no Layer-3 display module, PBLE/1 capability, or user-code
GPIO abstraction. The generic S3, classic, and C3 images contain none of this
board-specific path ([ADR-0024](../decisions/0024-opt-in-waveshare-boot-splash.md),
[ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md)).

## 4. Chip targets and release profiles

The initial v1 agent codebase builds three ESP-IDF targets:

| Target | IDF target | Notes |
|---|---|---|
| `esp32` | `esp32` | Classic; tightest heap; the conservative baseline. |
| `esp32-s3` | `esp32s3` | More RAM (often PSRAM), native USB; most headroom. |
| `esp32-c3` | `esp32c3` | Single-core RISC-V, least RAM — the **footprint constraint**; validate the agent fits here early. |

All three use **NimBLE**. The release build matrix distinguishes those three
chip targets from four build variants: `esp32`, lean `esp32-s3`, exact-board
`waveshare-esp32-s3-lcd-147b`, and `esp32-c3`. The two S3 variants both compile
for `esp32s3` but have independent overlays, retained source/build roots, and
artifacts. Differences remain confined to Layer 2, and the shared agent core
contains no runtime board detector or per-chip product routing logic.

The browser installer does not publish unqualified family-wide images. The
exact v0.4.2 bundle is offered as a hardware-tested beta for `esp32-4mb`
(classic ESP32, 4 MiB flash) and `esp32-s3-n16r8` (ESP32-S3, 16 MiB flash plus
8 MiB Octal PSRAM). On both exact profiles, browser installation and
interrupted-flash recovery passed; complete release qualification remains
pending. The v0.5.1 source candidate set is exactly `esp32-4mb`,
`esp32-s3-n16r8` (lean ESP32-S3, 16 MiB flash plus 8 MiB Octal PSRAM), and
`waveshare-esp32-s3-lcd-147b` (the exact B-version board with the same memory
topology plus its display stack). That source contract does not authorize new
public bytes or selector activation: fresh reproducible builds, license audit,
and final-candidate HIL remain required independently for all three profiles.
`esp32-c3-4mb` remains a known initial v1 profile but is unavailable and has no
public image until exact-profile real-hardware validation is complete. Its
ESP32-C3-MINI-1-N4 v0.4/4 MiB/no-PSRAM engineering reference and still-pending
identity, behavior, resource, dual-app, and reference-carrier peripheral gates
are frozen separately in
[firmware/ports/esp32-c3-4mb.md](firmware/ports/esp32-c3-4mb.md); this adds no
build variant or board-routing profile. ESP Web
Tools detects the chip family but cannot by that fact alone prove the required
flash/PSRAM topology or distinguish the two S3 images. The full compatibility,
artifact, historical public-beta, and candidate-gate contracts are frozen in
[firmware/browser-flashing.md](firmware/browser-flashing.md).

The Waveshare ESP32-S3-LCD-1.47B uses its own
`waveshare-esp32-s3-lcd-147b` provisioning image. Its ESP32-S3R8 and external
W25Q128 provide the same 8 MiB Octal-PSRAM / 16 MiB flash topology as the lean
S3 profile, but matching memory does not identify onboard peripherals. The
exact profile is a build/release/installer identity, not a PBLE/1 routing
profile: both images continue to report target `esp32-s3`. Display pins remain
explicit user-program values for ordinary programs; only the exact-board
ADR-0024 companion contains the published values for its bounded cosmetic boot
frame. ADR-0029 makes that frame factory-enabled only in the separately chosen
exact-board image after an erased installation.

These targets are the initial reference/build family, not the product boundary.
A future port MAY use another upstream MicroPython port, CPU
architecture, BLE host, native integration mechanism, build system, storage
backend, or provisioning tool. It MUST preserve PBLE/1, the protected
control-plane boundary, capability negotiation, workspace safety, and the
conformance/HIL gates. Target-specific behavior belongs behind Layer 2; the app
MUST NOT require a known-chip allowlist.

### 4.1 Ports in progress

| Target | Upstream port · board | BLE host | RTOS | Layer 2 |
|---|---|---|---|---|
| `rpi-pico2-w` | `rp2` · `RPI_PICO2_W` | BTstack (via `bluetooth`) | none (bare-metal pico-sdk) | `firmware/board_overlays/rpi-pico2-w/`, copied to `ports/rp2/boards/PYBLE_RPI_PICO2_W/` at build prep (submodule pristine, CON-1/CON-4 pattern) |

The port's derived requirements, execution model, resource gates, provisioning
contract, and HIL matrix live in
[firmware/ports/rpi-pico2-w.md](firmware/ports/rpi-pico2-w.md), per
[firmware/specs.md §1.1](firmware/specs.md).

## 5. Runtime rules

- **BLE stays responsive while user code runs.** The runner executes user code on its own task; the BLE/agent task keeps servicing the link, so `STOP` always lands.
- **STOP is authoritative.** `STOP` interrupts the runner promptly; on interrupt or exception the runner tears down cleanly and reports `RUN_STATE`.
- **The agent owns the filesystem bridge**, but user code may also touch the FS normally; uploads use temp-write-then-rename to avoid corrupting a file mid-transfer.
- **Console mirrors everywhere.** `stdout`/`stderr` go to BLE and (if connected) USB-serial, regardless of who started the run.
- **Cold boot is safe.** On boot the board advertises and waits; it does not auto-run user `main.py` unless explicitly enabled (a HELLO/`DEVICE_INFO` capability flag), so a bad `main.py` can't lock you out of the board.
- **Exact-board identity is independent and fail-open.** On an explicitly
  configured Waveshare 1.47B running its exact-board image, one
  BLE-readiness-gated splash may run before workers/autorun. Disabled state,
  timeout, or display failure produces no user-code execution and cannot
  prevent normal agent recovery. The lean S3 image has no splash path at all.

## 6. Build & distribution

- For the current ESP32 reference family, `firmware/scripts/build.sh <variant>`
  builds one of the four admitted variants and `build_all.sh` builds the
  complete four-variant/three-chip matrix.
- Every resolved target manifest contains the pinned upstream `neopixel` module exactly once; no PyBLE-authored WS2812 driver is built.
- The exact Waveshare manifest contains `pyble_st7789` and the
  factory-enabled-after-erase, persistently disableable
  exact-board companion exactly once. Its NVS guard runs before every hardware
  import or readiness wait. The lean S3, classic ESP32, and ESP32-C3 manifests
  contain zero copies and compile out the splash-only native readiness seam.
- Pinned versions live in `firmware/versions.lock` (MicroPython tag + ESP-IDF version); upstream MicroPython is a submodule under `firmware/upstream/`.
- Each current ESP32 build emits a merged `firmware.bin`, application image,
  bootloader, partition table, and authoritative `flasher_args.json`. Release
  packaging validates the merged image against those components and the frozen
  merge settings, then emits the exact single-image ESP Web Tools manifest,
  companion size/SHA-256 metadata, provenance, licenses, recovery guide, and
  HIL report defined by
  [firmware/browser-flashing.md](firmware/browser-flashing.md).
- The immutable bundle at `pyble.dev/firmware/v<version>/` is the canonical
  public firmware distribution. A v0.x mirror is optional and MUST be
  byte-identical if published; v1.0 and later additionally require the matching
  **GitHub Release**. Future target ports MUST document and publish their
  matching artifact, integrity contract, recovery path, and HIL evidence.
- Any unavoidable upstream patch is isolated under `firmware/patches/micropython-<tag>/` with a reason — never edited in place.
- The `rpi-pico2-w` port builds via the sibling `firmware/scripts/build_rp2.sh`
  (same `--plan`/fail-clean contract as `build.sh`; the existing ESP build
  matrix remains `esp32`, lean `esp32-s3`, exact-board
  `waveshare-esp32-s3-lcd-147b`, and `esp32-c3`). `versions.lock` gains
  `[targets_rp2]` (PyBLE
  target → upstream rp2 board) and `[arm_gnu_toolchain]` (pinned ARM GNU
  release + SHA-256; the build verifies the compiler version and fails cleanly
  on mismatch — never a silent substitution, BLD-4 equivalent). pico-sdk,
  BTstack, cyw43-driver etc. are pinned transitively as `lib/` submodules of
  the one `[micropython]` commit — no new external pin. Artifacts:
  `firmware.uf2` (primary, BOOTSEL/picotool-flashable), `firmware.elf`,
  `firmware.bin`, provenance JSON (`port: "rp2"`), with a hard image-size gate
  of 1,572,864 bytes.
- The first source identity that combines this RP2 port with the four existing
  ESP build variants is agent version **0.6.0**. Version `0.5.1` remains the
  earlier Waveshare/ESP source candidate and MUST NOT be retagged with different
  bytes. Selecting `0.6.0` is source versioning only: Pico remains excluded
  from public release metadata and the web installer until GP2, while every
  publishable ESP or RP2 artifact still requires fresh version-bound build,
  provenance, resource, recovery, and HIL evidence.

## 7. Footprint budget (provisional, per target)

The measurement method is frozen in
[firmware/specs.md §5.3](firmware/specs.md#53-footprint-gates-nfr-fp);
the v0.4.2 two-profile policy and evidence remain immutable history. The
exact-board split invalidates any pre-split v0.5 baseline for current-source
qualification, so the v0.5.1 source candidate requires the controlled
three-profile refresh defined there. No current-source numeric qualification is
claimed until the retained baseline, policy, and final-candidate records exist.
The scope is profile-specific:

| Profile | Current numeric status | Release effect |
|---|---|---|
| `esp32-4mb` | v0.4.2 browser install/recovery passed; refresh the current-source baseline and verify the final candidate | Required before v0.5.1 candidate qualification and installer activation |
| `esp32-s3-n16r8` | v0.4.2 browser install/recovery passed; measure the lean N16R8 bytes/runtime independently, derive thresholds, then verify the final candidate | Required before v0.5.1 candidate qualification and installer activation |
| `waveshare-esp32-s3-lcd-147b` | No public exact-byte qualification; measure the exact-board bytes/runtime independently, derive thresholds, then verify the final candidate and display gate | Required before v0.5.1 candidate qualification and installer activation |
| `esp32-c3-4mb` | Engineering contract frozen; all observations, threshold, and HIL rows pending ([derived contract](firmware/ports/esp32-c3-4mb.md)) | Blocks C3 enablement and v1.0, but not qualification of the three-profile candidate |

The enforced metrics are:

- exact shipped `application.bin` bytes and derived factory-partition headroom
  (static build/candidate ceiling and floor);
- Python `gc.mem_free()` after collection plus internal 8-bit ESP-IDF current,
  largest-block, and minimum-free heap (runtime HIL floors);
- controlled reset release to the first fresh PyBLE service advertisement
  (runtime HIL ceiling), with a separate physical power-cycle check;
- committed PUT and verified GET goodput at observed ATT MTU 247 (runtime HIL
  floors); and
- one exact 20 × 16 KiB reliability workload with byte/size/CRC integrity and
  zero unexpected disconnects.

The existing HELLO/INFO `free_mem` value is retained as diagnostic
default-capability heap. It may include PSRAM on S3 and is not the user or
internal-heap gate. Total application-image size is the normative flash
quantity; an “agent-only overhead” requires a matched no-agent control build
and is supplemental only.

Thresholds are never fitted to a candidate run: heap floors round the minimum
of the frozen sample set outward to 1 KiB; reset-to-advertisement uses the
fixed 3,000 ms end-to-end product SLO; and goodput floors apply the exact
integer 5% host/radio repeatability allowance before rounding outward to 100
bytes/s. The reset metric ends at a host scanner callback, so it is a
user-visible discovery SLO rather than a tight firmware boot-regression
statistic. Static image/headroom quantities remain exact, and
integrity/reliability assertions receive no allowance. The engineering
baseline derives the remaining committed policy values; only hash-locked
final-candidate HIL qualifies a release. C3 continues to build and participate
in reproducibility and license audits while its real-board qualification is
deferred.

Published v0.4.2 metadata and HIL evidence retain their historical exact
two-profile contract. They are validated by their own source-era schema and
are never expanded or reinterpreted as this v0.5.0 matrix.

<!-- SPDX-License-Identifier: MIT -->
