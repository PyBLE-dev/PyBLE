// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 / A-22 — the shell's Riverpod wiring: the single runtime-session
/// injection seam and the derived, read-only state providers (NFR-MAINT-2 /
/// ADR-0007 + ADR-0009, FR-CONN-5, FR-CONNECT-*, CON-8, D1/D3).
///
/// This layer knows only the neutral [ConnectionManager] / [Connection] seam and
/// the frozen neutral types from `lib/pble` — never `lib/ble`, never a transport
/// type (D2). Every widget binds to a board exclusively through these providers.
library;

import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/pble/pble.dart';

/// The single runtime-session injection point (ADR-0009, D1/D3, CON-8).
///
/// A-22 moves the root seam here: the active [Connection] CHANGES at runtime
/// (scan → connect → disconnect), and building a live board from a scan hit is
/// transport-facing, so the session orchestration lives in a NEUTRAL `lib/pble`
/// [ConnectionManager]. Deliberately unimplemented: it MUST be overridden at the
/// `ProviderScope` root so no widget can bind to a hidden default transport.
/// `main.dart` injects `PbleConnectionManager.production(...)` (the real fbp
/// stack, built inside `lib/pble` so no `lib/ble` type crosses the seam); tests
/// inject a `PbleConnectionManager` wired from neutral fakes.
final Provider<ConnectionManager>
connectionManagerProvider = Provider<ConnectionManager>((ref) {
  throw UnimplementedError(
    'connectionManagerProvider must be overridden at the ProviderScope root '
    '(main.dart injects PbleConnectionManager.production(...); tests inject a '
    'PbleConnectionManager built from neutral fakes).',
  );
});

/// The single Connection seam every widget binds to (D1/D3, CON-8).
///
/// A-22: now DERIVED from the manager's ONE stable facade — its identity never
/// changes across scan/connect/disconnect, so every existing widget that reads
/// [connectionProvider] / [connStateProvider] keeps working unchanged (the seam
/// is preserved). With no [connectionManagerProvider] override this propagates
/// the manager's `UnimplementedError` (still throw-until-injected). Tests may
/// override [connectionProvider] directly with a scripted [FakeConnection] — an
/// explicit override wins over this derivation, so the existing shell suite is
/// untouched.
final Provider<Connection> connectionProvider = Provider<Connection>((ref) {
  return ref.watch(connectionManagerProvider).connection;
});

/// The observable link/run state, derived from the injected [Connection]
/// (FR-CONN-5). Read-only from the UI: widgets consume it through a
/// `ValueListenableBuilder`; nothing here can mutate the board's state.
final Provider<ValueListenable<ConnState>> connStateProvider =
    Provider<ValueListenable<ConnState>>(
      (ref) => ref.watch(connectionProvider).state,
    );

/// The live run-state stream from the seam (A-16, ADR-0010, TDD §11.6e).
///
/// Mirrors `Connection.runState` so run-control consumers (the console run-state
/// indicator and any run-availability logic) observe program lifecycle
/// transitions without touching a transport type. Re-derives if the seam
/// identity ever changes. Read-only from the UI (CON-8, D1).
final StreamProvider<RunState> runStateProvider = StreamProvider<RunState>(
  (ref) => ref.watch(connectionProvider).runState,
);

/// The primary shell surfaces, in navigation order (FR-UI).
///
/// S1 navigation is index-based (this enum + an `IndexedStack`) via a
/// `StateProvider`; `go_router` is deliberately deferred.
enum AppSurface { connect, editor, console, files, blocks }

/// The currently focused shell surface. Drives the shell's `IndexedStack` and
/// the selected index of the `NavigationRail` / `NavigationBar`.
final StateProvider<AppSurface> selectedSurfaceProvider =
    StateProvider<AppSurface>((ref) => AppSurface.connect);

/// Whether the landscape left-hand Files sidebar is collapsed (FR-UI-1).
///
/// The landscape three-pane layout keeps Files as a persistent left pane; this
/// flag lets the user collapse it to a thin rail to reclaim width. In landscape
/// the Files navigation destination TOGGLES this flag rather than duplicating
/// Files into the centre pane (Files never doubles as the centre surface). The
/// stacked layout ignores this — there Files is an ordinary destination.
final StateProvider<bool> filesPaneCollapsedProvider = StateProvider<bool>(
  (ref) => false,
);

/// Whether the on-demand console is expanded beneath focused landscape Blocks.
///
/// It starts collapsed so the visual canvas owns the height. The shell expands
/// it after a Blocks run, on new output, or when the user explicitly opens it.
/// Other workbenches continue to render the normal expanded console strip.
final StateProvider<bool> blocksConsoleExpandedProvider = StateProvider<bool>(
  (ref) => false,
);

/// Live content available in the landscape secondary pane (ADR-0013).
///
/// A-32 adds Plots when its surface is implemented; no inert destination is
/// exposed in the meantime.
enum RightPaneSurface { blocks, pins }

/// Pins remains the landscape default, preserving the established shell and
/// ensuring the platform WebView is created only after an explicit selection.
final StateProvider<RightPaneSurface> selectedRightPaneSurfaceProvider =
    StateProvider<RightPaneSurface>((ref) => RightPaneSurface.pins);
