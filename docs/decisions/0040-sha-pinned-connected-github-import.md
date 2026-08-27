# ADR 0040 — Ship GitHub import first as a SHA-pinned connected-board subset

**Status:** Accepted (2026-08-22). Scopes a connected working-loop subset of
story A-33. Extends [ADR-0009](0009-runtime-connection-manager.md) (runtime
connection sessions) and [ADR-0010](0010-working-loop-in-memory-document.md)
(durable local persistence deferred to A-24). It does **not** close full A-33,
FR-IMPORT-4, FR-IMPORT-6, or DAT-6.

## Context

PyBLE already has a connected Files surface and a verified
`Connection.putFile` path. The next useful increment is therefore a bounded
way to browse a public GitHub repository and copy selected Python examples to
the connected board. The full product contract is broader: imported files
must also become durable local project files and the app must record their
provenance. Those capabilities depend on the A-24 Drift project store, which
is not part of the current working loop.

Remote source is untrusted, mutable, and network-dependent. A branch name can
move between directory browse and content download; repository entries can be
symlinks or submodules; file names can become unsafe board paths; GitHub can
rate-limit unauthenticated clients; and a multi-file PBLE/1 upload is not an
atomic transaction. The UI must not imply that browsing is execution, that a
batch is all-or-nothing, or that a branch label identifies immutable bytes.

This feature is authored fresh against GitHub's public REST contract and
PyBLE's existing `Connection` seam. A behavioral request to offer convenient
example download does not authorize copying another application's source,
assets, endpoint construction, data model, or interaction implementation.

## Decision

**The first GitHub-import increment is a connected Files action that resolves
one public repository/ref to an immutable commit, lazily browses that snapshot,
downloads and validates one bounded batch completely, and only then uploads
the selected `.py` files sequentially to the current board directory.**

1. **Repository input is deliberately narrow.** The user enters a canonical
   public repository-root URL of the form
   `https://github.com/<owner>/<repository>` and an optional ref. One trailing
   slash may be normalized away. Credentials, ports, query/fragment data,
   `.git`, `tree`/`blob` subpaths, non-HTTPS schemes, non-`github.com` hosts,
   and any path other than exactly two non-empty segments are rejected. The
   app sends no account credential, token, cookie, board datum, or user file.
   If ref is blank, it reads the repository's public `default_branch`; an
   explicit ref may name a public branch, tag, or commit.

2. **Every browse is pinned before it begins.** The GitHub REST API resolves
   the explicit or default ref once to the returned full commit SHA. The UI
   displays that SHA and every subsequent directory/content request is derived
   from that immutable commit, never from the moving ref and never from a
   response-provided arbitrary download URL. A refresh of the ref is an
   explicit new resolution and clears the old tree and selection.

3. **Directory browsing is lazy and selection is folder-scoped.** Resolving a
   repository does not recursively enumerate its tree. Opening a directory
   fetches only that directory at the pinned commit; Up is bounded at the repo
   root. One response is capped at 2 MiB and 512 direct entries; exceeding
   either limit rejects the folder before it reaches the eager tablet view. A
   selection contains direct children of one currently chosen remote directory
   only. Changing directory clears it. Only Git-tree entries with an ordinary
   blob mode (`100644` or `100755`) and a lowercase `.py` suffix are eligible.
   Directories remain browsable; symlink mode `120000`, submodule mode `160000`,
   non-files, `.mpy`, `.pyc`, and every other suffix are visible only as
   ineligible or omitted and are never fetched or written by this increment.

