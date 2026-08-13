# ADR-0034 — Read Waveshare qualification link facts through RUN

- Status: **Accepted**
- Date: 2026-08-13

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
5. The HIL runner invokes the getter only through the existing PBLE/1 RUN
   opcode. A host-generated nonce names one strict-ASCII marker line whose
   suffix is JSON. Exactly one matching marker, a successful RUN response, no
   stderr, and terminal RUN_STATE(done) are required within the existing
   bounded probe timeout. The parser accepts exact keys and types only, bounds
   every integer, list, output chunk, and total output, and fails closed on a
   missing, duplicate, stale, malformed, unsettled, overflowed, or timed-out
   snapshot. Arbitrary non-marker stdout is discarded and never enters
   evidence.
6. After each of the first nine measured sessions disconnects, the runner
   makes one diagnostic reconnect and queries the getter. The returned
   `last_ended` epoch must be positive and final; the returned active epoch
   must be its exact non-wrapping successor. Those facts and the diagnostic
   session itself are discarded. This replaces only the Waveshare UART
   session-end boundary.
7. On the tenth measured connection, the runner polls its active snapshot for
   at most five seconds. The epoch is retained only after `settled=true`,
   `final=false`, `overflow=false`, and the existing exact Waveshare
   `transfer_link_facts` validator passes. No timed transfer starts first.
   After all transfers, reliability work, and the final heap probe, it queries
   again before disconnect and requires the same active epoch and valid
   settled ladder.
8. After that disconnect, the runner makes one bounded diagnostic reconnect.
   Its active epoch must be the exact non-wrapping successor of the retained
   transfer epoch, and `last_ended` must be the final, non-overflowed record for
   that exact transfer epoch. The final public `transfer_link_facts` object is
   derived only from this immutable ended record, including its final
   TX-mbuf-starvation count. The diagnostic connection is then disconnected.
9. The physical RESET prompts and release-to-advertisement measurement remain
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
- The diagnostic is qualification-only implementation surface in one named
  image. It does not make board identity or link tuning a dynamic app
  capability.
