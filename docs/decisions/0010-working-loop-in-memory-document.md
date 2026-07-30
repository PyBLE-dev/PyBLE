# ADR 0010 — The working-loop current document is a volatile in-memory provider; feature packages cross-import public providers

**Status:** Accepted (2026-07-02). Extends [ADR-0007](0007-riverpod-state-management.md) (Riverpod / D3) and [ADR-0009](0009-runtime-connection-manager.md) (runtime session behind the seam). Enables the **working feature loop** increment across stories **A-20** (editor), **A-21** (console), **A-16** (run-control toolbar; wire lands on the A-11 client) and **A-30** (files). Does **not** supersede the `Connection` seam (D1) or the offline-first mandate — it scopes a temporary, recorded deviation with a hard re-freeze at **A-24**.

## Context

`connectionProvider` is now real ([ADR-0009](0009-runtime-connection-manager.md)): the app discovers and connects to a physical ESP32/ESP32-S3 over BLE, and the seam yields a live `Connection` whose verbs (`runSource`/`stop`/`softReboot`, `console`/`sendInput`, `listDir`/`getFile`/`putFile`/…) are built and conformance-tested against `FakeConnection`. But the verbs are **unwired**: the toolbar Run/Stop/Soft-reboot slots are inert (`onPressed: null`), and `lib/editor`, `lib/console`, `lib/files` are empty barrels whose pages are designed empty states. The owner's standard is explicit: *built-but-unwired features are junk; designed-but-unimplemented features suck.* The goal is a working product loop — edit → run → watch output → manage files — on the already-built protocol layer.

Two things the full stories assume are **not yet available** and are deliberately out of scope for this increment:

1. **Drift persistence (`lib/data/`, story A-24).** [specs.md](../specifications/App/specs.md) FR-EDIT-7 and FR-PROJ-2/NFR-REL-3 mandate that Save persists the buffer to a local project (offline-first) and that open buffers survive a process restart. `lib/data/` is not built yet, so this increment cannot honor durable persistence.
2. **The editor's rich surface (`flutter_code_editor`, OI-1).** FR-EDIT-1/2/3 mandate syntax highlighting, tabs, and find/replace via a package still under evaluation ([OI-1](../specifications/App/specs.md)). The offline-first / dependency-hygiene posture (NFR-OFF, no heavy code-editor / `google_fonts`) rules a heavy widget out for v1.

