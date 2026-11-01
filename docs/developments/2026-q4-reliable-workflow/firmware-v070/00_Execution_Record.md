<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Firmware v0.7 development — committed run/session status

Started 1 November 2026 following the user's implementation request and the
preceding recommendation to deliver PYB-017.1 → PYB-018 first. The user supplied
Lenovo, iPad and all five existing boards for physical work. This record owns
selected-increment evidence; it does not announce a full firmware release.
Progress snapshot: 1 November 2026, 04:15 UTC; final corrected-app evidence is
still being collected.

## Selected scope and identities

| Item | Selection |
|---|---|
| Firmware | Source-selected development identity `0.7.0-dev.1`; existing upstream pins retained |
| Companion app | Development source `0.4.0+10`; isolated qualification bundles preserve store apps and earlier candidates; R3 is frozen at `c4ac9af`, and a transport-corrected R4 is pending |
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
| Companion app | Initial synchronization, cached controls, bounded refresh, generation-scoped failure handling and exact balanced typing integrated; all 1,035 ordinary tests pass at `c4ac9af`. Actual ATT23 exposed interleaved outgoing frames; red/green serialization correction is in progress |
| Exact builds | All four ESP variants and Pico 2 W built successfully from frozen `1093bab3de811469c14bb1b8e77d4f91b29fa962` with the pinned toolchains |
| Hardware backup | Full-flash backups verified for classic ESP32, generic S3, C3 and Pico; Waveshare USB recovery still requires operator action |
| Physical status bench | All four accessible profiles pass both command-fragment limits and autorun/reconnect/STOP with verified restoration. All three ESP profiles also pass tight-loop/console-flood query cases; Pico load and Waveshare pending |
| Both-tablet compatibility | R1 legacy-agent C3 fallback passes on both tablets. R3 Lenovo/Pico and iPad/classic + generic S3 normal UI rows pass; final transport-corrected artifact and remaining rows pending |
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
These comparisons apply to programming. Later owned test-file/configuration
transactions have their own logical restoration checks; they do not imply that
filesystem journal bytes remain identical to the original full-flash backup.

| Exact profile | Verified backup / candidate installation | Mac status bench, command fragments23/247 | Lenovo new app | iPad new app | Cross-version evidence |
|---|---|---|---|---|---|
| esp32-4mb | Full4MB verified; candidate device component MD5 and protected ranges verified | Pass / pass; actual ATT247 for both | Final artifact pending | R3 normal row pass; final artifact pending | Old client on candidate pending |
| esp32-s3-n16r8 | Full16MB verified; exact component MD5/readback SHA-256 and protected ranges verified | Pass / pass; actual ATT247 for both | Final artifact pending | R3 normal row pass; final artifact pending | Old client on candidate pending |
| waveshare-esp32-s3-lcd-147b | USB recovery unresolved; no verified backup or candidate write | Pending | Pending | Pending | Pending |
| esp32-c3-4mb | Full4MB verified; exact component MD5/readback SHA-256 and protected ranges verified | Pass / pass; actual ATT247 for both | Final artifact pending | Final artifact pending | R1 on old0.6.1 passed on both tablets; final artifact and old-client-on-candidate rows pending |
| rpi-pico2-w | Full4MB verified; candidate program footprint and unchanged remaining flash verified | Pass / pass; actual ATT247 for both | R3 normal row pass; final artifact pending | Final artifact pending | Old client on candidate pending |

The two Mac packet-size runs do **not** establish ATT23: the actual backend and
HELLO MTU were247. The bench records backend MTU, negotiated MTU and command
fragment limit separately. Its passing cases cover exact empty-query grammar,
an ongoing run recovered after reconnect with the same boot/run identity,
STOP/idempotence, completed/error terminals and VM boot-token rotation.
Actual Android ATT23/247 requires the independently observed GATT MTU and HELLO
value plus the expected two/one fragments of the tagged status event. Protocol
central evidence remains separate from normal tablet UI evidence.

The four autorun probes refuse an existing `main.py`, enabled autorun or active
program. Each passing receipt proves owned fixture byte/CRC readback, new-boot
origin3, the same run after reconnect, stopped terminal, restored `auto_run=0`,
fixture absence and initial idle after the cleanup reboot. Native load probes
likewise prove the unique stdout execution marker, three coherent active-run
queries and the owned stopped terminal, without files/configuration changes.
Observed query times on those three boards are approximately37–62ms; this is
an observation, not a new performance SLO or the full recovery/resource matrix.

