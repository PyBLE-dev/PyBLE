# PBLE/1 — PyBLE BLE Wire Protocol

Status: **§2–§10 FROZEN for v1.0 (complete)** · Version: 1 · Last updated: 2026-08-15

> PBLE/1 is a **clean-room, original** protocol authored for PyBLE. It reuses no closed-source wire format, opcodes, or UUIDs. It carries PyBLE's app↔board messages over a BLE GATT service.
>
> This document is a working draft. Sections are frozen one at a time before the code that depends on them is written (see [`AGENTS.md`](../../AGENTS.md)).

The 2026-07-29 portability amendment clarifies that the existing `chip` and
`device_id` values are port-defined metadata and that clients accept unknown
targets. It changes no PBLE/1 key, payload shape, opcode, status, UUID, or other
wire byte.

The 2026-08-14 RUN-admission amendment makes the existing response-before-run
ordering fail closed under local TX pressure. It changes no PBLE/1 byte.

The 2026-08-15 default-MTU delivery amendment makes response-bearing writes
acknowledged and makes incomplete-fragment restart semantics explicit. It also
binds the ESP reference agent's bounded, session-scoped generic-response
delivery. It changes no PBLE/1 byte.

The 2026-08-15 runner-event amendment binds each newly created `RUN_STATE` and
`CONSOLE_DATA` event to the live connection session at that instant. It changes
no PBLE/1 byte.

**Freeze ledger (per-section):**

