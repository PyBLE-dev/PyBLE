# PyBLE — Agent Firmware

Status: **DRAFT** · Last updated: 2026-08-01

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

## 3. Modules

| Module | Owns |
|---|---|
| `pyble_ble` | NimBLE peripheral: advertising (`PyBLE-XXXX`), the GATT service (RX/TX/INFO), MTU, fragmentation (PBLE/1 §3.2). |
| `pyble_proto` | PBLE/1 frame encode/decode, CRC32, request/response correlation, dispatch. |
| `pyble_runner` | Run a file or source on a separate task; capture `stdout`/`stderr`; implement `STOP` (KeyboardInterrupt) and `SOFT_REBOOT`; emit `RUN_STATE`. |
| `pyble_fs` | Filesystem bridge: list/stat/get/put/delete/mkdir/rename; windowed upload with CRC + resume (PBLE/1 §5). |
| `pyble_console` | Tee `stdout`/`stderr` to BLE as `CONSOLE_DATA` events (and to USB-serial if present, for local debugging). |
| `pyble_info` | Assemble `DEVICE_INFO`/HELLO caps: chip, MicroPython version, free memory, fs root, MTU, SD presence. |

There is **no** GPIO-routing, actuator-safety, TFT, calibration, or board-profile
module. PyBLE exposes the board's hardware to **user code** via standard
MicroPython, not via the agent. Every initial ESP32-family target freezes the
pinned upstream `neopixel` package so `from neopixel import NeoPixel` is
available offline; the program still supplies its own `Pin`, pixel count,
colours, and timing. A future port claims this API only after validating both
the package and its required runtime primitive
([ADR-0018](../decisions/0018-standard-micropython-neopixel.md)).

## 4. Chip targets and release profiles

The initial v1 agent codebase builds three ESP-IDF targets:

| Target | IDF target | Notes |
|---|---|---|
| `esp32` | `esp32` | Classic; tightest heap; the conservative baseline. |
| `esp32-s3` | `esp32s3` | More RAM (often PSRAM), native USB; most headroom. |
| `esp32-c3` | `esp32c3` | Single-core RISC-V, least RAM — the **footprint constraint**; validate the agent fits here early. |

All three use **NimBLE**. Within this initial ESP32 port, differences are
confined to Layer 2 (board overlay: pins, flash size, USB), and the shared agent
core contains no per-chip product logic.

The browser installer does not publish unqualified family-wide images. The
exact v0.4.2 bundle is offered as a hardware-tested beta for `esp32-4mb`
(classic ESP32, 4 MiB flash) and `esp32-s3-n16r8` (ESP32-S3, 16 MiB flash plus
8 MiB Octal PSRAM). On both exact profiles, browser installation and interrupted-flash recovery passed;
complete release qualification remains pending.
`esp32-c3-4mb` remains a known initial v1 profile but is unavailable
and has no public image until exact-profile real-hardware validation is
complete. ESP Web Tools detects the chip family but cannot by that fact alone
prove the required flash/PSRAM topology. The full compatibility, artifact, and
bounded public-beta contracts are frozen in
[firmware/browser-flashing.md](firmware/browser-flashing.md).

These targets are the initial reference/build family, not the product boundary.
A future port MAY use another upstream MicroPython port, CPU
architecture, BLE host, native integration mechanism, build system, storage
backend, or provisioning tool. It MUST preserve PBLE/1, the protected
control-plane boundary, capability negotiation, workspace safety, and the
conformance/HIL gates. Target-specific behavior belongs behind Layer 2; the app
MUST NOT require a known-chip allowlist.

## 5. Runtime rules

- **BLE stays responsive while user code runs.** The runner executes user code on its own task; the BLE/agent task keeps servicing the link, so `STOP` always lands.
- **STOP is authoritative.** `STOP` interrupts the runner promptly; on interrupt or exception the runner tears down cleanly and reports `RUN_STATE`.
- **The agent owns the filesystem bridge**, but user code may also touch the FS normally; uploads use temp-write-then-rename to avoid corrupting a file mid-transfer.
- **Console mirrors everywhere.** `stdout`/`stderr` go to BLE and (if connected) USB-serial, regardless of who started the run.
- **Cold boot is safe.** On boot the board advertises and waits; it does not auto-run user `main.py` unless explicitly enabled (a HELLO/`DEVICE_INFO` capability flag), so a bad `main.py` can't lock you out of the board.

## 6. Build & distribution

- For the current ESP32 reference family, `firmware/scripts/build.sh <target>`
  builds one chip and `build_all.sh` builds all three.
- Every resolved target manifest contains the pinned upstream `neopixel` module exactly once; no PyBLE-authored WS2812 driver is built.
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

## 7. Footprint budget (provisional, per target)

The measurement method is frozen in
[firmware/specs.md §5.3](firmware/specs.md#53-footprint-gates-nfr-fp);
numeric values remain provisional until derived from retained baseline samples.
The current v0.4.2 qualification work remains profile-scoped:

| Profile | Current numeric status | Release effect |
|---|---|---|
| `esp32-4mb` | Browser install/recovery passed; numeric/resource qualification pending | Enabled only by the exact v0.4.2 public-beta exception; required for qualification |
| `esp32-s3-n16r8` | Browser install/recovery passed; numeric/resource qualification pending | Enabled only by the exact v0.4.2 public-beta exception; required for qualification |
| `esp32-c3-4mb` | Deferred; no current threshold or HIL row | Blocks C3 enablement and v1.0; absent from the v0.4.2 beta |

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

Thresholds are never guessed: heap floors round the minimum of the frozen
sample set outward to 1 KiB, boot ceilings round the maximum outward to 10 ms,
and goodput floors round the minimum outward to 100 bytes/s. The engineering
baseline derives the committed policy; only hash-locked final-candidate HIL
qualifies a release. C3 continues to build and participate in reproducibility
and license audits while its real-board qualification is deferred.
