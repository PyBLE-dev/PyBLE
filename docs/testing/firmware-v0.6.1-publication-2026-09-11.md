<!-- SPDX-License-Identifier: MIT -->

# Firmware v0.6.1 public deployment — 2026-09-11

Published at https://pyble.dev/flash at approximately 12:41 UTC.

This records the initial Flash publication. Later page updates and the current
deployment are recorded in the
[complete website deployment report](website/site-v061-consistency-2026-09-11.md).
The source, paths and page hashes below remain historical evidence.

The project owner explicitly stopped further testing, confirmed that their
qualification was complete, and requested immediate publication. Publication
relies on that owner-provided confirmation. Incomplete automated HIL records
were preserved unchanged; no missing results were marked passed.

- Firmware source: `c8f549eeabe6d2b8c2766eab022517944bb09c8c`.
- Flash source: `415d4776827da8fb51475463dc31068d61ac234a`, local branch
  `release/v061-owner-confirmed`, separate worktree `web-v061-owner-confirmed`.
- Deployment: `/srv/pyble/releases/20260911-v061-owner-confirmed`.
- Previous deployment retained for rollback:
  `/srv/pyble/releases/20260901T124313Z-bccdf3deef97`.
- All five original v0.6.1 packages published under `/srv/pyble/firmware/v0.6.1`.
  Firmware, release metadata, manifests, checksum list, licenses and existing
  HIL report were not modified. All 28 listed artifact checksums matched on VPS.
- Public Flash HTTP content SHA-256:
  `3dbcbe67dce7976f3c29e1760bec99d9659ef9aa962c440cbc469beb48d462e3`.
- Public release.json SHA-256:
  `71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd`.
- All five public firmware download endpoints and the new Flash JavaScript
  bundle returned HTTP 200. These were deployment delivery checks, not board
  qualification tests. No boards or tablets were operated on during publication.
- `/learn` and its tutorial directory were preserved byte-for-byte. Public
  `/learn` SHA-256 remains
  `7985529abf7960687fa0e59e5b669f649b881ee04c432e1bbb36e5ae8ff8a677`.
- Other existing pages, assets and old firmware versions retained. Additional
  web dependency notices appended to the retained website license document.

Public confirmation record:
https://pyble.dev/firmware-v0.6.1-owner-confirmation.md

No GitHub release, source push, PR merge, App Store upload, new firmware build,
or additional hardware qualification was performed in this publication step.
The standard automated-qualified deployment mode remains unchanged; the new
owner-confirmed mode is restricted to this exact version, metadata digest and
five-profile set. Future automated deployment must explicitly account for this
owner-confirmed release rather than misrepresenting it as collector-complete.