| Section | Freeze status | Freeze act |
|---|---|---|
| §2 BLE transport (GATT) — Service/RX/TX/INFO UUID base, advertising, MTU | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; default-MTU delivery · 2026-08-15 · `[docs]` |
| §3 Framing — §3.1 message frame, §3.2 fragmentation | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; restart/delivery semantics · 2026-08-15 · `[docs]` |
| §4 Opcodes — the v1.0 opcode set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` (closes OI-4) |
| §8 Status / error codes — the 1-byte status set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §6 Run/Stop/Console — RUN{file,source}, RUN_STATE, EBUSY, STOP, SOFT_REBOOT, CONSOLE_DATA/INPUT | **FROZEN for v1.0 (amended)** | G1 · 2026-07-01; transactional RUN admission · 2026-08-14; default-MTU STOP/SOFT_REBOOT admission and per-event session binding · 2026-08-15 · `[docs]` (RUN-file at S3; STOP / console / RUN-source at S4) |
| §7 HELLO & capabilities — caps field set, HELLO-first, INFO==DEVICE_INFO, label max = 24 B (label half of OI-6) | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §9 Versioning policy — accept only `VER 0x01`, refuse unsatisfiable, additive caps | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §5 File transfer — read + windowed upload + workspace jail | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §10 Security — pairing/encryption baseline (non-gating), connected-client-trust, single active writer, no PII/MAC-gating/telemetry | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |

The §2 GATT UUID base (`7079626c-…`), the §3 frame + fragmentation bytes, the §4 opcode set + numbers, and the §8 status set + numbers are now **stable inputs** to the firmware M1 stories (F-01, F-02) and the app `pble` client. The §4/§8 freeze **closes OI-4**: opcode and status numbers no longer change within v1.0. No wire bytes changed at this freeze — it flips status only. **Note:** freezing §4 fixes the *opcode set and its numbers*; the label / identify **payload encodings** (`SET_LABEL` max byte-length, `SET_IDENTIFY_LED` GPIO+active-level encoding, `IDENTIFY` blink-duration bound) remain **OI-6** — owned by §4/§7 and frozen before their S3/S4 stories (F-22, F-23), not at this freeze.

## 1. Goals

- Run, stop, and stream the console of a MicroPython program over BLE.
- Transfer files reliably (with verification and resume) over a lossy, MTU-bounded link.
- Stay small enough for constrained MicroPython + BLE targets, with ESP32-C3
  as the initial v1 footprint floor, and simple enough to re-implement.
- Be **versioned and capability-negotiated** from day one.

## 2. BLE transport (GATT)

> **FROZEN for v1.0 (G0 · 2026-07-01 · `[docs]`).** The UUID base and characteristic roles/properties, advertising rule, and MTU are stable; amend only via a `[docs]` commit before dependent code.

PyBLE defines one primary GATT service with a PyBLE-owned 128-bit UUID base. The base `7079626c-…` encodes ASCII `pybl`.

| Role | UUID | Properties |
|---|---|---|
| **Service** | `7079626c-1ab1-4d50-9e3a-000000000001` | — |
| **RX** (app → board) | `7079626c-1ab1-4d50-9e3a-000000000002` | Write, Write-Without-Response |
| **TX** (board → app) | `7079626c-1ab1-4d50-9e3a-000000000003` | Notify |
| **INFO** (board → app) | `7079626c-1ab1-4d50-9e3a-000000000004` | Read |

- **Advertising:** the board advertises the Service UUID and a device name. By
  default the name is `PyBLE-XXXX`, where `XXXX` is a stable, non-personal,
  locally derived device suffix in uppercase hex (e.g. `PyBLE-9F3A`), so a
  client can recognize a board. The ESP32 reference agent derives it from the
  last two bytes of the BLE MAC; another conforming port MAY use an equivalent
  stable platform identifier. If a **device label** has been set (§4
  `SET_LABEL`, persisted on the board), the label **replaces** the default name
  in the advertisement so it is visible in the scan list before connecting.
  The app scans **filtered to the Service UUID** — never a raw device list.
- **MTU:** the app requests MTU **247**; the usable per-packet payload is `MTU − 3` (ATT header) minus the 1-byte fragmentation header.
- **RX write acknowledgement:** every fragment of a `CMD` for which the client
  awaits an `RSP` uses the RX characteristic's **Write** operation (an
  acknowledged GATT write). A caller that explicitly uses the fire-and-forget
  API MAY use **Write-Without-Response**; this includes commands for which
  PBLE/1 defines no `RSP` and the existing `SOFT_REBOOT` fire-then-disconnect
  client path. One absolute command deadline begins before the first write and
  covers all acknowledged fragment writes plus the matching response wait;
  fragment progress MUST NOT restart or extend it.
- **INFO characteristic:** a read returns the same payload as a `DEVICE_INFO` response (chip, MicroPython version, free memory, `fs_root`, MTU, the stable `device_id`, and the `label`), so a client can identify a board before subscribing.

## 3. Framing

> **FROZEN for v1.0 (G0 · 2026-07-01 · `[docs]`).** The §3.1 message frame and §3.2 fragmentation bytes are stable; amend only via a `[docs]` commit before dependent code. (`OPCODE` *values* are §4-owned and remain DRAFT; the frame *structure* is frozen.)

### 3.1 Message (after reassembly)

```
+------+------+--------+------+----------+-------------------+----------+
| VER  | TYPE | OPCODE |  ID  |   LEN    |      PAYLOAD       |  CRC32   |
| 1 B  | 1 B  |  1 B   | 1 B  |  2 B LE  |   LEN bytes        |  4 B LE  |
+------+------+--------+------+----------+-------------------+----------+
```

- `VER` = `0x01`.
- `TYPE` = `CMD (0x01)` | `RSP (0x02)` | `EVT (0x03)`.
- `OPCODE` — see §4.
- `ID` — request id chosen by the app (1–255); the board echoes it in the matching `RSP`. `EVT` uses `ID = 0`.
- `LEN` — payload length, little-endian `uint16` (≤ 65535).
- `CRC32` — IEEE CRC-32 over `VER…PAYLOAD` (the header + payload, excluding the CRC itself), little-endian.

For a response-bearing command, the connection-local correlation key is the
originating `{OPCODE, ID}` pair and the matching frame's `TYPE` is `RSP`. A
pending command MUST complete only from a frame with all three exact values.
A different-opcode `RSP` that happens to carry the same reused `ID`, and a
non-`RSP` frame that happens to carry a nonzero `ID`, are unrelated frames:
neither may complete the command, consume or replace its matching response, or
reset its absolute deadline. This is true in either arrival order, including
when the unrelated frame is a delayed response for an earlier use of that ID.
Response arrival at or before the command's §2 absolute deadline is decisive;
later task scheduling may process that already-arrived response, but a response
arriving after the deadline cannot complete the command.

### 3.2 Fragmentation (over GATT)

A message larger than one packet is split across consecutive RX writes (or TX notifications). Each packet is:

```
+----------+-------------------------------+
| FRAG_HDR |          FRAGMENT DATA         |
|   1 B    |        up to (MTU−4) bytes      |
+----------+-------------------------------+
```

`FRAG_HDR` bits: `bit7 = FIRST`, `bit6 = LAST`, `bits5..0 = index mod 64`. The receiver concatenates `FRAGMENT DATA` from the `FIRST` packet through the `LAST` packet (indices increasing mod 64) to reconstruct the §3.1 message, then validates the CRC. Receipt of `FIRST` always abandons any incomplete fragment run and starts a new one; a non-`FIRST` packet with no active run or with the wrong next index is dropped. This restart rule lets a sender restart an identical whole frame after its logical message ownership was preempted, without completing a stale prefix; ordinary transient pressure alone retries only the unaccepted fragment. A frame whose CRC fails is dropped and answered with `EVT ERROR(ECRC)` referencing the opcode if known.

The ESP reference agent lifecycle-gates the entire RX write callback, not only
complete-message dispatch. Before reading or copying any fragment byte, the
host callback makes one non-blocking lifecycle-activity entry. A closed or
not-ready refusal atomically clears the incomplete reassembly run and drops the
fragment. Admission and this refusal reset are one authoritative lifecycle-lock
transaction: the refusal reset occurs before releasing that lock and only
while the refused callback's VM epoch is still the same closed epoch. It cannot
pause after refusal, allow a new VM to become ready and accept a fresh `FIRST`,
then clear that fresh run. A successful entry remains counted through index validation, copy,
`LAST` completion, and any resulting CMD dispatch, then leaves once. VM reset
first closes/invalidates admission and drains these callbacks; only afterward,
under the same synchronization, may it clear the RX buffer/index/run state.
Thus a callback paused after copying `FIRST` cannot resume into recycled state,
and a `FIRST` dropped while closed cannot be completed by a `LAST` received
after the next VM becomes ready. This adds no wire byte and never blocks the
NimBLE host callback.

**ESP reference-agent generic-response delivery (amended 2026-08-15).** The
largest ordinary response the reference dispatcher accepts is 491 encoded
bytes (6-byte header + 481-byte payload including status + 4-byte CRC), or 26
fragments at ATT MTU 23. Before an ordinary synchronous response-bearing
handler can make a side effect, the agent atomically reserves fixed, bounded
capacity for that entire encoded response. If capacity is unavailable, the
handler is not invoked, no unreserved response is attempted, and the
originating connection is terminated; observable link loss is the bounded
refusal outcome rather than a silent live-session drop. Deferred filesystem
commands reserve the same capacity before their bounded host-to-worker enqueue.
If that enqueue is full, the dispatcher invokes no filesystem operation and
publishes `RSP{EBUSY}` through the same reserved slot; it does not discard the
reservation or attempt an unreserved fallback response. The reservation is a
ticket bound to a slot incarnation, the originating connection session
(including a generation that cannot be confused by numeric connection-handle
reuse), and the current MicroPython VM epoch. The native ticket stores that VM
epoch; reserve captures it, and every match, publish, completion, and cancel
operation compares it rather than consulting only the current global epoch. A deferred worker builds its
result in private scratch and revalidates the whole ticket before and after
each VFS operation and before copying into that slot until response completion.
`FILE_GET_BEGIN` then waits for that response to complete and recycle its slot
before streaming dependent data. From that cut onward, each VFS read and event
revalidates the queue item's immutable `{handle, connection generation, VM
epoch}` token; it MUST NOT inspect or touch the recycled response slot.

When a fully encoded response enters the ready FIFO, one absolute 1000 ms
publication deadline begins. One pre-created NimBLE-host callout owns the
logical message. Each callback validates ticket, connection generation,
deadline, and TX stream generation; takes the physical TX mutex with zero wait;
attempts exactly one fragment Notify; then releases and returns. On success it
advances offset/index and rearms after one RTOS tick if data remains. On
transient pressure it retains the same unaccepted fragment and rearms after at
most 15 ms. The callback never sleeps, loops, or waits for capacity. Non-control
and bulk senders cannot interleave while the logical ownership is held.

A specialized single-fragment `RUN`, `STOP`, or `SOFT_REBOOT` response MAY
wait under one absolute **15 ms** deadline only for the current complete-message
TX-mutex boundary. Declaring that specialized attempt pending prevents a later
ordinary or bulk message from starting; it does not interrupt a fragment run
already in progress. Once the mutex is acquired, the agent revalidates the
originating session and makes exactly one local Notify submission, with no wait
or retry for mbuf/controller capacity. A successful response MAY preempt between
generic-response fragments and increments a stream generation under the same TX
mutex; the response callout observes the change and then restarts its identical
encoded frame from `FIRST`, which abandons the interrupted prefix. Boundary
deadline expiry or local submission failure suppresses the specialized side
effect and generic fallback without terminating an otherwise-live session. By
contrast, expiry of the generic response's 1000 ms publication deadline on a
still-live connection terminates that session rather than silently losing an
admitted response. Disconnect stops/cancels the callout and invalidates its
ticket before normal re-advertising; any already-queued callback revalidates and
emits nothing. No queued or late response byte may cross into a later
connection session.

**ESP reference-agent bounded failed-session termination (amended
2026-08-15).** A response-capacity refusal or publication-deadline expiry first
atomically changes the exact `{handle, connection generation}` from `OPEN` to
`CLOSING`. A closing token is retained only for exact GAP lifecycle matching:
it is not live for CMD admission, response-ticket reservation or validation,
ordinary/event/control TX, or the specialized `RUN`, `STOP`, and `SOFT_REBOOT`
paths. Entering `CLOSING` makes existing work logically non-live, so it cannot
begin another side effect or publish a byte, but it does not yet physically
cancel tickets/work or invalidate the retained token. That physical cleanup is
reserved for exact `CLEANING` after any required watchdog stop succeeds.
Repeated close requests for the same token are idempotent. Every TX attempt
carries its originating full token to the sole Notify exit; a new snapshot of
a reused numeric handle cannot substitute for that ownership. The physical
recursive TX mutex has one lock order with lifecycle state: TX mutex first,
then the session critical section. The final exact-token check and
`ble_gatts_notify_custom` remain inside that TX ownership, and every
connect/open, `OPEN → CLOSING`, and disconnect/reset cleanup claim uses the
same serialization. A Notify therefore either completes while its token is
still `OPEN`, or a winning lifecycle transition makes it fail before the
NimBLE call. The state machine is `CLOSED`/`OPEN`/`CLOSING`/`CLEANING`/
`RESTARTING`, and neither a reused handle nor a later lifecycle event can open
or clean a terminal `RESTARTING` token.

Cold native initialization initializes this retained state exactly once and
pre-creates one task-dispatched ESP timer before NimBLE can start or advertise;
MicroPython soft reset and repeated agent initialization do not reset either.
Creation failure leaves the agent unadvertised. A successful GAP connect mints
a nonzero generation and opens the exact token under the session critical
section before exposing it. If the state is not `CLOSED`, the board restarts
instead of overwriting an old token.

The `OPEN → CLOSING` reducer step reads `esp_timer_get_time()` once and stores
one absolute deadline 2500 ms ahead. The initial physical arm uses only the
positive residual `deadline - esp_timer_get_time()`, never a fresh 2500 ms
interval; reaching the deadline before the arm instead claims `RESTARTING`.
The reducer begin, residual calculation, `esp_timer_start_once`, and reducer
arm acknowledgement form one uninterrupted session-critical transaction. A
task-dispatched callback therefore cannot consume the physical one-shot while
the reducer still considers it unarmed. Only after a successful acknowledgement
does the host make exactly one `ble_gap_terminate` call, outside that critical
section. The deadline never moves. Initial arm failure claims `RESTARTING` and
restarts without attempting GAP. Return `0` and `BLE_HS_EALREADY` mean only
that GAP teardown is already pending; the agent waits for exact disconnect or
NimBLE reset while the watchdog remains armed. Any other return claims
`RESTARTING` and invokes public non-returning `esp_restart()` immediately. A
`BLE_GAP_EVENT_TERM_FAILURE` is an explicit no-op: it cannot stop/rearm the
timer, change the deadline, clean the token, advertise, or restart. The agent
never retries termination and never calls `ble_hs_sched_reset`,
`nimble_port_stop`, direct NimBLE/controller teardown, or a private restart
entry point, because the pinned host may already have scheduled its own reset
before returning an error.

Exact disconnect or NimBLE reset first atomically claims `CLEANING`; a stale
token does nothing. Normal `OPEN` cleanup has no termination timer to stop.
Cleanup claimed from `CLOSING` must receive `ESP_OK` from `esp_timer_stop()`
before it may invalidate exact-token work, complete `CLEANING → CLOSED`, or
advertise. Any other stop result cannot prove that the task callback is not
already running, so it claims `RESTARTING` and restarts. After the successful
required stop, cleanup invalidates all exact-token work/tickets/TX ownership
and only then permits later advertising or admission.

The callback carries the immutable armed `{handle, generation, deadline}` and
revalidates all three. An early callback rearms only the residual
`deadline - now` interval; rearm failure claims `RESTARTING`. At or after the
inclusive deadline it claims `RESTARTING` before restarting. A stale callback
therefore cannot affect a reused handle even when its successor is also
`CLOSING`. Thus every requested termination produces either exact GAP teardown
or a whole-board restart within the fixed bound rather than leaving a live
session that silently lost an admitted response.

**ESP reference-agent VM boundary (amended 2026-08-15).** Static native
workers, queues, semaphores, and response slots can outlive one MicroPython VM,
so VM reset is an explicit admission boundary even when the BLE link and its
numeric handle survive. `SOFT_REBOOT` first closes filesystem admission under
the same zero-wait synchronization with which host-context filesystem enqueue
inserts an item and the FS worker marks itself busy, and may proceed only if
that worker is idle and its queue is empty. If
not, the gate reopens and the command returns `RSP{EBUSY}` with no reset side
effect. Both host-context enqueue and the `SOFT_REBOOT` quiescence attempt take
this gate with zero wait. Gate contention is a bounded refusal: a
response-bearing FS command publishes `RSP{EBUSY}` through its reserved ticket,
`FILE_PUT_DATA` is dropped for protocol-level retransmission, and
`SOFT_REBOOT` returns `RSP{EBUSY}` with no side effect. The successful quiescence check provisionally closes all non-reboot
CMD admission. Only after the transactional `RSP{OK}` submission and reset
timer arm both succeed does that closure proceed through the graceful path.
Response-submission failure reopens all gates and leaves the VM intact. Local
acceptance of `RSP{OK}` is the irreversible reset-commit cut: gates never reopen
after it; failure to arm the already-created timer immediately invokes
non-returning `esp_restart()` rather than strand an acknowledged reboot. A
new VM initialization keeps admission closed while it atomically rotates the
live connection generation and VM epoch with old-ticket invalidation, prevents
future response-callout scheduling, synchronizes with pool/TX ownership, and
hard-recycles every response-slot incarnation. It drains response-completion
signals, resets filesystem queues and transfer state, and resets the runner
hand-off semaphore, run-state machine,
request buffers, worker pointer, console buffers, and BLE RX reassembly state.
The reset clears the FS gate, busy/outstanding state, and dequeue claim; runner
`stop_requested`, `soft_reboot_pending`, timer armed epoch, semaphore, state,
buffers, and worker pointer; console ring indices/count and worker pointer; and
response scheduling/active/logical-owner flags. None reopen before final
readiness.
It explicitly sets both custom VM roots, `pble_runner_sysexit` and
`pble_fs_put_file`, to `MP_OBJ_NULL` before new-VM registration allocates or
opens either.
It reopens admission only after all native handlers and new-VM workers are
registered, entered, and safe. The reference ESP port binds this lifecycle to
two pinned port seams without editing upstream MicroPython. An allocation-free,
idempotent linker wrapper around `mp_thread_deinit` closes all admission,
invalidates old tickets/session work, and detaches runner/console worker
pointers before calling the exact upstream function that deletes old VM
threads. Admission and lifecycle activity share one authoritative lock and
counter: every complete CMD enters only while open and leaves only after all of
its handler effects, while every off-MP callback that can touch VM/rooted or
epoch-owned state enters with its exact armed epoch. Persistent runner and
filesystem worker tasks are not members of this wrapper activity counter: the
FS worker's entire-dispatch `busy` state belongs only to the earlier
`SOFT_REBOOT` quiescence gate. This exclusion relies on the pinned ESP runtime:
the main task owns the MicroPython GIL when it reaches `mp_thread_deinit`, and
the wrapper MUST NOT release that GIL. Consequently another MP worker cannot
still be executing a VFS or rooted-VM operation; an old worker parked in an
explicitly off-GIL queue/TX wait is reclaimed by the exact upstream deinit.
The wrapper atomically closes and invalidates, then mints one absolute deadline
exactly 2500 ms ahead and passes that same deadline through activity drain,
soft-reboot and identify timer disarm, prevention of future callout scheduling,
and physical recursive TX-mutex acquisition. Every stage and retry consumes
only the residual time; no helper may restart a 2500 ms budget. An inactive or already-fired lifecycle
timer is idempotent disarm success. Timeout, counter invariant failure,
unexpected timer-disarm failure, or TX-quiescence failure invokes non-returning
`esp_restart()`; the host callback is never made to wait. The wrapper owns the
physical TX mutex while it detaches worker pointers, sets both custom VM roots
to `MP_OBJ_NULL`, and calls `__real_mp_thread_deinit`; it releases the mutex only
after that function has deleted the old VM tasks and returned. Thus a paced
sender cannot reacquire the mutex and then be deleted while owning it.

The soft-reboot timer carries its armed VM epoch and must enter/leave lifecycle
activity before reading a rooted `SystemExit` or calling the scheduler. The
identify timer likewise carries/revalidates its epoch and stops without another
GPIO transition once invalidated. Wrapper disarm clears soft-reboot pending and
the armed epoch even when the timer is inactive/already fired. This closes passed-gate races for
`RUN`/`STOP`/`SOFT_REBOOT`, console input, and filesystem enqueue as well as
timer races. Each PyBLE ESP board overlay then uses `MICROPY_PORT_INIT_FUNC` to
rotate the VM epoch and retained connection generation and perform the hard
reset exactly once per subsequent `mp_init`. Repeating agent initialization in
one VM is idempotent. Agent initialization does not itself open the gate: final boot wiring explicitly crosses the
readiness barrier only after both workers have entered and auto-run admission
has completed. Because each `_thread` worker must first acquire the MicroPython
GIL, the pinned main task's final ready call releases the GIL while waiting on
both entry flags under one absolute 2500 ms readiness deadline, then reacquires
it before returning. Timeout or a boot-wiring failure leaves admission closed. A response
callback is a static event with no captured epoch or frame pointer. It first
enters lifecycle activity and, while reset/not-ready admission is closed, does
nothing. Once ready it can act only as a fresh kick that peeks the current
ticket, incarnation, epoch, and connection token under their locks. A callback
preempted after that peek remains counted, so wrapper reset cannot recycle its
state until it leaves. Reset MUST NOT depend on callout deinitialization or
removal of a queued host event. If either lifecycle seam observes the retained
connection already in `CLOSING`, it immediately invokes `esp_restart()` rather
than rotate to an `OPEN` generation or disarm the independent termination
watchdog. The release build and link map MUST prove that every ESP target resolves
`mp_thread_deinit` through the wrapper and includes the per-`mp_init` hook; no
upstream source is edited. Work dequeued under an older epoch MUST fail its token checks and MUST
NOT start a VFS operation, publish a response, emit an event, wake the runner,
or touch a recycled slot. An indivisible VFS operation that validly started
before invalidation MAY finish, but its owner MUST revalidate afterward and
MUST start or publish nothing further.

Response completion has transition ownership: an exact live ticket may move
to complete and signal its waiter once, whether that transition originates in
cancellation, publication failure, or a TX success/error result. Repeated cancellation or completion of
an already-complete incarnation is idempotent and emits no second wake; slot
reserve drains any stale completion signal before exposing a later incarnation.
The physical semaphore give remains outside the pool mutex. After every wake,
the waiter rechecks the exact slot incarnation and authoritative state under
that mutex: a matching `RESERVED`/`READY` slot treats the wake as stale and
continues waiting; exact `COMPLETE` returns its result; an incarnation mismatch
returns cancelled. This remains correct when an old give is delayed across hard
recycle/reserve and when a new completion fills the binary semaphore before the
old give. Filesystem no-response `FILE_PUT_DATA` work and
`FILE_GET_DATA`, `FILE_GET_END`, and `FILE_PUT_ACK` event
attempts are bound to the exact `{handle, connection generation, VM epoch}` and
serialize their final token check plus Notify with connection lifecycle. An
outer worker check alone is not sufficient. These are reference-agent
lifecycle rules and change no PBLE/1 wire byte. Every raw VFS effect, including
stat/open, each directory iterator step, each bounded CRC/read/write chunk,
close, remove/rmdir, mkdir, and rename, is bracketed by exact token checks. A
single pair around an entire handler or multi-operation loop is insufficient;
the check after one operation may serve as the check before the immediately
following operation only when no other effect intervenes.

`RUN`, `STOP`, and `SOFT_REBOOT` retain their specialized one-fragment
response-before-side-effect contracts in §6. Their response attempt is
connection-bound and may wait only for the current complete-message TX-mutex
boundary under the single absolute 15 ms deadline above. It then makes exactly
one local Notify submission and never waits or retries for mbuf/controller
capacity. Failure suppresses generic fallback and causes no corresponding
execution, interrupt, or reset side effect.

## 4. Opcodes

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`, closes OI-4).** The full v1.0 opcode set and its 1-byte numbers are stable; amend only via a `[docs]` commit before dependent code. This freeze is **status-only** — no wire byte changed. It fixes the opcode *set and numbers* (the DoR for F-02 `pyble_proto`). The **payload encodings** for the identity/identify opcodes freeze incrementally: `0x50 SET_LABEL` label max = **24 bytes UTF-8** is frozen in §7 (G1 · S3, for F-22); `0x51 SET_IDENTIFY_LED` GPIO+active-level encoding and `0x52 IDENTIFY` blink-duration bound are frozen in §7/§4 (G1 · S4, **closing OI-6**) for F-23.

