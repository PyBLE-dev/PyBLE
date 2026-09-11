<!-- SPDX-License-Identifier: MIT -->

# Firmware v0.6.1 and v0.7.0 roadmap

Status: **v0.6.1 APPROVED for implementation; v0.7.0 remains PROPOSED**

Baseline: **qualified firmware v0.6.0**

Last updated: **2026-09-03**

## 1. Purpose and status

This document records the firmware direction after v0.6.0. It is a public plan
whose per-release approval state is recorded above. It promises no date,
approves no wire encoding, and makes no release, qualification, installer, or
hardware-support claim.

On 2026-09-02, the maintainer approved the v0.6.1 hardening scope for
specification-first and test-first implementation. That approval does not
approve v0.7.0 implementation, new opcode numbers, release qualification, or
publication.

The proposal separates two kinds of work:

1. **v0.6.1 — contract hardening:** correct and test behavior already promised
   by PBLE/1 and the v0.6.0 firmware contracts, and add compatible defensive
   hardening without adding a public operation or changing a frozen payload.
2. **v0.7.0 — Reliable Projects:** add capability-gated, backward-compatible
   project, recovery, status, and filesystem operations.

The next feature release should strengthen the five supported profiles before
adding another board family or a broad board-peripheral stack.

Every accepted item remains subject to specification-first design, a failing
`[red]` test commit, the minimum `[green]` implementation, optional
`[refactor]`, shared conformance, exact-profile HIL, DCO sign-off, dependency
review, and `tools/ci/no_leak.sh`.

## 2. v0.6.0 baseline

The proposal builds on the exact five-profile release admitted by
[ADR-0033](../decisions/0033-qualify-v060-as-five-profile-heterogeneous-release.md):

1. `esp32-4mb`
2. `esp32-s3-n16r8`
3. `waveshare-esp32-s3-lcd-147b`
4. `esp32-c3-4mb`
5. `rpi-pico2-w`

Firmware v0.6.0 already supplies the following common platform surface:

- BLE GATT RX, TX, and INFO characteristics with PBLE/1 framing,
  fragmentation, CRC-32, bounded reassembly, and negotiated MTU support;
- HELLO and DEVICE_INFO capability discovery;
- file list/stat, offset download, CRC-verified windowed upload, reconnect
  resume, delete, mkdir, and rename inside the workspace jail;
- one active transfer, upload scratch files, cumulative acknowledgements, and
  atomic destination replacement after successful verification;
- one active program, file/source RUN, STOP, soft reboot, opt-in autorun, and
  idle/running/done/error events;
- tagged stdout/stderr and bounded stdin over BLE;
- persisted device labels and optional Identify support;
- upstream MicroPython v1.28.0 with no PyBLE patch to upstream MicroPython;
- native ESP32-family and portable frozen-Python Pico 2 W agent
  implementations; and
- exact-byte build, resource, protocol, provisioning, recovery, and physical
  iPad/Android HIL gates.

This roadmap preserves those operations. It does not replace PBLE/1, weaken
the workspace jail, make identity an authorization signal, or turn a firmware
image identity into physical-board detection.

## 3. Gaps that motivate the roadmap

The priorities below come from concrete limits in the current contracts and
implementations:

1. **Incomplete large-directory enumeration.** Legacy `FILE_LIST` is bounded
   by one approximately 480-byte worker response. It reports `more=1` when
   truncated but has no continuation operation. The official example catalog
   therefore uses bounded category directories instead of one flat directory.
2. **Transition-only run state.** `RUN_STATE` events created without a live
   connection are omitted. A client reconnecting during autorun or a manual
   run cannot query an authoritative snapshot.
3. **v0.6.0 execution-isolation discrepancy.** The native ESP runner executes in a
   reused module/global context, while the Pico runner creates a fresh
   `{"__name__": "__main__"}` dictionary. File RUN does not define portable
   `__file__`, working-directory, sibling-import, or project-module cleanup
   semantics.
4. **v0.6.0 input and console loss are not attributable.** The bounded stdin ring can
   accept input while idle and can drop overflow. Bounded console output may
   also be dropped under sustained congestion without a user-visible loss
   counter.
