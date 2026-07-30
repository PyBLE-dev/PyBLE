// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-05 [red] — Riverpod provider wiring for the shell (NFR-MAINT-2, FR-CONN-5,
// CON-8). Verifies the single injection point and the derived, read-only state
// providers from the frozen shell contract:
//   • connectionProvider is the sole seam and MUST be overridden at the root;
//   • connStateProvider is derived from Connection.state and tracks it live;
//   • selectedSurfaceProvider defaults to AppSurface.connect (index-based nav);
//   • ConnState / AppSurface are the frozen enums.
//
// CURRENTLY RED: `lib/app/providers.dart` and the `lib/pble/**` seam slice do
// not exist. HAND-OFF: lib/app → app-architect; lib/pble → app-protocol-engineer.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

void main() {
  group('A-05 shell providers wire to the Connection seam', () {
    test(
      'connectionProvider requires an override at the ProviderScope root',
      () {
        final container = ProviderContainer();
        addTearDown(container.dispose);
        expect(
          () => container.read(connectionProvider),
          throwsA(isA<UnimplementedError>()),
          reason:
              'the seam must be injected at the root — never a default impl',
        );
      },
    );

    test('connStateProvider is derived from Connection and tracks emit()', () {
      final fake = FakeConnection(initial: ConnState.disconnected);
      final container = ProviderContainer(
        overrides: <Override>[connectionProvider.overrideWithValue(fake)],
      );
      addTearDown(container.dispose);

      final listenable = container.read(connStateProvider);
      expect(listenable.value, ConnState.disconnected);

      fake.emit(ConnState.connecting);
      expect(listenable.value, ConnState.connecting);
      fake.emit(ConnState.ready);
      expect(listenable.value, ConnState.ready);
      fake.emit(ConnState.running);
      expect(listenable.value, ConnState.running);
    });

    test('selectedSurfaceProvider defaults to AppSurface.connect', () {
      final container = ProviderContainer(
        overrides: <Override>[
          connectionProvider.overrideWithValue(FakeConnection()),
        ],
      );
      addTearDown(container.dispose);
      expect(container.read(selectedSurfaceProvider), AppSurface.connect);
    });

    test('ConnState is the frozen four-value enum (app.md §3 / TDD §5.2)', () {
      expect(ConnState.values, <ConnState>[
        ConnState.disconnected,
        ConnState.connecting,
        ConnState.ready,
        ConnState.running,
      ]);
    });

    test(
      'AppSurface includes Blocks as the stacked visual-workspace surface',
      () {
        expect(AppSurface.values, <AppSurface>[
          AppSurface.connect,
          AppSurface.editor,
          AppSurface.console,
          AppSurface.files,
          AppSurface.blocks,
        ]);
      },
    );

    test('landscape secondary pane defaults to Pins', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      expect(
        container.read(selectedRightPaneSurfaceProvider),
        RightPaneSurface.pins,
      );
    });
  });
}