| Opcode | Name | Dir | Notes |
|---|---|---|---|
| `0x01` | HELLO | CMD/RSP | Version + capability negotiation. First message after connect. |
| `0x02` | DEVICE_INFO | CMD/RSP | Chip, MicroPython version, free memory, fs root, MTU, `device_id`, `label`. |
| `0x10` | FILE_LIST | CMD/RSP | List a directory. |
| `0x11` | FILE_STAT | CMD/RSP | Size + crc of one path (used for resume). |
| `0x12` | FILE_GET_BEGIN | CMD/RSP | Start a download; board streams data as events. |
| `0x13` | FILE_GET_DATA | EVT | Download chunk (offset + bytes). |
| `0x14` | FILE_GET_END | EVT | Download complete (crc). |
| `0x15` | FILE_PUT_BEGIN | CMD/RSP | Start an upload (path, size, crc). |
| `0x16` | FILE_PUT_DATA | CMD | Upload chunk (offset + bytes); acked by window (§5). |
| `0x17` | FILE_PUT_END | CMD/RSP | Finish upload; board verifies crc. |
| `0x18` | FILE_DELETE | CMD/RSP | Delete a file. |
| `0x19` | MKDIR | CMD/RSP | Create a directory. |
| `0x1A` | FILE_RENAME | CMD/RSP | Rename/move. |
| `0x20` | RUN | CMD/RSP | Run a file path **or** an inline source snippet. |
| `0x21` | STOP | CMD/RSP | Interrupt the running program (KeyboardInterrupt). |
| `0x22` | SOFT_REBOOT | CMD/RSP | Soft-reset the MicroPython VM. |
| `0x23` | SET_AUTORUN | CMD/RSP | Enable/disable auto-run of `/main.py` at boot: `[enable:u8]` (0=off default, 1=on), persisted. **Additive opcode** (§9), gated by the `auto_run` cap — older clients ignore it. |
| `0x30` | CONSOLE_DATA | EVT | `stdout`/`stderr` bytes from the running program. |
| `0x31` | CONSOLE_INPUT | CMD | Feed bytes to the program's `stdin`. |
| `0x40` | RUN_STATE | EVT | State transition: `idle` / `running` / `done` / `error`. |
| `0x41` | FILE_PUT_ACK | EVT | Cumulative-offset acknowledgement for uploads (§5). |
| `0x50` | SET_LABEL | CMD/RSP | Set the persisted device label (UTF-8, bounded length); it becomes the advertised name and `DEVICE_INFO.label`. Empty clears it back to `PyBLE-XXXX`. |
| `0x51` | SET_IDENTIFY_LED | CMD/RSP | Configure the **single** optional identify status-LED: payload `[gpio:u8][active_level:u8]` (`active_level` 0=active-low, 1=active-high), persisted; **empty payload clears it**. `ERANGE` if `gpio` out of range, `EBADREQ` if `active_level`∉{0,1}. Device config only — **not** a routing/pin profile, never exposed to user code. |
| `0x52` | IDENTIFY | CMD/RSP | Blink the configured identify LED (5 Hz) for an optional `[duration_ds:u8]` (1–50 deciseconds; absent/0 → default 20 = 2 s; >50 clamped). Non-blocking — `RSP{OK}` returns immediately. `EUNSUPPORTED` if no identify LED is configured. |

