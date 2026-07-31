# HIL harness (`tests/firmware_tests/hil/`)

Hardware-in-the-loop bench drivers for the firmware track. These talk PBLE/1 to a
**real PyBLE board** over BLE (via [`bleak`](https://github.com/hbldh/bleak) —
CoreBluetooth on macOS, BlueZ on Linux). They are **test artifacts owned by
firmware-test-author**; none of this ships in the firmware image.

A milestone gate is green **only on a real-hardware HIL demo**, not on merged
code (PRD §1B.7). These drivers are that demo, made repeatable.

## Files

| File | Role |
|---|---|
| `_pble_wire.py` | Pure-Python PBLE/1 codec (§3.1 frame + §3.2 fragmentation + IEEE CRC-32) + the frozen §4 opcode / §8 status numbers. **No dependencies.** Cross-checked byte-for-byte against the shared corpus by `host/conformance/test_hil_wire.py` (host-runnable, no hardware) — the harness can never drift from the firmware↔Dart wire. |
| `_pble_central.py` | Minimal PBLE/1 BLE central over `bleak`: filtered scan/connect, conservative pre-HELLO fragmentation, optional real backend-MTU evidence, TX-notify reassembly, RSP correlation, and transfer-scoped ACK/event cursors. An unknown backend MTU remains unknown; it is never replaced with 247 as evidence. |
| `_pble_bench.py` | Shared frozen OI-1 operations: strict caps, SHA-256-counter payloads, ESP partition/build arithmetic, reset timing, RUN heap probe, exact PUT/GET timers, offset/byte/CRC verification, retransmit accounting, reliability workload, threshold derivation, and canonical JSON. |
| `oi1_profile_bench.py` | Single-profile OI-1 orchestrator. `baseline` emits one canonical redacted profile fragment; `verify` loads the committed policy, evaluates all nine thresholds, and emits the exact completed `oi1_observation`. It accepts only `esp32-4mb` or `esp32-s3-n16r8`. |
| `f11_reliability_bench.py` | **F-11** multi-file reliability bench: performs mandatory HELLO, uses the board-advertised `window` and `chunk` (current reference `W=8`), uploads N files back-to-back, asserts every file's whole-file CRC (`FILE_PUT_END`) **and** an independent `FILE_STAT` re-verify, and reports a throughput baseline. |
| `file_roundtrip_bench.py` | Upload/download regression bench for the reported 11.9 KiB stall: consumes HELLO caps, supports an exact canonical `--expect-chip`, and now requires contiguous unique GET offsets plus exact bytes/size/CRC. |

## Prerequisites (HIL runner only)

```sh
python3 -m pip install bleak pyserial
```

Plus a board flashed with the exact firmware candidate under test. The current
pre-v1 public release requires the complete operator HIL matrix for both
included exact profiles (`esp32-4mb` and `esp32-s3-n16r8`).
`esp32-c3-4mb` remains unavailable and is not part of this matrix until a later
candidate is exercised on matching real hardware. Neither a serial-port name
nor a chip family alone proves the required flash/PSRAM profile.

For controlled reset samples, select an explicit USB serial adapter for the
same board. The orchestrator uses the common ESP development-board wiring:
**RTS asserts EN/reset low**, while **DTR remains deasserted** so GPIO0 is not
pulled into the ROM bootloader. Confirm that wiring for the exact board before
running. Opening a serial port can toggle control lines, so close Thonny,
`screen`, and other serial monitors first.

## OI-1 profile qualification

The orchestrator always runs the frozen workload:

- 10 scanner-before-reset samples with a 1,000 ms reset hold and 15,000 ms
  discovery timeout, then HELLO and one GC/internal-IDF heap probe each;
- HELLO `mtu=247`, `window=8`, `chunk=229`, with a real backend MTU required to
  agree when the backend exposes one;
- five deterministic 65,536-byte PUT/GET round trips with exact nanosecond
  timer boundaries, strict offsets/bytes/size/CRC, then one heap probe each;
- a separate 20 × 16,384-byte byte-verified reliability run and final heap
  probe; and
- one interactive physical power-cycle advertising check.

It creates the raw log with exclusive-create semantics. Use a new,
access-controlled path for every attempt; the log deliberately excludes the
BLE address, serial path, device ID, and personal label. The output is written
atomically as sorted, two-space-indented UTF-8 JSON with one final LF.

Before the first policy exists, stage the exact measurement inputs from two
fresh clean build roots:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  create-baseline-inputs <primary-build-root> <private>/oi1-inputs \
  --reproducibility-build-root <second-build-root> \
  --repo-root ../../..
```

This validates all three maintained ESP32 build targets and both retained
source trees, but emits only `esp32-4mb` and `esp32-s3-n16r8`. Use each
profile's staged `firmware.bin`, `manifest.json`, `application.bin`, and
`partition-table.bin` as the one immutable input set for the baseline run.
The output is deliberately not a candidate or website artifact.

Example baseline for the classic 4 MB profile:

```sh
python3 oi1_profile_bench.py \
  --mode baseline \
  --profile esp32-4mb \
  --expect-chip esp32 \
  --address <BLE-UUID-or-MAC> \
  --reset-port /dev/cu.usbserial-<adapter> \
  --application-bin <candidate>/esp32-4mb/application.bin \
  --partition-table-bin <candidate>/esp32-4mb/partition-table.bin \
  --board-manufacturer Espressif \
  --board-model "<exact board model>" \
  --module-marking ESP32-WROOM-32 \
  --device-flash-capacity-bytes 4194304 \
  --device-psram-capacity-bytes 0 \
  --firmware-sha256 <64-lowercase-hex> \
  --manifest-sha256 <64-lowercase-hex> \
  --ble-backend "Bleak CoreBluetooth <version>" \
  --ble-adapter "Mac built-in Bluetooth <description>" \
  --raw-log <private>/esp32-4mb-raw.jsonl \
  --output <private>/esp32-4mb-baseline-profile.json
```

For the owned N16R8 S3, change the identity arguments to:

```text
--profile esp32-s3-n16r8
--expect-chip esp32-s3
--device-flash-capacity-bytes 16777216
--device-psram-capacity-bytes 8388608
```

Baseline output is deliberately one **profile fragment**, not a release
approval and not a malformed one-profile substitute for the frozen
two-profile baseline envelope. Retain both successful fragments, then assemble
the envelope and policy without hand-editing JSON:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  assemble-oi1-baseline \
  <private>/oi1-inputs \
  <private>/esp32-4mb-baseline-profile.json \
  <private>/esp32-s3-n16r8-baseline-profile.json \
  --repo-root ../../.. \
  --created-at 2026-08-01T00:00:00Z
```

The helper obtains the common source commit and firmware version from the
clean proof checkout, binds both fragments to the staged bytes, creates the
canonical commit-scoped evidence file, and atomically updates
`firmware/qualification/oi1-gates.json` with mechanically derived thresholds.
Review and commit both generated files together. The individual bench command
also prints its derived thresholds for review; neither fragment nor assembled
baseline is release approval.

After that policy exists, run the exact final candidate in verify mode:

```sh
python3 oi1_profile_bench.py \
  --mode verify \
  --policy ../../../firmware/qualification/oi1-gates.json \
  --profile esp32-4mb \
  --expect-chip esp32 \
  --address <BLE-UUID-or-MAC> \
  --reset-port /dev/cu.usbserial-<adapter> \
  --application-bin <candidate>/esp32-4mb/application.bin \
  --partition-table-bin <candidate>/esp32-4mb/partition-table.bin \
  --board-manufacturer Espressif \
  --board-model "<exact board model>" \
  --module-marking ESP32-WROOM-32 \
  --device-flash-capacity-bytes 4194304 \
  --device-psram-capacity-bytes 0 \
  --firmware-sha256 <64-lowercase-hex> \
  --manifest-sha256 <64-lowercase-hex> \
  --ble-backend "Bleak CoreBluetooth <version>" \
  --ble-adapter "Mac built-in Bluetooth <description>" \
  --raw-log <private>/esp32-4mb-final-raw.jsonl \
  --output <private>/esp32-4mb-final-observation.json
```

Verify output is the exact `oi1_observation` object for insertion by the
release finalizer. It does not edit a policy, release bundle, or HIL report.
Any workload, integrity, threshold, or physical-power-cycle failure exits
non-zero without writing a successful observation.

After all other protected-candidate checks pass, put each verify observation
and that profile's bounded operator metadata/checks into one completion JSON
fragment, then create the completed report without editing Markdown:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  assemble-hil-report \
  <private>/candidate-v0.4.2 \
  <private>/esp32-4mb-hil-completion.json \
  <private>/esp32-s3-n16r8-hil-completion.json \
  <private>/completed-HIL_REPORT.md \
  --qualification-repo-root ../../..
```

The completion fragment has only mutable board/operator/environment fields,
six operator-demonstration checks (all `passed`), `oi1_observation`, and the
redacted console log. The helper computes the selected candidate digest,
copies every frozen identity/policy/build field, and derives the
`footprint_reliability` pass only after validating the observation.

The C3 profile is intentionally refused by the CLI. A source build or license
audit for `esp32-c3-4mb` is not HIL evidence and cannot enable that profile.

## Standalone diagnostic benches

These remain useful for discovery and a shorter diagnostic run:

```sh
# discover boards (filtered to the PyBLE service UUID)
python3 f11_reliability_bench.py --scan

# reliability run: 20 files x 16 KiB, back-to-back
python3 f11_reliability_bench.py \
  --address <UUID/MAC> --expect-chip esp32-s3 --files 20 --size 16384

# prove SEC-11 (identity never gates access) — set a label mid-run
python3 f11_reliability_bench.py \
  --address <addr> --expect-chip esp32-s3 --relabel "bench-board"

# exact upload/download byte round trip
python3 file_roundtrip_bench.py \
  --address <UUID/MAC> --expect-chip esp32-s3 --size 12190
```

Exit `0` = reliability PASS. Non-zero = a file failed whole-file integrity, or a
**supplied** throughput floor was not met.

## Standalone throughput floors

The older F-11 diagnostic reports throughput and applies a pass/fail floor only
when the caller explicitly supplies one:

```sh
python3 f11_reliability_bench.py --address <addr> --tput-floor-bps 4000
# or: PYBLE_TPUT_FLOOR_BPS=4000 python3 f11_reliability_bench.py --address <addr>
```

With no floor, its throughput is report-only. Release qualification instead
uses `oi1_profile_bench.py` and the committed per-profile OI-1 policy.

## Release use and limits

- HELLO caps serialization is frozen. The F-11 bench requires a successful
  HELLO, parses positive `window` and `chunk` values, uses them by default, and
  may accept only a smaller explicit diagnostic override. The current reference
  agent advertises `W=8`; `file_roundtrip_bench.py` retains `W=4` only as a
  conservative compatibility fallback if a legacy caps payload omits `window`.
- `chip` uses canonical PBLE/1 target IDs: `esp32`, `esp32-s3`, or `esp32-c3`.
  It remains display/reference metadata rather than an app allowlist; the
  `--expect-chip` option is an operator guard for a specific HIL run.
- The OI-1 orchestrator covers the machine resource/performance workload only.
  Browser erase/install, deliberately interrupted recovery, app
  edit/save/run/console/STOP/soft-reboot, NeoPixel, and operator sign-off remain
  separate required rows in the versioned `HIL_REPORT.md`.
