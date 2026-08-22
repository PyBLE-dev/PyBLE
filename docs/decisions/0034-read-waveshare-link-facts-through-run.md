# ADR-0034 — Read Waveshare qualification link facts through RUN

- Status: **Accepted**
- Date: 2026-08-13
- Amended: 2026-08-14

## Context

ADR-0027 made the exact transfer connection's settled DLE, PHY,
connection-parameter, and TX-mbuf-starvation facts release evidence. The
generic ESP qualification fixtures receive those fixed records through an
independent UART bridge. The Waveshare ESP32-S3-LCD-1.47B exposes its native
USB peripheral on the same USB data pair used for flashing, however, and the
qualified MicroPython image does not deliver the retained UART0 records on
that endpoint. The board exposes UART0 pins separately, but requiring another
USB-to-TTL adapter would make that adapter an undeclared qualification
dependency and would not test the candidate as provisioned through its normal
USB connector.

PBLE/1 RUN already executes bounded qualification probes and returns their
stdout as CONSOLE_DATA on the connected BLE session. Adding a wire opcode,
GATT characteristic, INFO field, or public capability solely for release
instrumentation would expand the product protocol for a board-local evidence
transport.

Two consecutive v0.6.0 baseline attempts reached the tenth measured HELLO and
then exhausted the getter-RUN deadline before admitting any link fact. The
getter's fixed snapshot crosses multiple 200-byte CONSOLE_DATA events. Each
console event may use the runner's bounded 250 ms transmit pacing and each
RUN_STATE control event may use its bounded 1,000 ms pacing. The former 2,000
ms absolute getter-RUN deadline was therefore shorter than the normal bounded
transport it was intended to observe; it was not a link-settlement limit. Both
attempts remain failed and contribute no qualification evidence.

After that transport bound was corrected, a controlled reproduction returned
34 valid active snapshots inside the five-second settlement window, but every
one remained unsettled. Its ended record showed one DLE request with zero DLE
completion values while PHY and connection-parameter completion had landed.
In the pinned ESP-IDF, the real HCI data-length-change path routes the event to
the correct per-connection callback but does not populate
`event->data_len_chg.conn_handle`; only a separate synthetic same-parameters
path populates that member. Treating the member as authoritative therefore
misattributes a real completion whenever the live PBLE connection's controller
handle is not the incidental zero value.

## Decision

1. Only the exact `waveshare-esp32-s3-lcd-147b` image defines
   `PBLE_ENABLE_OI1_LINK_FACTS=1`. Generic S3, classic ESP32, and C3 images
   compile the diagnostic out and retain the ADR-0027 UART path. The hidden
   native name is `pble_ble._oi1_link_facts()`; it is not a PBLE/1 capability
   and is absent from other images.
2. Native code retains two bounded records: the active successful GAP session
   and the immutable last-ended session. Each successful connection receives
   a positive, monotonically increasing per-boot 64-bit epoch. Epoch zero is
   never valid and rollover is forbidden. A last-ended record is copied
   atomically before a later connection may create its successor; later link
   events cannot mutate it.
3. A record contains only its epoch, structural `final`, `settled`, and
   `overflow` booleans, and a `facts` object with exactly the public
   `transfer_link_facts` shape. PHY updates and connection-parameter updates
   each have capacity eight; connection-parameter request return codes have
   capacity three. Exceeding any capacity latches `overflow=true` for that
   session. No allocation, address, connection handle, device identifier,
   label, path, user source, or console text is retained.
4. The getter takes one atomic copy and returns exactly
   `{active: record-or-null, last_ended: record-or-null}`. It does not reset,
   consume, or alter either record. It raises instead of returning a wrapped
   epoch or an internally inconsistent copy.
5. DATA_LEN_CHG attribution is independent of controller-handle allocation,
   reuse, and prior connection history. The GAP callback MUST snapshot the
   agent's one cached live PBLE connection handle exactly once before any DLE
   confirmation or retained-record mutation. A `BLE_HS_CONN_HANDLE_NONE`
   snapshot fails closed. The snapshot is passed to the existing handle-bound
   retained-record mutation; if it no longer names the active retained session,
   that stale event records no DLE fact and the record remains unsettled.
   Disconnect invalidation and epoch/handle equality remain authoritative. The
   callback MUST NOT read or fall back to
   `event->data_len_chg.conn_handle`, including when its value is zero. Real HCI
   and synthetic same-parameters completions follow this same rule. The fix is
   local to `pble_ble`; it neither patches pinned ESP-IDF nor restricts the
   controller to one connection as a way to force a particular handle value.
