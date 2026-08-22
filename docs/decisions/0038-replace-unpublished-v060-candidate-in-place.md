# ADR-0038 — Replace the unpublished v0.6.0 candidate in place

- Status: **Accepted**
- Date: 2026-08-20
- Builds on: ADR-0033 and ADR-0037
- Last superseded-source commit:
  `5620f2fdc672b440548119e3431cfa4f4ed3f5a3`

## Context

The local annotated tag `firmware-v0.6.0` has tag-object identity
`d86eb6473a8d0269479061f03cd4a7b48bc8dabe` and peels to candidate source
`719b211345028e49aee9df9b11c4b5fd110913de`. It was created before the
stateless C3 PHY-calibration and post-OI NVS-receipt increments and before the
fixed SLO decision in ADR-0037.

A pre-publication audit on 2026-08-20 found no
`refs/tags/firmware-v0.6.0` at `origin`, no GitHub Release for that tag, and a
not-found response at the canonical
`https://pyble.dev/firmware/v0.6.0/release.json` path. The local tag and its
candidate were therefore never a public release identity. Advancing to 0.6.1
would imply that users could possess a published 0.6.0 contract when no such
release exists, while silently applying new derivations to every source whose
embedded SemVer is 0.6.0 would destroy historical reproducibility.

## Decision

1. Keep the replacement release version and agent version exactly `0.6.0` and
   keep the atomic ADR-0033 five-profile order. This decision changes neither
   release schema 4, policy schema 3, baseline schema 2, nor HIL schema 5.
2. The old local `firmware-v0.6.0` tag and candidate at `719b211…` are
   abandoned and unpublished. They MUST NOT be pushed, mirrored, activated,
   described as released, or used as the replacement release provenance.
3. The superseded unpublished source era ends at and includes
   `5620f2fdc672b440548119e3431cfa4f4ed3f5a3`. The replacement v0.6.0 source
   era contains only strict descendants of that commit. Release tooling MUST
   select the derivation contract from the bound policy/candidate source
   commit's ancestry, not from SemVer alone, the baseline's `source_commit`,
   or the validator checkout.
4. A v0.6.0 source at or before that boundary retains the historical
   derivation object with `fixed-product-slo-3000-v3` and
   `floor-95pct-min-100-v2`. A replacement-era v0.6.0 source requires
   ADR-0037's `fixed-profile-product-slo-esp3000-pico7000-v4` and
   `fixed-product-slo-64k-under-10s-6600-v3`. Unknown, unrelated, or
   ancestry-unprovable 0.6.0 source identity fails closed.
5. Every old candidate bundle, artifact, protected-deployment result, and HIL
   observation bound to `719b211…` or any other source through the boundary is
   invalid for replacement qualification. No old pass, candidate digest,
   artifact digest, or physical-result lineage may be relabelled or carried
   into the replacement.
6. Retained metadata and engineering evidence are not deleted or rewritten.
   The old tag-object and peeled-source identities, candidate digests where
   retained, prior derivation revision, and superseded status remain
   auditable. The immutable
   `docs/validation/firmware/oi1/a8be631df46590166307aa41afaea30b39e29230.json`
   baseline remains byte-for-byte evidence. Its static/heap inputs are
   rederived under the replacement policy/candidate source era and its
   reset/goodput samples remain diagnostic; the baseline source identity never
   routes the derivation and the baseline does not qualify either candidate.
7. Source/docs/RED/GREEN work first updates the checked-in policy to ADR-0037.
   The replacement source then passes its clean build, two-root
   reproducibility, license, source, and audit gates before any tag or audited
   candidate is created.
8. Candidate provenance requires an annotated `firmware-v0.6.0` tag which
   peels to candidate `HEAD`. After the pre-candidate gates in item 7 pass, the
   old local unpublished tag may be replaced with that audited source identity
   and the audited candidate may be created. Superseded tag-object/source and
   candidate metadata MUST already be retained. The tag MUST NOT be pushed,
   mirrored, published, or activated at this stage.
9. The tagged candidate then requires fresh protected deployment, verify-mode
   HIL on all five profiles, C3/Pico private gates, both-platform app HIL,
   install/recovery, finalization, and public validation. Only after those
   gates pass may the replacement tag and exact bytes be considered for origin
   push, canonical website publication, optional mirror, or activation.

## Consequences

- Users see the intended first public 0.6.0 instead of an artificial 0.6.1
  created solely to replace private bytes.
- Two source eras can share SemVer without sharing qualification arithmetic;
  retained earlier evidence remains mechanically reproducible.
- The existing local tag cannot authorize shortcuts. The replacement is
  release-blocking until fresh exact-byte gates pass on all five profiles.
- No tag, candidate, build, hardware run, or publication action is performed
  by this decision itself.
