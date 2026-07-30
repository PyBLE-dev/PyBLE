# ADR-0020 — Package the static Next.js site for Sites with vinext

- Status: **Accepted**
- Date: 2026-07-29

## Context

[ADR-0019](0019-nextjs-static-public-site.md) selected a portable Next.js
static export for PyBLE's document-heavy public site. That remains the desired
content architecture and fallback artifact.

The selected Sites host does not deploy a bare `dist/` directory of HTML. Its
saved-version contract requires a supported OpenNext or vinext request
entrypoint, specifically `dist/server/index.js`, together with the exact Sites
project binding inside the artifact. Mirroring Next.js `out/` to `dist/`
therefore passes neither the host's artifact validation nor its runtime
contract.

## Decision

Keep Next.js App Router as the source framework and keep `next build` with
`output: "export"` as the portable static-build gate. Add vinext as a
deployment adapter:

- `next build` emits the canonical portable export in `out/`;
- `vinext build` emits the Sites-compatible Vite bundle in `dist/`;
- a small deterministic post-build step verifies `dist/server/index.js` and
  the fully rendered launch-route manifest, then copies the exact
  `.openai/hosting.json` binding to `dist/.openai/hosting.json`;
- that post-build step wraps the vinext handler with a static route boundary:
  launch routes and known assets delegate to vinext, while every unknown
  pathname returns the generated 404 HTML immediately;
- local development continues to use `next dev`;
- CI exercises both artifacts through `npm run check`.

The adapter does not authorize dynamic product behavior. Routes remain authored
at build time, render complete HTML without client JavaScript, and use no
database, runtime secret, remote CMS, or application-owned backend.

Canonical document paths omit a trailing slash (except `/`). vinext probes
App Router route patterns without a slash during speculative prerendering; a
trailing-slash normalization redirect makes those otherwise-static routes look
dynamic and leaves them on the host's runtime rendering path. Slashless paths
allow every launch route and the not-found page to be emitted as static HTML.
Robots, sitemap, and web-manifest endpoints are static public files for the same
reason.

The wrapper is required because the host's worker runtime does not reliably
close vinext's dynamic not-found response for an unmatched App Router path. It
does not add a second router or backend: its allowlist is derived from the
frozen public surface, and its only direct response is the already-generated
static 404 document.

## Rationale

- The output matches the host's documented supported-entrypoint contract.
- The portable `out/` artifact remains available for static hosts and offline
  inspection.
- vinext preserves the existing Next.js route and component source while using
  Vite only at the deployment boundary.
- Validating the entrypoint, rendered-route manifest, static metadata files, and
  project binding before a version is saved turns host-only failures into local
  build failures.

## Consequences

- Production builds run two compilers and take longer than the static-only
  build.
- vinext and its Vite/React Server Components peers become pinned build
  dependencies and must be reviewed during upgrades.
- `dist/` is a host-specific generated artifact and is not byte-identical to
  `out/`.
- Requests for `/privacy/`, `/support/`, and `/flash/` normalize permanently to
  `/privacy`, `/support`, and `/flash`.
- A future move to a host that accepts plain static files may deploy `out/`
  directly and retire this adapter without changing page source.

<!-- SPDX-License-Identifier: MIT -->
