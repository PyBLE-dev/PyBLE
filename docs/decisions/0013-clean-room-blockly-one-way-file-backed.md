# ADR 0013 — Blockly is an offline, one-way Blocks → Python surface over the shared file-backed program actions

**Status:** Accepted (2026-07-27); responsive item 8 superseded by
[ADR-0014](0014-focused-blocks-landscape-workspace.md) on 2026-07-28. Freezes
the bounded **A-31** increment and
supersedes the M1-only reachability exception in
[design-system.md §7.12](../specifications/App/design-system.md). Extends
[ADR-0007](0007-riverpod-state-management.md) (Riverpod),
[ADR-0010](0010-working-loop-in-memory-document.md) (the current document and
public feature-provider imports), and [ADR-0011](0011-connection-gated-shell.md)
(the connected IDE shell). It does not change PBLE/1, the BLE adapter, or the
firmware.

## Context

A-31 requires an offline Blockly editor that generates inspectable MicroPython
for generic ESP32 boards, carries no board profile or pedagogy, and uses the
same save/run path as the text editor. The pinned input is the pristine
Apache-2.0 `RaspberryPiFoundation/blockly` submodule at
`app/upstream/blockly`; PyBLE has no permission to copy source, block catalogs,
identifiers, artwork, or lesson content from another product.

Several details were not previously frozen:

- whether Python edits round-trip back into a visual workspace;
- what exact source Run and Save act on, and whether they may replace an
  unrelated dirty editor buffer;
- whether the JavaScript bridge may see a board connection;
- how a Blockly program larger than PBLE/1's inline-source ceiling runs;
- what survives when the platform view is disposed before Drift (A-24) exists;
- how Blocks becomes reachable in the stacked layout after the M1 exception.

The interim working loop in ADR-0010 runs the editor buffer with `runSource`.
That is unsuitable as A-31's general path: Blockly output can exceed the
firmware's 2 KiB inline-source limit. The complete app flow already specifies a
CRC-verified file upload followed by `runFile`.

## Decision

**Blockly is a one-way, offline visual source that publishes immutable generated
program snapshots. Dart owns every board action.**

1. **One-way source model.** The Blockly workspace is authoritative for visual
   work. Each material workspace change publishes one
   `GeneratedProgram {source, workspaceJson, revision}`. The Blocks surface
   exposes freshly acknowledged `source` as selectable, read-only `.py`. Empty
   or generator-invalid snapshots are never actionable. PyBLE never tries to
   reconstruct blocks from edited Python.

2. **Independent editor hand-off.** “Open in editor” first acknowledges the
   current host revision, then copies it into a new dirty `blocks.py` editor
   document. It asks before
   replacing a different dirty editor document. Later editor changes do not
   mutate the Blockly workspace, and later block changes do not silently replace
   the editor document.

3. **One file-backed action path.** A shared Connection-only Dart
   `ProgramActions` owns source normalization, UTF-8 encoding, `putFile`, and
   `putFile → runFile`. Both the text editor and Blocks delegate to it. Blocks
   Preview, Open in editor, Save, and Run each request and await a fresh snapshot
   from the active host, then freeze and revalidate that acknowledged revision
   for the action. Dart supplies a per-host request ID that only the
   request-specific snapshot/error echoes; unsolicited change snapshots may
   update retained state but cannot authorize an action. One action lock
   serializes all four source consumers. Save
   writes it to `/blocks.py`; Run uploads it to `/blocks.py`, waits for verified
   completion, then calls `runFile('/blocks.py')`. The explicit Save/Run action authorizes
   replacing that feature-owned target. `runSource` remains available only for
   deliberately bounded snippets, not the primary editor/Blocks toolbar path.

4. **A narrow, versioned bridge.** The WebView sends versioned JSON snapshot or
   error messages containing only strings, JSON workspace state, and a monotonic
   revision. Every WebView generation has a Dart-owned host epoch: a new host
   returns the feature to loading, delayed messages from older hosts are
   ignored, and actions stay disabled until the new host restores and publishes
   a newer revision. Dart rejects malformed, unknown-version, and over-limit
   messages, request IDs/revisions above the shared 32-bit bound, and empty
   action acknowledgements. The five-second action timeout covers both invoking
   JavaScript and receiving its acknowledgement. A first-message watchdog stops
   only for an accepted snapshot or terminal host error; a stale pre-restore
   snapshot cannot mask a hung restore. An error before an epoch's first
   accepted snapshot is a retryable host error. Generator/serialization errors
   after readiness leave the live workspace editable but keep every
   source-consuming action disabled until a valid snapshot repairs the state.
   Host-load failures replace the workspace with Retry; when retained JSON
   cannot be restored, a confirmed **Start fresh** discards only that volatile
   workspace and creates an empty host. JavaScript never receives a
   `Connection`, board identifier, chip, pin map, PBLE/1 opcode, path outside the
   fixed generated target, or any transport object.

