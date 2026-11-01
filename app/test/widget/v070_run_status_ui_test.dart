// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/pble/pble.dart';

import '../support/fake_readiness_seam.dart';
import '../support/feature_harness.dart';

class _StatusConnection extends FakeConnection
    implements ConnectionRunStatusSource {
  _StatusConnection({
    required RunSnapshot? snapshot,
    super.initial = ConnState.ready,
  }) : runSnapshot = ValueNotifier<RunSnapshot?>(snapshot);

  @override
  final ValueNotifier<RunSnapshot?> runSnapshot;

  @override
  Future<RunSnapshot> refreshRunStatus() async => runSnapshot.value!;
}

const RunSnapshot _failed = RunSnapshot(
  bootId: '0102030405060708',
  runId: 1,
  revision: 3,
  state: RunState.error,
  origin: RunOrigin.file,
  terminalReason: RunTerminalReason.exception,
);

void main() {
  testWidgets(
    'console mounted after handshake displays cached terminal status',
    (tester) async {
      final _StatusConnection board = _StatusConnection(snapshot: _failed);
      addTearDown(board.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: board);
      expect(find.text(l10nOf(tester).runStateError), findsOneWidget);
      expect(find.text(l10nOf(tester).runStateIdle), findsNothing);
    },
  );

  testWidgets(
    'connecting has no false idle badge before status synchronization',
    (tester) async {
      final _StatusConnection board = _StatusConnection(
        snapshot: null,
        initial: ConnState.connecting,
      );
      addTearDown(board.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: board);
      expect(find.text(l10nOf(tester).connStatusConnecting), findsOneWidget);
      expect(find.text(l10nOf(tester).runStateIdle), findsNothing);
    },
  );

  test(
    'stable facade captures an already synchronized board and clears on detach',
    () async {
      final _StatusConnection board = _StatusConnection(snapshot: _failed);
      final PbleConnectionManager manager = PbleConnectionManager(
        scanner: FakeScanner(),
        readiness: FakeSeamReadiness(BleReadiness.ready),
        connectionFactory: (_) async => board,
      );
      addTearDown(manager.dispose);
      await manager.connect('board');
      final ConnectionRunStatusSource facade =
          manager.connection as ConnectionRunStatusSource;
      expect(facade.runSnapshot.value, _failed);
      final RunSnapshot running = RunSnapshot(
        bootId: _failed.bootId,
        runId: 2,
        revision: 4,
        state: RunState.running,
        origin: RunOrigin.autorun,
        terminalReason: RunTerminalReason.none,
      );
      board.runSnapshot.value = running;
      expect(facade.runSnapshot.value, running);
      await manager.disconnect();
      expect(facade.runSnapshot.value, isNull);
    },
  );
}
