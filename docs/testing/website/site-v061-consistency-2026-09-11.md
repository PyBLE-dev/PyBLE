<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Whole-site v0.6.1 consistency — 2026-09-11

## Reason and scope

Earlier route-only deployments updated Flash and Features but preserved an old
homepage, support page, and tutorial baseline. A coherent full static build
now uses the same exact owner-confirmed v0.6.1 selector on every release-aware
route. Source is maintained in the primary PyBLE checkout.

Home, support and target cards recognize the owner-confirmed release as
available on all five exact profiles. Tutorial guidance references v0.6.1 and
explains fresh RUN globals, LFS2 migration and non-destructive mount refusal.
The example snapshot's original v0.6.0 baseline and screenshot version labels
remain historical facts, explicitly distinguished from current guidance.
The Flash artifact verifier, consent, manifests and firmware bytes are unchanged.

The primary checkout also incorporates the already-deployed patched website
dependencies and exact owner-confirmed release policy, without changing App
or firmware sources. Its previous dependency installation is retained in the
ignored local work directory, not deleted.

## Social image provenance

The existing PyBLE-authored social SVG is reused with new title/description
and badge wording: “FIRMWARE v0.6.1 AVAILABLE”. Original App and logo source
image bytes, placement and clipping are unchanged. No hardware rendering or
retouched App screen was created. The App beta status is separate from the
firmware version. Historical card assets remain available.

- SVG: `/social/pyble-v061-og-d3bab0c0-1200x630.svg`;
  SHA-256 `d3bab0c05e2c07783b6f7006a7cd8152b4b0a8798f4ade55e31d28076cb9bb1f`.
- PNG: `/social/pyble-v061-og-297b270f-1200x630.png`;
  SHA-256 `297b270fd4ec7637752ff954416cf4ca69570992b28d48b4530982db07c03af9`.
- Dimensions: 1200 × 630.
- Rasterization: existing pinned Sharp package; exact same-origin image
  references embedded in memory for rendering, without changing source pixels.
  The first local render lacked resolved image references and was rejected.
  The final PNG was visually inspected and includes the real App screenshot.
- All shared Open Graph/Twitter metadata selects the new content-addressed PNG.

## Validation and deployment

The added consistency cases first failed (five expected failures), then the
full website suite passed (342 tests). No hardware tests are part of this task.
Deployment uses a new complete static site, preserves old assets/downloads,
and atomically switches the site symlink with the previous release retained.
Production route and artifact delivery checks are recorded in the local
deployment workspace; qualification claims remain owner-provided.

## Published result

Activated `/srv/pyble/releases/20260911-v061-complete-site` on 2026-09-11.
Website source: `14139e945053fabaa783a25233c83035b4aa87f2`.
The previous `/srv/pyble/releases/20260911-v061-functional-diagram` is retained
for rollback. All 17 public route responses matched the complete local build
byte-for-byte. The diagram, new social PNG, and protocol snapshot matched their
published hashes; all five firmware download endpoints returned HTTP 200.

Public homepage SHA-256:
`3c0789790a2f9224a92b9e98746686f0707fd69c3531accd79eed51ca690a86f`.
Firmware release.json remains unchanged at
`71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd`.
The final 342-test website run passed after updating the two no-selection
fallback-copy assertions. No firmware tests, device actions, source push, or
App publication occurred.
