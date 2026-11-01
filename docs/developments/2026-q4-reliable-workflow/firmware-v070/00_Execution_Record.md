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
| Portable implementation | Signed red/green commits; shared vectors and real dispatcher/runner races pass; integrated; final parity review underway |
| Companion app | Signed red/green commits; initial synchronization, cached controls and bounded refresh; ordinary tests and analysis pass; device builds underway |
| Hardware backup | Pico full-flash verified and returned to runtime; ESP non-erasing backups underway |
| Physical status bench | Implemented with strict shared-vector validation; actual candidate results pending builds |
| Both-tablet compatibility | Pending exact candidate installation and per-profile evidence |
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
ROM identity must be verified before its backup/programming. A USB port name
alone never establishes a profile.

| Exact profile | Verified backup | New firmware status bench MTU23/247 | Lenovo new app | iPad new app | Legacy app / fallback |
|---|---|---|---|---|---|
| esp32-4mb | In progress | Pending build | Pending | Pending | Pending |
| esp32-s3-n16r8 | In progress | Pending build | Pending | Pending | Pending |
| waveshare-esp32-s3-lcd-147b | In progress | Pending build | Pending | Pending | Pending |
| esp32-c3-4mb | In progress | Pending build | Pending | Pending | Pending |
| rpi-pico2-w | Verified full4MB backup | Pending build | Pending | Pending | Pending |

Raw results and manifests stay in ignored `local/v070/`. Fill rows only from
actual retained artifacts and observations. A host test or Mac BLE probe is
not a tablet row. Existing October app-only evidence remains historical input.

The Android production audience/CDM decision and previous store reviews remain
separate from this firmware development work. The new companion app is neither
a production update nor a resolution of that audience decision.
