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
| `_pble_bench.py` | Shared frozen OI-1 operations: strict caps, SHA-256-counter payloads, ESP partition/build arithmetic, reset timing, RUN heap probe, exact PUT/GET timers, offset/byte/CRC verification, retransmit accounting, reliability workload, source-era fixed performance SLOs, static/heap threshold derivation, and canonical JSON. |
| `oi1_profile_bench.py` | Single-profile OI-1 orchestrator. `baseline` emits one canonical redacted profile fragment; `verify` loads the committed policy, evaluates the target-specific thresholds, and emits the exact completed `oi1_observation`. Its v0.6 catalog is the four ESP profiles plus `rpi-pico2-w`; RP2 uses its own build, heap, reset, and BTstack adapter. |
| `f11_reliability_bench.py` | **F-11** multi-file reliability bench: performs mandatory HELLO, uses the board-advertised `window` and `chunk` (current reference `W=8`), uploads N files back-to-back, asserts every file's whole-file CRC (`FILE_PUT_END`) **and** an independent `FILE_STAT` re-verify, and reports a throughput baseline. |
| `file_roundtrip_bench.py` | Upload/download regression bench for the reported 11.9 KiB stall: consumes HELLO caps, supports an exact canonical `--expect-chip`, and now requires contiguous unique GET offsets plus exact bytes/size/CRC. |
| `target_smoke.py` | Target-neutral service/HELLO/DEVICE_INFO/INFO identity smoke. It requires an explicit expected chip, defaults the expected agent to `versions.lock`, and excludes BLE address, device ID, and label from its result line. |
| `target_run_stop.py` | Target-neutral busy-loop and print-flood RUN/STOP lifecycle bench. It proves one matching `RSP{OK}` before one idle event in less than 500 ms, then runs a bounded same-link console nonce before file-mode cleanup. |

## Prerequisites (HIL runner only)

```sh
python3 -m pip install bleak pyserial
```

Plus a board flashed with the exact firmware candidate under test. v0.6.0 is
one atomic five-profile matrix, in this order: `esp32-4mb`,
`esp32-s3-n16r8`, `waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, and
`rpi-pico2-w`. Run them sequentially when USB capacity is limited; they do not
need to be connected simultaneously. A missing profile blocks the whole
release. Neither a serial-port name nor a chip family alone proves the required
board, flash, PSRAM, or provisioning profile.

For controlled reset samples, select an explicit USB serial adapter for the
same board. The orchestrator uses the common ESP development-board wiring:
**RTS asserts EN/reset low**, while **DTR remains deasserted** so GPIO0 is not
pulled into the ROM bootloader. Confirm that wiring for the exact board before
running. Opening a serial port can toggle control lines, so close Thonny,
`screen`, and other serial monitors first.

Pico uses `--operator-reset`, the exact candidate `firmware.bin` and
`firmware.uf2`, and the physical power/reset prompts; it never opens the ESP
reset UART. Its pacing fact is source-bound: capacity `2048` bytes divided by
refill rate `20` bytes/ms has the exact ceiling horizon `103 ms`. The bench
imports and rechecks that runtime formula and records
`console_tx_budget_ms = 103`; it has no pacing-number option. Do not pass the
unrelated ESP native
`250 ms` wait budget or a host-fixture value as Pico evidence.

## OI-1 profile qualification

The orchestrator always runs the frozen workload:

- 10 scanner-before-reset samples with a 1,000 ms reset hold and 15,000 ms
  discovery timeout, then HELLO and one GC/internal-IDF heap probe each;
- HELLO `mtu=247` and `chunk=229`, with `window=8` for ESP and `window=4` for
  Pico, and with a real backend MTU required to agree when exposed;
- on classic ESP32, after each of the first nine disconnects, wait at most
  2,000 ms for
  exactly one parser-owned session-end line, discard every private UART byte
  and the terminal count, and clear residual state; missing or duplicate
  termination fails closed; before the tenth reset, clear the private UART
  input buffer; after that connection's HELLO, wait at most 5,000 ms for strict
  DLE, profile-specific PHY, and connection-interval settlement facts before
  any timed transfer; generic S3, Waveshare, and C3 instead read the exact
  ended/active epoch pair through a bounded diagnostic PBLE/1 RUN after each first-nine
  disconnect, bind and recheck reset ten's active epoch, and seal only that
  epoch's final ended facts after one last diagnostic reconnect; generic S3
  and C3 serial endpoints remain reset/release plumbing and their received
  bytes are never qualification authority; Pico instead retains only the exact BTstack
  transport facts and forbids those ESP-only fields;
- five deterministic 65,536-byte PUT/GET round trips with exact nanosecond
  timer boundaries, strict offsets/bytes/size/CRC, then one heap probe each;
- a separate 20 × 16,384-byte byte-verified reliability run and final heap
  probe, followed by BLE disconnect and at most 2,000 ms for the same session's
  report-only TX-mbuf starvation count; and
- one interactive physical power-cycle advertising check.

For replacement v0.6.0, all 10 reset samples must meet 3,000 ms on each ESP
profile or 7,000 ms on Pico, and all five PUT plus five GET samples must meet
6,600 bytes/s on every profile. There is no trim, replacement, retry, or
post-failure widening. The exact-service callback endpoint, 15-second health
timeout, physical check, byte/offset/CRC integrity, reliability, disconnect
counts, duration arithmetic, and settled link facts remain exact.

It creates the raw log with exclusive-create semantics. Use a new,
access-controlled path for every attempt; the log deliberately excludes the
BLE address, serial path, device ID, and personal label. The output is written
atomically as sorted, two-space-indented UTF-8 JSON with one final LF.
Only classic ESP32 retains parser-owned structured link facts from UART;
arbitrary serial or console lines are discarded rather than copied into
evidence.

Before the first policy exists, stage the exact measurement inputs from two
fresh clean build roots:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  create-baseline-inputs <primary-build-root> <private>/oi1-inputs \
  --reproducibility-build-root <second-build-root> \
  --repo-root ../../..
```