5. **Transfers cannot be inspected or explicitly aborted.** Disconnect
   preserves PUT scratch for resume, but there is no status/abort operation or
   complete storage preflight. Stale scratch can consume space.
6. **Resolved for v0.6.1 — capability-contract discrepancy.** Historical
   semantic prose named `max_file_size`, but it was absent from the frozen
   serialized-key list and both v0.6.0 agent payloads. The v0.6.1 protocol and
   firmware amendments preserve that wire reality: no such key is invented,
   and `FILE_PUT_BEGIN` performs dynamic, overflow-checked free-space admission
   with the specified filesystem reserve.
7. **Protocol and persistence hardening gaps.** HELLO version offers and some
   inbound frame invariants need stronger agent enforcement; native and
   portable CRC-error behavior need executable parity; configuration writes
   and label-byte validation need fail-closed durability.
8. **Recovery remains incomplete for hostile user code.** User code can
   disable keyboard interrupts with `micropython.kbd_intr(-1)`. The existing
   STOP contract and recovery ladder need a tested, explicit resolution rather
   than an undocumented reset side effect.

The relevant frozen contracts are [PBLE/1 file transfer](../specifications/protocol.md#5-file-transfer-the-reliability-core),
[Run/Stop/Console](../specifications/protocol.md#6-run--stop--console),
[HELLO and capabilities](../specifications/protocol.md#7-hello--capabilities),
and the [Pico 2 W port contract](../specifications/firmware/ports/rpi-pico2-w.md).

## 4. Approved v0.6.1 — contract hardening

v0.6.1 should introduce no new public operation or payload. Its purpose is to
make the existing PBLE/1 and firmware contracts consistently true on both
agent implementations and add explicitly specified, wire-compatible defensive
bounds.

### 4.1 PBLE/1 negotiation and dispatch parity

Before implementation, clarify in `docs/specifications/protocol.md` the exact
observable ordering between connection, TX notification readiness, and HELLO
so an implementation can both enforce HELLO-first and deliver its response.

Then:

- parse the HELLO request and refuse it when `proto_versions[]` does not offer
  PBLE/1;
- keep per-connection negotiation state and clear it on disconnect or VM-epoch
  change;
- reject inbound frames whose type is not `CMD` or whose request ID is `0`;
- apply bounded fragment deadlines and malformed-frame budgets so a partial
  sender cannot retain reassembly state indefinitely, after the exact bounds
  and refusal/disconnect behavior are specified;
- make the native CRC-error response identical to the frozen PBLE/1 behavior;
  and
- run the same semantic vectors against Dart, portable Python, and compiled
  native C rather than treating the Python twin as sufficient proof for C.

Current conforming app versions already offer PBLE/1 and use nonzero command
IDs. The stricter firmware must therefore preserve the supported app workflow
while refusing malformed or nonconforming third-party traffic.

### 4.2 Run and stdin isolation

- Execute each ordinary RUN with fresh user globals on every profile.
- Prevent a prior run's variables from affecting a later run.
- Clear stdin at RUN admission, accepted STOP, terminal state, disconnect, and
  VM reset.
- Discard `CONSOLE_INPUT` while no program is active.
- Ensure overflow in one run cannot be consumed by another run.
- Preserve a future, separately specified interactive-session feature if a
  deliberately persistent namespace is ever desired.

Fresh execution changes observable behavior and therefore requires a firmware
specification amendment and compatibility tests even though it adds no opcode.
The frozen amendment scopes fresh globals to ordinary and autorun execution;
it does not prohibit a future capability-gated persistent interactive mode,
which would need its own specification and must not silently weaken ordinary
`RUN` isolation.

### 4.3 Configuration durability and byte validation

- Accept only well-formed UTF-8 labels within the existing 24-byte encoded
  limit.
- Reject embedded NUL, newline, carriage return, and other disallowed control
  bytes before persistence or capability serialization.
- Check all ESP NVS set/erase and commit results.
- Keep the old in-memory label, Identify configuration, autorun state, and
  advertisement when persistence fails.
- Replace Pico's direct JSON overwrite with a versioned temporary-write,
  flush, and atomic-rename transaction, with integrity validation on load.
- Distinguish missing first-boot configuration from corrupt persisted
  configuration, fail closed, and retain a bounded internal fault marker for
  the separately proposed v0.7.0 diagnostic surface.

### 4.4 Transfer scratch and mutation safety

- Omit reserved `.pbltmp` artifacts from every user-visible listing.
- Serialize DELETE, RENAME, and other conflicting mutations against an active
  transfer.
- Resolve and enforce the effective upload size and a filesystem safety
  reserve on the official LFS2 workspace.
- Recover safely from malformed scratch state without damaging the previous
  destination file.
- Never automatically format a nonblank workspace merely because mounting or
  configuration loading failed.

The official images standardize on LFS2 across all five profiles under
[ADR-0047](../decisions/0047-standardize-official-workspaces-on-lfs2.md). The
ESP partition-table `data,fat` subtype is container metadata, not an on-media
FAT claim. Explicit LFS2 construction and fail-closed incompatible-media
handling resolve this roadmap's former FAT/LFS2 ambiguity without changing the
qualified v0.6.0 bytes.

## 5. Proposed v0.7.0 — Reliable Projects

All wire names and opcode numbers in this section are placeholders for
specification review. Each operation must be additive, explicitly advertised
by capability, ignored safely by old clients, and unavailable to a new client
when the capability is absent.

| Priority | Proposed capability | Required outcome |
| --- | --- | --- |
| P0 | Complete directory enumeration | Every visible entry can be retrieved without silent truncation |
| P0 | Queryable run/session status | A reconnecting app can reconstruct the board's current execution state |
| P0 | Project-aware file execution | Multi-file examples and sibling imports behave identically on all profiles |
| P0 | Transfer status and abort | A user can inspect or cancel GET/PUT without corrupting an existing destination |
| P1 | Storage/build diagnostics | The app can preflight space and report the exact installed source artifact |
| P1 | Loss-aware console/input | Bounded loss remains possible but never silent |
| P1 | Explicit recovery ladder | A novice has a defined recovery from code that defeats ordinary STOP |

### 5.1 Complete directory enumeration

Preserve legacy `FILE_LIST` byte-for-byte. Add a bounded streaming operation,
provisionally shaped as:

- `DIR_LIST_BEGIN`
- `DIR_LIST_DATA`
- `DIR_LIST_END`

Streaming is preferred over a nominal seek cursor because the supported
MicroPython VFS implementations do not provide one universal stable directory
position. The specification must define:

- whether a mutation during enumeration causes an explicit restart-required
  error or produces documented best-effort results;
- the single-transfer interaction and cancellation behavior;
- connection/VM-epoch binding and disconnect cleanup;
- LFS2 ordering expectations for the five official profiles, with any future
  alternative VFS requiring its own explicit semantics and qualification;
- bounded memory and notification pacing; and
- exclusion of internal scratch/configuration artifacts.

### 5.2 Queryable run/session snapshot

Add a capability-gated `RUN_STATUS` or `RUN_INFO` request. Its response should
contain only bounded diagnostic metadata:

- a boot nonce or equivalent boot identity;
- a monotonically increasing run ID within that boot;
- current state: idle, running, done, or error;
- origin: file, inline source, or autorun;
- last terminal reason/status;
- relevant console/input loss counters;
- active recovery or pending reboot state; and
- elapsed monotonic time where the port can provide it safely.

Do not echo inline source, console contents, secrets, or unnecessary file
contents. Existing `RUN_STATE` events remain unchanged.

### 5.3 Project-aware file RUN semantics

Define one portable file-execution transaction:

- `__name__ == "__main__"`;
- `__file__` is the exact executed workspace path;
- the script's parent directory is available for sibling imports only for the
  duration of the run;
- current directory and `sys.path` are restored after done, error, or STOP;
- project-local modules loaded by the run cannot survive into an unrelated
  later run; and
- system, frozen, and standard-library modules are not incorrectly removed.

Inline-source RUN remains isolated and receives a documented virtual filename.
This feature enables real multi-file examples without automatic board/pin
detection or a hidden hardware profile.

### 5.4 Transfer status, abort, and capacity

Add capability-gated operations, provisionally:

- `TRANSFER_STATUS`
- idempotent `TRANSFER_ABORT`
- `FS_INFO`, or equivalent additive storage fields

The resulting contract must:

- report source path, total size, and current offset for GET, without inventing
  an up-front expected CRC that PBLE/1 deliberately does not provide;
- report destination, total size, expected whole-file CRC, and contiguous
  watermark for PUT;
- bind resumable PUT metadata to destination, total size, and expected CRC;
- keep the old destination byte-for-byte intact after abort or failure;
- remove only the explicitly aborted PUT's scratch data;
- preserve resumable PUT state after an ordinary disconnect;
- return an idempotent success when aborting an already-idle transfer; and
- report filesystem total, free space, safety reserve, and effective maximum
  upload size so the app can preflight a batch.

### 5.5 Loss-aware console and acknowledged input

The console must remain bounded so output cannot exhaust memory or starve STOP
and file acknowledgements. v0.7.0 should report loss rather than promise a
lossless log.

Candidate additions are:

- a cumulative, saturating console-lost byte/chunk counter;
- a sequence or `CONSOLE_GAP` signal that cannot create an event storm;
- counters included in the queryable run snapshot; and
- a capability-gated `CONSOLE_INPUT_V2` carrying a run ID and returning the
  accepted byte count and remaining input credit.

Legacy `CONSOLE_INPUT` remains available for old apps and retains its existing
wire encoding. A new app should prefer the acknowledged path when advertised.

### 5.6 Diagnostics and recovery

Expose bounded, non-personal diagnostic data useful for support and release
verification:

- immutable build/source fingerprint;
- flashed image identity and agent version;
- uptime and tested reset cause;
- filesystem totals and effective upload limit;
- current and minimum free heap where supported;
- queue high-water marks and console loss counters; and
- last boot stage or last bounded agent error.

Image identity describes only the installed artifact. It must not become
physical-board inference, a pin map, an authorization signal, or an app routing
allowlist.

First verify on every profile that the existing acknowledged SOFT_REBOOT path
recovers from `micropython.kbd_intr(-1)`, a Python tight loop, console flood,
and documented native-blocking cases. If a gap remains, specify an explicit,
capability-gated `FORCE_RESET` as the last recovery rung:

1. STOP
2. SOFT_REBOOT
3. explicit FORCE_RESET

Do not silently redefine every STOP as a hardware reset without an approved
PBLE/1 contract decision. Recovery must preserve the workspace and valid
configuration unless the user separately confirms a destructive repair.

## 6. Cross-version compatibility contract

The v0.7.0 design must satisfy all of the following:

- keep all 24 v0.6.0 operation numbers and payload encodings unchanged;
- use new opcodes only for additive behavior permitted by PBLE/1 versioning;
- advertise an explicit capability for every new operation or semantic mode;
- make old apps safely ignore unknown capability keys;
- let the current app that supports v0.6.0 firmware complete its existing
  workflow against candidate v0.7.0 firmware;
- let an updated app connect to v0.6.0 firmware and fall back when a new
  capability is absent;
- keep firmware versions independent from Flutter app versions; and
- require PBLE/2 for any change that is genuinely backward-incompatible.

The capability registry and exact wire encodings must be added to
`docs/specifications/protocol.md` before `[red]` implementation tests. App and
firmware specifications must consume that one contract rather than redefine it.

## 7. Acceptance and HIL gates

Every candidate must pass on the same five exact profiles listed in section 2.
No result from one profile, agent implementation, board, build, filesystem, or
provisioning method may fill another row.

### 7.1 Run isolation and project execution

- Run two programs sequentially without reset; a sentinel created by run 1 is
  absent from run 2.
- File RUN observes the specified `__name__` and exact `__file__`.
- A project entry point imports a sibling helper.
- Replacing that helper before the next RUN loads the new contents rather than
  a stale `sys.modules` entry.
- Working directory and `sys.path` equal their pre-run values after done,
  error, and STOP.
- Fifty sequential bounded programs remain above the existing profile resource
  floors with no monotonic leak.

### 7.2 Input and console isolation

- Input sent while idle cannot satisfy a later `input()` call.
- Input sent only after a prompt is consumed by that exact run.
- STOP, terminal state, disconnect, and overflow cannot carry bytes into a
  successor run.
- Every dropped output/input byte is represented by a monotonic or saturating
  counter, without a gap-event storm.
- Console flooding does not regress the existing control-response and STOP
  latency gates.

### 7.3 Complete directory enumeration

- Populate at least 100 mixed files/directories whose legacy encoding exceeds
  the one-response ceiling.
- Legacy `FILE_LIST` still reports truncation exactly as v0.6.0 specifies.
- For an unchanged directory, the new operation returns every visible entry
  exactly once at ATT MTU 23 and negotiated MTU 247.
- Cover empty directories, valid maximum-length paths/names, UTF-8 names,
  congestion, disconnect, and VM reset.
- For mutation during enumeration, prove the separately approved snapshot,
  restart-required error, or documented best-effort semantics exactly.
- Exercise LFS2 on all five official profiles and prove internal artifacts are
  never returned; any future alternative VFS requires separate qualification.

### 7.4 Transfer status and abort

- Start a partial PUT over an existing sentinel, abort, and prove the old
  target is byte-identical.
- Prove explicit abort removes the applicable scratch state and permits a new
  transfer immediately.
- Abort GET and immediately complete another GET/PUT.
- Duplicate abort is idempotent.
- Disconnect still preserves a valid resumable PUT; explicit abort deletes it.
- Cover full storage, stale/corrupt scratch metadata, conflicting mutations,
  same-path/same-size/different-CRC content, and power interruption at each
  commit boundary.

### 7.5 State, diagnostics, and recovery

- Connect during autorun and reconnect during every manual run/terminal state.
- Verify boot identity changes after reset and run IDs cannot be confused
  across boot identities.
- Verify HELLO, DEVICE_INFO, and INFO expose identical shared additive values.
- Confirm `0 <= fs_free <= fs_total` and observed allocation changes remain
  within the documented filesystem-block tolerance.
- Bind the build fingerprint to the immutable release manifest without a
  personal identifier.
- Exercise STOP and the complete recovery ladder against a tight loop,
  `micropython.kbd_intr(-1)`, console flood, and every separately claimed
  blocking case.
- After recovery, HELLO, list, upload, RUN, and STOP must work again within the
  approved reset/discovery SLO.

### 7.6 Compatibility and release admission

- Run the current app against candidate v0.7.0 firmware through every legacy
  workflow.
- Run the updated app against v0.6.0 and prove capability fallback.
- Run the updated end-to-end workflow on one physical iPadOS device and one
  physical Android device for every firmware profile.
- Re-run the complete shared conformance, resource, recovery, deterministic
  build, provenance, installer, and exact-byte release gates.
- Run `tools/ci/no_leak.sh` and all relevant license/SBOM gates.

## 8. Work explicitly deferred from v0.7.0

### 8.1 v0.8.0 candidate scope

- Atomic multi-file deployment with a manifest, staging area, commit, abort,
  and boot-time power-loss journal recovery.
- Workspace diff/verification using source SHA-256 while retaining CRC-32 for
  PBLE/1 transport-corruption detection.
- Optional Pico parity increments that survive independent resource/HIL review.

Atomic project deployment must prove the visible project is wholly old or
wholly new after every interruption. It must not be rushed into the same
release as the lower-level transfer status/abort foundation it depends on.

### 8.2 Separate security milestone

PBLE/1 currently trusts a connected client. An authenticated-owner mode needs
a written threat model covering physical-presence bootstrap, secret storage,
nonce/replay protection, downgrade behavior, session expiry, lost-client
recovery, credential reset, rate limiting, and which read-only operations
remain public.

Bluetooth NoInputNoOutput "Just Works" pairing does not by itself authenticate
the peer against an active man-in-the-middle. Making application authentication
mandatory would break existing clients and is therefore likely a PBLE/2
boundary. An optional PBLE/1 mode still requires a complete recovery design
before implementation. See the official
[Bluetooth Security Manager specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/host/security-manager-specification.html).

### 8.3 Other deferred work

- Universal BLE firmware OTA/DFU. ESP safe OTA requires suitable partition and
  rollback design, while RP2 uses a different UF2/BOOTSEL recovery model. See
  the official [ESP-IDF OTA documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html)
  and [Raspberry Pi MicroPython/UF2 documentation](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html).
- A sixth board family or automatic board/pin detection.
- Broad Waveshare peripheral additions, Pico core1 transfer concurrency,
  built-in LED Identify, or NeoPixel claims without separate exact-hardware
  qualification.
- On-board network package installation, compiled `.mpy` examples, Wi-Fi
  credentials, cloud accounts, telemetry, or remote code storage. A future
  app-side pinned source-only dependency workflow may be considered separately;
  see [MicroPython package management](https://docs.micropython.org/en/latest/reference/packages.html).
- Recursive delete by default, raw REPL tunneling, unbounded console buffering,
  or a debugger/breakpoint protocol before run/session foundations stabilize.

## 9. Dependencies before implementation

An approved release increment requires, in order:

1. maintainer review and explicit scope selection from this proposal;
2. focused GitHub issues/milestones with acceptance criteria and owners;
3. protocol/specification amendments for every changed contract;
4. an ADR for material decisions such as directory mutation semantics, project
   import cleanup, recovery escalation, or authenticated ownership;
5. `[red]` tests and cross-language conformance vectors;
6. minimal `[green]` implementation and optional `[refactor]` cleanup;
7. app integration behind capability fallback;
8. exact five-profile automated and physical HIL evidence; and
9. deterministic release build, provenance, SBOM/license, no-leak, DCO, and
   publication review.

### 9.1 Recorded v0.6.1 process deviation

Step 2 was not completed before v0.6.1 implementation began. Milestone
[Firmware v0.6.1 — Contract hardening](https://github.com/PyBLE-dev/PyBLE/milestone/1)
and focused issues [#24](https://github.com/PyBLE-dev/PyBLE/issues/24),
[#25](https://github.com/PyBLE-dev/PyBLE/issues/25),
[#26](https://github.com/PyBLE-dev/PyBLE/issues/26),
[#27](https://github.com/PyBLE-dev/PyBLE/issues/27), and
[#28](https://github.com/PyBLE-dev/PyBLE/issues/28) were created
retrospectively on 2026-09-03. This restores explicit ownership, acceptance
criteria, and remaining-work tracking, but it does not retroactively satisfy
the required ordering and must not be represented as doing so. Issues #25–#28
record source/host completion; #24 remains open and exclusively owns fresh
candidate-bound five-profile physical qualification and release admission.
Firmware v0.6.1 therefore remains source-selected, unqualified, unpublished,
and unavailable to installers until #24 closes. This deviation approves no
v0.7.0 scope and creates no precedent for a future release.

## 10. Maintainer review checklist

Before implementation begins, the maintainer should explicitly approve or
revise:

- [x] the v0.6.1 hardening / v0.7.0 feature-release split;
- [ ] v0.7.0's P0 versus P1 scope;
- [ ] streaming directory enumeration and mutation behavior;
- [ ] fresh per-run globals and project-local import cleanup semantics;
- [ ] run/boot identity fields and their privacy bounds;
- [ ] transfer-abort and scratch-retention behavior;
- [ ] loss-counter and acknowledged-input behavior;
- [ ] the STOP/SOFT_REBOOT/optional FORCE_RESET recovery ladder;
- [ ] the diagnostic build/image identity wording and non-routing rule;
- [ ] the v0.8 atomic-deployment dependency; and
- [ ] whether authenticated ownership starts as a separate PBLE/2 design
  milestone.

Approval of this roadmap still does not approve opcode numbers, payload bytes,
implementation, qualification, or publication. Those decisions follow the
repository's specification-driven and test-driven process.