The ESP reference `IDENTIFY` timer must also close a task-dispatch race that is
not visible on the wire. In the pinned ESP-IDF, a due periodic timer is
reinserted and its callback/argument are copied before the timer-list lock is
released; `esp_timer_stop()` can remove the reinserted timer but cannot revoke
that already-dequeued invocation. The handler therefore MUST NOT publish or
start a successor active arm immediately after `stop`. It records the request
as pending and queues a timer-task quiescence boundary. The first callback after
that boundary is drain-only: it consumes no tick, changes no GPIO, performs no
terminal stop, stops any still-armed handler boundary (accepting only `OK` or
already-inactive), and queues a distinct activation callback. Only that later
callback may mint/publish the successor `{VM epoch, arm incarnation, ticks}` and
start its periodic schedule, again without consuming a tick. Activation first
enters lifecycle activity for the pending epoch and then revalidates pending
phase/epoch under the identify domain; refusal cancels the pending request and
starts no periodic timer. Clear, reconfiguration, and VM disarm set the phase
idle and clear both pending and active state. Every active tick
then revalidates the exact arm before GPIO or timer-stop effects. A callback
already dequeued from any older periodic, quiescence, or activation phase can
therefore become only the drain callback; it cannot read/adopt, toggle, consume,
or stop the successor arm. Both phases remain non-blocking and allocation-free
per toggle. This is an execution clarification and changes no PBLE/1 bytes.