For v0.6.0 this validates all four ESP variants plus RP2 over both retained
clean build roots. It emits four ESP input directories containing
`firmware.bin`, `manifest.json`, `application.bin`, and
`partition-table.bin`, plus `rpi-pico2-w/{firmware.uf2,firmware.bin}`. Use each
profile's staged bytes as its one immutable baseline input set. The output is
measurement input only, never a candidate or website artifact.

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
  --install-sha256 <merged-firmware.bin-64-lowercase-hex> \
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

For the owned Waveshare board, select its distinct image and identity; its
PBLE/1 chip identity remains the underlying `esp32-s3`:

```text
--profile waveshare-esp32-s3-lcd-147b
--expect-chip esp32-s3
--device-flash-capacity-bytes 16777216
--device-psram-capacity-bytes 8388608
```

Never substitute the exact-board image for generic S3 qualification. Only the
Waveshare image contains the TFT driver, board companion, boot splash, QR code,
and exact pin map; the generic S3 image must remain free of all of them.

For C3, use the documented C3N4 reference hardware for the exact
`esp32-c3-4mb` profile, record the observed module marking without expanding
it into an unobserved suffix, and use:

```text
--profile esp32-c3-4mb
--expect-chip esp32-c3
--device-flash-capacity-bytes 4194304
--device-psram-capacity-bytes 0
```

For Pico, use the staged raw image and UF2, the RP2 operator-reset adapter, and
the exact Pico identity:

```text
--profile rpi-pico2-w
--expect-chip rpi-pico2-w
--operator-reset
--firmware-bin <oi1-inputs>/rpi-pico2-w/firmware.bin
--firmware-uf2 <oi1-inputs>/rpi-pico2-w/firmware.uf2
--firmware-sha256 <raw-firmware.bin-64-lowercase-hex>
--install-sha256 <firmware.uf2-64-lowercase-hex>
--device-flash-capacity-bytes 4194304
--device-psram-capacity-bytes 0
```

Do not add `--console-tx-budget-ms`. Pico evidence always uses the frozen
runtime-derived `103 ms` refill horizon, and the CLI rejects an operator
override.

Baseline output is deliberately one **profile fragment**, not a release
approval. The immutable `v0.4.2` evidence remains frozen as its historical
two-profile envelope and must not be broadened or reinterpreted. Initial v0.6.0
baseline assembly used all five source-selected fragments as shown below; the
result at `a8be631….json` is now immutable retained input evidence:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  assemble-oi1-baseline \
  <private>/oi1-inputs \
  <private>/esp32-4mb-baseline-profile.json \
  <private>/esp32-s3-n16r8-baseline-profile.json \
  <private>/waveshare-esp32-s3-lcd-147b-baseline-profile.json \
  <private>/esp32-c3-4mb-baseline-profile.json \
  <private>/rpi-pico2-w-baseline-profile.json \
  --repo-root ../../.. \
  --created-at 2026-08-01T00:00:00Z
