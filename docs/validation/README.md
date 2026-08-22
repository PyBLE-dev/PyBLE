# Validation evidence

This directory contains public, machine-readable evidence used by firmware and
release qualification gates.

Evidence records are tied to exact source revisions and hardware profiles.
Pre-publication records are retained only when their provenance is explicitly
described; new releases must be regenerated from commits in the canonical
public repository.

`browser-flashing/v0.4.2-production.md` is the human-readable post-release
attestation for the supplemental production-browser installation and
interrupted-flash recovery run on the two enabled v0.4.2 profiles. Its
companion `browser-flashing/v0.4.2-production.json` is the public, redacted
machine-readable record. They support only the scope stated in those records
and do not replace the formal final-candidate HIL, OI-1 resource, app, or PBLE/1
qualification matrices.

The retained firmware 0.4.1 OI-1 record was produced from the archived private
development history. Its source identifier is deliberately not resolvable in
this fresh public history. It documents the legacy release baseline and must
not be reused as evidence for a new public-source release.

The five-profile records at `firmware/oi1/7441a762….json` and
`firmware/oi1/a8be631d….json` are immutable pre-publication v0.6.0 engineering
baselines. The latter remains the active input for replacement-policy
rederivation: static/heap thresholds are recomputed from it, while reset and
goodput arrays remain diagnostic under ADR-0037's fixed SLOs. Its own
`source_commit` never selects the derivation; the bound policy/candidate source
era does. Neither record is candidate HIL or public release approval, and
neither may be edited to fit the replacement.