5. **Offline, pinned runtime.** The shipped runtime is the minimal generated
   core/built-in-blocks/Python-generator/English-message/media bundle built from
   the exact pristine Blockly pin. PyBLE-authored HTML, CSS, JavaScript, and
   toolbox configuration are fresh MIT work. All references are local Flutter
   assets, external navigation is denied, and the content-security policy
   denies network connections. The full upstream Apache-2.0 license ships and
   is registered with Flutter's license registry.

6. **Initial toolbox.** A-31 exposes Blockly's standard language categories:
   logic, loops, math, text, lists, variables, and functions. These generate
   ordinary Python accepted by MicroPython. No copied third-party catalog,
   board profile, GPIO mapping/default, commercial-board block, or pedagogy is
   present. Generic hardware blocks may be added later only with their contract
   and tests frozen first and every hardware value supplied explicitly.

7. **Volatile workspace increment.** `blocksDocumentProvider` retains the latest
   serialized Blockly JSON and source across shell navigation and platform-view
   recreation within the app process. A rebuilt WebView restores that JSON.
   A confirmed Start fresh action is the recovery escape hatch for incompatible
   or corrupt retained JSON and does not mutate the file already on the board.
   Durable project storage/migrations remain the A-24 hook. This is a recorded
   deviation from the full project-persistence requirement; the UI never claims
   the workspace is durably saved merely because `/blocks.py` was uploaded.

8. **Responsive reachability — SUPERSEDED by ADR-0014.** This ADR originally
   placed Blocks beside Pins in the landscape secondary pane and added Blocks as
   a full-width stacked destination. That placement made the visual workspace
   compete with Files, Editor, Pins, and the permanently-open console.
   ADR-0014 replaces only this placement: Blocks is now a first-class landscape
   rail destination that replaces the three text-workbench panes with a focused,
   canvas-first host while retaining top chrome. It freezes one feature-owned
   Blocks Run, the conditional 360–420 dp generated-Python inspector, off-canvas
   notices, a collapsed/on-demand console, and workspace restoration across
   rotation. Items 1–7 of this ADR remain unchanged.

## Alternatives considered

- **Import another app's implementation or block catalog.** Rejected by the
  clean-room and licensing posture. Only the desired high-level workflow informs
  this fresh implementation.
- **Let JavaScript call the board directly.** Rejected: it crosses the
  `Connection` seam, duplicates error/transfer behavior, and creates a hidden
  transport path that cannot be exercised with `FakeConnection`.
- **Run generated code with `runSource`.** Rejected: valid visual programs can
  exceed the inline-source ceiling. The file-backed action handles programs of
  the normal file-transfer size and is shared with the editor.
- **Publish generated code by mutating the current editor buffer before every
  Run/Save.** Rejected: it could silently replace or later save over an unrelated
  open file. Only the explicit editor hand-off mutates the document.
- **Bidirectional Python ↔ Blocks conversion.** Rejected: it is lossy and would
  make neither representation authoritative.
- **Load Blockly from a CDN.** Rejected: violates offline-first behavior,
  expands the WebView's network attack surface, and makes builds non-reproducible.

## Consequences

The code shown in the preview is the code uploaded and run; failures propagate
through the existing typed Connection path; the WebView stays replaceable and
testable behind a fake host; and no platform or product-specific material enters
the feature. The costs are a fixed generated filename in this bounded increment,
no Python-to-block conversion, and no durable workspace recovery until A-24.
Real WebView rendering/interaction still requires iPadOS and Android integration
coverage because Flutter host widget tests cannot inspect a platform view's DOM.

## Related

- [App specs §4.10](../specifications/App/specs.md)
- [App TDD §4.6 and §11.2](../specifications/App/TDD.md)
- [Public roadmap](../ROADMAP.md)
- [ADR-0014 — Focused responsive Blocks landscape
  workspace](0014-focused-blocks-landscape-workspace.md)
- [ADR-0002](0002-fresh-protocol.md) and
  [ADR-0003](0003-license-mit.md)
