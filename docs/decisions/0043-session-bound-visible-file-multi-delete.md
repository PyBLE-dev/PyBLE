# ADR-0043 — Bind visible-file multi-delete to one board session

- Status: **Accepted**
- Date: 2026-08-27
- Extends: [ADR-0010](0010-working-loop-in-memory-document.md)

## Context

The connected Files surface can delete one board entry after one confirmation,
while FR-FILES-5 has kept multi-select bulk operations deferred. Deleting
several files is useful for examples and classroom cleanup, but PBLE/1 exposes
only one `FILE_DELETE` command per path. It has no batch transaction, rollback,
recursive delete, or delete cancellation. A connection loss can also replace
the live board behind the app's stable `Connection` facade.

A bulk UI must therefore avoid implying that the operation is atomic or that a
confirmation from one board session remains valid for another. It must also
avoid selecting the PyBLE control plane or transfer scratch files that the
firmware workspace jail rejects.

The requested interaction may use familiar multi-selection behavior, but its
source, identifiers, copy, visuals, state model, and tests are authored fresh
from PyBLE's Material design system and PBLE/1 contract.

## Decision

1. **The first bulk-delete increment selects visible regular files only.** One
   selection contains eligible direct file children of the current Files
   directory. It never includes descendants or the directory itself. Folders
   retain the existing one-at-a-time deletion behavior, under which only an
   empty folder can be removed. Recursive deletion is not introduced or
   implied.

2. **Selection is explicit, local, and temporary.** A labelled Select action is
   the discoverable entry point; long-pressing an eligible file is an optional
   shortcut that enters selection and selects that row. In selection mode, a
   tap or keyboard activation toggles a checkbox instead of opening the file.
   The normal navigation, create, transfer, import, rename, delete, and
   Open-as-Blocks affordances are replaced by a contextual selected-count bar.
   Cancel, Escape, system Back, navigation that hides the Files presentation, a
   replaced listing, Files disposal, disconnect, or connection-session
   replacement clears the selection. Changing Editor/Console centre focus while
   the landscape Files sidebar remains visible is not navigation away from Files.

3. **Select all means all eligible files currently shown.** It never claims to
   include entries omitted by a truncated board listing, folders, locked
   entries, or descendants. Activating it while every eligible shown file is
   selected clears the selection. The accessible label states “shown files.”

4. **Firmware-reserved entries are locked before selection.** Relative to the
   board-reported `fs_root`, a lowercase top-level component beginning `pyble`
   or `pble`, exact top-level `boot.py` or `_boot.py`, and any component ending
   `.pbltmp` are non-editable. The predicate is case-sensitive and mirrors the
   PBLE/1 workspace jail. Such rows expose no open, rename, delete, Blocks, or
   bulk-selection action and are excluded from Select all. Ordinary files such
   as root `main.py`, and a `pyble*` basename below an ordinary child folder,
   remain eligible.

5. **One confirmation names one immutable intent.** Before deletion, the app
   shows the exact current board folder and every selected filename in stable
   display order, states that removal is permanent, and initially focuses the
   non-destructive action. Confirming captures the current directory, exact
   ordered direct-child paths, and opaque local connection-session stamp.

6. **The controller validates before the first mutation.** It rejects an empty
   or unknown selection, duplicate or unsafe leaf, directory, reserved path,
   path outside the captured directory, and path over PBLE/1's 128-byte UTF-8
   ceiling without sending `FILE_DELETE`. Once a valid ordered batch exists, a
   local busy or stale-session refusal reports every path as unattempted; an
   empty or malformed request has no accepted path list. It verifies the
   captured directory and session before the first command and again before
   every later command.

7. **Deletion is sequential, fail-fast, and non-atomic.** The controller awaits
   one ordinary `Connection.delete(path)` before issuing the next. It stops on
   the first typed failure or session change. Confirmed earlier successes are
   never rolled back, and failed or unattempted paths are never retried
   automatically. Parallel `Future.wait`, recursion, and a new PBLE opcode are
   not used.

