# Validation evidence

This directory contains public, machine-readable evidence used by firmware and
release qualification gates.

Evidence records are tied to exact source revisions and hardware profiles.
Pre-publication records are retained only when their provenance is explicitly
described; new releases must be regenerated from commits in the canonical
public repository.

`browser-flashing/v0.4.2-production.json` is a public, redacted summary of the
supplemental production-browser installation and interrupted-flash recovery run
for the two enabled v0.4.2 profiles. It supports only the scope stated in that
record and does not replace the formal final-candidate HIL, OI-1 resource, app,
or PBLE/1 qualification matrices.

The retained firmware 0.4.1 OI-1 record was produced from the archived private
development history. Its source identifier is deliberately not resolvable in
this fresh public history. It documents the legacy release baseline and must
not be reused as evidence for a new public-source release.
