# PyBLE — `esp32-c3-4mb` engineering qualification

Status: **C3-G0–C3-G7 FROZEN (`[docs]` 2026-08-12); all results PENDING**.
This is the derived engineering contract for the existing ESP32-family native
agent on one matching physical reference. It implements
[ADR-0032](../../../decisions/0032-qualify-generic-esp32-c3-4mb-on-reference-hardware.md)
under the authoritative ESP32-family
[firmware requirements](../specs.md). It neither creates a new port/image nor
claims that C3 is qualified. [ADR-0033](../../../decisions/0033-qualify-v060-as-five-profile-heterogeneous-release.md)
now selects this existing profile for the atomic v0.6.0 candidate, but its row
is admitted to a qualified public bundle only after every gate below passes on
the final hash-locked bytes.

## C3.1 Scope and exact reference

| Identity layer | Frozen qualification value |
|---|---|
| Physical carrier | User-owned dual-Type-C ESP32-C3 development carrier; vendor listing retained only as procurement/reference evidence |
| Module | **ESP32-C3-MINI-1-N4**; operator-observed `C3N4` marking |
| Embedded chip revision | **v0.4**; MUST also satisfy the generic profile's v0.3-or-newer runtime/tool probe |
| Flash | **4,194,304 bytes (4 MiB)** addressable flash |
| PSRAM | **0 bytes; no PSRAM assumed or required** |
| PyBLE build variant | `esp32-c3` |
| IDF target | `esp32c3` |
| Upstream MicroPython board | generated `PYBLE_ESP32_C3` overlay target |
| Provisioning profile under qualification | `esp32-c3-4mb` |
| PBLE/1 `chip` value | `esp32-c3` |
| Agent version | Canonical `versions.lock [pyble].agent_version`, currently `0.6.0`; identical across every maintained ESP and RP2 build target |