8. **The result reports reality.** A result records exact succeeded paths, the
   failed/current path when present, exact unattempted paths, and the neutral
   localized failure kind. Complete success exits selection mode. A failed or
   partial result removes succeeded names from the selection, retains unresolved
   names that still exist in the reconciled listing, and announces how many were
   deleted and remain selected. A failed path absent from reconciliation remains
   recorded in the result but is not kept as a non-rendered selection ghost. A
   later selection edit dismisses rather than rewrites that terminal accounting.
   It never calls the batch transactional.

9. **Files refreshes once, and never refreshes a successor board.** After any
   `FILE_DELETE` was attempted—including a timeout whose board-side outcome may
   be uncertain—the controller lists the captured directory once if and only if
   the captured session is still current. A primary delete failure remains the
   visible error even if that reconciliation also fails. If every delete
   succeeded, a reconciliation failure is surfaced separately through the
   existing file-error mapping.

10. **The UI remains adaptive and accessible.** The contextual bar uses the
    Signal selected-count and destructive colors; selected rows use
    `surfaceContainerHigh`; controls remain at least 48 dp. The bar and exact
    confirmation scroll or reflow in a narrow Files pane and at 2× text without
    clipping. Selected counts and partial results are live regions; focus moves
    into selection, never defaults to destructive confirmation, and returns to
    Select after cancel or completion. While deletion is active, selection and
    Files mutations are locked and item progress remains visible.

11. **Delivery remains spec-first and test-driven.** Controller tests prove
    validation, stable sequential order, no overlap, first-failure accounting,
    no rollback, one refresh, session replacement, and a concurrent-batch
    refusal. Widget, semantics, keyboard, and golden tests prove discoverable
    selection, shown-file Select all, protected/folder exclusion, exact
    confirmation, cancel-with-zero-I/O, partial truth, focus recovery, narrow
    panes, high contrast, and 2× text. Physical iPad and board acceptance is
    required before the feature's pull request is opened.

## Consequences

- Users can remove several board files with one review and confirmation.
- Folders remain deliberately non-recursive and cannot be selected in this
  first bulk increment.
- A late failure can leave an honestly reported partial deletion because
  PBLE/1 has no transaction or safe rollback.
- The controller performs one final listing instead of one listing per file,
  reducing BLE round trips while preserving reconciliation.
- Control-plane and scratch files become visibly locked in Files rather than
  relying only on a later firmware `EACCES` response.

## Alternatives considered

- **Call the existing single-delete method in a loop.** Rejected because it
  refreshes after every item, swallows the typed exception needed for partial
  accounting, and cannot prevent later deletes after failure.
- **Delete files in parallel.** Rejected because PBLE/1 has one serialized
  mutation stream and parallel calls obscure deterministic failure accounting.
- **Include folders or recursively delete trees.** Rejected for this increment:
  PBLE/1 removes only empty directories and supplies no recursive transaction.
- **Roll back earlier successes.** Rejected because recreating deleted bytes is
  impossible without downloading and retaining every file, and a compensating
  write could overwrite a concurrent board change.
- **Keep selection in the shared controller state.** Rejected because selection
  is presentation-local and must disappear when the Files presentation is
  disposed; the controller owns only the validated batch execution and result.

## Related

- [App requirements §4.5](../specifications/App/specs.md#45-workspace-file-explorer-libfiles--fr-files)
- [App TDD §4.5](../specifications/App/TDD.md#45-libfiles--workspace-file-explorer)
- [PBLE/1 file transfer §5](../specifications/protocol.md#5-file-transfer-the-reliability-core)
- [Signal Files chrome §7.13](../specifications/App/design-system.md#713-files-pane-chrome-fr-files-tdd-45--84)

<!-- SPDX-License-Identifier: MIT -->
