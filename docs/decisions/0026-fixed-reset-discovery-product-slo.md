# ADR-0026 — Use a fixed product SLO for reset discovery

- Status: **Accepted**
- Date: 2026-08-02
- Supersedes: ADR-0025 decision items 3 and 6 for reset-to-advertisement only

## Context

OI-1 measures from controlled EN/reset release to the first matching PyBLE
service event delivered by the host BLE scanner. The endpoint is useful to a
user because it bounds when a restarted board can reappear in the scan list,
but it is not a firmware-local timestamp. Radio phase, missed advertising
opportunities, CoreBluetooth scan acquisition, and callback scheduling are
inseparable from firmware boot in that value.

ADR-0025 added 300 ms to one baseline maximum. A later complete run of the
same byte-identical classic ESP32 firmware produced a valid 1,823 ms sample
against the resulting 1,800 ms ceiling. All other samples in that run were
1,448 ms or faster, all transfer and heap gates cleared, all 20 reliability
files verified with zero corruption or disconnects, and the physical
power-cycle passed. Across the retained complete classic runs, the same bytes
also show rare callback tails above 1,800 ms. Repeating until a favorable host
schedule occurs would be p-hacking, while adding another fitted margin would
retain the same category error.

## Decision

For source releases at or after `0.5.0`:

1. `reset_to_service_advertisement_max_ms` is the fixed end-to-end product SLO
   `3,000` for every qualified profile.
2. Its derivation identifier is `fixed-product-slo-3000-v3`.
3. All 10 controlled samples remain mandatory and every sample must satisfy
   the SLO. No sample may be trimmed, replaced, or retried for a better value.
4. The scanner still starts before the exact 1,000 ms asserted-reset quiet
   interval, rejects a matching callback during reset, requires a fresh event
   after release, completes HELLO after every sample, and retains the 15,000 ms
   hard health timeout.
5. The separate physical power-cycle advertisement check remains exact.
6. Static build quantities, heap floors, goodput derivation, integrity,
   reliability, and historical pre-`0.5.0` contracts do not change.
7. The private `ceil-max-plus-300-10-v2` candidate policy is superseded before
   public release and cannot qualify public `0.5.0` bytes.

The 3-second value is a product requirement, not a confidence bound inferred
from the candidate that must pass it. A future tight firmware boot-regression
gate requires a device-local or serial readiness timestamp that can be
separated from host scan delivery; it must not be reconstructed by fitting
this host-observed metric.

## Consequences

- Release qualification asserts a clear user-visible discovery bound without
  turning CoreBluetooth scheduling into a rerun lottery.
- A sample above 3 seconds still fails even when the 15-second health timeout
  eventually observes the board.
- Both exact profiles use the same product SLO; a noisy profile cannot fit its
  own ceiling.
- The policy/source/candidate identity changes, so reproducible candidate
  assembly and fresh verify-mode HIL on both profiles remain mandatory.