Any unexpected stop result or failure to queue the quiescence boundary makes
the initiating handler return `EINTERNAL` with pending/active state cleared and
the LED off. A drain or activation re-arm failure likewise clears to idle and
has no GPIO/tick effect. Active-incarnation mint remains nonzero and fails closed
before wrap, so the quiescence seam cannot reintroduce ABA.

## 5. File transfer (the reliability core)

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`).** The file-transfer wire below (read + windowed upload + jail) is stable — the DoR for F-08/F-09/F-17. Amend only via a `[docs]` commit before dependent code. Designed for a lossy, MTU-bounded link. All multi-byte fields little-endian; paths are `[plen:u16][path UTF-8]`, **max 128 B** (`ERANGE` over). File `DATA` chunks are sized to one BLE packet and never fragment. Exactly **one active transfer** (PUT or GET) at a time — a second `*_BEGIN` while one is active → `EBUSY`.

### Read (F-08)

- **`FILE_LIST` (0x10)** `[plen][path]` → `RSP [status]`; on `OK`, then `[more:u8][count:u16]` and count× `{[etype:u8][esize:u32][nlen:u16][name]}` (`etype` 0=file / 1=dir; `more`=1 if the listing was truncated to the worker buffer).
- **`FILE_STAT` (0x11)** `[plen][path]` → `RSP [status]`; on `OK`, then `[size:u32][crc32:u32]`. Missing path → `ENOENT`.
- **`FILE_GET_BEGIN` (0x12)** `[offset:u32][plen][path]` → `RSP [status]`; on `OK`, then `[total_size:u32]`. The whole-file CRC is delivered in `FILE_GET_END` (not up front — avoids a pre-scan double read); `FILE_STAT` first if you want it early.
- **`FILE_GET_DATA` (0x13, EVT, id 0)** `[offset:u32][bytes]` — one BLE packet each.
- **`FILE_GET_END` (0x14, EVT, id 0)** `[crc32:u32]` — whole-file CRC over `[0,total_size)` (the worker CRCs a skipped prefix on a resume-download too).

### Windowed upload (F-09) — sliding window, cumulative ACK, Go-Back-N

- **`FILE_PUT_BEGIN` (0x15)** `[total_size:u32][crc32:u32][plen][path]` → `RSP [status]`; on `OK`, then `[resume_offset:u32]` (0 in S5; resume fills it later). Opens a jailed temp `<dest>.pbltmp` (truncated); watermark = 0.
- **`FILE_PUT_DATA` (0x16, CMD, no RSP)** `[offset:u32][bytes]`. `offset==watermark` → write + advance + `ACK{watermark}`; `offset<watermark` → duplicate → re-`ACK` (idempotent); `offset>watermark` → gap → drop + `ACK{watermark}` (app resends from there). No out-of-order buffering.
- **`FILE_PUT_ACK` (0x41, EVT, id 0)** `[ack_offset:u32]` = highest contiguous byte written = next expected offset.
- **`FILE_PUT_END` (0x17)** `[crc32:u32]` → `RSP [status]`. `watermark ≠ total_size` → `ERANGE`; a latched write error → `ENOSPC`/`EIO`; temp CRC ≠ `crc32` → `ECRC`. In **every** failure the temp is deleted and **the old file is kept** (FR-FS-14). Else fsync + `rename(temp,dest)` (atomic on LittleFS) → `OK`.
- **`FILE_DELETE` (0x18)** `[plen][path]`: file → remove; empty dir → rmdir; non-empty dir → `EACCES` (no recursive delete); missing → `ENOENT`.
- **`MKDIR` (0x19)** `[plen][path]`: already-a-dir → `OK` (idempotent); an existing file → `EBADREQ`; missing parent → `ENOENT`.
- **`FILE_RENAME` (0x1A)** `[slen][src][dlen][dst]`: both jailed; src missing → `ENOENT`; dst a non-empty dir → `EACCES`; else atomic rename → `OK`.

**Resume on reconnect (F-10):** a link drop mid-`PUT` resets the in-RAM transfer state, but the jailed `<dest>.pbltmp` + its watermark persist on flash. On reconnect a `FILE_PUT_BEGIN` for the same dest returns `resume_offset` = the existing temp length (the contiguous prefix the board itself wrote; the worker re-CRCs `temp[0,len)` to re-seed the running whole-file CRC and set the watermark). `temp_len > total_size` → truncate to 0 (`resume_offset = 0`). The app resumes `FILE_PUT_DATA` from `resume_offset`; the whole-file CRC at `FILE_PUT_END` stays the only correctness gate — a bad/foreign prefix → `ECRC`, temp deleted, **old file kept byte-for-byte** (never a silent corruption or restart-from-zero).

**Workspace jail (F-17):** every path is canonicalized against `fs_root` at a **single chokepoint** before any vfs op; traversal (`../`) / absolute escapes outside `fs_root`, the reserved `.pbltmp` suffix, and protected top-level names → `EACCES` (SEC-4). The protected-name predicate is case-sensitive and applies only to the first canonical component relative to `fs_root`: names beginning with lowercase `pyble` or `pble`, plus exact `boot.py` and `_boot.py`, are protected. The same basename below a child directory is allowed, and ordinary root names such as `main.py` remain allowed. **`.py` / data only** — the agent never requires, generates, or accepts `.mpy` / `.pyc` transfer artifacts; no server-side compilation.

## 6. Run / Stop / Console

> **FROZEN for v1.0 (amended)** — RUN-file at G1 · S3; **`RUN{source}`, `STOP`, `SOFT_REBOOT`, `CONSOLE_DATA`, `CONSOLE_INPUT` frozen at G1 · S4 (2026-07-01 · `[docs]`)**; transactional RUN admission clarified 2026-08-14; default-MTU `STOP`/`SOFT_REBOOT` response-before-side-effect admission, per-event session binding, the runner pickup/control-resolution cut, and the bounded current-message TX-boundary wait clarified 2026-08-15. Wire below; amend only via a `[docs]` commit before dependent code.

- **`RUN` (0x20)** payload `[mode:u8][data]` — `mode` 0=file (`data` = UTF-8 path), 1=source (`data` = UTF-8 snippet). → `RSP{status}` (`OK` | `EBUSY` if one already running, FR-RUN-4 | `EBADREQ` bad mode | `ERANGE` over-length), then `RUN_STATE(running)`. Both modes share one lifecycle. Completion → `RUN_STATE(done)`; an uncaught exception → `CONSOLE_DATA(stderr, traceback)` then `RUN_STATE(error)`. A missing/inaccessible file surfaces asynchronously (`CONSOLE_DATA(stderr)` + `RUN_STATE(error)`), not as the `RSP`.

  An otherwise valid, non-busy RUN is admitted transactionally. The ESP
  reference agent makes a provisional, non-observable reservation and copies
  the request, then declares one specialized response attempt pending. Under one
  absolute 15 ms deadline it may wait only for the current complete-message TX-
  mutex boundary; once acquired it revalidates the connection and makes exactly
  one single-fragment local Notify submission for its matching `RSP{OK}`, with no
  capacity wait or retry. At the minimum ATT MTU 23, a fragment carries 19
  PBLE/1 message
  bytes and the response frame is 11 bytes, so it is always one fragment.
  Local Notify acceptance is the admission cut: only after it succeeds may the
  agent wake the runner exactly once. Therefore user code, console output, and
  every RUN event follow the response submission. Boundary-deadline expiry, a
  missing or changed connection, or local Notify backpressure restores the exact
  prior
  runnable state and produces no wake, execution, event, fallback response, or
  retry. A timeout caused by one of these local admission failures is therefore
  side-effect-free. Timeout alone does not prove rejection: a disconnect or
  response loss after local acceptance does not revoke the already-admitted run.
- **`STOP` (0x21)** no payload. Idempotent — on successful connection-bound,
  single-fragment `RSP{OK}` submission, STOP while idle is a no-op and STOP
  while running raises `KeyboardInterrupt` **in the runner task only** (the link
  stays live, FR-BLE-11) → clean teardown → `RUN_STATE(idle)` (FR-RUN-5/6/10).
  Local response-submission failure emits no fallback and performs no interrupt.

  Response acceptance and a delayed worker pickup are one ordered control
  transaction. Before attempting the response, the reference runner marks the
  control attempt unresolved under its runner-domain synchronization, then
  releases that synchronization before entering the TX domain. A reserved
  worker MUST NOT cross its event/execution gate while an earlier control
  attempt is unresolved. It waits on a pre-created resolution signal outside
  the runner domain, then loops and rechecks both the unresolved predicate and
  stop snapshot together under that domain. After the bounded single-submission
  response attempt, one runner-domain
  cut either (a) publishes the accepted STOP intent and worker pending exception
  before resolving the gate, or (b) resolves a failed attempt without an
  interrupt or stop effect; either resolution then wakes the worker. Thus response success before pickup permits no user
  code or RUN event from that reservation; pickup first makes the command an
  ordinary active-run interrupt.

  An active worker's terminal classification is a second consumer of the same
  gate. It MUST NOT commit `done`, `error`, or `idle` while a control attempt
  whose begin cut precedes that terminal cut remains unresolved. It waits on the
  same signal outside both the runner domain and the MicroPython GIL, then in one
  runner-domain cut observes the resolved stop flag and commits either
  `RUN_STATE(idle)` for accepted `STOP`/`SOFT_REBOOT` or the natural
  `done`/`error` state after response failure. If the terminal cut wins first,
  the natural terminal state is already authoritative and a later accepted
  `STOP` is the specified idle no-op. This ordering closes the local Notify
  acceptance-to-intent gap without holding the runner lock across TX or a wait.
  A successful later RUN reservation may consume
  only resolved stale idle-STOP intent, never an unresolved control attempt.
- **`SOFT_REBOOT` (0x22)** no payload. On the normal successfully armed grace
  path, `RSP{OK}` is immediate; the command stops any run, then soft-resets the
  MicroPython VM and returns to `RUN_STATE(idle)` (FR-RUN-8). VM teardown MUST
  NOT begin merely because the local BLE stack
  accepted the notification: the implementation MUST allow a short bounded
  delivery grace after submitting `RSP{OK}` so queued response bytes can reach
  the central. The ESP32 reference agent uses a pre-created 250 ms one-shot and
  refuses a second reboot with `EBUSY` while that reset is pending. If the
  `SOFT_REBOOT` response attempt fails, it MUST leave the VM running and
  emit no generic fallback rather than perform an ambiguous reset. Once the
  non-blocking FS quiescence gate succeeds and the response submission
  succeeds, all non-reboot CMD admission remains closed. The handler then arms
  the pre-created timer; arm failure immediately invokes non-returning
  `esp_restart()` with admission still closed. This post-`RSP{OK}` timer-arm
  failure is the sole hardware-restart exception to the normal delivery-grace
  and soft-reset path;
  the next VM initialization performs the epoch/reset transaction in §3.2 and
  reopens admission only after workers have entered, final wiring is safe, and
  auto-run admission has completed. A busy FS worker or
  non-empty FS queue returns `EBUSY` after reopening the provisional gate; a
  response-submission failure likewise reopens all gates and leaves the VM
  intact. This is an
  execution-order and lifecycle clarification; it changes no PBLE/1 bytes.

  `SOFT_REBOOT` uses the same unresolved-control pickup gate as `STOP`. It marks
  that gate only after its provisional FS/VM closure succeeds and before its
  response attempt. `PBLE_TX_OK` publishes runner stop intent while resolving
  the gate, before timer arm. On failure the provisional FS/VM gates are aborted
  before pickup is released without stop intent. Timer-arm failure remains the documented
  post-acceptance non-returning restart exception.
- **`CONSOLE_DATA` (0x30, EVT, id 0)** payload `[stream:u8][bytes]` — `stream` 0=stdout, 1=stderr (FR-CON-1/2).
- **`CONSOLE_INPUT` (0x31, CMD, no RSP)** payload `[bytes]` — appended to the running program's `stdin` (`input()`/`sys.stdin`); fire-and-forget, no reply frame (FR-CON-3).
- **`RUN_STATE` (0x40, EVT, id 0)** payload `[state:u8]` — 0 idle / 1 running / 2 done / 3 error (FR-RUN-7).

The console is **observe-anywhere**: `stdout`/`stderr` stream regardless of
which client triggered the run. Each new logical `RUN_STATE` event and each
newly formed `CONSOLE_DATA` chunk independently captures the then-current live
`{connection handle, connection generation, VM epoch}` at event creation. If
no live session exists then, that event is omitted rather than retained for a
future client. Every fragment and retry of one created event retains that exact
token and MUST NOT retarget: disconnect or VM-epoch change invalidates its
buffered work, while a later new event MAY bind a successor session after
reconnect. This rule applies equally to command-started and opt-in auto-runs.
It does not change `RUN` command admission: the matching response and execution
cut remain bound to the command's originating session. USB is a local-debug
mirror only — never a runtime transport (FR-CON-5).

## 7. HELLO & capabilities

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`).** The capability field set below, the **HELLO-is-the-first-exchange** rule, and the invariant that an **INFO-characteristic read returns the same `DEVICE_INFO` payload** are stable — the DoR for F-03 `pyble_info` and F-16. **Closes the label half of OI-6: the `SET_LABEL` / `label` maximum is 24 bytes (UTF-8 encoded); an over-length label is rejected with `ERANGE` and not stored, and the same bound applies to the advertised name.** **Closes the OI-6 remainder at S4:** `SET_IDENTIFY_LED` = `[gpio:u8][active_level:u8]` (empty clears), `IDENTIFY` = optional `[duration_ds:u8]` (1–50 ds, default 20, 5 Hz). Amend only via a `[docs]` commit before dependent code.

