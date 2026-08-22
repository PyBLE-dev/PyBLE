# ADR-0025 — Use metric-specific OI-1 repeatability allowances

- Status: **Accepted**
- Date: 2026-08-02

## Context

The original OI-1 derivation used only outward quantization around the minimum
or maximum observed in one baseline run. That is suitable for exact build
quantities and stable memory measurements, but it made noisy host-observed BLE
timing an accidental rerun lottery. On the same byte-identical classic ESP32
firmware, one complete run observed a 1,764 ms reset-to-advertisement tail and
7,138 bytes/s minimum PUT goodput, while the selected baseline observed 1,498
ms and 7,354 bytes/s. The selected policy therefore left only 2 ms of reset
margin and 54 bytes/s (0.74%) of PUT margin. Two later complete candidate runs
kept perfect integrity and reliability yet crossed one or both bounds by only
2 ms and 92 bytes/s.

The reset clock ends at a host CoreBluetooth callback. Radio phase, missed
advertising opportunities, scanner behavior, and callback scheduling create an
additive discovery/delivery tail. PUT/GET measure a complete file transaction
across many BLE acknowledgement windows and therefore accumulate smaller
proportional host/radio scheduling variance. Neither effect is a firmware
regression, retransmission, disconnect, integrity fault, or resource loss.

## Decision

For firmware source releases at or after `0.5.0`, OI-1 uses these exact,
profile-independent derivations:

1. Application image and factory-partition headroom remain exact.
2. Runtime heap keeps the existing `floor_1024(min(samples))` rule. It receives
   no percentage allowance.
3. Reset-to-advertisement uses `ceil_10(max(samples) + 300 ms)`. The fixed
   allowance represents host discovery/delivery variance; it does not alter
   the timed firmware work.
4. PUT and GET goodput use
   `floor_100(floor(95 * min(samples) / 100))`, implemented with integer
   arithmetic.
5. Integrity, retransmit/rewind counts, disconnect counts, sample counts,
   physical power cycling, and every other pass/fail assertion remain exact.
6. The new derivation identifiers are `ceil-max-plus-300-10-v2` and
   `floor-95pct-min-100-v2`; heap remains `floor-min-1024-v1`.
7. Historical pre-`0.5.0` releases keep their v1 identifiers and arithmetic.
   A validator selects the exact contract by source era.

The active two-profile policy is rederived atomically from the already-retained
immutable `0.5.0` baseline. The policy change invalidates the current candidate
identity, so a new reproducible candidate and fresh verify-mode HIL on both
exact profiles are mandatory. Failed verify runs justify this amendment but do
not qualify the replacement candidate.

## Consequences

- Normal host/radio discovery and scheduling variance no longer encourages
  repeated runs until a favorable sample appears.
- A reset tail beyond the fixed 300 ms allowance and a goodput loss beyond 5%
  still fail the release gate.
- Stable heap and exact build gates retain their original sensitivity.
- Old public evidence remains reproducible under its historical contract.
- Multi-run baseline aggregation remains a future contract revision; merely
  collecting more extrema without a repeatability allowance would still leave
  the threshold at the most favorable quantization boundary.
- Any future advertising or measurement-boundary change requires a new
  spec-first derivation revision rather than silently changing this one.
