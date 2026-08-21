# ADR-0039 — Admit the Waveshare single-page largest-block transient

- Status: **Accepted**
- Date: 2026-08-21
- Supersedes: ADR-0037 decision item 8 for the Waveshare
  `idf_internal_largest_block_min_bytes` floor only, and ADR-0038's
  fresh-observation requirement only under the exact byte-identity
  conditions of decision item 6
- Preserves: every other ADR-0037/ADR-0038 rule, the immutable `a8be631…`
  baseline, and all historical derivation revisions

## Context

Three consecutive replacement-era Waveshare OI-1 verify runs on candidate
source `7d853289815751c7381c9fd0b9a9a4409bdb6879` failed at exactly one gate:
one heap snapshot per run recorded `idf_internal_largest_block_bytes` of
`98304` against the frozen floor of `102400`. Every other value passed in the
same runs — reset samples 749–1,531 ms, all ten PUT/GET samples well above
6,600 bytes/s, 20/20 reliability with zero integrity failures, settled 2M
PHY/DLE 251 transport, and the physical power seam.

The dip is characterized, not anomalous:

- It is exactly one 4,096-byte page: `98304 = 102400 - 4096`.
- `idf_internal_free_bytes` and `idf_internal_minimum_free_bytes` are
  unchanged at the dip instant — transient fragmentation of the largest
  block, not memory consumption.
- It appears once per run at a timing-dependent post-HELLO snapshot
  (reset samples 4, 6, and 1 across the three runs).
- The generic `esp32-s3-n16r8` profile — identical chip, identical floor —
  recorded 41 snapshots across three runs the same day with zero dips.
  The behavior is specific to the Waveshare image.
- The retained `a8be631…` baseline capture recorded no dip, so
  `floor-min-1024-v1` froze the floor at the un-fragmented value.

`floor-min-1024-v1` cannot express a floor below its baseline minimum, so
admitting the transient requires a new heap-floor derivation identifier and a
new source era, exactly as ADR-0037 introduced fixed reset/goodput
identifiers for the V4 era.

This decision does not fit a gate to a failure. The floor remains a
fragmentation regression guard, not a performance promise; the admitted value
is the baseline-derived floor minus exactly one page — the minimal relaxation
that admits a single-page transient — and the three failed runs confirm,
rather than define, that arithmetic. The sanctioned ADR-0037 item 9 path is
followed in full: spec-first ADR, then fresh qualification of a new candidate.

## Decision

For the second-replacement v0.6.0 source era:

1. The era boundary is `7d853289815751c7381c9fd0b9a9a4409bdb6879` — the
   superseded first-replacement candidate source. Strict descendants use
   `QUALIFICATION_DERIVATION_V5`; the boundary and its ancestors keep their
   historical derivations (V4 era per ADR-0038, version-routed before it).
   Unknown or unrelated ancestry still fails closed.
2. `QUALIFICATION_DERIVATION_V5` changes exactly one identifier relative to
   V4: `heap_floor` becomes `floor-min-1024-waveshare-block-98304-v2`.
   `application_image`, `application_headroom`, `boot_ceiling`, and
   `goodput_floor` keep their exact V4 identifiers and arithmetic.
3. Under `floor-min-1024-waveshare-block-98304-v2`, every heap floor for
   every profile keeps `floor-min-1024-v1` arithmetic from the immutable
   `a8be631…` baseline, with exactly one exception:
   `idf_internal_largest_block_min_bytes` for
   `waveshare-esp32-s3-lcd-147b` is the fixed value `98304`.
4. The active policy for the V5 era is therefore the exact V4 policy with
   the `heap_floor` derivation identifier replaced and exactly one numeric
   field changed: the Waveshare `idf_internal_largest_block_min_bytes`
   `102400 -> 98304`. All other 10 largest-block/heap values, every static
   image/headroom bound, every reset ceiling, and every goodput floor are
   byte-for-byte unchanged.
5. The floor value `98304` is a fixed product decision. A verify run that
   records any heap sample below it fails, and per ADR-0037 item 9 its
   values MUST NOT be used to relax the policy again; a further change
   requires another spec-first ADR and fresh qualification.
6. Evidence captured under the superseded first-replacement candidate MAY
   bind into the successor candidate's completion, per profile, only if
   every one of these mechanical conditions holds:
   a. the successor candidate's install artifacts for that profile are
      byte-identical (equal SHA-256 and size) to the artifacts the evidence
      was captured against;
   b. every policy threshold applicable to that profile is value-identical
      between the superseded and successor policies;
   c. the evidence passed its frozen evaluator when captured, unmodified.
   The eligible evidence classes are OI-1 verify observations, the C3
   post-OI NVS capture (its receipt re-bound to the successor
   candidate digest from re-derived bytes), and provisioning
   install/readback evidence. If any condition fails for a profile, the
   clause is void for that profile and ADR-0038's fresh-observation rule
   applies unchanged. `waveshare-esp32-s3-lcd-147b` is excluded by
   construction (condition b fails) and always requires a fresh
   observation. App HIL matrix rows are NOT eligible and are re-run
   against the successor candidate.
7. The byte-identity and threshold-identity proofs for every carried
   profile must be recorded alongside the completion evidence (exact
   SHA-256 pairs and the compared threshold rows).
8. The tag/candidate replacement procedure of ADR-0038 applies unchanged:
   retain the superseded tag object and candidate metadata as superseded
   evidence, never publish them, and require fresh candidate creation,
   validation, and completion under the successor policy.

## Consequences

- The Waveshare profile is qualifiable on truthful evidence: its
  characterized single-page transient no longer fails an otherwise fully
  passing run, while a genuine fragmentation regression below `98304`
  still fails closed.
- One more derivation era exists. Historical eras remain byte-reproducible;
  the V4 era's policy and arithmetic are untouched for ancestry at or
  below the `7d85328…` boundary.
- If the successor build proves byte-identical per profile, already-passed
  physical observations remain valid evidence instead of being discarded
  for a policy-only source change — bounded strictly by the mechanical
  conditions of decision item 6. If it does not, every profile requalifies
  fresh, so the clause can only reduce redundant bench work, never admit
  unproven hardware behavior.
- The firmware bytes are not changed by this decision. If a later change
  eliminates the transient allocation, the floor may be restored to the
  baseline-derived value by a further spec-first ADR.
