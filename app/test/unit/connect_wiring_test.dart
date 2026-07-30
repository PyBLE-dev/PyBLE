// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-22 [red] — the runtime-connection wiring shift (frozen contract ADR-0009,
// TDD §5.2/§7.1). The single override point moves from connectionProvider to
// connectionManagerProvider; connectionProvider is now DERIVED from the manager's
// stable facade, so every existing widget that reads connectionProvider /
// connStateProvider keeps working (the seam is preserved, CON-8).
//
//   connectionManagerProvider  → throw-until-overridden (the new root seam)
//   connectionProvider         → ref.watch(connectionManagerProvider).connection
//   connStateProvider          → ref.watch(connectionProvider).state  (unchanged)
//
// Also pins app_info.dart: the ASCII HELLO wire ids used by the production
// PbleConnectionManager (FR-I18N-4, BLD-2 — no package_info_plus).
//
// CURRENTLY RED: providers.dart has no connectionManagerProvider (still
// throw-until-overridden connectionProvider), and lib/app/app_info.dart does not
// exist; lib/pble has no PbleConnectionManager. HAND-OFF: lib/app → app-architect;
// lib/pble → app-protocol-engineer.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app_info.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

import '../support/fake_readiness_seam.dart';

PbleConnectionManager _fakeManager() => PbleConnectionManager(
  scanner: FakeScanner(),
  readiness: FakeSeamReadiness(),
  connectionFactory: (String id) async =>
      FakeConnection(initial: ConnState.ready),
);

void main() {
  group('A-22 root injection moves to connectionManagerProvider', () {
    test('connectionManagerProvider MUST be overridden at the root', () {
      final ProviderContainer container = ProviderContainer();
      addTearDown(container.dispose);
      expect(
        () => container.read(connectionManagerProvider),
        throwsA(isA<UnimplementedError>()),
        reason: 'the manager is the sole root seam — never a hidden default',
      );
    });

    test('connectionProvider derives from the manager stable facade', () {
      final PbleConnectionManager manager = _fakeManager();
      addTearDown(manager.dispose);
      final ProviderContainer container = ProviderContainer(
        overrides: <Override>[
          connectionManagerProvider.overrideWithValue(manager),
        ],
      );
      addTearDown(container.dispose);

      // connectionProvider is the manager's ONE facade, not a fresh object.
      expect(
        identical(container.read(connectionProvider), manager.connection),
        isTrue,
      );
      // connStateProvider stays derived off Connection.state (unchanged seam).
      expect(
        identical(container.read(connStateProvider), manager.connection.state),
        isTrue,
      );
      expect(container.read(connStateProvider).value, ConnState.disconnected);
    });

    test(
      'reading connectionProvider with no override still throws (via manager)',
      () {
        final ProviderContainer container = ProviderContainer();
        addTearDown(container.dispose);
        expect(
          () => container.read(connectionProvider),
          throwsA(isA<UnimplementedError>()),
          reason:
              'derived from the un-overridden manager → propagates the throw',
        );
      },
    );
  });

  group('A-22 app_info exposes ASCII HELLO wire ids (FR-I18N-4, BLD-2)', () {
    test('kAppName is the wordmark, ASCII', () {
      expect(kAppName, 'PyBLE');
      expect(kAppName.codeUnits.every((int c) => c < 128), isTrue);
    });

    test('kAppVersion is a non-empty ASCII version string', () {
      expect(kAppVersion, isNotEmpty);
      expect(kAppVersion.codeUnits.every((int c) => c < 128), isTrue);
      expect(kAppVersion, matches(RegExp(r'^\d+\.\d+\.\d+')));
    });
  });
}
