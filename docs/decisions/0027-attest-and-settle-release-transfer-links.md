# ADR-0027 — Attest and settle release transfer links

- Status: **Accepted**
- Date: 2026-08-03

## Context

The first final-candidate `0.5.0` S3 qualification produced five clean PUT
samples of 12,594–13,329 bytes/s and five clean GET samples of
22,314–22,563 bytes/s, below the frozen floors. The candidate bytes, ATT MTU
247, chunk 229, window 8, heap, integrity, reliability, reset SLO, and physical
power-cycle checks all matched. Retained history contains the same slow S3
band, while a separate diagnostic connection on the identical bytes produced
15,100 bytes/s PUT and 28,810 bytes/s GET with DLE 251, 2M PHY, and a recovered
connection-parameter collision. A blind rerun would therefore select a link
state rather than demonstrate release quality.

The native ladder already logs DLE, PHY, connection-parameter, and TX-pool
facts over the local serial console. However, PHY and connection-parameter
requests are currently submitted back-to-back. If the parameter request
returns nonzero and `PHY_UPDATE_COMPLETE` never arrives, no timer retries it,
despite the frozen design requiring missing-event recovery. OI-1 records only
application-visible ATT facts, so it cannot distinguish this state.

## Decision

1. DLE, PHY, and connection-parameter procedures are separate bounded phases.
   The one-shot 200 ms callout is the progress guarantee; completion events may
   accelerate the next phase but are never its sole trigger.
2. DLE retains four attempts. BLE-5 profiles receive at most four PHY attempts.
   Connection parameters receive at most three submissions. Every nonzero
   submission return schedules the next bounded callout while budget remains.
3. Disconnect stops the callout and clears every phase, counter, and latch.
4. Every attempt and completion is logged at the retained ERROR level using a
   fixed, parser-owned grammar. This is local qualification telemetry, not a
   PBLE/1 field or public device capability.
5. After each of the first nine disconnects, OI-1 waits up to 2 seconds for one
   complete parser-owned session-end record, discards all bytes and the
   terminal count, and clears residual private serial state; missing or
   duplicate termination fails closed. It clears the buffer again before the
   tenth reset, parses only that transfer session's fixed link-fact lines,
   waits up to 5 seconds for the ladder to settle, and starts no throughput
   timer before success.
6. S3 qualification requires DLE at least 244 octets, a confirmed 2M/2M PHY,
   and a final successful interval in the requested 12..24-unit range. Classic
   requires DLE and the interval but records the compiled-out PHY rung
   explicitly. The same session's final TX-mbuf starvation count is retained
   as report-only evidence after disconnect.
7. The HIL report retains only the strict structured facts. It never retains
   arbitrary UART lines, BLE identifiers, serial paths, labels, or personal
   data.
8. The failed candidate remains failed. Firmware, HIL schema, source commit,
   candidate identity, and evidence all change, so both profiles require a new
   reproducible candidate and wholly fresh qualification.

## Consequences

- A slow alternate S3 link cannot be hidden by rerunning until favorable.
- A missing controller event cannot strand the connection-parameter phase.
- The performance gate becomes explainable: the exact timed connection carries
  its DLE/PHY/interval facts.
- Qualification still measures real end-to-end goodput; link facts supplement
  rather than relax any floor, integrity, reliability, heap, or reset gate.
- No PBLE/1 opcode, UUID, capability, or application behavior changes.