`HELLO { proto_versions[], app_name, app_version }` is the **first exchange after connect** (before subscribing to TX) → `RSP { proto_version, caps }` where `caps` includes: `chip` (the PBLE/1 wire key for a port-defined ASCII target identifier; the v1 reference agents emit `esp32`/`esp32-s3`/`esp32-c3`), `mpy_version`, `agent_version` (the PyBLE agent firmware SemVer), `fs_root`, `max_file_size`, `put_window W`, `chunk_size`, `has_sd`, `free_mem`, `device_id` (a stable, non-personal port-defined suffix; MAC-derived on the ESP32 reference port), `label` (the user-set device label, or empty; **max 24 bytes UTF-8, else `ERANGE`**), `has_identify` (the board supports `IDENTIFY`), `identify_led` (the configured identify-LED GPIO as a byte, or `0xFF` = none), and `auto_run` (whether `/main.py` auto-runs at boot: 0=off default, 1=on; set via `SET_AUTORUN`). Reading the **INFO characteristic returns the same `DEVICE_INFO` caps payload** (no subscription needed).

**Caps payload serialization (frozen 2026-07-02 · `[docs]`, S2-app coordination):** the caps payload is newline-separated ASCII `key=value` text, one pair per line, with the short key tokens the reference agent emits — `proto`, `agent`, `chip`, `mpy`, `fs_root`, `mtu`, `window`, `chunk`, `free_mem`, `has_sd`, `has_identify`, `identify_led` (integer GPIO; `255` = none), `auto_run`, `device_id`, `label` (may be empty). Booleans are `0`/`1`; integers are decimal. Clients MUST parse tolerantly — unknown keys are ignored (additive caps, §9) and key order is not significant. The `HELLO` RSP payload is `[status:u8]` followed by this same caps text.

