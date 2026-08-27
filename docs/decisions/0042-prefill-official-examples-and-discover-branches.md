# ADR-0042 — Prefill the official examples repository and discover branches

- Status: **Accepted**
- Date: 2026-08-27
- Extends: [ADR-0040](0040-sha-pinned-connected-github-import.md)
- Extends: [ADR-0041](0041-separate-official-examples-repository.md)

## Context

The connected GitHub importer accepts any canonical public repository URL and
an optional branch, tag, or commit. That generic input is powerful, but an
empty repository field and free-form ref field make the first import harder
than necessary for a novice. The separately governed official collection now
has a stable public identity at <https://github.com/PyBLE-dev/examples>, so the
app can offer that identity as a starting value without coupling to the
maintainer's local checkout or granting the repository additional trust.

GitHub exposes public branch names through a paginated, unauthenticated REST
endpoint. Branch discovery is mutable navigation metadata, not an immutable
source identity: a selected name must still be resolved again and pinned to a
full commit SHA before any tree or blob is browsed. Unauthenticated requests
are also rate- and resource-limited, so “all branches” needs a complete,
explicitly bounded result rather than an unbounded or silently partial list.

ADR-0040 deliberately preserved explicit tag and commit refs. Removing those
inputs would break existing advanced and reproducible-import workflows.

## Decision

1. **Prefill, but keep the repository editable.** Every newly opened GitHub
   import action initializes **Public repository URL** to
   `https://github.com/PyBLE-dev/examples`. The user may replace it with any
   other canonical public GitHub repository root accepted by the existing
   parser. Reopening the action starts again from the official value; the app
   does not persist a previous repository in this increment.

2. **Treat the official value as ordinary untrusted input.** The prefill is a
   local UI convenience, not an allowlist, trust signal, compatibility claim,
   build input, or link to `/Users/vyv/Working/SciLabPro/PyBLE-Examples`. It
   crosses the same exact-host network boundary and the same SHA pinning,
   object validation, size, UTF-8, overwrite, session, and board-write gates as
   every custom repository. It causes no automatic file selection, source
   fetch, import, editor open, Save, or Run.

3. **Make branches the normal ref workflow.** The normal control is a
   searchable, keyboard- and screen-reader-operable branch-only chooser. The
   app reads the repository's reported default branch, places it first, marks
   it as the default, and initially selects it. Remaining exact branch names
   use deterministic code-point order. Branch names are opaque technical
   values and are never localized or rewritten.

4. **Retain advanced explicit refs.** A clearly labelled advanced action
   switches to manual branch, tag, or commit entry. The existing ref
   validation and blank-default behavior remain available there. Switching
   modes or changing the manual ref invalidates any pinned snapshot,
   navigation, selection, review, and overwrite consent. This preserves
   ADR-0040's compatibility while keeping the default surface novice-focused.

5. **Discover only after a user opens the importer.** App launch and ordinary
   Files navigation make no GitHub request. Opening the explicit **Import
   examples from GitHub** action may automatically discover branches for the
   prefilled repository. Editing the URL immediately cancels and clears that
   catalog and every dependent snapshot. It does not request on each
   keystroke; the user explicitly loads or refreshes branches for an edited
   canonical URL.

6. **Return a complete bounded catalog or none.** Discovery first reads public
   repository metadata for `default_branch`, then serially requests
   `GET /repos/{owner}/{repo}/branches?per_page=100&page=N` without a
   `protected` filter. It accepts at most 512 branch names over at most six
   pages, at most 512 KiB per branch page, and at most 2 MiB for all branch-page
   bodies. A 513th branch, another next page after the sixth, duplicate or
   invalid name, malformed page, or exceeded byte bound returns a typed failure
   and publishes no partial catalog. An empty catalog is displayed honestly
   and cannot be browsed in branch mode.

7. **Keep pagination inside the exact-host boundary.** Repository metadata
   also supplies a positive numeric repository `id`. The client validates
   GitHub's `Link` pagination metadata, including exact HTTPS host, either the
   locator-derived `/repos/{owner}/{repo}/branches` path or GitHub's canonical
   `/repositories/{id}/branches` path bound to that metadata identity,
   `per_page`, and a `page` that advances by exactly one. It never directly
   follows a response-provided URL; it constructs the next exact
   `api.github.com` request from the validated local locator and page number.
   Each page uses the existing absolute request deadline, cancellation,
   response-body, error, and rate-limit rules.

8. **Pin after selection.** A branch catalog and any commit SHA contained in a
   branch-list response are advisory and moving. Browse passes only the chosen
   name to the existing resolution operation, requires the returned full
   commit and root-tree SHAs, displays the pinned commit, and derives every
   subsequent tree/blob read from that immutable snapshot.

9. **Share cancellation and rate state.** Branch loading is a distinct visible
   network phase. Repository edits, refresh, mode changes, cancellation, and
   dismissal advance the presentation generation and cancel any active
   discovery. Late pages cannot repopulate the chooser. A GitHub-supplied
   positive rate-limit delay gates branch load/refresh and all other
   network-producing actions on the surface under ADR-0040's existing rule.

10. **Specify and test the complete interaction.** ARB owns branch labels,
    loading, refresh, default, empty, advanced-mode, and bound/error text.
    Automated tests cover the editable prefill, custom-repository parity,
    initial/default selection, branch-only results, advanced tag/commit
    compatibility, bounded pagination, no partial publication, cancellation,
    stale-result suppression, rate gating, immutable resolution, compact/wide
    layouts, keyboard use, semantics, and 2× text.

## Consequences

- A novice can open the importer and choose an official branch without knowing
  Git ref syntax or copying a URL.
- Experienced users retain exact tags and commits for reproducible imports.
- Large or changing repositories fail explicitly instead of showing a partial
  list that could be mistaken for all branches.
- Opening the importer uses additional public GitHub requests, but no other app
  workflow becomes network-dependent and the existing rate-limit guidance
  remains authoritative.
- The official repository remains independently released and untrusted at the
  importer boundary; this decision creates no filesystem or build coupling.

## Alternatives considered

- **Remove tags and commits entirely.** Rejected because it breaks the
  explicit-ref contract and makes immutable, release-specific imports harder.
- **Request branches after every URL keystroke.** Rejected because it wastes
  the unauthenticated request budget and creates avoidable stale-response races.
- **Follow `Link` URLs directly.** Rejected because response-provided URLs must
  not widen the exact-host request boundary.
- **Show only the first 100 branches.** Rejected because a partial list would
  contradict the selector's “available branches” meaning.
- **Make the official repository trusted or board-aware.** Rejected because
  repository ownership is not evidence that source is safe for a particular
  board or should execute automatically.

## Related

- [App requirements §4.9](../specifications/App/specs.md#49-github-public-repo-import-libgithub_import--fr-import)
- [App TDD §10](../specifications/App/TDD.md#10-github-import-design-libgithub_import)
- [PRD §9.7](../specifications/prd.md#97-github-public-repo-import-https)

<!-- SPDX-License-Identifier: MIT -->