4. **The board target is explicit and flat for this subset.** Opening the
   action captures the Files controller's current board directory (`cwd`).
   Each selected direct child maps to
   `join(capturedCwd, basename(remotePath))`; no remote parent is recreated and
   this subset never calls `Connection.mkdir`. Before download, the review
   surface shows every exact remote path and exact board target path. It
   rejects empty/dot names, separators, NUL, duplicate targets, paths outside
   the captured directory, and targets over PBLE/1's 128-byte UTF-8 path
   ceiling. The action also captures the board-reported `fs_root` and mirrors
   PBLE/1's protected top-level names: when the captured directory equals that
   root, a target beginning with lowercase `pyble` or `pble`, or named exactly
   `boot.py` or `_boot.py`, is blocked before a board listing, Git blob fetch,
   or PUT. The surface warns whenever the captured destination is the board
   root. A path-specific localized failure names a selected protected target
   and instructs the user to close Import, create and enter a child directory
   such as `/examples` in Files, and then reopen Import so the new destination
   is captured. The same basename remains valid below a child directory.
   Ordinary non-protected basenames remain valid at the board root; this is
   targeted preflight, not a blanket root-import ban or confirm-to-continue
   warning.
   Preserving a remote hierarchy is a future, separately specified extension.

5. **Overwrite is always an informed choice.** Review lists the captured board
   directory and marks exact target names already present. Existing
   directories or other non-regular conflicts block the batch. Existing files
   require a separate, explicit confirmation naming the target paths; selecting
   Import is not itself overwrite consent. Immediately before the first PUT,
   the controller lists the directory again. Both listings must carry explicit
   PBLE/1 completeness metadata: `FILE_LIST more=1`, or a Connection test double
   that cannot prove completeness, blocks the batch because an omitted entry
   could hide a conflict. A new or changed conflict invalidates prior consent
   and returns to review without writing.

6. **All bytes are acquired and validated before any board mutation.** The
   controller fetches every selected object from the pinned snapshot into one
   bounded in-memory candidate batch. Each raw file is at most 256 KiB; the
   sum of raw selected bytes is at most 1 MiB. Declared sizes are an early
   rejection only; actual decoded byte counts are authoritative. Every file
   must decode as strict UTF-8 and contain no NUL byte. A missing, changed-type,
   mismatched-path/object, HTTP, rate-limit, decode, or bound failure rejects
   the whole candidate before the first `putFile`. Candidate bytes are not
   interpreted, preview-executed, persisted, or logged.

7. **One connection session owns the commit.** The action captures the stable
   `Connection` facade's opaque local session stamp with `cwd`. The stamp must
   still be current before every board preflight and immediately before each
   `putFile`; attach or detach advances it. The facade also advances it once
   when an attached live connection leaves an established `ready`/`running`
   state for `connecting` or `disconnected`, so an in-place reconnect to the
   same board is a successor session; ordinary `ready` ↔ `running` transitions
   retain it. A mismatch stops the batch before the next board verb. This stamp
   is in-memory action consistency only—not identity, authentication, persisted
   provenance, or PBLE/1 wire data.

8. **The commit is sequential and honestly non-atomic.** After the entire
   candidate is valid and overwrite consent is current, files are uploaded in
   the stable order displayed by review through sequential
   `Connection.putFile(targetPath, bytes)`. There is no `mkdir`, parallel PUT,
   rollback claim, automatic editor open, Save, Run, or `runFile`/`runSource`.
   On the first upload failure, cancellation request, or stale session, no
   further PUT begins. The result distinguishes succeeded, failed/current, and
   unattempted target paths and says that successful earlier files may already
   be present. The Files controller refreshes the captured directory after any
   outcome that may have written a file.

9. **Network state and cancellation are first-class.** Resolve, browse, fetch,
   review, upload, cancelled, failed, partial, and complete are distinct states;
   one action cannot be started twice. Browse/fetch cancellation aborts a
   request where supported and always ignores late responses through an
   operation generation. It causes zero board writes before commit. During a
   PUT, cancellation is cooperative: the in-flight verified PUT may finish,
   but no next PUT starts, and the partial result remains visible. HTTP
   offline/not-found/forbidden/rate-limit/server/malformed-response failures
   map to localized user actions. `403`/`429` rate limiting shows the public
   API limit and reset/retry guidance when GitHub supplies it; the app performs
   no tight or unbounded automatic retry. A positive supplied retry delay gates
   every network-producing action on the surface until its deadline; local
   navigation, selection, and review transitions cannot clear or bypass it.
   Every individual REST GET has one absolute wall-clock deadline spanning
   request send, response headers, and the complete bounded response body;
   arriving chunks do not extend it, and expiry aborts the request.
   Header-rejected HTTP responses have their body streams cancelled before the
   typed failure is returned so repeated failures do not strand resources.