```

The helper obtains the common source commit and firmware version from the
clean proof checkout, binds all five fragments to the staged bytes, creates the
canonical commit-scoped evidence file, and atomically updates
`firmware/qualification/oi1-gates.json` with mechanically derived thresholds.
Review and commit both generated files together. The individual bench command
also prints its derived thresholds for review; neither fragment nor assembled
baseline is release approval, and neither claims that `v0.6.0` has completed
exact-byte HIL qualification or is ready for publication.

For the ADR-0037/ADR-0038 pre-publication replacement, do **not** rerun that
baseline merely to fit new performance numbers and do not edit its bytes. The
policy tool reuses the exact `a8be631…` file, derives unchanged static/heap
values from it, retains its reset/goodput arrays diagnostically, and emits the
new fixed identifiers and five rows under the bound replacement
policy/candidate source era. The baseline's `source_commit` never selects the
derivation. The predecessor policy remains reproducible when explicitly
validated against its predecessor candidate source. Only after the checked-in
replacement policy exists and the pre-candidate build/reproducibility/license/
audit gates pass may the local unpublished tag be replaced and the audited
candidate created; fresh five-profile verify HIL follows.

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
  --install-sha256 <merged-firmware.bin-64-lowercase-hex> \
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

After all other protected-candidate checks pass, create C3 and Pico's private
gate results from the exact immutable candidate. Every `--passed-gate` is an
explicit attestation made only after that gate's retained evidence has passed;
the helper derives all identity and digest fields and cannot waive a missing
gate:

```sh
python3 ../../../firmware/qualification/v060_profile_release_gate.py \
  create-result <private>/candidate-v0.6.0 esp32-c3-4mb \
  <private>/esp32-c3-4mb-private-result.json \
  --passed-gate C3-G0 --passed-gate C3-G1 --passed-gate C3-G2 \
  --passed-gate C3-G3 --passed-gate C3-G4 --passed-gate C3-G5 \
  --passed-gate C3-G6

python3 ../../../firmware/qualification/v060_profile_release_gate.py \
  create-result <private>/candidate-v0.6.0 rpi-pico2-w \
  <private>/rpi-pico2-w-private-result.json \
  --passed-gate GP0 --passed-gate GP1 --passed-gate GP2
```

For every profile, combine its verify observation with the bounded canonical
operator input by using `create-hil-completion`. C3/Pico additionally require
their private result; the helper derives `profile_gate_summary` from it and
rejects an operator-authored map. It writes canonical mode-`0600` JSON without
replacement:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  create-hil-completion \
  <private>/candidate-v0.6.0 esp32-c3-4mb \
  <private>/esp32-c3-4mb-operator-input.json \
  <private>/esp32-c3-4mb-final-observation.json \
  <private>/esp32-c3-4mb-hil-completion.json \
  --qualification-repo-root ../../.. \
  --profile-qualification-result \
    <private>/esp32-c3-4mb-private-result.json
```

The workflow-contract host test remains deliberately RED until these two safe
writers land. Do not work around it by hand-authoring a private result,
`profile_gate_summary`, candidate digest, or artifact digest.

After exactly five fragments exist, create the completed report without
editing Markdown:

```sh
python3 ../../../firmware/scripts/release_bundle.py \
  assemble-hil-report \
  <private>/candidate-v0.6.0 \
  <private>/esp32-4mb-hil-completion.json \
  <private>/esp32-s3-n16r8-hil-completion.json \
  <private>/waveshare-esp32-s3-lcd-147b-hil-completion.json \
  <private>/esp32-c3-4mb-hil-completion.json \
  <private>/rpi-pico2-w-hil-completion.json \
  <private>/completed-HIL_REPORT.md \
  --qualification-repo-root ../../..
```

The completion fragment has only mutable board/operator/environment fields,
six operator-demonstration checks (all `passed`), both real-app results,
`oi1_observation`, the derived target gate map where applicable, and the
redacted console log. The report helper computes the selected candidate
digest, copies every frozen identity/policy/build field, and derives the
`footprint_reliability` pass only after validating the observation. A build or
license audit alone is never HIL evidence for C3, Pico, or any other profile.

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

# exact target identity and INFO agreement; expected agent comes from versions.lock
python3 target_smoke.py \
  --address <UUID/MAC> --expect-chip esp32-c3

# busy-loop + print-flood STOP ordering/deadline and same-link recovery
python3 target_run_stop.py \
  --address <UUID/MAC> --expect-chip esp32-c3
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
