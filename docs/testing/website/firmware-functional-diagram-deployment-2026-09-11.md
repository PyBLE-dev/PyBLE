# Firmware v0.6.1 functional diagram publication

Published on 2026-09-11 at https://pyble.dev/features.

- Source commit: `44717bdac281903912a5106f7dc1d37971197bf2`.
- Source worktree:
  `/Users/vyv/Working/SciLabPro/PyBLE-worktrees/web-v061-owner-confirmed`.
- Source branch: `release/v061-owner-confirmed` (local; no push performed).
- New SVG: `/features/pyble-firmware-v0.6.1-functional-block-diagram-0d2bb826c64f8.svg`.
- SVG SHA-256:
  `0d2bb826c64f8ba24f34bc70d2a9ba5750bb77b1a7f6a0998a9baccd0123b768`.
- Source-backed changes include LFS2 on all five profiles, session admission,
  fresh RUN globals, run-owned stdin, CRC-backed resume, and checked settings.
- The page explains the nonblank-media USB-recovery exception and distinguishes
  owner qualification confirmation from incomplete automated HIL records.
- Historical v0.6.0 diagram retained unchanged.

Focused website validation: expected RED (5 failures, 1 pass), followed by
46 passing tests in the page, Sites-output, and VPS-contract suites. Production
static build completed. The SVG, desktop page, and emulated 390-pixel mobile
viewport were visually reviewed. Mobile document width was 390 pixels; only
the diagram viewport scrolled (360-pixel viewport, 1040-pixel inner content).
Raw PNGs remain in the ignored local qualification workspace.

Active VPS release: `/srv/pyble/releases/20260911-v061-functional-diagram`.
Previous owner-confirmed release retained for rollback. Only Features documents,
its new SVG/protocol snapshot, and supporting static bundles were overlaid.
Flash HTML/RSC, release selection, Learn documents, and older firmware artifacts
were preserved; no firmware, App, or hardware qualification action occurred.

Public response hashes after activation:

- Features HTML: `244e463ccc4f78fa77a9e8e336d20cf6fa39fcb231e64208688995e676650f9c`.
- Flash unchanged: `3dbcbe67dce7976f3c29e1760bec99d9659ef9aa962c440cbc469beb48d462e3`.
- Learn unchanged: `7985529abf7960687fa0e59e5b669f649b881ee04c432e1bbb36e5ae8ff8a677`.
- Protocol snapshot: `e88387706bf3705edb0d889fd9870800aa95306d4a17b55398cacbb364fa5c2d`.

## Primary checkout synchronized

The finished Features changes were subsequently integrated into
`/Users/vyv/Working/SciLabPro/PyBLE`, including the updated SVG under
`tools/web/public/features`, page source, specification, provenance, protocol
snapshot, owner-confirmation document, and focused tests/deployment references.
All 46 focused website tests passed in that checkout. The updated tracked page
and deployment-reference files exactly match the published source commit.

The live Features HTML and SVG were already current and matched the recorded
hashes. No redundant deployment, firmware change, Flash change, or Learn change
was made during this synchronization. Unrelated local changes were preserved.
