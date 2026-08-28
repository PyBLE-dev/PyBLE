# ADR-0046 — Publish a release-bound static learning center

- Status: **Accepted**
- Date: 2026-08-28
- Extends: [ADR-0019](0019-nextjs-static-public-site.md)
- Extends: [ADR-0040](0040-sha-pinned-connected-github-import.md)
- Extends: [ADR-0041](0041-separate-official-examples-repository.md)

## Context

The public website explains PyBLE, distributes the app beta, provisions
firmware, publishes privacy information, and provides troubleshooting. The app
and firmware now expose a substantially broader working loop: five qualified
firmware profiles, BLE connection and identity, editing, Save/Run/Stop, console,
Files, reviewed GitHub import, multi-file deletion, Blocks, and bounded
Python-to-Blocks conversion. Short landing-page and support checklists no longer
teach a novice how those pieces fit together safely.

The separately governed `PyBLE-dev/examples` repository contains 32 authored
development examples at commit
`8f4529b3cd0d62e8d53d7deb4f37e5cd2a171fd1`, but it has no release tag or HIL
records and every catalog entry remains planned. The website must not convert
designed compatibility into a validation claim, duplicate the runnable source,
or silently bind its build to that repository.

The public privacy page also predates the shipped connected GitHub importer. It
still says that the app makes no HTTP request even though a user who opens the
importer can start unauthenticated requests to GitHub's public API. Tutorials
cannot describe that workflow while leaving the public disclosure stale.

## Decision

1. **Add a first-class learning center.** `pyble.dev/learn` becomes the
   canonical tutorial hub and a primary-navigation destination. The initial
   ordered sequence is Setup, First program, Files, GitHub import, Blocks,
   Examples catalog, Hardware safety, Configured hardware, Pico 2 W, and the
   exact Waveshare LCD board. Each lesson has its own `/learn/*` route.

2. **Keep learning separate from support.** `/learn` teaches complete,
   progressive workflows. `/support` remains the concise recovery and issue
   intake surface. The app and firmware landing pages link into the learning
   sequence without duplicating it.

3. **Keep the site static and local.** Tutorial text, metadata, components, and
   visual treatment live in `tools/web/` and render completely during both
   static builds. There is no CMS, tutorial API, client-side content fetch,
   analytics, remote font, embedded media, or runtime examples-repository
   request.

4. **Preserve examples ownership.** Runnable `.py` sources, catalog metadata,
   release tags, and HIL evidence remain owned by `PyBLE-dev/examples`. The
   website may show small explanatory snippets and link an exact HTTPS commit or
   released tag, but it does not mirror full source files or grant the official
   repository elevated trust. A mutable branch is never a tutorial provenance
   claim.

5. **Publish validation state, not aspiration.** The current examples snapshot
   is labelled development-only, unreleased, and not HIL-validated. A tutorial
   may explain how to review and import it, but must not call an example
   validated, released, compatible, or supported until matching immutable
   evidence exists. Future release labels change only with the examples
   repository's own tag and evidence.

6. **Make firmware guidance release-aware.** Tutorials direct users to the
   active `/flash` selector and derive any active firmware version/profile claim
   from the same build-selected descriptor. The five stable profile identities
   remain explicit, in release order. Generic ESP profiles have no carrier pin
   map; only the exact Waveshare B-version and Pico 2 W lessons may use their
   documented exact-board surfaces. The two S3 images must not be inferred from
   their shared runtime chip token.

7. **Teach safe explicit execution.** No imported or generated code is described
   as opening or running automatically. Every hardware path requires a reviewed
   profile, wiring, voltage/current limits, configured pins, bounded expected
   behavior, Stop/cleanup guidance, and a truthful compatibility label.

8. **Correct the network disclosure.** The privacy specification and public
   policy identify user-started public GitHub import as the app's sole optional
   Internet workflow. They explain the exact host and unauthenticated metadata
   sent, GitHub's independent processing, the absence of account credentials or
   board/project upload, and the offline independence of editing, BLE, Files,
   Blocks, and Run.

9. **Treat tutorials as release routes.** Every learning route has canonical
   metadata, sitemap coverage, exact static-export and Nginx mapping,
   trailing-slash normalization, Sites delegation and prerender enforcement,
   authenticated deployment inventory coverage, and byte-for-byte production
   smoke testing. Adding a tutorial route requires changing these contracts
   together.

10. **Require accessible progression.** Every tutorial includes prerequisites,
    approximate time, outcomes, numbered steps, expected observations,
    troubleshooting or safety callouts, and previous/next navigation. The
    sequence must work without client JavaScript and remain usable by keyboard,
    at 200% text, with reduced motion, and from 320 CSS pixels through wide
    desktop layouts.

## Consequences

- A new user can move from exact-board provisioning to a complete BLE coding
  workflow without interpreting implementation specifications.
- Tutorial claims remain coupled to public release state and immutable example
  provenance instead of mutable repository content.
- The website gains explicit static routes and therefore pays a maintenance
  cost in Nginx, deployment, sitemap, and prerender contracts.
- Hardware lessons begin as safety and configuration guidance; examples become
  validated lessons only after their own HIL evidence exists.
- The public privacy policy once again matches the shipped app.

## Alternatives considered

- **Expand `/support` into a manual.** Rejected because troubleshooting and
  progressive teaching serve different user goals and would make urgent help
  harder to scan.
- **Publish tutorials only in the examples README.** Rejected because app
  installation, firmware selection, UI workflows, navigation, accessibility,
  and privacy are product concerns rather than example-source ownership.
- **Fetch tutorial content or catalog metadata from GitHub at runtime.**
  Rejected because it adds availability, privacy, drift, and build-coupling
  risks to an otherwise static public site.
- **Call all 32 examples supported on all designed profiles.** Rejected because
  design metadata and host tests are not physical validation evidence.

## Related

- [Public website specification](../specifications/website.md)
- [Official examples repository boundary](0041-separate-official-examples-repository.md)
- [GitHub importer trust boundary](0040-sha-pinned-connected-github-import.md)
- [Qualified five-profile firmware decision](0033-qualify-v060-as-five-profile-heterogeneous-release.md)

<!-- SPDX-License-Identifier: MIT -->
