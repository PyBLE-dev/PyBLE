<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Firmware functional diagram provenance — 2026-09-11

Original PyBLE functional architecture SVG, updated from the preserved
v0.6.0 diagram. No vendor artwork and no generated board likeness is included.
Existing engineering-document styling, selectable text, orthogonal connections,
and exact profile boundaries are retained.

- Public path: `/features/pyble-firmware-v0.6.1-functional-block-diagram-0d2bb826c64f8.svg`.
- Dimensions: 1920 × 1470; size: 22,446 bytes.
- SHA-256: `0d2bb826c64f8ba24f34bc70d2a9ba5750bb77b1a7f6a0998a9baccd0123b768`.
- Firmware: 0.6.1; source: `c8f549eeabe6d2b8c2766eab022517944bb09c8c`.
- Release metadata: `/firmware/v0.6.1/release.json`, SHA-256
  `71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd`.
- Publication basis: project-owner qualification confirmation on 2026-09-11,
  recorded at `/firmware-v0.6.1-owner-confirmation.md`. No missing automated
  HIL result is represented as passed.

## Source review

The unchanged PBLE/1 surface is 24 operations and 15 serialized capability keys.
Actual overlays at `firmware/board_overlays/*/_boot.py` now mount LFS2 through
`firmware/pyble/pyble_workspace.py`; ESP partition metadata named `data,fat`
does not establish the mounted filesystem type.

The revised modules correspond to the v0.6.1 amendments in
`docs/specifications/firmware/specs.md`: FR-BLE-10 (bounded fragments);
FR-PROTO-2/3/5/7/8/9 (session and command admission); FR-RUN-1/2/9 (fresh globals);
FR-CON-3 (run-owned input); FR-FS-1/4/7/8/9/14/15 (resume, reserve, mutations);
FR-BOOT-3/6 (durable settings and non-destructive mount refusal).
Both native C and portable Python implementations were consulted.

The public protocol snapshot `/reference/firmware-v0.6.1/protocol.md` is
byte-identical to the protocol specification at the firmware source commit.
SHA-256: `e88387706bf3705edb0d889fd9870800aa95306d4a17b55398cacbb364fa5c2d`.
The source commit/tag is not yet available through the public GitHub API, so
the page links the published release notes/source identity and exact protocol
snapshot instead of inventing an available GitHub source URL.

## Review and publication boundaries

The SVG's title, description, page alternative text, visible caption, and
reflowing HTML cover the new behavior. Nonblank or uncertain failed mounts
require USB recovery without agent startup. Fresh globals do not imply a full
VM or hardware reset. The diagram does not claim authentication, lossless
console output, additional opcodes, or new board-specific hardware APIs.

Header/body spacing and the provisioning warning were adjusted for legibility.
Raw PNG layout renders remain in the ignored local review workspace.
The SVG has no scripts, embedded rasters, external references, or foreignObject.
The historical v0.6.0 SVG and its provenance remain unchanged.

This website-only update does not change firmware bytes, the selected Flash
release, App binaries, or qualification evidence, and performs no hardware tests.