6. The HIL runner invokes the getter only through the existing PBLE/1 RUN
   opcode. Every probe selects one host-internal exact projection, `pair` or
   `active`; it is never user text. Both source forms call the native getter
   exactly once, preserving its one atomic copy. `pair` serializes that full
   `{active,last_ended}` copy unchanged. `active` projects the already-copied
   value to exactly `{active: copy.active, last_ended: null}` before JSON
   serialization. A host-generated nonce names one strict-ASCII marker line
   whose suffix is JSON. Exactly one matching marker, a successful RUN
   response, no stderr, and terminal RUN_STATE(done) are required within the
   projection's absolute transport ceiling: **8,000 ms for `pair`** and
   **5,000 ms for `active`**. Each one ceiling includes command writes, the RUN
   response, all CONSOLE_DATA delivery, and the terminal state, with no
   progress extension. The parser accepts exact keys and types only, bounds
   every integer, list, output chunk, and total output, and fails closed on a
   missing, duplicate, stale, malformed, overflowed, or timed-out snapshot.
   `active` additionally requires a positive-epoch, non-final, non-overflowed
   active record and exact `last_ended=null`; `pair` requires non-null final
   ended and non-final active records with no overflow.
   The first-nine boundary snapshots are structural isolation records and MAY
   be unsettled because those measured links disconnect immediately after
   HELLO and the heap probe; they are discarded and never authorize timed
   work. Only the tenth transfer session's active and ended records MUST be
   settled and pass the exact public fact validator. Arbitrary non-marker
   stdout is discarded and never enters evidence.
7. After each of the first nine measured sessions disconnects, the runner
   makes one diagnostic reconnect with separate deadlines: 20 seconds for
   `PbleCentral.connect`, 5 seconds for diagnostic HELLO, and 8 seconds for the
   `pair` getter RUN. After HELLO completes and before that single getter RUN,
   the runner requests one 1,000 ms same-session stabilization delay so the
   board's bounded DLE, PHY, and connection-parameter callouts do not collide
   with the qualification-only command write. This delay is diagnostic
   plumbing outside every measured interval. The returned
   `last_ended` epoch must be positive and final; the returned active epoch
   must be its exact non-wrapping successor. Those facts and the diagnostic
   session itself are discarded. This replaces only the Waveshare UART
   session-end boundary.
8. On the tenth measured connection, the runner polls its active snapshot for
   at most five seconds. This settlement deadline remains an independent outer
   ceiling: each `active` getter invocation receives the lesser of its 5-second
   transport ceiling and the remaining settlement budget, and a snapshot
   returned at or after the outer deadline is rejected. A timed-out, malformed,
   or failed probe ends the measurement; only a successfully returned but
   unsettled snapshot may be polled again. The epoch is retained only after
   `settled=true`, `final=false`, `overflow=false`, and the existing exact
   Waveshare `transfer_link_facts` validator passes. No timed transfer starts
   first.
   After all transfers, reliability work, and the final heap probe, it queries
   again with one separate 5-second `active` probe before disconnect and
   requires the same active epoch and valid settled ladder.
9. After that disconnect, the runner makes one diagnostic reconnect with the
   same separate 20-second connect, 5-second HELLO, and 8-second `pair`
   getter-RUN deadlines.
   Its active epoch must be the exact non-wrapping successor of the retained
   transfer epoch, and `last_ended` must be the final, non-overflowed record for
   that exact transfer epoch. The final public `transfer_link_facts` object is
   derived only from this immutable ended record, including its final
   TX-mbuf-starvation count. The diagnostic connection is then disconnected.
   The HELLO ceiling includes its acknowledged GATT command write and response;
   it is diagnostic transaction plumbing, not a measured OI threshold. Repeated
   CoreBluetooth connection churn produced valid live-link writes completing at
   about 3.23 seconds, so the former 2-second ceiling rejected healthy sessions.
   The runner never retries HELLO or the getter, never reconnects after a
   diagnostic failure, and inserts no inter-session quiet delay. A failed
   diagnostic disconnect replaces the one-deep `last_ended` record, so a
   reconnect could not prove the original measured-session boundary and MUST
   fail closed instead.
10. The physical RESET prompts and release-to-advertisement measurement remain
   unchanged. Waveshare qualification no longer opens, reopens, reads, or
   requires a serial endpoint and never treats native-USB RTS/DTR as reset
   evidence.

## Consequences

- The exact Waveshare candidate can produce the same public link-fact evidence
  without an external UART adapter or a new PBLE/1 surface.
- Session epochs prove that the immutable ended record belongs to the timed
  connection and that no intervening successful link was substituted.
- Fixed arrays and strict host parsing keep the diagnostic bounded and prevent
  identifiers or arbitrary console output from entering retained evidence.
- DLE evidence works for any live controller handle without an ESP-IDF patch or
  a handle-zero/MAX_CONNECTIONS masking assumption. Other BLE clients must
  still be closed during qualification to preserve an exclusive measurement;
  that operator precondition never authorizes an assumed handle value.
- The diagnostic is qualification-only implementation surface in one named
  image. It does not make board identity or link tuning a dynamic app
  capability.