The module facts are cross-checked against Espressif's
[ESP32-C3-MINI-1 series table](https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.html);
the carrier description is the
[ControllersTech dual-Type-C listing](https://shop.controllerstech.com/products/esp32-c3-dual-type-c-wifi-bluetooth-ble-5-0-devkitm-1-core-development-board).
Qualification evidence records the physical marking and machine-reported chip
revision/flash facts, not merely these URLs.

This reference qualifies only the generic silicon/memory profile. The carrier
name, USB bridge/layout, buttons, LEDs, and pin routing do not enter the build,
PBLE/1 caps, app connection policy, or generic compatibility claim. No
reference-board file is added below `firmware/board_overlays/`; all target
differences remain in the existing `esp32-c3` overlay.

## C3.2 Evidence and candidate binding

Every attempted result MUST bind to one immutable input set:

- full 40-hex source commit, clean-tree state, `versions.lock` bytes, agent
  version, MicroPython commit, and ESP-IDF commit;
- SHA-256 and byte length of `firmware.bin`, `micropython.bin` (application),
  bootloader, partition table, manifest where applicable, and build provenance;
- exact non-personal module/carrier description and probed revision, flash, and
  PSRAM facts; and
- for app HIL, app version/build number, platform/OS major version, and
  firmware SHA-256.

The connected-device preflight MUST resolve one explicit serial target, prove
it is the intended C3 before erase/write, and ensure no other process owns the
port. Evidence committed to the public repository MUST omit serial-device
paths, BLE addresses, MAC/device IDs, personal labels, raw INFO, raw console
output, and other owner-identifying data. Private raw logs remain
access-controlled and are never release artifacts.

An observation from different bytes, a dirty build, a stale build directory,
another C3 module/memory tuple, classic ESP32, or ESP32-S3 cannot fill a gate.

## C3.3 PHY-calibration persistence policy (FROZEN)

The `esp32-c3` overlay MUST explicitly disable
`CONFIG_ESP_PHY_CALIBRATION_AND_DATA_STORAGE`. The pinned ESP-IDF therefore
performs full PHY calibration on every boot instead of retaining calibration
data in NVS. ESP-IDF documents approximately 100 ms for a full calibration;
that cost is accepted inside the unchanged 3,000 ms reset ceiling. None of the
frozen reset, heap, reliability, or throughput thresholds may be relaxed to
adopt this policy.

This C3-only setting removes a state-dependent qualification failure. A sealed
A/B/A diagnostic held the application and VFS bytes exact and showed that the
two-page PHY-calibration NVS state alone reduced both current and minimum-ever
internal heap by 312 bytes, from 67,148/63,556 bytes to 66,836/63,244 bytes.
The latter minimum crosses the frozen 63,488-byte floor. PyBLE does not require
persisted PHY calibration, and NVS remains available for ordinary application
state; this policy only prevents ESP-IDF from creating the `phy` namespace and
rewriting its calibration entry on this profile.

Every candidate using this setting MUST receive a full-chip erase before the
exact verified install. An application-only reflash can retain the old PHY NVS
pages and does not qualify the fixed bytes. After the erased install, the
existing 10 controlled C3-G4 reset samples MUST still pass the 3,000 ms ceiling
and every frozen heap floor. A read-only NVS namespace/key/type inventory taken
after those repeated resets MUST pass partition integrity checks and contain no
written `phy` namespace or key; values are neither required nor retained as
public evidence. The C3 private-result writer MUST require that inventory as a
stable, exclusive mode-`0600` canonical receipt. It derives and stores the
receipt's exact SHA-256 and byte length plus a candidate-bound summary; the
summary binds the candidate release and firmware digests, the exact OI raw-log
digest, 10 reset samples, NVS offset `0x9000`, size `0x6000`, integrity pass,
and the complete written namespace list. The writer rejects a missing,
changed, malformed, non-exclusive, wrong-candidate, wrong-offset,
wrong-size, integrity-failed, or `phy`-containing receipt. Finalization MUST
cross-check its OI raw-log binding against the completed C3 observation. The
public summary omits the private receipt body; its private-result digest binds
the validated receipt transitively. The application and VFS regions remain
subject to their existing exact-byte and functional checks.

The existing V5 `provisioning_install: passed` check remains the mechanical
full-chip-erase/install attestation and MUST still be present. The NVS receipt
does not duplicate or replace that check.

## C3-G0 — Identity, build, and install (FROZEN)

1. Operator inspection records `ESP32-C3-MINI-1-N4`/`C3N4`; the connected-chip
   probe reports ESP32-C3 silicon compatible with revision v0.4 and never below
   the profile minimum v0.3; the flash probe reports exactly 4,194,304 bytes;
   build/runtime inspection proves no PSRAM is selected or relied upon.
2. `firmware/scripts/build.sh esp32-c3` starts from the pinned, clean inputs,
   maps only to `esp32c3` and the existing `PYBLE_ESP32_C3` overlay, and emits
   the standard ESP artifact/provenance set. Its resolved manifest contains the
   common agent and upstream `neopixel` exactly as specified, with zero
   Waveshare display/splash inputs.
3. Two fresh retained build roots produce byte-identical application and
   merged images and pass the existing SHA drift, source/no-leak, SPDX,
   license, partition arithmetic, reproducibility, and build-provenance gates.
   The factory application fits its `0x1f0000` partition; no numeric C3 release
   ceiling is invented before C3-G4.
4. The exact candidate is installed through the documented erased ESP32
   provisioning path and verified byte-for-byte where the existing installer
   contract requires it. Merely booting an old or locally altered image fails
   the gate.

## C3-G1 — Generic BLE and lifecycle smoke (FROZEN)

On erased install, controlled reset, and physical power-on, the exact candidate
MUST:

- advertise the PyBLE service and a non-personal default `PyBLE-XXXX` name;
- be found by service-UUID-filtered scan, connect, negotiate HELLO first, and
  return protocol/caps with `chip = "esp32-c3"`, the candidate agent version,
  the actual MicroPython version, valid `fs_root`, positive file/chunk/window
  limits, and internally consistent INFO/HELLO payloads;
- accept an ATT MTU request of 247 while retaining correct operation down to
  the BLE default MTU;
- disconnect, re-advertise, reconnect, and complete HELLO again under the
  existing reset-to-discovery timeout; and
- remain independent of carrier identity: the app uses only PBLE/1 discovery
  and capability negotiation, with no new C3 or carrier allowlist.

Cold boot remains safe with missing, invalid, and infinite-loop `/main.py`
content; autorun is off until explicitly enabled. Each safe-boot/recovery
variant MUST return the control plane to advertising.

## C3-G2 — RUN, console, and authoritative STOP (FROZEN)

The same candidate MUST pass file and inline-source RUN, stdout and stderr
streaming, `CONSOLE_INPUT`, normal `RUN_STATE(done)`, exception traceback then
`RUN_STATE(error)`, idempotent STOP while idle, and one subsequent clean RUN
after every stopped workload.

Two separate runaway workloads are mandatory:

```python
while True:
    pass
```

```python
while True:
    print("x")
```

For each workload, measure from host submission of the complete STOP command
until receipt of the terminal state. The on-wire result MUST contain exactly
one matching `RSP{OK}` before `RUN_STATE(idle)`; the idle event MUST arrive in
**less than 500 ms**. No `done` or `error` state may follow that STOP, the link
MUST remain usable, and a subsequent bounded RUN/console exchange MUST pass.

The print-flood case freezes a transport priority invariant. At the minimum
ATT MTU, both the STOP response and one-byte terminal RUN_STATE each fit one
notification fragment. `CONSOLE_DATA` MUST leave the four `msys_1` blocks
concurrently owned from receipt of the acknowledged STOP write through its
small control notification: incoming request, preallocated ATT write response,
PBLE/1 response data, and ATT notification wrapper. The STOP response submits
first; paced terminal idle then reuses the blocks returned as that transaction
drains. Bulk traffic MUST permit a pending STOP response to pre-empt the next
console message promptly. The specialized response may wait under one
absolute **15 ms** deadline only for the complete-message TX-mutex owner that
was current when STOP became pending; later ordinary/bulk messages MUST NOT
begin ahead of it. After acquiring that boundary it revalidates the session and
makes exactly one local Notify submission, with no wait or retry for mbuf/
controller capacity. The boundary budget does not replace the four-block
capacity reserve. Pre-emption occurs only at a
complete PBLE/1 message boundary: fragments of the current message remain
contiguous, no control fragment is inserted into a bulk message, and the app's
single reassembly buffer never sees interleaved messages. The implementation
MUST also bound console notifications already accepted into the ESP
host/controller path, because local Notify acceptance is not proof of delivery
to the central. The console tee admits its first notification immediately and
then admits at most one notification every **40 ms**. Each interval begins from
the completion time of the preceding paced attempt, never from an older
schedule, so delayed attempts cannot produce a catch-up burst. The interval
wait releases the MicroPython GIL and holds no physical TX mutex. A newly
staged chunk captures its exact live session once before that wait; immediately
after the wait the worker rechecks STOP before submission, and neither a retry
nor a disconnect/reconnect may refresh or retarget the captured session. An
offline chunk is omitted without waiting and clears the pacing deadline, as
does VM reset; every access to that 64-bit deadline MUST be synchronized on
32-bit ESP targets. The implementation MAY additionally discard bounded bulk
output during a deliberate flood. Retaining every flood byte is not a gate;
preserving bounded memory, the four-block reserve, STOP delivery/order, valid
reassembly, and a live control plane is. The 40 ms limit is console-only and
does not pace control or filesystem traffic, weaken the strict 500 ms gate, or
change the specialized response's single 15 ms boundary budget.

## C3-G3 — Files, reliability, and resume (FROZEN)

Using paths confined to `fs_root`, the candidate MUST pass:

1. `FILE_LIST`, `FILE_STAT`, `FILE_GET`, windowed `FILE_PUT`, `MKDIR`,
   `FILE_RENAME`, and `FILE_DELETE`, including missing-path/error mapping and
   path-jail/control-plane-write rejection;
2. exact upload and download byte/size/whole-file-CRC verification at the
   advertised `window` and `chunk`, with temp-write-then-rename preserving the
   old destination until successful commit;
3. the frozen **20 files × 16,384 bytes** reliability workload with 20 exact
   completions, zero corruption, zero failed statuses, and zero unexpected
   disconnects; and
4. a deliberate link drop after a nonzero contiguous upload prefix, followed
   by fresh scan/connect/HELLO, a `FILE_PUT_BEGIN` returning that verified
   nonzero `resume_offset`, completion from the offset, and exact final bytes,
   size, and CRC. A mismatched/foreign prefix MUST end in `ECRC`, delete the
   temp, and retain the prior destination byte-for-byte.

No throughput floor is inferred from these functional observations. Numeric
goodput gates come only from C3-G4.

## C3-G4 — Independent OI-1 engineering baseline (FROZEN)

The C3 reference runs the complete frozen workload and metric definitions in
[firmware specs §5.3](../specs.md#53-footprint-gates-nfr-fp): two independent
clean builds; 10 controlled reset/HELLO/heap snapshots; five deterministic
65,536-byte PUT/GET round trips and post-round-trip heap snapshots; the one
20 × 16,384-byte reliability workload and final heap snapshot; and a physical
power-cycle advertising check. Thus every C3 heap floor derives from exactly
16 snapshots, reset retains the fixed 3,000 ms product ceiling, application
bytes/headroom remain exact, and PUT/GET floors use the existing integer 5%
allowance and outward 100-byte/s quantization. No sample from another profile
may enter a C3 threshold.

The C3 transfer connection MUST settle the same link-fact contract before
timing. C3 requires the BLE 2M rung: `phy.required_2m = true`, request attempts
are `1..4`, at least one update is retained, and settled TX/RX are exactly
`2`/`2`; DLE and connection interval use the frozen §5.3.1 bounds. A failed or
unsettled rung produces no baseline result.

**Retained session evidence — FROZEN (2026-08-16 · `[docs]`,
[ADR-0035](../../decisions/0035-read-c3-link-facts-through-run.md)).** The C3
image enables the same bounded, hidden `pble_ble._oi1_link_facts()` state as
the exact Waveshare profile. The WCH bridge remains the mandatory RTS-to-EN
reset/release adapter, but its received bytes are private diagnostics only and
MUST NOT authorize a C3 session boundary or link fact. After each of reset
samples 1–9 disconnects, one diagnostic BLE successor must expose the ended
session and its exact non-wrapping active successor through the strict `pair`
RUN projection. Reset ten uses the strict `active` projection to bind settled
facts before timing and again before disconnect; one final diagnostic `pair`
must expose that exact transfer epoch as immutable `last_ended`. Null, stale,
wrapped, non-successor, malformed, overflowed, or wrong-epoch state fails
closed with no retry. Classic ESP32 retains the unchanged 2,000 ms UART
terminal gate; generic S3 follows
[ADR-0036](../../decisions/0036-read-generic-s3-link-facts-through-run.md), and
C3 neither lengthens nor consumes the classic gate.

The output is a redacted, canonical **C3 engineering profile fragment** bound
to the source and exact firmware/manifest bytes, plus mechanically derived C3
thresholds. It is not inserted into the historical schema-2 three-profile
policy, does not mutate historical evidence, and is not final-candidate
verification. ADR-0033 supplies the successor contract: one controlled
five-profile baseline atomically creates the schema-3 policy, after which the
final v0.6.0 candidate is rebuilt and this C3 profile reruns verify-mode HIL on
those different, hash-locked bytes.

## C3-G5 — Real app HIL on both platforms (FROZEN)

One physical iPad and one physical Android tablet MUST each, in separate runs
against the same firmware digest and using an identified PyBLE app build:

- find the board through the ordinary service-filtered scan, connect, complete
  HELLO, and display the verbatim `esp32-c3` target without an app allowlist;
- create/edit/save a Python file, run it, display live stdout, and observe the
  correct terminal state;
- invoke Stop through the real UI against both a tight loop and a print flood,
  receive `RSP{OK}` then idle inside the C3-G2 bound, and remain connected;
- upload/read back a file with exact content, disconnect, reconnect, and see
  the same workspace; and
- surface every BLE/PBLE failure honestly rather than converting a timeout or
  missing event into success.

Simulator, fake transport, host CLI, or one mobile platform standing in for
the other fails this gate. Device serials, BLE addresses, and owner data are
not retained in public evidence.

## C3-G6 — Operator-supplied GPIO8 NeoPixel observation (FROZEN)

This gate applies only to the exact connected reference carrier. Before any
GPIO operation, the operator MUST independently confirm from that carrier's
pinout/wiring that its single onboard NeoPixel data input is GPIO8. Through the
ordinary, manually selected generic Blocks example, the operator explicitly
enters GPIO **8** and pixel count **1**. Generated source MUST use only standard
MicroPython APIs equivalent to:

```python
from machine import Pin
from neopixel import NeoPixel

pixel = NeoPixel(Pin(8), 1)
```

A bounded red/green/blue/off sequence is run through the normal app path; the
operator confirms the visible sequence and the final off state, and the link
remains responsive to INFO/STOP. Import before and after soft reboot MUST also
pass FR-LIB-1.

GPIO8 is not a firmware default, app suggestion, pin profile, Identify setting,
PBLE/1 capability, or generic C3 promise. The board runtime validates the
user-entered pin. Another `esp32-c3-4mb` carrier may have no NeoPixel or route
one elsewhere and can still satisfy the generic profile through its own
explicit user wiring.

## C3-G7 — Qualification result and release separation (FROZEN)

Only one candidate with C3-G0 through C3-G6 all passing may be described as
**engineering-qualified on the ESP32-C3-MINI-1-N4 reference**. Open, failed,
mixed-candidate, or partly manual results retain `pending`/`failed`; a source
build is never promoted to HIL evidence.

ADR-0033 is the separate spec-first public-admission decision anticipated by
ADR-0032. It does not waive or pre-pass this matrix. C3 may enter the v0.6.0
qualified public selector only when all of the following bind the same final
candidate: C3-G0…C3-G6; the schema-3 resource row; both iPad and Android app
HIL; erased Web Serial install and interrupted-flash recovery; full build,
license, and two-root reproducibility gates; `PYBLE_HIL_RECORDS_V5`
finalization; and explicit release approval. Its V5 C3 summary is `null` in
the candidate and may become `passed` only when the finalizer derives it from
validated private evidence.

Until that completes, the authoritative status remains **pending; no
qualified public C3 image**. The historical v0.4.2 and v0.5.1 contracts remain
unchanged, and no partial C3 result may mutate or reinterpret them.

<!-- SPDX-License-Identifier: MIT -->
