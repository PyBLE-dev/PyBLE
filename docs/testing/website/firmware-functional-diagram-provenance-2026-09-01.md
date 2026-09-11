<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Firmware functional diagram provenance — 2026-09-01

Status: **reviewed and approved for public website use**

## Published asset

- Public path:
  `/features/pyble-firmware-v0.6.0-functional-block-diagram-473a85d475aa.svg`
- Intrinsic dimensions: `1920 × 1470`
- Size: `21,995` bytes
- SHA-256:
  `473a85d475aa90b1031ba100c0ab05c9227d44462134e92feee8d15b9d15003a`
- Release scope: qualified PyBLE firmware `v0.6.0`, agent `0.6.0`, and
  protocol `PBLE/1`

The public asset is a byte-for-byte promotion of the final reviewed SVG from
the ignored local review workspace. No PNG review rendering is published.

## Authorship and clean-room review

This is an original PyBLE-authored functional architecture diagram. Its visual
organization uses ordinary engineering-document conventions: a system
boundary, a central protocol bus, orthogonal connectors, and labeled rectangular
modules. The design contains no vendor artwork and no generated board image,
physical board likeness, schematic, pinout, proprietary identifier, or copied
vendor content. A public ST product page was considered only as an example of
the general functional-block-diagram form; none of its text, artwork, layout
measurements, symbols, or semiconductor content was reused.

Earlier AI-generated board renderings were rejected during local review because
their invented hardware could confuse visitors. Those rejected images and
their prompts remain in the ignored review workspace and are not used by this
asset or the website.

## Evidence and factual review

The diagram was checked against:

- the immutable public
  [`v0.6.0` release descriptor](https://pyble.dev/firmware/v0.6.0/release.json);
- annotated source tag
  [`firmware-v0.6.0`](https://github.com/PyBLE-dev/PyBLE/releases/tag/firmware-v0.6.0),
  which resolves to source commit
  `0c7230d6708797c241160ba71fbd37e6b22f180a`; and
- the version-bound
  [PBLE/1 protocol specification](https://github.com/PyBLE-dev/PyBLE/blob/firmware-v0.6.0/docs/specifications/protocol.md).

Review confirmed the complete 24-operation surface, the exact ordered five
release profiles, and the separate generic-memory-profile versus exact-board
boundaries. Final wording also records `.pbltmp` upload commit behavior, file
and empty-directory deletion, ESP Just Works pairing that is not access-gating,
and the narrower statement that the PyBLE agent sends no telemetry and needs no
cloud service.

## Accessibility and asset safety

- The SVG has an internal `<title>` and `<desc>`, selectable text, and no
  embedded raster image.
- It contains no script, `foreignObject`, external URL, `href`, or
  `xlink:href`.
- Small-screen review proved that whole-image fitting is too dense. The public
  page therefore supplies a keyboard-focusable inspection viewport, a
  full-size SVG link, and a complete reflowing HTML equivalent.
- The page-level alternative text and visible caption explicitly say that this
  is a functional diagram, not a board drawing, automatic detector, schematic,
  or pinout.

The maintainer approved the functional-diagram direction and publication on
2026-09-01.
