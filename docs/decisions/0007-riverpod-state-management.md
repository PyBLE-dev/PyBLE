# ADR 0007 — Riverpod as the single declarative state-management approach

**Status:** Accepted (2026-07-02). **Closes OI-2** (App [specs.md §12](../specifications/App/specs.md#12-open-items) / **NFR-MAINT-2**). Ratifies App [TDD.md §2.3](../specifications/App/TDD.md#23-single-declarative-state-management-riverpod) Decision **D3**.

## Context

[NFR-MAINT-2](../specifications/App/specs.md#57-maintainability--nfr-maint) requires the app to fix **one** declarative state-management approach and record it in an ADR before broad adoption; until then it is tracked as open item **OI-2**. The App design ([TDD.md §2.3](../specifications/App/TDD.md#23-single-declarative-state-management-riverpod), **D3**) names **Riverpod** as the working choice with **Bloc** the documented alternative, and the whole app is structured around a single [`Connection`](../specifications/app.md#3-the-connection-api-the-seam-every-widget-binds-to) seam (**D1**) that must be injectable as one overridable handle so every widget/golden test runs against a `FakeConnection` (**D5**).

App Sprint S1 (story **A-05**, the app shell + state foundation) cannot author its `[red]` tests or shell code until this choice is ratified: A-05's first acceptance criterion — "a single declarative state-management approach is chosen, recorded as an **ADR**, and applied consistently across the app" (NFR-MAINT-2) — makes the ADR a Definition-of-Ready blocker. This ADR discharges it.

## Decision

**The PyBLE app uses Riverpod (`flutter_riverpod`) as its single declarative state-management approach across every surface, from v1.0.** Concretely:

- The active `Connection` is exposed through **one** root provider, `connectionProvider` (`Provider<Connection>`), overridden at the `ProviderScope` root — with the real `PbleConnection` in production (from A-02 / A-14) and with a scriptable `FakeConnection` in tests and as the S1 shell stand-in.
- All `Connection`-derived runtime state (connection state, console buffer, run state, file listing, transfer progress) is exposed as **derived providers** read off `connectionProvider`; widgets `watch` derived providers and **never** hold a transport handle, a `flutter_blue_plus` type, or a wire type directly (**D1/D2**, CON-8, FR-BLE-8).
- Durable user state stays in Drift (`lib/data/`, **D4**); Riverpod carries runtime/UI state only. Ephemeral view state (active tab, selection, scroll) stays in widget/controller scope.
- This is applied **consistently**: no surface may introduce a second state-management library (Bloc, GetX, `provider`, hand-rolled `InheritedWidget` graphs) for shared/app state.

Unchanged by this ADR: the `Connection` seam (**D1**), the neutral types (**D2**), the `FakeConnection`-driven test model (**D5**), the strict `UI → lib/pble → lib/ble` layering (NFR-MAINT-1), and the clean-room / no-leak rule.

## Alternatives considered

- **Bloc / Cubit** — the documented alternative (TDD **D3**). Mature, explicit event→state modelling, strong testability. Not chosen as the default because injecting a single `Connection` via a compile-safe provider override and deriving read-only providers off one seam is more direct in Riverpod, with the least ceremony for deterministic widget/golden tests. Bloc remains the viable fallback; adopting it would be a new ADR superseding this one.
- **`provider` (InheritedWidget wrapper)** — lighter, but lacks compile-safe overrides and auto-dispose and scales poorly across many derived states.
- **GetX / other batteries-included frameworks** — rejected: opaque global state, weaker testability, and (GetX) navigation/DI coupling that a clean-room, seam-tested app does not want.
- **Raw `setState` / `InheritedWidget`** — insufficient for shared cross-surface state and the single-seam injection pattern.

## Consequences

**Positive**
- One overridable `connectionProvider` is the injection point for `FakeConnection`, so every widget/golden/unit test drives UI with no BLE and no hardware (FR-CONN-7, **D5**) — the structural precondition for Test-Driven Development.
- State flows down from `Connection`, intents flow up through it, keeping the strict layering (NFR-MAINT-1, CON-8) observable and the editor/console/files transport-agnostic.
- A single approach keeps the codebase uniform (NFR-MAINT-2) and golden tests deterministic (one provider to override).

**Costs / mitigations**
- The team standardizes on Riverpod idioms. **Mitigation:** the S1 shell (A-05) lands the canonical provider set + `ProviderScope` wiring the other engineers copy; the import-boundary + no-leak gates keep the seam clean.
- S1 pins Riverpod 2.x; a later move to a new major (3.x) is a dependency-ledger change with rationale, not a re-decision of the approach.

**Process**
- **OI-2 is closed;** NFR-MAINT-2 is satisfied by this ADR.
- `flutter_riverpod` is the only non-SDK app dependency permitted in Sprint S1 (dependency governance, BLD-2); it is MIT-licensed and recorded in `app/DEPENDENCIES.md`.
- Spec-first: this ADR lands in its own `[docs]` commit before A-05's `[red]`/`[green]`, per SDD.

## Related

- Ratifies App [TDD.md §2.3](../specifications/App/TDD.md#23-single-declarative-state-management-riverpod) (**D3**) and [§6](../specifications/App/TDD.md#6-state-management--data-flow) (state management & data flow); satisfies [specs.md](../specifications/App/specs.md) **NFR-MAINT-2**; closes **OI-2**.
- Seam it plugs into: [app.md §3](../specifications/app.md#3-the-connection-api-the-seam-every-widget-binds-to) `Connection` / `FakeConnection`; [ADR-0002](0002-fresh-protocol.md) (fresh protocol), [ADR-0003](0003-license-mit.md) (MIT).
- Consumed first by App story **A-05** (shell + state foundation, Sprint S1).
