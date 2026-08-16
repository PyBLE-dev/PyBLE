# ADR-0035 — Read C3 qualification link facts through RUN

- Status: **Accepted**
- Date: 2026-08-16
- Supersedes: ADR-0034 only where that decision limits retained link facts to
  the exact Waveshare image

## Context

ADR-0027 made the transfer session's settled DLE, PHY,
connection-parameter, and final TX-mbuf-starvation facts release evidence.
ADR-0034 replaced the exact Waveshare board's unavailable UART evidence with
one bounded native `{active,last_ended}` snapshot read through ordinary
PBLE/1 RUN. The generic ESP32-C3 profile retained the earlier private-UART
path because its WCH bridge also supplies the controlled RTS-to-EN reset edge.

During the v0.6.0 C3 baseline, two independent attempts intermittently failed
while waiting for the pre-capture UART session-end boundary. A bounded
reproduction lost three of fifteen boundaries. In every lost sample both
adjacent callback records, `disconnect reason` and `link tune session end`,
were absent from the host UART stream; later samples delivered both together.
The next 52 disconnects, including 12 exact controlled-reset cycles, delivered
both records. Native and pinned-IDF inspection found no conditional
session-end branch: NimBLE synchronously calls the GAP disconnect callback,
and the primary UART writer admits every byte. The available evidence cannot
distinguish a peripheral disconnect completion delayed beyond the private
2,000 ms observer window from loss in the external WCH/macOS receive path.
Neither ambiguity is acceptable as authoritative release evidence.

Increasing the UART wait, retrying a favorable run, or accepting a later
session's line would weaken session identity without resolving that ambiguity.
The C3 already supports the same bounded native state used by ADR-0034; only
its compile-time enable and HIL executor selection differ.

## Decision

1. Exactly `waveshare-esp32-s3-lcd-147b` and `esp32-c3-4mb` define
   `PBLE_ENABLE_OI1_LINK_FACTS=1`. Classic ESP32 and generic ESP32-S3 keep the
   ADR-0027 UART evidence path. The hidden native getter remains
   `pble_ble._oi1_link_facts()` and remains absent from those other images.
   This adds no PBLE/1 opcode, characteristic, INFO/HELLO field, or public
   capability.
2. C3 uses ADR-0034's bounded native record, atomic getter, strict parser,
   `active`/`pair` projections, epoch rules, overflow handling, and absolute
   probe deadlines unchanged. A valid boundary requires a positive final
   `last_ended` epoch and its exact non-wrapping, non-final active successor.
   Null, stale, wrapped, non-successor, malformed, or overflowed records fail
   closed.
3. The C3 WCH serial bridge remains the required controlled-reset adapter.
   RTS still supplies the reset assertion/release edge used by the numeric
   reset measurement. UART bytes MAY be inspected as private diagnostics, but
   neither the HIL executor nor any release assembler may treat them as C3
   link-fact or session-boundary evidence. The qualification path does not
   call its serial read seam to authorize progress.
4. After each of the first nine C3 measured sessions disconnects, the runner
   makes the same single diagnostic reconnect as ADR-0034: bounded connect,
   bounded HELLO, one stabilization guard, then exactly one `pair` getter RUN.
   It validates finality and exact epoch succession, disconnects the diagnostic
   session, and discards both records. It never retries or reconnects after a
   diagnostic failure.
5. On C3 reset ten, the runner uses the same `active` polling and independent
   5,000 ms outer settlement ceiling as Waveshare. Before the measured
   disconnect it revalidates the same epoch and settled ladder. One final
   diagnostic reconnect must return that exact epoch as immutable
   `last_ended` and its exact active successor; only the ended record's facts,
   including its final starvation count, enter public evidence.
6. The strict 2,000 ms UART session-end gate remains unchanged for
   `esp32-4mb` and `esp32-s3-n16r8`. It is neither lengthened nor converted to
   a retry. C3 leaves that UART-authority path entirely, so a delayed or lost
   WCH line cannot pass or fail C3 qualification.
7. Enabling the retained state changes the C3 application image. All earlier
   C3 builds and failed measurements remain non-evidence. Qualification must
   use fresh reproducible candidate bytes and rerun the complete C3 workload.

## Consequences

- C3 session identity is proved by immutable firmware state rather than the
  timing behavior of an external UART receive chain.
- C3 retains its host-observable reset edge without turning that same bridge
  into an authority for BLE teardown.
- Waveshare behavior and deadlines are unchanged; the implementation becomes
  a shared retained-link-fact executor for the two enabled profiles.
- The bounded diagnostic costs a reconnect after each short measured session,
  but those transactions remain outside every numeric OI threshold.