Normal R3 rows use the normal application, paced platform text input and an
exactly verified disposable file. They prove ordinary quoted/bracketed typing
without manually deleting closers, Run, visible console output, explicit
disconnect/reconnect without a new Run/upload, recovered Running controls and
late console state, Stop, owned-file deletion/absence and explicit disconnect.
The iPad Classic row links its original run and corrected navigation/cleanup
receipts; its earlier navigation failure remains retained. R3 evidence does not
silently become evidence for the forthcoming transport-corrected artifact.

On actual Android ATT23, both the GATT and HELLO MTU are23. Six decoded tagged
events have valid CRC,25-byte payloads and two fragments. Run identity survives
query-only reconnect, STOP and normal completion. The overall attempt is still
**failed**, because the next fragmented RUN was interrupted by a concurrent
automatic status query and timed out. At ATT247 a separate attempt reached
Running but its immediate reconnect failed during GATT establishment. Neither
partial attempt is an overall physical PASS.

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
| R3 normal Android APK (`c4ac9af`; private bundle `dev.pyble.firmwarequalification3`) | `5f26ad777d6d1aebc8587575a1f304a952951a319e7dbfa1abda12f10cf76ee9` |
| R3 signed iOS app archive (same source/bundle suffix) | `682dc28864671ee2ea8f2b8cdc265c923f862bd62009bb8f579f8217747fd4dc` |

R3 app tree is `a2b12c7d27e294ecb16ab084d3396b2e186d3c76`. Both real platform
builds and strict iOS signature verification pass. Private build manifests bind
the normal entry point and four reviewed application identity/display overrides.
Earlier functional/autorun receipts do not embed the executing bench SHA; retain
the recorded invocations, unchanged harness content and source history rather
than inventing an embedded provenance field after the run. The load receipts
also record the bench commit explicitly.

### Failures retained and corrected

- The first Pico bench incorrectly attempted to confirm MTU23 against a real
  ATT247 backend. It failed before RUN. Red/green correction introduced a
  command-fragment limit without weakening actual MTU confirmation.
- The initial complete host run exposed missing local pinned MicroPython
  dependencies and stale candidate/version/native-source inventory checks.
  Both exact dependencies were initialized; strict source admission now lists
  the new C module explicitly. Current-candidate assertions and SemVer-aware
  runtime validation were corrected while historical0.6.1 fixtures remain
  explicitly source-bound. The frozen `2db3026` CI firmware-host job passes all
  shell and complete host/release tests. A separate final local run uses an
  immutable `c4ac9af` checkout; newer load/ledger tests also pass independently.
- A normal iPad legacy run initially used an invalid automation-entered buffer
  and raised SyntaxError. The retained failure is not counted as a pass. Exact
  buffer verification and normal UI correction preceded the valid subsequent
  Run/console/Stop pass. Real widget tests then reproduced the extra closers in
  the rich editor. A specification-first adapter correction disables optional
  delimiter insertion while retaining indentation and PyBLE's Tab handling.
  R3 physical input on both tablets now preserves the exact balanced source.
- A delayed automatic app status query from a retired generation could retire
  a newly synchronized session. Source review and a failing regression
  reproduced it; the generation-scoped correction passes and is included in R3.
- Actual ATT23 bytes exposed outgoing RUN/STATUS fragment interleaving. A new
  FIRST resets the peer's incomplete frame by design. This is an app writer
  defect, not proof of a firmware error; complete-frame serialization across
  response-bearing and fire-and-forget commands is being implemented and will
  be requalified with a newly frozen app artifact.
- Initial Android GATT133 failures occur before MTU/HELLO/RUN; the normal app
  also showed an initial failure followed by a successful retry. Retained native
  callbacks show link-establishment failure, not an established MTU defect.
  Test bootstrap retries remain bounded and cannot retry an accepted RUN.
- One local complete run advanced integration HEAD during source-bound fixture
  checks and reported one failure; that test passes in isolation. It is retained
  as an unsuitable final run, with a frozen checkout used for final validation.
- Later roadmap checkbox reconciliation required updating the exact ledger
  allowlist. The six ledger tests now pass while future unselected work stays
  explicitly unchecked.

Raw results and manifests stay in ignored `local/v070/`. Fill rows only from
actual retained artifacts and observations. A host test or Mac BLE probe is
not a tablet row. Existing October app-only evidence remains historical input.

The Android production audience/CDM decision and previous store reviews remain
separate from this firmware development work. The new companion app is neither
a production update nor a resolution of that audience decision.
