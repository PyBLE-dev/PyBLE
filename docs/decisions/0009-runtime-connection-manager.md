# ADR 0009 — The active `Connection` is a runtime session, held by a `ConnectionManager`

**Status:** Accepted (2026-07-02). Extends [ADR-0007](0007-riverpod-state-management.md) (Riverpod / D3) and ratifies the runtime-session design added to App [TDD.md §4.8](../specifications/App/TDD.md#48-libconnect--scanconnect-flow-ui) / [§6.2](../specifications/App/TDD.md#62-binding-pattern). Enables story **A-22** (scan/connect flow). Does **not** supersede the `Connection` seam (D1) — it strengthens it.

## Context

Through Sprints S1–S3 the app injected a **single, static** `Connection` at the `ProviderScope` root: `main.dart` overrode `connectionProvider` with a `FakeConnection` stand-in ([ADR-0007](0007-riverpod-state-management.md)), and every widget bound to that one handle. This was correct for a shell that never talked to a radio.

Making **Connect real** breaks that assumption in one specific way: the active `Connection` **changes at runtime**. The app launches with no board, the user scans, picks a board, a GATT link opens, HELLO negotiates, and only *then* does a live `PbleConnection` exist — and it goes away again on disconnect. The transport-facing plumbing this requires (a `flutter_blue_plus` scan, `BleAdapter.connect(id) → BleLink`, then `PbleConnection.fromLink(...)`) touches `lib/ble` types, which **no widget, no `lib/app` provider, and not `main.dart`** may import (CON-8, FR-BLE-8, enforced by `tools/ci/import_boundary.sh`, which scans all of `lib/**` outside `lib/pble/`).

So the runtime-session orchestration cannot live in the UI or the app wiring. It must live behind the seam, in `lib/pble` — the sole package permitted to import `lib/ble`.

## Decision

**A neutral `ConnectionManager` in `lib/pble` owns the runtime connection session; the UI drives it through Riverpod and binds only to neutral types.** Concretely:

1. **`ConnectionManager` (neutral, `lib/pble`)** is the single object that holds the live session. It composes a `Scanner` (scan seam), a `BleReadinessSource` (adapter/permission seam), and a `ConnectionFactory` (`Future<Connection> Function(String deviceId)`), and exposes: a **stable facade `Connection`**, the live scan results, readiness, a `ConnectPhase` (`idle | scanning | connecting | connected | failed`), the selected board, the last error, and the verbs `startScan` / `stopScan` / `connect(id)` / `disconnect`. Its production constructor `PbleConnectionManager.production({appName, appVersion})` wires the real `flutter_blue_plus` stack **internally**, so callers name no `lib/ble` type.

2. **The `connectionProvider` handle stays, but is preserved as a *stable facade*.** `ConnectionManager.connection` is one `Connection` object whose **identity never changes** across scan/connect/disconnect cycles: its `state` reflects the full session lifecycle (`disconnected` while idle/scanning/failed, `connecting` during GATT+HELLO, then the live board's `ready`/`running`), and its verbs delegate to the live board when connected and throw a typed *not-connected* error otherwise. `connectionProvider` becomes `manager.connection`; `connStateProvider` is **unchanged** (`connectionProvider.state`). Every existing widget (`ConnectionStatusPill`, `PinReferencePage`, `FilesPage`) keeps compiling and now reflects real state.

3. **The root injection point moves up one level, from `connectionProvider` to `connectionManagerProvider`.** `main.dart` overrides `connectionManagerProvider` with `PbleConnectionManager.production(...)` (importing `lib/pble` only); tests override it with a fake manager, or override `connectionProvider` directly with a `FakeConnection` (which still wins, so the S1–S3 widget suite is untouched).

4. **Riverpod remains the one state approach (ADR-0007).** A `ConnectController` (`Notifier`, `lib/connect`) projects the manager into a `ConnectState` for the connect UI; all `Connection`-derived state stays in derived providers. No second state library is introduced.

Unchanged: the `Connection` seam (D1), neutral types (D2), the `FakeConnection` test model (D5), the strict `UI → lib/pble → lib/ble` layering (NFR-MAINT-1), the service-UUID-filtered scan / no-raw-list rule (CON-1, SEC-4, FR-BLE-1), and scan→connect→use with no pairing/account/identity-gating (FR-CONNECT-5, SEC-6).

## Alternatives considered

- **Keep the static `connectionProvider`, swap its value at runtime with `overrideWith` from the UI.** Rejected: the UI would need to build a `PbleConnection` from a `BleLink`, importing `lib/ble` and breaking CON-8; and runtime re-scoping of a root override is fragile.
- **Put the orchestration in `lib/connect` or `lib/app`.** Rejected: both are `lib/**` outside `lib/pble/` and may not import `lib/ble` (import-boundary gate). The bridge from `BleAdapter`/`BleLink` to a published `Connection` is intrinsically transport-facing.
- **Make `connectionProvider` nullable (`Connection?`).** Rejected: every existing reader (`.state`, `.deviceInfo()`) would need null-handling; the stable disconnected facade preserves the non-null seam with honest typed errors.
- **A second state-management library (Bloc) for the session.** Rejected — contradicts ADR-0007 / NFR-MAINT-2.

## Consequences

**Positive**
- The whole runtime session is testable with **neutral fakes** (`FakeScanner`, a `ConnectionFactory` returning `FakeConnection`, a fake `BleReadinessSource`) — no fake radio, no fake `BleLink` (FR-CONN-7, D5).
- `main.dart` and every widget stay `lib/ble`-free; the import-boundary and no-leak gates keep passing.
- The seam is unchanged in shape, so S1–S3 widgets and their tests carry forward with no rewrite.

**Costs / mitigations**
- One new neutral concept (`ConnectionManager`) and its provider. **Mitigation:** it is the *only* new seam object; `Scanner`/`ScanHit`/`ConnectPhase` are small value types, and `production()` hides all wiring.
- The disconnected facade must throw honest typed errors (not silently succeed). **Mitigation:** frozen in TDD §5/§6.2; covered by `[red]` before `[green]`.

**Process**
- Spec-first: this ADR + the TDD §4.8/§5.2/§6.2/§7.1 freeze land in their own `[docs]` commit before A-22's `[red]`/`[green]`.
- No new dependency: `flutter_blue_plus` is already pinned; `permission_handler` is **not** added (TDD §7.4). Riverpod 2.x `Notifier` is used (already the app's state approach).

## Related

- Extends [ADR-0007](0007-riverpod-state-management.md) (Riverpod / D1/D3); builds on [ADR-0002](0002-fresh-protocol.md) (fresh PBLE/1) and [ADR-0008](0008-signal-design-system.md) (Signal UI for the connect surface).
- Ratifies App [TDD.md §4.8](../specifications/App/TDD.md#48-libconnect--scanconnect-flow-ui), [§5.2](../specifications/App/TDD.md#52-shared-types), [§6.2](../specifications/App/TDD.md#62-binding-pattern), [§7.1](../specifications/App/TDD.md#71-scan--connect); satisfies [specs.md](../specifications/App/specs.md) **FR-CONNECT-1/2/3/5/6**, **FR-CONN-5/6**, **FR-BLE-8**, **NFR-MAINT-1/2**, **CON-8**.
- Consumed first by App story **A-22** (scan/connect flow with diagnostics), Sprint S5.
