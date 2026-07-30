# ADR-0019 — Build the public site as a statically exported Next.js app

- Status: **Accepted; deployment packaging amended by
  [ADR-0020](0020-vinext-sites-deployment-adapter.md)**
- Date: 2026-07-29

## Context

PyBLE needs a trustworthy public home for product information, support, privacy
disclosures, and a future browser-based firmware installer. The site must serve
`pyble.dev`, with `pyble.org` redirecting to the canonical domain as decided in
[ADR-0005](0005-standalone-domain.md).

Most routes are durable public documents that should be usable without
client-side JavaScript. The future firmware installer is the exception: it will
need a small browser-only component around Web Serial. The repository already
uses Node.js tooling nowhere else, so the website should remain an isolated,
portable package.

## Decision

Build the website as a **Next.js App Router** package in `tools/web/`, written in
strict TypeScript and configured for static export.

- Next.js owns routing, metadata, and pre-rendered HTML. Vite is not layered
  underneath Next.js; it remains a valid alternative for a future standalone
  client tool, but combining both bundlers in this package adds no value.
- The production artifact is the portable `tools/web/out/` directory. The
  deployed site needs no long-running Node.js server.
- `pyble.dev` is the only canonical origin. The hosting/DNS edge permanently
  redirects every `pyble.org` path and query to its `pyble.dev` equivalent.
- The initial routes are `/`, `/privacy/`, `/support/`, and `/flash/`.
- `/flash/` is an honest readiness page until reviewed, versioned firmware
  artifacts and a production manifest exist. It must not present a working
  install control before that release gate is green.
- The first release has no analytics, advertising, tracking pixels, contact
  form, cookie banner, remote font service, or runtime content-management
  dependency.
- Authored website source is MIT-licensed and participates in the repository's
  no-leak, SPDX, lint, type, test, and production-build gates.

## Rationale

- App Router emits useful HTML and route-specific metadata for the document-heavy
  part of the site while still allowing the flasher to become a client component.
- Static output keeps the host replaceable, the attack surface small, and the
  site fast on phones and tablets.
- Keeping the package under `tools/` respects the repository's root layout and
  places the future web flasher beside other provisioning tools.
- A staged `/flash/` avoids advertising a capability that cannot yet be
  delivered safely.

## Consequences

- Deployment must configure HTTPS for the `.dev` domain and a host-level
  permanent redirect for `.org`; application code cannot reliably implement a
  cross-domain redirect in a static export.
- Features requiring a server, database, account system, or form handler need a
  later ADR and privacy review.
- Firmware publishing must supply a same-origin manifest, immutable versioned
  binaries, integrity metadata, and three-target release validation before the
  install control is enabled.
- Browser flashing remains a one-time provisioning path. PyBLE's normal runtime
  transport stays BLE-first.
