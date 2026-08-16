# ADR-0036 — Read generic S3 qualification link facts through RUN

- Status: **Accepted**
- Date: 2026-08-16
- Supersedes: ADR-0035 only where that decision leaves
  `esp32-s3-n16r8` on UART link-fact authority

## Context

ADR-0034 introduced bounded, session-bound retained link facts for the exact
Waveshare S3 profile. ADR-0035 reused that mechanism for C3 after its external
UART receive path intermittently failed to expose an authoritative disconnect
boundary. Generic `esp32-s3-n16r8` retained the ADR-0027 UART path.

Two consecutive baseline attempts using the exact same v0.6.0 candidate failed
after reset sample eight because the required UART session-end record was not
observed within 2,000 ms. In both attempts the host disconnect call returned;
the second serial name was an operating-system alias for the same physical
CH343 bridge, not an independent transport. Earlier candidate generations had
completed this gate, so the evidence establishes an unreliable observer path,
not a deterministic missing firmware callback. Increasing the wait, repeating
until favorable, accepting later bytes, or switching aliases cannot establish
which session produced a delayed line.

Generic S3 requires the same DLE, 2M-PHY, and connection-parameter fact shape
as the already-retained Waveshare S3 profile. Its external serial bridge must
remain open for the controlled RTS-to-EN reset edge, but it need not be a
second authority for the BLE session boundary.

## Decision

1. Exactly `esp32-s3-n16r8`, `waveshare-esp32-s3-lcd-147b`, and
   `esp32-c3-4mb` define `PBLE_ENABLE_OI1_LINK_FACTS=1`. Classic ESP32 remains
   the only ESP profile using the ADR-0027 UART link-fact authority. Pico keeps
   its separate BTstack observation.
2. Generic S3 uses the same bounded native records, atomic getter, strict
   `active`/`pair` RUN projections, epoch rules, overflow handling, and
   absolute probe deadlines accepted by ADR-0034 and ADR-0035. No native
   record shape or PBLE/1 surface changes.
3. Generic S3 retains `SerialResetController` and its explicit RTS-to-EN
   assertion/release edge. Its received UART bytes are private diagnostics
   only. The retained executor MUST NOT read or clear them to authorize a
   session boundary, link fact, or timed workload.
4. Each of the first nine measured disconnects permits exactly one diagnostic
   successor transaction: one bounded connect, one bounded HELLO, one
   stabilization guard, and one bounded `pair` getter RUN. Null, stale,
   wrapped, non-successor, malformed, overflowed, failed, or timed-out state
   ends the measurement without retry.
5. Reset ten uses `active` polling to retain its settled epoch before timing,
   revalidates that same epoch and tuning ladder before disconnect, and uses
   one final diagnostic `pair` to seal facts only from the exact immutable
   ended record. Its diagnostic active record must be the exact non-wrapping
   successor.
6. Waveshare and C3 behavior is unchanged. Classic ESP32 retains its strict
   2,000 ms UART boundary and seal gates without extension or retry.
7. Enabling the getter changes the generic S3 application bytes. Every earlier
   generic S3 build and candidate-bound measurement remains non-evidence. The
   release must restart reproducible builds and the complete generic S3
   workload from the new source identity.

## Consequences

- All three BLE-5 ESP qualification profiles use one fail-closed retained
  session-identity mechanism; only their reset adapters differ.
- Generic S3 keeps its host-observable reset edge without relying on CH343 or
  host-driver receive timing for link-fact authority.
- The generic S3 image gains the bounded hidden getter and retained POD state.
  Its N16R8 build must still pass the existing exact flash and heap gates.
- Diagnostic reconnects add bounded wall time outside every numeric OI
  threshold and never add a retry or public protocol capability.
