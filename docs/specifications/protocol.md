# PBLE/1 — PyBLE BLE Wire Protocol

Status: **§2–§10 FROZEN for v1.0 (complete)** · Version: 1 · Last updated: 2026-09-02

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

The 2026-09-02 v0.6.1 hardening amendment freezes HELLO request syntax and
session state, inbound-validation precedence, bounded hostile-fragment
handling, fresh RUN namespaces and stdin boundaries, upload admission and
scratch recovery, and label-byte validation. It adds no opcode, status,
capability key, payload field, UUID, or other PBLE/1 wire byte.

**Freeze ledger (per-section):**

| Section | Freeze status | Freeze act |
|---|---|---|
| §2 BLE transport (GATT) — Service/RX/TX/INFO UUID base, advertising, MTU | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; default-MTU delivery · 2026-08-15; negotiation ordering · 2026-09-02 · `[docs]` |
| §3 Framing — §3.1 message frame, §3.2 fragmentation | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; restart/delivery semantics · 2026-08-15; inbound bounds/precedence · 2026-09-02 · `[docs]` |
| §4 Opcodes — the v1.0 opcode set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` (closes OI-4) |
| §8 Status / error codes — the 1-byte status set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §6 Run/Stop/Console — RUN{file,source}, RUN_STATE, EBUSY, STOP, SOFT_REBOOT, CONSOLE_DATA/INPUT | **FROZEN for v1.0 (amended)** | G1 · 2026-07-01; transactional RUN admission · 2026-08-14; default-MTU STOP/SOFT_REBOOT admission and per-event session binding · 2026-08-15; namespace/stdin isolation · 2026-09-02 · `[docs]` (RUN-file at S3; STOP / console / RUN-source at S4) |
| §7 HELLO & capabilities — caps field set, HELLO-first, INFO==DEVICE_INFO, label max = 24 B (label half of OI-6) | **FROZEN for v1.0 (amended)** | G1 · 2026-07-01; request/session syntax and label-byte validation · 2026-09-02 · `[docs]` |
| §9 Versioning policy — accept only `VER 0x01`, refuse unsatisfiable, additive caps | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §5 File transfer — read + windowed upload + workspace jail | **FROZEN for v1.0 (amended)** | G1 · 2026-07-01; scratch/mutation/admission hardening · 2026-09-02 · `[docs]` |
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

GATT discovery, enabling the TX characteristic's CCCD, an INFO read, and an
optional MTU exchange are transport setup, not PBLE/1 message exchanges. A
client MUST enable TX notifications before writing its first PBLE/1 frame so
the board can deliver the HELLO response. The first complete PBLE/1 `CMD` in
each connection/VM epoch is HELLO; reading INFO neither negotiates nor changes
that ordering.

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

**Inbound hardening (amended 2026-09-02).** Each `FIRST` starts one absolute
**5000 ms** receive-reassembly deadline. Fragment progress never extends it.
The receiver checks that deadline before accepting every continuation; an
expired continuation discards the whole run. A new `FIRST` is always permitted
to abandon and replace an incomplete or expired run. Reassembly storage remains
bounded by the port's advertised/defined maximum message size; an oversize run
is discarded as one run, and its trailing non-`FIRST` fragments are suppressed
rather than counted repeatedly.

The agent validates one completed inbound frame in this order: exact structural
length, CRC, direction/request ID, `VER`, HELLO/session state, then opcode and
handler payload. CRC failure is always the existing `EVT` with the offending
opcode where safely available, `ID=0`, and payload `ECRC`; it is never a `RSP`.
A structurally invalid frame receives `RSP{EBADREQ}` only when the complete
six-byte header is safely present and identifies `VER=1`, `TYPE=CMD`, and a
nonzero request ID;
otherwise it is silently dropped. After structural and CRC validation, an
inbound frame whose `TYPE` is not `CMD` or whose request ID is zero is silently
dropped, preventing response loops. A different `VER` in an otherwise valid
`CMD` receives `RSP{EBADREQ}`. An unknown opcode after successful negotiation
receives `RSP{EUNSUPPORTED}`.

Each exact connection/VM epoch has a monotonic malformed-input budget of
**8 protocol violations**. The counted units are one per discarded bad
fragment run/frame or rejected command: expired continuation, fragment gap or
wrong index, oversize run, structural/CRC/`VER`/direction/ID failure, malformed
HELLO syntax, and a non-HELLO command before negotiation. A valid but
unsupported HELLO version offer, an unsupported opcode after negotiation, and
handler-level payload/status errors do not consume this budget. On the eighth
violation the agent clears RX state and terminates that exact session without
attempting another error frame. Only disconnect or VM-epoch rotation clears
the counter.

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
recursive TX mutex has one lock order with lifecycle state for ordinary TX,
connect/open, and disconnect/reset cleanup: TX mutex first, then the session
critical section. The final exact-token check and `ble_gatts_notify_custom`
remain inside that TX ownership. Required termination first claims an exact-
session terminal-admission latch under the session critical section and records
the start of the one absolute termination deadline. Every live/admission check
treats that latch as non-live before the host waits for the physical TX mutex
using only the deadline residual. A Notify that already passed its final exact-
token check may finish during that bounded drain; no new CMD, ticket, or TX
admission can begin. With TX ownership, the host revalidates the latch and uses
the normal TX-then-session lock order to claim `OPEN → CLOSING`. Failure to
acquire the TX mutex by the deadline claims `RESTARTING` and restarts. The state
machine is `CLOSED`/`OPEN`/`CLOSING`/`CLEANING`/
`RESTARTING`, and neither a reused handle nor a later lifecycle event can open
or clean a terminal `RESTARTING` token.

Cold native initialization initializes this retained state exactly once and
pre-creates one task-dispatched ESP timer before NimBLE can start or advertise;
MicroPython soft reset and repeated agent initialization do not reset either.
Creation failure leaves the agent unadvertised. A successful GAP connect mints
a nonzero generation and opens the exact token under the session critical
section before exposing it. If the state is not `CLOSED`, the board restarts
instead of overwriting an old token.

The terminal-admission latch reads `esp_timer_get_time()` once. The later
`OPEN → CLOSING` reducer step receives that same start time and therefore
stores one absolute deadline 2500 ms ahead. The initial physical arm uses only
the positive residual `deadline - esp_timer_get_time()`, never a fresh 2500 ms
interval; reaching the deadline before mutex acquisition or arm instead claims
`RESTARTING`. Reducer begin, immutable watchdog-ticket capture, residual
calculation, `esp_timer_start_once`, and reducer arm acknowledgement form one
uninterrupted session-critical transaction while the TX mutex remains owned. A
task-dispatched callback therefore cannot consume the physical
one-shot while the reducer still considers it unarmed. Only after a successful
acknowledgement does the host make exactly one `ble_gap_terminate` call, outside
both locks. The deadline never moves. TX-drain timeout or initial arm failure
claims `RESTARTING` and restarts without attempting GAP. Return `0` and
`BLE_HS_EALREADY` mean only
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
| `0x51` | SET_IDENTIFY_LED | CMD/RSP | Configure the **single** optional identify status-LED: payload is **exactly** `[gpio:u8][active_level:u8]` (`active_level` 0=active-low, 1=active-high), persisted; **exactly empty** payload clears it. Every other length, including trailing bytes, is `EBADREQ`; `ERANGE` if `gpio` is out of range, `EBADREQ` if `active_level`∉{0,1}. Device config only — **not** a routing/pin profile, never exposed to user code. |
| `0x52` | IDENTIFY | CMD/RSP | Blink the configured identify LED (5 Hz) for an optional `[duration_ds:u8]` (1–50 deciseconds; absent/0 → default 20 = 2 s; >50 clamped). Non-blocking — `RSP{OK}` returns immediately. `EUNSUPPORTED` if no identify LED is configured. |

Every opcode payload above and in §§5–7 is an exact grammar. A structured or
fixed-length payload MUST be consumed in full; otherwise trailing bytes are
`EBADREQ` with no handler side effect. This includes empty `DEVICE_INFO`,
`STOP`, and `SOFT_REBOOT`; all path and offset/CRC forms; one-byte
`SET_AUTORUN`; zero-or-two-byte `SET_IDENTIFY_LED`; and zero-or-one-byte
`IDENTIFY`. A field explicitly defined as the remaining bytes—RUN file/source,
`FILE_PUT_DATA` data, `CONSOLE_INPUT`, or `SET_LABEL`—naturally consumes that
remainder. PBLE/1 has no implicit extension bytes; a future additive form needs
a capability/opcode or a documented amendment before implementation.

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

- **`FILE_LIST` (0x10)** `[plen][path]` → `RSP [status]`; on `OK`, then `[more:u8][count:u16]` and count× `{[etype:u8][esize:u32][nlen:u16][name]}` (`etype` 0=file / 1=dir; `more`=1 if at least one **visible** entry was truncated to the worker buffer). Every entry whose basename ends with the case-sensitive reserved `.pbltmp` suffix is omitted before stat, count, and response-budget accounting, whether that entry is a file or directory.
- **`FILE_STAT` (0x11)** `[plen][path]` → `RSP [status]`; on `OK`, then `[size:u32][crc32:u32]`. Missing path → `ENOENT`.
- **`FILE_GET_BEGIN` (0x12)** `[offset:u32][plen][path]` → `RSP [status]`; on `OK`, then `[total_size:u32]`. The whole-file CRC is delivered in `FILE_GET_END` (not up front — avoids a pre-scan double read); `FILE_STAT` first if you want it early.
- **`FILE_GET_DATA` (0x13, EVT, id 0)** `[offset:u32][bytes]` — one BLE packet each.
- **`FILE_GET_END` (0x14, EVT, id 0)** `[crc32:u32]` — whole-file CRC over `[0,total_size)` (the worker CRCs a skipped prefix on a resume-download too).

### Windowed upload (F-09) — sliding window, cumulative ACK, Go-Back-N

- **`FILE_PUT_BEGIN` (0x15)** `[total_size:u32][crc32:u32][plen][path]` → `RSP [status]`; on `OK`, then `[resume_offset:u32]`. It prepares the jailed sibling `<dest>.pbltmp`, verifies any resumable prefix, applies the admission rule below, and sets the watermark to `resume_offset`.
- **`FILE_PUT_DATA` (0x16, CMD, no RSP)** `[offset:u32][bytes]`. `offset==watermark` and `offset + len(bytes) <= total_size` → write + advance + `ACK{watermark}`; `offset<watermark` → duplicate → re-`ACK` (idempotent); `offset>watermark` → gap → drop + `ACK{watermark}` (app resends from there). A chunk that would cross `total_size` writes no byte and latches `ERANGE` for `FILE_PUT_END`. Watermark and CRC advance only after the VFS reports exact, positive progress covering the entire input chunk; `None`, zero, an impossible count, or an incomplete write latches `EIO`. No out-of-order buffering.
- **`FILE_PUT_ACK` (0x41, EVT, id 0)** `[ack_offset:u32]` = highest contiguous byte written = next expected offset.
- **`FILE_PUT_END` (0x17)** `[crc32:u32]` → `RSP [status]`. `watermark ≠ total_size` → `ERANGE`; a latched write error → `ENOSPC`/`EIO`; temp CRC ≠ `crc32` → `ECRC`. For every such failure, abort closes the scratch object, removes the scratch path non-recursively, and confirms absence before reporting the originating status; **the old file is kept** (FR-FS-14). A close/removal/absence-verification failure returns `EIO` instead, retains the old target, and never reports successful cleanup; any unremovable scratch remains reserved and hidden. Else fsync + `rename(temp,dest)` (atomic on LittleFS) → `OK`.
- **`FILE_DELETE` (0x18)** `[plen][path]`: file → remove; empty dir → rmdir; non-empty dir → `EACCES` (no recursive delete); missing → `ENOENT`.
- **`MKDIR` (0x19)** `[plen][path]`: already-a-dir → `OK` (idempotent); an existing file → `EBADREQ`; missing parent → `ENOENT`.
- **`FILE_RENAME` (0x1A)** `[slen][src][dlen][dst]`: both jailed; src missing → `ENOENT`; dst a non-empty dir → `EACCES`; else atomic rename → `OK`. Each path independently retains the 128-byte maximum, so the receiver and any deferred-work envelope MUST accept the legal 260-byte request payload (`2 + 128 + 2 + 128`); 129 bytes in either path is `ERANGE`.

The three namespace mutations parse and jail-resolve every supplied path first.
While a PUT is active they then return `EBUSY` before any stat or mutation;
therefore malformed payloads still take `EBADREQ`, forbidden paths still take
`EACCES`, and a valid mutation takes `EBUSY` independent of path existence.
`FILE_LIST` and `FILE_STAT` remain available during PUT. This serialization is
only for the PBLE/1 bridge; ordinary user code retains direct VFS access.

**Resume on reconnect (F-10):** a link drop mid-`PUT` resets the in-RAM transfer state, but the jailed `<dest>.pbltmp` prefix persists on flash. A scratch prefix is resumable only when it is a regular file, `0 < length <= total_size`, exactly that many bytes are read and CRC'd, and its type and length remain stable through that scan. Only then may `FILE_PUT_BEGIN` return the verified length as a nonzero `resume_offset`, re-seed the running whole-file CRC, and set the watermark. A missing or zero-length regular scratch means a fresh upload. An oversized, short-read, unreadable, changed, or type-invalid scratch is malformed: the agent removes a malformed regular file or empty scratch directory, confirms absence, and restarts at zero. It never recursively removes, truncates, renames, or otherwise changes a nonempty scratch directory or the old destination; a nonempty scratch directory or failed safe removal returns `EIO`. A structurally valid but foreign prefix may resume, but the whole-file CRC at `FILE_PUT_END` remains the content-identity gate: `ECRC` deletes the scratch and keeps the old destination byte-for-byte.

Every queued or in-flight transfer operation owns the exact `{handle,
connection generation, VM epoch}` from its command. Disconnect/VM invalidation
atomically advances a transfer generation before successor work can publish
state. In particular, a delayed `FILE_PUT_BEGIN` may finish one indivisible VFS
call that began while its token was live, but after the mandatory revalidation
it may only close its own newly opened object: it MUST NOT install or clear
active-transfer state, clear/adopt successor state, emit an ACK, or publish a
response. Transfer-state publication and its final ownership check form one
indivisible cut. A later session may reclaim an active record only when that
record's stored generation is stale; DATA and END require an exact generation
match. These rules prevent a predecessor disconnect race from erasing or
adopting a successor upload and change no PBLE/1 byte.

Any VFS stream count is validated before the corresponding buffer range is
read, CRC'd, copied, or exposed. It MUST be an integer in `0..requested`; a
negative, non-integer, or over-reported count is `EIO`. A zero count before the
promised extent is complete is a short read and is also `EIO`. For the portable
binary-file API, the exact equivalent is an exact `bytes` result whose length
is in `0..requested`; any other result is `EIO`. A fault discovered before a
response is committed returns `EIO` normally. Once a successful
`FILE_GET_BEGIN` response is committed, a read fault aborts that stream, emits
no later `FILE_GET_DATA`, and MUST NOT emit `FILE_GET_END`; the client therefore
uses its existing missing-END/extent timeout and reports an unsuccessful
download. No replacement response or new error event is invented within
PBLE/1.

**Upload admission (amended 2026-09-02):** PBLE/1 retains the existing
`total_size:u32`; v0.6.1 adds no fixed-size capability. Before creating or
growing scratch, `FILE_PUT_BEGIN` reads `statvfs(fs_root)` and applies a
**65,536-byte safety reserve** using checked 64-bit arithmetic:

```text
unit      = f_frsize
free      = f_bavail * unit
remaining = total_size - resume_offset
needed    = ceil(remaining / unit) * unit
accept iff free >= 65,536 + needed
```

Zero/invalid geometry, invalid counters, or arithmetic overflow returns `EIO`;
insufficient space returns `ENOSPC`. Existing scratch allocation is already
reflected in `free`, so only its verified remainder is charged. Space occupied
by the old destination is never credited because that file remains until the
atomic commit. The reserve is admission headroom, not a promise about the exact
post-write free count because VFS metadata can consume additional blocks.

**Workspace filesystem.** Official PyBLE images mount their internal workspace
as LFS2 on all five profiles. The ESP partition-table `data,fat` subtype is only
ESP-IDF block-container metadata; the label `vfs` selects MicroPython's LFS2
first-use provisioning and the on-media format is LFS2. ESP boot must construct
the LFS2 VFS explicitly instead of accepting the generic FAT fallback. A
nonblank incompatible or corrupt workspace fails closed without formatting or
starting the PBLE/1 agent; migration/recovery is an explicit operator action.
This is what makes the successful scratch-to-target replacement above an
atomic filesystem commit rather than FAT's delete-then-rename sequence.

**Workspace jail (F-17):** every path is strict scalar UTF-8 and is canonicalized against `fs_root` at a **single chokepoint** before any vfs op; malformed UTF-8 → `EBADREQ`, while traversal (`../`) / absolute escapes outside `fs_root`, any component ending with the case-sensitive reserved `.pbltmp` suffix, and a case-sensitive reserved first canonical component relative to `fs_root` → `EACCES` (SEC-4). The reserved first component is any lowercase name beginning `pyble` or `pble`, or exact `boot.py` / `_boot.py`; the same basename below an ordinary first component is allowed, and ordinary root names such as `main.py` remain allowed. Scratch names are also hidden from listings as specified above. **`.py` / data only** — the agent never requires, generates, or accepts `.mpy` / `.pyc` transfer artifacts; no server-side compilation.

## 6. Run / Stop / Console

> **FROZEN for v1.0 (amended)** — RUN-file at G1 · S3; **`RUN{source}`, `STOP`, `SOFT_REBOOT`, `CONSOLE_DATA`, `CONSOLE_INPUT` frozen at G1 · S4 (2026-07-01 · `[docs]`)**; transactional RUN admission clarified 2026-08-14; default-MTU `STOP`/`SOFT_REBOOT` response-before-side-effect admission, per-event session binding, the runner pickup/control-resolution cut, and the bounded current-message TX-boundary wait clarified 2026-08-15. Wire below; amend only via a `[docs]` commit before dependent code.

- **`RUN` (0x20)** payload `[mode:u8][data]` — `mode` 0=file (`data` = UTF-8 path), 1=source (`data` = UTF-8 snippet). → `RSP{status}` (`OK` | `EBUSY` if one already running, FR-RUN-4 | `EBADREQ` bad mode | `ERANGE` over-length), then `RUN_STATE(running)`. Both modes share one lifecycle. Completion → `RUN_STATE(done)`; an uncaught exception → `CONSOLE_DATA(stderr, traceback)` then `RUN_STATE(error)`. A missing/inaccessible file surfaces asynchronously (`CONSOLE_DATA(stderr)` + `RUN_STATE(error)`), not as the `RSP`. Every ordinary or autorun execution receives a fresh globals/locals dictionary containing `__name__ = "__main__"`; variables created by an earlier run are absent. PBLE/1 v0.6.1 does not yet define `__file__`, working-directory changes, sibling-import setup, or `sys.modules` cleanup.

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

  While an accepted `SOFT_REBOOT` keeps global command admission closed, that
  closing state has precedence over HELLO/session negotiation and malformed-
  session violation accounting, including if a numeric handle is re-presented
  before the 250 ms grace ends. Every otherwise structurally valid response-
  bearing CMD, including `DEVICE_INFO`, `HELLO`, and a duplicate
  `SOFT_REBOOT`, returns `EBUSY`; a no-response command is silently discarded.
  No handler side effect or violation debit occurs. Only VM initialization may
  reopen admission.
- **`CONSOLE_DATA` (0x30, EVT, id 0)** payload `[stream:u8][bytes]` — `stream` 0=stdout, 1=stderr (FR-CON-1/2).
- **`CONSOLE_INPUT` (0x31, CMD, no RSP)** payload `[bytes]` — appended to the active program's bounded `stdin` (`input()`/`sys.stdin`); fire-and-forget, no reply frame (FR-CON-3). Input received while no program is active is silently discarded. A successful RUN response-admission cut clears stdin before waking the runner; autorun admission does the same. Accepted STOP clears it after response handoff, and every terminal transition, disconnect, and VM reset clears it. Disconnect does not itself stop a continuing run, so the active flag remains true and a newly negotiated client may feed that same run; only the queued bytes from before the disconnect are lost. These boundaries prevent idle input and overflow from one run being consumed by another.
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

Terminal state publication, stdin deactivation/clear, and release of the
single-run reservation are one ordered lifecycle cut. A successor RUN cannot
become reservable until its predecessor's stdin is empty and inactive;
terminal cleanup from the predecessor cannot later erase bytes admitted for
the successor. The clear/deactivate operation is allocation-free, including
under memory pressure.

## 7. HELLO & capabilities

> **FROZEN for v1.0 (G1 · 2026-07-01; amended 2026-09-02 · `[docs]`).** The capability field set below, the **HELLO-is-the-first-exchange** rule, and the invariant that an **INFO-characteristic read returns the same `DEVICE_INFO` payload** are stable — the DoR for F-03 `pyble_info` and F-16. **Closes the label half of OI-6: the `SET_LABEL` / `label` maximum is 24 bytes (UTF-8 encoded); an over-length label is rejected with `ERANGE` and not stored, and the same bound applies to the advertised name.** **Closes the OI-6 remainder at S4:** `SET_IDENTIFY_LED` = `[gpio:u8][active_level:u8]` (empty clears), `IDENTIFY` = optional `[duration_ds:u8]` (1–50 ds, default 20, 5 Hz). Amend only via a `[docs]` commit before dependent code.

`HELLO` is the first complete PBLE/1 frame after the §2 transport setup. Its
request payload is newline-separated ASCII `key=value` text no longer than
**192 bytes**. A valid request contains exactly one each of the required keys
`proto_versions`, `app_name`, and `app_version`; key order is insignificant.
Lines use LF (`0x0A`), one optional trailing LF is accepted, and empty interior
lines are invalid. Each line is split at its first `=`. Keys match
`[a-z][a-z0-9_]{0,31}`. Unknown well-formed keys with printable ASCII values no
longer than 32 bytes are ignored. A duplicate or missing required key,
CR/NUL/non-ASCII byte, malformed key/value line, or over-bound payload/value is
`EBADREQ`.

`proto_versions` is 1–8 comma-separated unsigned canonical decimal integers
in `0..255`; empty elements, leading zeroes except the single token `0`, and
non-digits are invalid. `app_name` and `app_version` are each 1–32 bytes of
printable ASCII (`0x20..0x7E`). The v1 agent chooses version 1 exactly when the
offer contains 1. A syntactically valid offer without 1 returns
`EUNSUPPORTED`; malformed syntax returns `EBADREQ`. The agent neither persists,
logs, nor echoes the two app-identification values.

Each exact `{connection generation, VM epoch}` begins `UNNEGOTIATED`. INFO
reads remain allowed and do not change it. Before negotiation, HELLO is the
only command admitted to an opcode handler. Any other response-bearing command
returns `EBADREQ` without side effects; `FILE_PUT_DATA` and `CONSOLE_INPUT`,
whose opcodes define no `RSP`, are silently dropped without side effects. The
session becomes `NEGOTIATED(v1)` only after the final fragment of its
`HELLO RSP{OK}` is accepted by the bounded, session-bound local Notify path.
Repeating a compatible HELLO is idempotent and returns current caps. A failed
initial HELLO leaves the session unnegotiated; a failed repeated HELLO leaves
an already negotiated session negotiated. Disconnect and VM-epoch rotation
clear negotiation before later RX admission.

The response contains the frozen caps text below; `proto=1` is the selected
version and no additional selected-version byte exists. The fields describe
`chip` (a port-defined target token), `agent` (agent SemVer), `mpy`, `fs_root`,
`mtu`, `window`, `chunk`, `free_mem`, `has_sd`, `has_identify`, `identify_led`,
`auto_run`, `device_id`, and `label`. Reading INFO returns the same caps text
without subscription or negotiation. `max_file_size` was never a serialized
PBLE/1 key and is not added in v0.6.1; §5 defines dynamic upload admission.

**Caps payload serialization (frozen 2026-07-02; clarified 2026-09-02 · `[docs]`, S2-app coordination):** the caps payload is newline-separated UTF-8 `key=value` text, one pair per line, with the short key tokens the reference agent emits — `proto`, `agent`, `chip`, `mpy`, `fs_root`, `mtu`, `window`, `chunk`, `free_mem`, `has_sd`, `has_identify`, `identify_led` (integer GPIO; `255` = none), `auto_run`, `device_id`, `label` (may be empty). Keys and every non-label value are ASCII; `label` is the sole UTF-8 value. Booleans are `0`/`1`; integers are decimal. Clients MUST parse tolerantly — unknown keys are ignored (additive caps, §9) and key order is not significant. The `HELLO` RSP payload is `[status:u8]` followed by this same caps text.

For `SET_LABEL`, encoded length is checked first: more than 24 bytes returns
`ERANGE`. Otherwise nonempty input must be strict, well-formed UTF-8 and must
not contain Unicode control code points U+0000–U+001F or U+007F–U+009F;
failure returns `EBADREQ`. Empty input remains the clear operation. Rejected or
failed persistence leaves the stored label, caps value, and advertisement
unchanged.

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

> **FROZEN for v1.0 (G1 · 2026-07-01; clarified 2026-09-02 · `[docs]`).** v1.0 supports **exactly `VER = 0x01`** (`PBLE_PROTO_VERSION = 1`). Under §3.1 response eligibility, an otherwise valid inbound `CMD` frame with another `VER` receives `EBADREQ`; a syntactically valid HELLO offer without version 1 receives `EUNSUPPORTED`; malformed HELLO syntax receives `EBADREQ`. A compatible repeated HELLO is idempotent. Capabilities are additive within v1.0 (an older client ignores unknown caps). Amend only via a `[docs]` commit before dependent code.

`VER` and the HELLO `proto_versions[]` exchange let either side refuse or downgrade gracefully. Backward-incompatible changes bump the protocol to PBLE/2; additive opcodes are gated behind capability flags so old clients keep working. No silent wire-format changes within version 1.

## 10. Security note (v1)

> **FROZEN for v1.0 (G1 · 2026-07-01 · `[docs]`) — this completes PBLE/1 (§2–§10 all frozen).** The v1 posture: link-layer pairing/encryption is **available and used** (NimBLE Just-Works, LE Secure Connections, bonding; `sm_io_cap = NO_INPUT_OUTPUT`, MITM off) but is **not access-gating** — the RX/TX/INFO characteristics carry no per-characteristic encryption-permission flag, so a normal central connects and speaks PBLE/1 without a mandatory pairing step (SEC-1/2). No application-layer auth (a connected client is trusted). A **single active writer** serializes mutating file ops + program runs (SEC-3, via the file single-active-transfer + the runner's single-program `EBUSY`). Identity is **display-only** — never gate or branch trust on MAC / `device_id` / `label` (SEC-7/11); the advertisement carries only the Service UUID + name (no PII, SEC-10); nothing is transmitted off-device (no telemetry, SEC-5). Amend only via a `[docs]` commit before dependent code.

BLE link-layer pairing/encryption is the baseline. v1 has no application-layer auth (a connected client is trusted), matching the "personal board on a workbench" model. A future capability may add an application-layer pairing token; it would be negotiated in HELLO and is intentionally out of v1 scope.

Setting the device label (`SET_LABEL`), configuring the identify LED (`SET_IDENTIFY_LED`), and triggering `IDENTIFY` are ordinary control commands under this connected-client trust model. The device **label is broadcast** in the advertisement, so it **MUST NOT** contain personal data: the board bounds the label length and the default name (`PyBLE-XXXX`) carries no personal data. The board **MUST NOT** gate access by MAC or label — `device_id` is for recognition/display only, never authorization.
