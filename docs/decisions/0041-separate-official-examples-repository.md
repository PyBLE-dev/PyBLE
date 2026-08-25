# ADR-0041 — Maintain the official runnable examples in a separate repository

- Status: **Accepted**
- Date: 2026-08-25
- Extends: [ADR-0040](0040-sha-pinned-connected-github-import.md)
- Examples repository: <https://github.com/PyBLE-dev/examples>
- Initial planning commit:
  [`0afe334a1435131f2bdc6189cad3b54cef59e3bc`](https://github.com/PyBLE-dev/examples/commit/0afe334a1435131f2bdc6189cad3b54cef59e3bc)

## Context

ADR-0040 lets the connected PyBLE Files surface browse any qualifying public
GitHub repository and copy a bounded selection of Python files to a board. The
main PyBLE repository also retains two small files under
`examples/github-import/` as deterministic integration fixtures for that
generic importer. Neither fact provides a systematic, independently releasable
source collection covering all five qualified firmware profiles.

A complete user-facing collection needs its own catalog, compatibility claims,
example-specific tests, hardware-validation evidence, governance, and release
cadence. Growing that collection inside the product repository would couple
example work to app, PBLE/1, firmware, and product-release history and would
make the integration fixtures look like the authoritative catalog.

The public `PyBLE-dev/examples` repository and its sibling maintainer checkout
now exist. The initial repository contains planning documents only: its draft
catalog explicitly blocks runnable-example implementation until maintainer
review. Repository existence is not evidence that an example is implemented,
runnable, compatible, or hardware-validated.

## Decision

1. **Use a separate canonical collection.** The official user-facing runnable
   example collection is <https://github.com/PyBLE-dev/examples>. It is a
   public, MIT-licensed companion to the canonical PyBLE product source at
   <https://github.com/PyBLE-dev/PyBLE>.

2. **Keep repository ownership explicit.** The examples repository owns all
   official example source, catalog metadata and schema, example-specific
   tests, example HIL evidence, authoring rules, and examples tags/releases.
   The PyBLE repository continues to own the app and generic GitHub importer,
   PBLE/1, firmware profiles and module contracts, product documentation, and
   any cross-repository compatibility requirement.

3. **Develop through separate work sessions and histories.** Official example
   implementation is performed in the examples checkout and committed to its
   own history. It is not developed in the PyBLE worktree. A change that also
   requires an app, protocol, or firmware contract follows a separate
   spec-first PyBLE session and commit; an examples task alone does not
   authorize such a product change.

4. **Record the maintainer checkout without making it portable state.** The
   current primary-maintainer sibling checkout is
   `/Users/vyv/Working/SciLabPro/PyBLE-Examples`. This path is informational
   local organization only. It is not a contributor requirement, source
   identity, application default, build input, release input, or CI assumption;
   the public HTTPS repository URL is authoritative.

5. **Do not embed or mirror the collection.** The examples repository is not a
   Git submodule, subtree, vendored directory, generated mirror, or automatic
   synchronization target of PyBLE. Cross-repository compatibility is recorded
   through reviewed immutable commits, tags, hashes, and evidence rather than
   filesystem coupling.

6. **Retain narrow PyBLE-owned examples where their ownership differs.** The
   existing `examples/github-import/hello.py` and `count.py` remain small,
   board-neutral importer integration fixtures owned by PyBLE tests and release
   instructions; they are not the official catalog. The eight bundled offline
   Blocks examples remain app assets governed by ADR-0016 and are not migrated
   or superseded by this decision.

7. **Treat the official collection as ordinary untrusted import input.** Its
   URL receives no importer allowlist, elevated trust, relaxed validation,
   implicit ref, automatic profile inference, auto-selection, auto-open, or
   auto-run behavior. A future prefilled URL, catalog browser, compatibility
   filter, or other app integration requires its own specification and tests.

8. **Respect the planning gate.** At acceptance, the examples repository's
   catalog plan is still a draft for review and no runnable examples exist
   there. All examples are implemented only after that plan is approved and
   only under the examples repository's own clean-room, DCO, test, safety, and
   validation contracts.

## Consequences

- Example work can proceed systematically without adding unrelated source or
  validation churn to the PyBLE product repository.
- Product releases and examples releases may move independently while still
  binding compatibility claims to immutable firmware and examples identities.
- Contributors must look to the repository URL, not the maintainer's local
  path, for source identity and collaboration.
- The main repository's two importer fixtures and bundled Blocks examples stay
  intentionally small and continue satisfying their existing tests/contracts.
- Cross-repository features require explicit coordination; no hidden sync or
  runtime dependency can make one repository's moving branch control the other.

## Alternatives considered

- **Implement the complete catalog under `PyBLE/examples/`.** Rejected because
  it couples two release/validation lifecycles and obscures the fixture/catalog
  distinction.
- **Add the examples repository as a submodule or generated mirror.** Rejected
  because it introduces checkout and synchronization coupling without helping
  the current public GitHub import flow.
- **Special-case the official URL in the app immediately.** Rejected because
  repository creation changes no importer requirement and grants no additional
  trust or reliable runtime profile signal.
- **Move the existing importer fixtures now.** Rejected because current tests,
  README instructions, and retained TestFlight evidence depend on their stable
  PyBLE-repository paths.

## Related

- [Initial examples catalog plan](https://github.com/PyBLE-dev/examples/blob/0afe334a1435131f2bdc6189cad3b54cef59e3bc/docs/planning/examples-catalog-plan.md)
- [ADR-0016](0016-offline-beginner-blockly-examples.md)
- [ADR-0040](0040-sha-pinned-connected-github-import.md)
- [System architecture](../specifications/architecture.md)
- [PRD §16.3](../specifications/prd.md#163-repository-structure)

<!-- SPDX-License-Identifier: MIT -->
