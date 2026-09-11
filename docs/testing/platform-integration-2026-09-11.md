<!-- SPDX-License-Identifier: MIT -->

# PyBLE platform source consolidation — 2026-09-11

## Scope

The maintainer requested local commits, recoverable worktree/branch cleanup,
and a pushed pull request targeting `main`.

The integration combines:

- Primary platform work through `66f1916`: reviewed Lenovo tutorial captures,
  firmware features and diagram, site-wide v0.6.1 guidance, and the App build-8
  offline privacy policy and publication handoff.
- Current `main` through `2ce0e8c`, including patched website dependencies.
- Exact published firmware source `c8f549eeabe6d2b8c2766eab022517944bb09c8c`,
  its measured baseline, specifications, host tooling and tests, and the
  previously reviewed App connection-lifecycle fixes.

After integration, the complete firmware and firmware-test trees, firmware
specification directory and protocol match `c8f549e` exactly. The website tree
initially matched the deployed primary source exactly. Subsequent pre-PR
formatting changes are whitespace-only; the frozen protocol bytes are retained.

The public protocol copy's relative `../../AGENTS.md` link lacked its target.
`tools/web/public/AGENTS.md` now supplies the exact contributor-guideline bytes
from `c8f549e`, SHA-256
`2462fdb3823bdec527de4da8323fc44570ca95e68f453ac3c469e5c4494072db`.
Both source snapshots are excluded from automatic formatting to preserve their
provenance. Existing publication/link tests caught the missing target and pass
with it present.

## Local verification

- Flutter analysis: no issues.
- Flutter non-golden suite: 894 tests passed.
- Complete website check: formatting, lint, type checking, zero-vulnerability
  dependency audit, license checks, 342 tests in 23 files, compatibility check,
  and both static and Sites builds passed.
- Publication suite: 41 tests passed; all repository-local Markdown targets
  exist.
- Clean-room, SPDX, import-boundary, localization, patch-policy and PR-range
  DCO checks passed. SPDX ran against a tracked-source export so ignored
  qualification workspaces were not recursively scanned as product source.

The exact firmware source already has its retained full host/build evidence,
described in the [engineering chronology](firmware-v0.6.1-five-board-engineering-2026-09-06.md).
This Git integration does not claim new board qualification. No hardware was
operated, firmware rebuilt, store artifact uploaded or website redeployed.
The [owner-confirmed publication record](firmware-v0.6.1-publication-2026-09-11.md)
and its distinction from incomplete automated HIL remain unchanged.

## Cleanup boundary

Auxiliary worktree directories, including dirty edits and ignored backups, are
archived intact outside the active repository. Git metadata, a verified bundle,
original branch/HEAD mappings and restoration instructions accompany them.
Private qualification experiments are preserved, not silently merged into the
production branch. The primary generated MicroPython board inputs are untouched.

The two remote documentation branch names may be removed after their complete
history is reachable from the pushed integration branch. Opening this PR does
not itself merge or bypass any checks on `main`.