The loop nonetheless needs **one shared "current document"** that the editor edits, the run-control runs, and the files explorer opens-into and uploads-from — a single source that survives tab/navigation switches (FR-CONSOLE-7's sibling requirement for the editor) but need not survive an app restart yet.

## Decision

**For the working-loop increment, the current document lives in a volatile in-memory Riverpod provider; feature packages cross-import each other's *public* providers; Drift-backed durable persistence is deferred to A-24.** Concretely:

1. **`editorDocumentProvider` (`lib/editor`, in-memory `Notifier<EditorDocument>`)** holds the single current document (`name`, `content`, `dirty`, `boardPath`). It survives navigation (a normal keep-alive provider at the `ProviderScope` root) but **not** a process restart. `EditorDocument` is an immutable value type; the notifier exposes `newDocument()` / `setContent(text)` / `openFromBoard(path, content)` / `markSaved({boardPath})`.

2. **Connection-derived runtime controllers are providers** ([ADR-0007](0007-riverpod-state-management.md) / TDD §6.1): `runControllerProvider` + `runAvailabilityProvider` (`lib/editor`), `consoleBufferProvider` (`lib/console`, a capped ring subscribing to `Connection.console`), `fileExplorerProvider` (`lib/files`). A shared `runStateProvider` (`StreamProvider<RunState>` off `Connection.runState`) is added to the seam-wiring layer `lib/app/providers.dart` beside `connectionProvider`/`connStateProvider`.

3. **App-layer packages may import each other's *public* providers.** `lib/files` reads `editorDocumentProvider` (open-in-editor, upload-current-buffer); `lib/editor`'s run-control and `lib/console` read `connectionProvider`/`runStateProvider`; the shell reads `runControllerProvider`/`runAvailabilityProvider` to wire the toolbar. This app-layer coupling is explicitly allowed. **The one boundary that never moves: no UI package imports `lib/ble`** (CON-8, FR-UI-7, `tools/ci/import_boundary.sh`); every board verb goes through the neutral `Connection` seam and neutral types, so the whole loop stays `FakeConnection`-testable (D5).

4. **The document provider is designed so A-24 swaps the storage backend without changing the seam.** `openFromBoard`/`markSaved` are the persistence hooks: A-24 rebinds them onto Drift `project_files` (Save → persist; hydrate open buffers on launch) with no change to how the editor/console/files widgets read the document.

**Recorded deviation (SDD honesty).** This increment does **not** satisfy FR-EDIT-7 (Save-persists-to-project) or NFR-REL-3/FR-PROJ-6 (buffers survive restart). Those acceptance criteria of A-20/A-30 are **carried, not dropped**, and re-freeze at A-24; the working-loop freeze note in [TDD.md §11.6](../specifications/App/TDD.md#116-working-loop-provider-contract-frozen) states the exact in-scope subset. FR-EDIT-1's rich surface (highlighting/tabs/find, OI-1) is likewise deferred: v1 ships a monospace editable surface styled with `SignalCodeColors`, which is a *real* editor for the loop, not a placeholder.

Unchanged: the `Connection` seam (D1), neutral types (D2), Riverpod as the one state approach (ADR-0007), the runtime-session facade (ADR-0009), the `UI → lib/pble → lib/ble` layering (NFR-MAINT-1), and every §1A.3 rejection (no accounts/cloud, no `.mpy`/`.pyc`, no board/pin profile, no identity gating).

## Alternatives considered

- **Build `lib/data/` (Drift, A-24) now, before the loop.** Rejected: pulls a schema/migration story forward, delays the working loop the owner needs, and couples four surfaces to persistence before their shapes are proven. The provider seam lets A-24 land later with no widget rewrite.
- **Persist the buffer to a single on-disk scratch file (no Drift).** Rejected: adds a `path_provider`-class dependency (NFR-OFF dep hygiene) for a stopgap that A-24 immediately replaces; volatile-until-A-24 is honest and cheaper.
- **Hold the document in widget/page state instead of a provider.** Rejected: it would not survive navigation (FR-CONSOLE-7's editor sibling), and files could not open-into / upload-from it without a shared handle.
- **Adopt `flutter_code_editor` / a WebView editor now.** Rejected for v1: OI-1 is still open and the dependency weight is unjustified for the loop; a `SignalCodeColors` monospace surface satisfies the loop's editing need.
- **A second cross-cutting "document service" object outside Riverpod.** Rejected — contradicts ADR-0007 / NFR-MAINT-2 (one declarative approach).

## Consequences

**Positive**
- A working edit→run→watch→manage loop lands on the existing, tested protocol layer with **no new dependency** and **no `lib/ble` leak** — the whole loop is `FakeConnection`-driven in widget/unit tests.
- Disjoint provider ownership (document/run in `lib/editor`, buffer in `lib/console`, explorer in `lib/files`, seam providers in `lib/app`) lets the feature engineers work in parallel without file conflicts.
- A-24 becomes a contained backend swap behind `openFromBoard`/`markSaved`, not a rewrite.

**Costs / mitigations**
- Edits are lost on a hard restart until A-24. **Mitigation:** recorded deviation with a hard re-freeze; the provider seam is persistence-ready; the owner proves the loop on real hardware (HIL) where the limitation is understood.
- App-layer packages now import each other's providers, a looser coupling than pure leaf packages. **Mitigation:** only **public** providers are cross-imported; the import-boundary gate still forbids `lib/ble`; the coupling is one-directional (`files → editor`, UI → seam) and small.

**Process**
- Spec-first: this ADR + the [TDD.md §11.6](../specifications/App/TDD.md#116-working-loop-provider-contract-frozen) contract + the scoping freeze notes in specs.md land in their own `[docs]` commit before any `[red]`.
- Test-first: `app-test-author` authors `[red]` against the frozen contract and adds all new `en` ARB keys in one place; then `[green]`; then the gates (no-leak, import-boundary, locale parity, iPadOS+Android golden parity).

## Related

- Extends [ADR-0007](0007-riverpod-state-management.md) (Riverpod / D3) and [ADR-0009](0009-runtime-connection-manager.md) (runtime session facade); honors [ADR-0008](0008-signal-design-system.md) (`SignalCodeColors` for the editor/console surfaces).
- Ratifies App [TDD.md §11.6](../specifications/App/TDD.md#116-working-loop-provider-contract-frozen) and the scoping freeze notes in [TDD.md §11.1](../specifications/App/TDD.md#111-editor)/[§11.4](../specifications/App/TDD.md#114-console--error-explanation) and [specs.md §4.5](../specifications/App/specs.md)/§4.6/§4.7/§4.8.
- Scopes App stories **A-20 / A-21 / A-16 / A-30** (working-loop subset); defers FR-EDIT-7, NFR-REL-3/FR-PROJ-6, and the rich-editor part of FR-EDIT-1 to **A-24** ([OI-1](../specifications/App/specs.md)).