10. **The surface is adaptive and accessible.** Import examples is an action
    on the connected Files surface, enabled only for a ready connection. Below
    600 dp the same controller is presented as a scroll-controlled modal bottom
    sheet; at 600 dp and wider it is a dialog. It survives keyboard insets and
    2× text without clipped actions; controls are at least 48 dp; directory
    rows, file eligibility/selection, loading state, pinned commit, target
    mapping, overwrite warning, progress, cancellation, and final result have
    localized labels and semantics. Focus moves to the first invalid field or
    error and returns to the invoking Files action on dismissal; important
    errors and the final outcome are announced once.

11. **The delivery remains test-driven and clean-room.** Unit tests cover URL
    and host rejection, ref-to-SHA pinning, lazy traversal, entry filtering,
    safe target derivation (including protected-root rejection and nested-path
    acceptance), UTF-8/NUL/size bounds, rate/error mapping, operation
    generations, and result accounting. Widget tests use an injected fake
    GitHub client and `FakeConnection` to prove actionable protected-root
    guidance, overwrite consent, all-fetches-before-first-PUT, sequential
    order, session changes, cancellation, partial truth, refresh, and zero
    open/run/mkdir calls. Goldens cover compact and
    wide layouts, portrait/landscape, loading/error/review/partial states, 2×
    text, high contrast, and keyboard inset. An integration/HIL row imports a
    small public pinned fixture into a disposable board directory and verifies
    exact bytes and no execution. No test depends on copying another app or on
    an unbounded live-network response.

12. **Full A-33 remains open.** This increment keeps candidates only in
    bounded memory long enough to write the connected board. FR-IMPORT-4's
    durable local project copy and FR-IMPORT-6/DAT-6's provenance record are
    carried, not dropped, and re-freeze with A-24/full A-33. A later increment
    must persist the exact pinned commit SHA and imported bytes transactionally
    before it may claim offline continuity or full import provenance.

## Alternatives considered

- **Download raw branch URLs directly.** Rejected because a branch can move
  between browse and fetch, and response-provided URLs broaden the network
  trust boundary unnecessarily.
- **Recursively import a remote tree and recreate it with `mkdir`.** Rejected
  for this subset: recursion increases API/rate/path/conflict complexity and
  PBLE/1 has no multi-file transaction. One selected folder of basenames is
  useful, bounded, and truthful.
- **Stream each GitHub response straight into `putFile`.** Rejected because a
  late invalid or oversized file would leave an avoidable partial board batch.
  Fetch-first gives all network/content validation a zero-mutation failure
  boundary.
- **Treat sequential PUTs as atomic or roll them back.** Rejected because a
  compensating delete could destroy an overwritten pre-existing file and the
  protocol supplies no directory transaction. The result reports reality.
- **Implement Drift files/provenance in this increment.** Rejected because it
  would pull the A-24 persistence schema into a connected UI slice. The full
  requirements remain explicit rather than being weakened.

## Consequences

- Users can deliberately copy public Python examples into the exact board
  folder they are viewing, with immutable source identity and bounded memory.
- GitHub is the sole optional network surface. Editing, Files, BLE, and Run
  remain usable during GitHub outage or rate limiting.
- The board may contain a truthful partial batch after a PUT failure or
  cancellation. The app exposes that state and refreshes instead of claiming
  rollback or success.
- Imports do not survive locally and have no durable provenance yet. That is a
  visible, recorded A-24/full-A-33 obligation, not an accidental omission.

## Related

- App requirements [§4.9](../specifications/App/specs.md#49-github-public-repo-import-libgithub_import--fr-import)
- App design [§10](../specifications/App/TDD.md#10-github-import-design-libgithub_import)
- [ADR-0009](0009-runtime-connection-manager.md)
- [ADR-0010](0010-working-loop-in-memory-document.md)