The client MUST treat `chip` as display/reference metadata rather than an
allowlist: an unknown value does not block a conforming connection. It must not
use a feature the board did not advertise — e.g. it offers an Identify action
only when `has_identify` is set. PBLE/1's numeric `identify_led` encoding is
optional: a port whose pins cannot be represented by `gpio:u8` advertises
`has_identify=0` and returns `EUNSUPPORTED`; a portable non-numeric pin encoding
would require a future additive capability/opcode or PBLE/2. These
identity/identify capabilities are **additive within PBLE/1** (§9): an older
client simply ignores them.

## 8. Status / error codes (1-byte `status` in RSP)

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`).** The 1-byte status set and its numbers are stable; amend only via a `[docs]` commit before dependent code. Status-only freeze — no wire byte changed. This is part of the DoR for F-02 `pyble_proto` (the status-mapping acceptance criteria, FR-PROTO-6).

| Code | Name | Meaning |
|---|---|---|
| `0x00` | OK | Success |
| `0x01` | EBADREQ | Malformed request |
| `0x02` | ENOENT | No such file/dir |
| `0x03` | EACCES | Path not permitted |
| `0x04` | ENOSPC | Filesystem full |
| `0x05` | EIO | I/O error |
| `0x06` | ENOMEM | Out of memory |
| `0x07` | EBUSY | A program is already running |
| `0x08` | ECRC | Checksum mismatch |
| `0x09` | ERANGE | Bad offset/length |
| `0x0A` | EUNSUPPORTED | Opcode/feature not supported |
| `0xFF` | EINTERNAL | Unexpected internal error |

## 9. Versioning policy

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`).** v1.0 supports **exactly `VER = 0x01`** (`PBLE_PROTO_VERSION = 1`): a frame with any other `VER` is refused (`EBADREQ`), and a `HELLO` whose `proto_versions[]` does not include `1` is refused rather than served — the DoR for F-16 (FR-PROTO-7). Capabilities are additive within v1.0 (an older client ignores unknown caps). Amend only via a `[docs]` commit before dependent code.

