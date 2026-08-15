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

**Freeze ledger (per-section):**

| Section | Freeze status | Freeze act |
|---|---|---|
| §2 BLE transport (GATT) — Service/RX/TX/INFO UUID base, advertising, MTU | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; default-MTU delivery · 2026-08-15 · `[docs]` |
| §3 Framing — §3.1 message frame, §3.2 fragmentation | **FROZEN for v1.0 (amended)** | G0 · 2026-07-01; restart/delivery semantics · 2026-08-15 · `[docs]` |
| §4 Opcodes — the v1.0 opcode set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` (closes OI-4) |
| §8 Status / error codes — the 1-byte status set + numbers | **FROZEN for v1.0** | G1 · 2026-07-01 · `[docs]` |
| §6 Run/Stop/Console — RUN{file,source}, RUN_STATE, EBUSY, STOP, SOFT_REBOOT, CONSOLE_DATA/INPUT | **FROZEN for v1.0 (amended)** | G1 · 2026-07-01; transactional RUN admission · 2026-08-14; default-MTU STOP/SOFT_REBOOT admission · 2026-08-15 · `[docs]` (RUN-file at S3; STOP / console / RUN-source at S4) |
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

### 3.2 Fragmentation (over GATT)

A message larger than one packet is split across consecutive RX writes (or TX notifications). Each packet is:

```
+----------+-------------------------------+
| FRAG_HDR |          FRAGMENT DATA         |
|   1 B    |        up to (MTU−4) bytes      |
+----------+-------------------------------+
```

`FRAG_HDR` bits: `bit7 = FIRST`, `bit6 = LAST`, `bits5..0 = index mod 64`. The receiver concatenates `FRAGMENT DATA` from the `FIRST` packet through the `LAST` packet (indices increasing mod 64) to reconstruct the §3.1 message, then validates the CRC. Receipt of `FIRST` always abandons any incomplete fragment run and starts a new one; a non-`FIRST` packet with no active run or with the wrong next index is dropped. This restart rule lets a sender restart an identical whole frame after its logical message ownership was preempted, without completing a stale prefix; ordinary transient pressure alone retries only the unaccepted fragment. A frame whose CRC fails is dropped and answered with `EVT ERROR(ECRC)` referencing the opcode if known.

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
ticket bound to a slot incarnation and the originating
connection session, including a generation that cannot be confused by numeric
connection-handle reuse. A deferred worker builds its result in private scratch
and revalidates the whole ticket before copying into that slot.

When a fully encoded response enters the ready FIFO, one absolute 1000 ms
publication deadline begins. One pre-created NimBLE-host callout owns the
logical message. Each callback validates ticket, connection generation,
deadline, and TX stream generation; takes the physical TX mutex with zero wait;
attempts exactly one fragment Notify; then releases and returns. On success it
advances offset/index and rearms after one RTOS tick if data remains. On
transient pressure it retains the same unaccepted fragment and rearms after at
most 15 ms. The callback never sleeps, loops, or waits for capacity. Non-control
and bulk senders cannot interleave while the logical ownership is held.

A successful single-fragment `RUN`, `STOP`, or `SOFT_REBOOT` response MAY
preempt between fragments. It increments a stream generation under the same TX mutex; the
response callout observes the change and then restarts its identical encoded
frame from `FIRST`, which abandons the interrupted prefix. Deadline expiry on a
still-live connection terminates that session rather than silently losing an
admitted response. Disconnect stops/cancels the callout and invalidates its
ticket before normal re-advertising; any already-queued callback revalidates and
emits nothing. No queued or late response byte may cross into a later
connection session.

`RUN`, `STOP`, and `SOFT_REBOOT` retain their specialized one-fragment
response-before-side-effect contracts in §6. Their response attempt is
connection-bound and zero-wait; failure suppresses generic fallback and causes
no corresponding execution, interrupt, or reset side effect.

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

**Workspace jail (F-17):** every path is canonicalized against `fs_root` at a **single chokepoint** before any vfs op; traversal (`../`) / absolute escapes outside `fs_root`, the reserved `.pbltmp` suffix, and reserved agent prefixes → `EACCES` (SEC-4). **`.py` / data only** — the agent never requires, generates, or accepts `.mpy` / `.pyc` transfer artifacts; no server-side compilation.

## 6. Run / Stop / Console

> **FROZEN for v1.0 (amended)** — RUN-file at G1 · S3; **`RUN{source}`, `STOP`, `SOFT_REBOOT`, `CONSOLE_DATA`, `CONSOLE_INPUT` frozen at G1 · S4 (2026-07-01 · `[docs]`)**; transactional RUN admission clarified 2026-08-14; default-MTU `STOP`/`SOFT_REBOOT` response-before-side-effect admission clarified 2026-08-15. Wire below; amend only via a `[docs]` commit before dependent code.

- **`RUN` (0x20)** payload `[mode:u8][data]` — `mode` 0=file (`data` = UTF-8 path), 1=source (`data` = UTF-8 snippet). → `RSP{status}` (`OK` | `EBUSY` if one already running, FR-RUN-4 | `EBADREQ` bad mode | `ERANGE` over-length), then `RUN_STATE(running)`. Both modes share one lifecycle. Completion → `RUN_STATE(done)`; an uncaught exception → `CONSOLE_DATA(stderr, traceback)` then `RUN_STATE(error)`. A missing/inaccessible file surfaces asynchronously (`CONSOLE_DATA(stderr)` + `RUN_STATE(error)`), not as the `RSP`.

  An otherwise valid, non-busy RUN is admitted transactionally. The ESP
  reference agent makes a provisional, non-observable reservation and copies
  the request, then makes exactly one
  connection-bound, single-fragment, zero-wait attempt to submit its matching
  `RSP{OK}`. At the minimum ATT MTU 23, a fragment carries 19 PBLE/1 message
  bytes and the response frame is 11 bytes, so it is always one fragment.
  Local Notify acceptance is the admission cut: only after it succeeds may the
  agent wake the runner exactly once. Therefore user code, console output, and
  every RUN event follow the response submission. Mutex contention, a missing
  or changed connection, or local Notify backpressure restores the exact prior
  runnable state and produces no wake, execution, event, fallback response, or
  retry. A timeout caused by one of these local admission failures is therefore
  side-effect-free. Timeout alone does not prove rejection: a disconnect or
  response loss after local acceptance does not revoke the already-admitted run.
- **`STOP` (0x21)** no payload. Idempotent — on successful connection-bound,
  single-fragment `RSP{OK}` submission, STOP while idle is a no-op and STOP
  while running raises `KeyboardInterrupt` **in the runner task only** (the link
  stays live, FR-BLE-11) → clean teardown → `RUN_STATE(idle)` (FR-RUN-5/6/10).
  Local response-submission failure emits no fallback and performs no interrupt.
- **`SOFT_REBOOT` (0x22)** no payload. `RSP{OK}` immediately; stops any run,
  then soft-resets the MicroPython VM and returns to `RUN_STATE(idle)`
  (FR-RUN-8). VM teardown MUST NOT begin merely because the local BLE stack
  accepted the notification: the implementation MUST allow a short bounded
  delivery grace after submitting `RSP{OK}` so queued response bytes can reach
  the central. The ESP32 reference agent uses a pre-created 250 ms one-shot and
  refuses a second reboot with `EBUSY` while that reset is pending. If the
  `SOFT_REBOOT` response attempt fails, it MUST leave the VM running and
  emit no generic fallback rather than perform an ambiguous reset. This is an execution-order clarification;
  it changes no PBLE/1 bytes.
- **`CONSOLE_DATA` (0x30, EVT, id 0)** payload `[stream:u8][bytes]` — `stream` 0=stdout, 1=stderr (FR-CON-1/2).
- **`CONSOLE_INPUT` (0x31, CMD, no RSP)** payload `[bytes]` — appended to the running program's `stdin` (`input()`/`sys.stdin`); fire-and-forget, no reply frame (FR-CON-3).
- **`RUN_STATE` (0x40, EVT, id 0)** payload `[state:u8]` — 0 idle / 1 running / 2 done / 3 error (FR-RUN-7).

The console is **observe-anywhere**: `stdout`/`stderr` stream regardless of which client triggered the run. USB is a local-debug mirror only — never a runtime transport (FR-CON-5).

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
