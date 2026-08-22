# ADR-0037 — Use fixed profile reset and product-wide transfer SLOs

- Status: **Accepted**
- Date: 2026-08-20
- Supersedes: ADR-0026 decision items 1–2 for replacement-v0.6.0
  reset qualification, and ADR-0025 decision items 4 and 6 for
  replacement-v0.6.0 goodput qualification
- Preserves: historical derivation revisions and immutable baseline evidence

## Context

The five-profile v0.6.0 baseline retained at
`docs/validation/firmware/oi1/a8be631df46590166307aa41afaea30b39e29230.json`
is valid engineering evidence, but it exposed two product-contract problems.
First, Pico 2 W has a materially different reset path from the four ESP
profiles. Its pinned upstream BTstack controller initialization normally needs
a 5–6 second allowance; applying the ESP 3-second discovery SLO to that path is
not a truthful cross-port requirement. Second, deriving each transfer floor as
95% of one profile's minimum baseline sample turns a product-usability bound
into five candidate-fitted regression thresholds.

The retained baseline diagnoses feasibility without selecting either new
value. Its ESP reset maxima are 1,828, 1,187, 1,594, and 1,167 ms, while the
Pico maximum is 3,378 ms. Its minimum PUT values are 6,870, 13,740, 13,656,
16,180, and 12,854 bytes/s; its minimum GET values are 13,240, 20,787, 25,654,
28,716, and 7,181 bytes/s. The product decision must remain independent of
those extrema so a failed qualification run can never fit or relax its own
gate.

## Decision

For the replacement v0.6.0 source era defined by ADR-0038:

1. Reset-to-service-advertisement remains the exact same end-to-end metric:
   controlled reset/power release to the first fresh host scanner callback
   containing the exact PyBLE service UUID.
2. `reset_to_service_advertisement_max_ms` is exactly `3000` for
   `esp32-4mb`, `esp32-s3-n16r8`, `waveshare-esp32-s3-lcd-147b`, and
   `esp32-c3-4mb`, and exactly `7000` for `rpi-pico2-w`. The derivation
   identifier is
   `fixed-profile-product-slo-esp3000-pico7000-v4`.
3. Pico's 7-second bound is independently budgeted from the pinned upstream
   BTstack's normal 5–6 second controller-initialization allowance plus one
   fixed second for service-advertisement acquisition and host callback
   delivery. It is not derived from the 3,378 ms observation and MUST NOT be
   widened again after a failure.
4. Every profile still records exactly 10 reset samples. All 10 must pass its
   profile ceiling; no sample is trimmed, replaced, retried, or selectively
   rerun. The scanner-before-reset ordering, exact-service match, HELLO after
   every sample, 15,000 ms hard health timeout, and separate physical
   power-cycle advertisement check remain exact.
5. Both committed PUT and verified GET use the fixed product-wide floor
   `6600` bytes/s on all five profiles. Its derivation identifier is
   `fixed-product-slo-64k-under-10s-6600-v3`.
6. The arithmetic is exactly
   `ceil_100(65536 bytes / 10 seconds) = ceil_100(6553.6) = 6600` bytes/s.
   Because reported goodput is the integer
   `floor(65536 * 10^9 / duration_ns)`, the largest passing duration is
   `9,929,696,969 ns` (approximately `9.9297 s`), not a rounded 10 seconds.
7. Exactly five PUT and five GET samples remain mandatory per profile. Every
   sample must meet 6,600 bytes/s with no retry or replacement. The exact
   65,536-byte unique-byte counts, duration arithmetic, byte/size/CRC and
   offset integrity, required ATT MTU/window/chunk, settled link facts,
   retransmit/rewind accounting, reliability totals, zero unexpected
   disconnects, and physical check receive no allowance.
8. Reset and transfer baseline samples remain immutable diagnostic evidence;
   neither contributes arithmetic to these product SLOs. Static image and
   headroom thresholds remain exact, and heap floors retain
   `floor-min-1024-v1` baseline derivation. The retained `a8be631…` baseline
   is rederived under the bound policy/candidate source era; its own
   `source_commit` never selects the derivation revision.
9. A candidate or verify run that crosses either fixed SLO fails. Its values
   MUST NOT be used to rederive, fit, trim, or relax the policy; changing a
   product SLO requires another spec-first ADR and fresh qualification.
10. Historical source eras retain their exact derivation objects and
    arithmetic. In particular, the earlier unpublished v0.6.0 source era
    remains reproducible with `fixed-product-slo-3000-v3` and
    `floor-95pct-min-100-v2`; it does not silently inherit this decision.

## Consequences

- Reset qualification reflects the real controller startup class of each port
  while keeping one exact host-visible endpoint and strict sample discipline.
- PUT and GET now express the minimum usable 64 KiB product transaction rather
  than the performance of the baseline used to exercise a particular build.
- The active five-profile policy must replace both derivation identifiers and
  atomically set four ESP reset ceilings to 3,000, Pico's to 7,000, and all ten
  transfer floors to 6,600 before a replacement candidate is built.
- The immutable `a8be631…` baseline is retained unchanged. It supplies the
  unchanged static/heap inputs and diagnostic performance samples, but is not
  release approval and does not route its own derivation.
