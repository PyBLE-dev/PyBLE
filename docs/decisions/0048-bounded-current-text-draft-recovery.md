<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# ADR 0048 — Recover one current text draft through the planned Drift store

**Status:** Accepted for the bounded implementation; candidate source implemented
2026-10-31 under the user's next-release request. The contract was specified
2026-09-25 during C1-S1. PR #40 merged the source and integrated CI passes.
Required physical acceptance and release admission remain pending; no named
human sign-off is claimed.

## Context

[ADR-0010](0010-working-loop-in-memory-document.md) recorded an intentionally
volatile current document and deferred Drift persistence to A-24. That
limitation was present in the C1-S1 inspected source. The 31 October candidate
implements the bounded successor described below. Its old rich-editor deferral has
already been superseded by [ADR-0012](0012-flutter-code-editor-behind-editorsurface.md),
so the persistence problem must be scoped against the current rich Editor,
Blocks handoff and file-backed Run implementation.

The C1-S1 provider had a mutation epoch, but Save/Run/Files completion guards
still compared document values. A stable Connection facade also makes object
identity insufficient to bind a multi-step text action to one attached board.
Recovery must not amplify either gap by restoring a historical target as
current write authority.

C1-S1 requests a bounded contract and an honest estimate, not the full A-24
implementation. The [design review and sizing](../developments/2026-q4-reliable-workflow/c1-s1/03_Recovery_Design_and_Sizing.md)
records this distinction and the proposed reforecast.

## Decision

Adopt [the bounded current-draft contract](../specifications/App/current-draft-recovery.md)
for the bounded implementation slice:

1. Use one current-text slot in the planned Drift `projects`/`project_files`
   subset and single SettingsStore. Commit its content and recovery metadata
   atomically. No scratch file or separate preferences backend.
2. Distinguish local checkpoint state from board-dirty state. A saved-local
   indication acknowledges a successful transaction for that exact revision.
3. Offer explicit offline Restore/Discard with nondestructive failure handling.
   A local recovery panel is a narrow extension of
   [ADR-0011](0011-connection-gated-shell.md); it does not implement the complete
   offline IDE.
4. Restore text without board authority. Require a current-session destination
   decision before a recovered document can be saved, uploaded or run on a
   board; use document epochs and the existing neutral session stamp across
   asynchronous boundaries.
5. Include interrupted-write, corrupt/full storage, version handling, stale
   completions and applicable platform evidence in the same usable increment.
   Keep Blocks graph recovery and the rest of A-24 explicitly carried.

This decision supersedes only ADR-0010's volatile-only current-text design for
the bounded candidate slice, subject to its acceptance evidence. It does not retroactively claim that released builds
persist drafts, change PBLE/1 or remove the existing provider/Connection seams.

## Alternatives considered

| Option | Decision |
|---|---|
| Ad-hoc text/JSON scratch file or separate preferences | Rejected: duplicates the accepted Drift direction and leaves another migration/storage boundary |
| Complete all A-24 projects, histories, imports and Blocks state together | Deferred: exceeds the first bounded outcome and needs separate contracts |
| Infer the old board from a recovered path or advertised name | Rejected: path and display identity do not authorize a new session |
| Restore automatically over a fresh empty provider | Rejected: races hydration, user edits and pending replacement decisions |
| Ship only successful restart recovery, add failure handling later | Rejected: cannot meet the recovery story's minimum safety acceptance |

## Consequences

The candidate adds Drift/native database dependencies, a versioned schema,
local recovery UI and epoch/session completion guards. The
[implementation record](../developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md)
and [operator recipe](../developments/2026-q4-reliable-workflow/c1-s2/01_Operator_Recipe.md)
record their evidence and remaining admission work. The estimate exceeds the
original C1-S2 allowance; the 60-hour S2–S4 option remains a planning proposal,
not measured effort or confirmed staffing. Physical evidence is still required.
Full project persistence and Blocks graph recovery remain unfinished.