`VER` and the HELLO `proto_versions[]` exchange let either side refuse or downgrade gracefully. Backward-incompatible changes bump the protocol to PBLE/2; additive opcodes are gated behind capability flags so old clients keep working. No silent wire-format changes within version 1.

## 10. Security note (v1)

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`) — this completes PBLE/1 (§2–§10 all frozen).** The v1 posture: link-layer pairing/encryption is **available and used** (NimBLE Just-Works, LE Secure Connections, bonding; `sm_io_cap = NO_INPUT_OUTPUT`, MITM off) but is **not access-gating** — the RX/TX/INFO characteristics carry no per-characteristic encryption-permission flag, so a normal central connects and speaks PBLE/1 without a mandatory pairing step (SEC-1/2). No application-layer auth (a connected client is trusted). A **single active writer** serializes mutating file ops + program runs (SEC-3, via the file single-active-transfer + the runner's single-program `EBUSY`). Identity is **display-only** — never gate or branch trust on MAC / `device_id` / `label` (SEC-7/11); the advertisement carries only the Service UUID + name (no PII, SEC-10); nothing is transmitted off-device (no telemetry, SEC-5). Amend only via a `[docs]` commit before dependent code.

BLE link-layer pairing/encryption is the baseline. v1 has no application-layer auth (a connected client is trusted), matching the "personal board on a workbench" model. A future capability may add an application-layer pairing token; it would be negotiated in HELLO and is intentionally out of v1 scope.

Setting the device label (`SET_LABEL`), configuring the identify LED (`SET_IDENTIFY_LED`), and triggering `IDENTIFY` are ordinary control commands under this connected-client trust model. The device **label is broadcast** in the advertisement, so it **MUST NOT** contain personal data: the board bounds the label length and the default name (`PyBLE-XXXX`) carries no personal data. The board **MUST NOT** gate access by MAC or label — `device_id` is for recognition/display only, never authorization.
