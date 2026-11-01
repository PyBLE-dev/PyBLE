<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Firmware v0.7 development — committed run/session status

Started 1 November 2026 following the user's implementation request and the
preceding recommendation to deliver PYB-017.1 → PYB-018 first. The user supplied
Lenovo, iPad and all five existing boards for physical work. This record owns
selected-increment evidence; it does not announce a full firmware release.

## Selected scope and identities

| Item | Selection |
|---|---|
| Firmware | Source-selected development identity `0.7.0-dev.1`; existing upstream pins retained |
| Companion app | Development source `0.4.0+10`; isolated `dev.pyble.firmwarequalification` installations preserve store apps |
| Contract | [PBLE/1 §6.1](../../../specifications/protocol.md#61-additive-runsession-status--selected-v07-increment), [ADR-0049](../../../decisions/0049-query-run-state-after-reconnect.md) |
| Tracking | [Milestone2](https://github.com/PyBLE-dev/PyBLE/milestone/2); agents [#44](https://github.com/PyBLE-dev/PyBLE/issues/44), app [#45](https://github.com/PyBLE-dev/PyBLE/issues/45), physical verification [#46](https://github.com/PyBLE-dev/PyBLE/issues/46) |
| Implementation | Native/portable agents, shared vectors, capability-gated query/events, initial app synchronization, revision merge/cache and bounded refresh |
| Remaining roadmap | Transfer status/abort, directory enumeration, project execution, diagnostics/loss and any new recovery operation remain proposed |
| Release boundary | Physical functional evidence and complete firmware release admission are separate; no production firmware or app-store publication by this work |

The problem is observable in the current contract: RUN_STATE events created
without a live session are omitted, so reconnect cannot infer idle from silence.
Status must report committed admission rather than a provisional reservation.
Random boot identity is ephemeral correlation, with no hardware identity or
authorization role. Existing 24 operations retain their encodings.

## Work and verification

| Task | State / required evidence |
|---|---|
| Normative contract and shared vectors | Committed before dependent implementation: `27811da` |
| Native implementation | Signed red/green commits; compiled lifecycle/wire/default-MTU/transport regression tests pass; integrated |
| Portable implementation | Signed red/green commits; shared vectors and real dispatcher/runner races pass; integrated |
| Companion app | Initial synchronization, cached controls and bounded refresh integrated; 1,028 ordinary tests and analysis passed before an additional reconnect race was reproduced and entered red/green correction |
| Exact builds | All four ESP variants and Pico 2 W built successfully from frozen `1093bab3de811469c14bb1b8e77d4f91b29fa962` with the pinned toolchains |
| Hardware backup | Full-flash backups verified for classic ESP32, generic S3, C3 and Pico; Waveshare USB recovery still requires operator action |
| Physical status bench | Pico and classic ESP32 pass the physical Mac BLE cases; remaining profiles and actual ATT23 Android cases pending |
| Both-tablet compatibility | Isolated development app installed on both tablets; both legacy-agent C3 Run/Stop rows pass; corrected-runtime and new-firmware rows pending |
| Complete release admission | Not claimed; normative resource/recovery/workspace/provenance and release gates require their own exact evidence |

Parallel work uses separate integration/native/portable/app Git worktrees under
ignored `local/v070/`. No generated binaries, signing material, raw UI captures
or private physical identities belong in Git. Retain failures alongside passes.

### Recorded tracking-order deviation

The protocol/specification commit preceded behavior tests and implementation.
The focused GitHub milestone/issues were created after initial red/green work
had begun, although roadmap §9 orders issue creation first. The actual ordering
is preserved here; later tracking does not retroactively satisfy that ordering
and creates no precedent to waive the requirement.

## Hardware evidence matrix

All five service-filtered advertisements and baseline HELLOs were observed on
1 November; each reported agent0.6.1 without the new capability. Both tablets
were available. The C3 USB endpoint initially was absent and later appeared;
ROM identity was verified before its full-flash backup. A USB port name alone
never establishes a profile. Programming preserves the workspace: Pico readback
compares every byte outside the UF2 program footprint; ESP programming compares
all complementary flash ranges before and after exact component writes.

| Exact profile | Verified backup / candidate installation | Mac status bench, command fragments23/247 | Lenovo new app | iPad new app | Cross-version evidence |
|---|---|---|---|---|---|
| esp32-4mb | Full4MB verified; candidate components/readback and protected ranges verified | Pass / pass; actual ATT247 for both | Pending corrected app | Pending corrected app | Old client on candidate pending |
| esp32-s3-n16r8 | Full16MB verified; programming in progress | Pending | Pending | Pending | Pending |
| waveshare-esp32-s3-lcd-147b | USB recovery unresolved; no verified backup or candidate write | Pending | Pending | Pending | Pending |
| esp32-c3-4mb | Full4MB verified; old0.6.1 retained through both legacy fallback rows; candidate programming next | Pending | Old-agent fallback pass | Old-agent fallback pass | New app on old agent passed on both tablets; old client on candidate pending |
| rpi-pico2-w | Full4MB verified; candidate program footprint and unchanged remaining flash verified | Pass / pass; actual ATT247 for both | About/HELLO observed only; full row pending | Pending | Old client on candidate pending |

The two Mac packet-size runs do **not** establish ATT23: the actual backend and
HELLO MTU were247. The bench records backend MTU, negotiated MTU and command
fragment limit separately. Its passing cases cover exact empty-query grammar,
an ongoing run recovered after reconnect with the same boot/run identity,
STOP/idempotence, completed/error terminals and VM boot-token rotation.
Actual Android ATT23/247 requires the independently observed GATT MTU and HELLO
value plus the expected two/one fragments of the tagged status event. Protocol
central evidence remains separate from normal tablet UI evidence.

### Frozen artifact identities

These are private development artifacts, not public release admissions. The
executed firmware is frozen at the source commit above; later host validator,
harness and documentation fixes do not substitute rebuilt binaries silently.

| Artifact / receipt | SHA-256 |
|---|---|
| Four-variant ESP build matrix receipt | `aa56c6526ec87ebd963d8cb9db86b8ab9e0d3e2069b1fc08ef500f74a45a7a1e` |
| Pico artifact receipt | `2b715f8af5b6e73222f4364278ecca25485a5f1c24ebde4bf5be6948ecb01fb1` |
| Pico firmware.bin (865,148 bytes) | `dc4041d956768b38e7e918d8679a56fb71c9dfa7a692070f0a36041ff8228caf` |
| Pico firmware.uf2 | `dcb7cc5e25724e65826dbcc7a59028d25dcd6e991c71db7a009d7fbb84bcff29` |

### Failures retained and corrected

- The first Pico bench incorrectly attempted to confirm MTU23 against a real
  ATT247 backend. It failed before RUN. Red/green correction introduced a
  command-fragment limit without weakening actual MTU confirmation.
- The initial complete host run exposed missing local pinned MicroPython
  dependencies and stale candidate/version/native-source inventory checks.
  Both exact dependencies were initialized; strict source admission now lists
  the new C module explicitly. Current-candidate assertions and SemVer-aware
  runtime validation were corrected while historical0.6.1 fixtures remain
  explicitly source-bound. Complete reruns are in progress.
- A normal iPad legacy run initially used an invalid automation-entered buffer
  and raised SyntaxError. The retained failure is not counted as a pass. Exact
  buffer verification and normal UI correction preceded the valid subsequent
  Run/console/Stop pass; the extra paired-character input remains under review.
- A delayed automatic app status query from a retired generation could retire
  a newly synchronized session. Source review and a failing regression
  reproduced it; generation-scoped correction precedes further tablet rows.

Raw results and manifests stay in ignored `local/v070/`. Fill rows only from
actual retained artifacts and observations. A host test or Mac BLE probe is
not a tablet row. Existing October app-only evidence remains historical input.

The Android production audience/CDM decision and previous store reviews remain
separate from this firmware development work. The new companion app is neither
a production update nor a resolution of that audience decision.
