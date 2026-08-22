// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-22 [red] — the runtime ConnectionManager: the session orchestration that
// holds the ACTIVE connection which changes at runtime (frozen contract
// ADR-0009, TDD §4.8/§5.2/§6.2). Drives disconnected → scanning → connecting →
// connected → disconnected off PURE NEUTRAL FAKES (FakeScanner + FakeSeamReadiness
// + a ConnectionFactory returning a FakeConnection) — NO radio, NO BleLink.
//
// Frozen invariants pinned here:
//   * ConnectPhase is the SESSION phase (idle/scanning/connecting/connected/
//     failed) — NEVER conflated with the 4-value ConnState;
//   * `manager.connection` is ONE stable-facade object whose identity never
//     changes across scan/connect/disconnect;
//   * verbs delegate to the live board when connected; otherwise throw a TYPED
//     not-connected error (never a silent success) — pinned as
//     NotConnectedException;
//   * connect(id) runs factory(id) → publishes the Connection → phase tracks the
//     board's ConnState (connecting → connected); a factory failure → phase
//     failed + lastError set;
//   * readiness (adapterOff/unauthorized/unsupported) is surfaced, never swallowed.
//
// CURRENTLY RED: `lib/pble` has no `connection_manager.dart`
// (ConnectionManager/PbleConnectionManager/ConnectPhase/ConnectionFactory), no
// `scanner.dart`, and the barrel does not re-export BleReadinessSource, nor does
// `pble_exception.dart` define NotConnectedException. HAND-OFF: all of `lib/pble`
// → app-protocol-engineer. This suite is the acceptance contract.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/pble.dart';

import '../support/fake_readiness_seam.dart';

const ScanHit _hitA = ScanHit(id: 'dev-a', name: 'PyBLE-A', rssi: -48);
const ScanHit _hitB = ScanHit(id: 'dev-b', name: 'PyBLE-B', rssi: -73);

/// A manager wired to neutral fakes. Returns the fakes so a test can drive them.
({
  PbleConnectionManager manager,
  FakeScanner scanner,
  FakeSeamReadiness readiness,
  FakeConnection board,
  List<String> factoryIds,
})
_rig({
  BleReadiness readiness = BleReadiness.ready,
  FakeConnection? board,
  ConnectionFactory? factory,
}) {
  final FakeScanner scanner = FakeScanner();
  final FakeSeamReadiness src = FakeSeamReadiness(readiness);
  final FakeConnection b =
      board ??
      FakeConnection(
        initial: ConnState.connecting,
        deviceInfo: const DeviceInfo(
          chip: 'esp32-s3',
          mpyVersion: '1.28.0',
          freeMem: 48000,
          fsRoot: '/',
        ),
      );
  final List<String> ids = <String>[];
  final PbleConnectionManager manager = PbleConnectionManager(
    scanner: scanner,
    readiness: src,
    connectionFactory:
        factory ??
        (String id) async {
          ids.add(id);
          return b;
        },
  );
  return (
    manager: manager,
    scanner: scanner,
    readiness: src,
    board: b,
    factoryIds: ids,
  );
}

void main() {
  group('A-22 ConnectionManager — initial state', () {
    test('starts idle with a disconnected stable facade', () async {
      final r = _rig();
      addTearDown(r.manager.dispose);

      expect(r.manager.phase.value, ConnectPhase.idle);
      expect(r.manager.connection.state.value, ConnState.disconnected);
      expect(r.manager.selected, isNull);
      expect(r.manager.lastError, isNull);
    });

    test('surfaces the injected readiness', () async {
      final r = _rig(readiness: BleReadiness.adapterOff);
      addTearDown(r.manager.dispose);
      expect(r.manager.readiness.current, BleReadiness.adapterOff);
    });
  });

  group('A-22 ConnectionManager — scan', () {
    test(
      'startScan → phase scanning; scanResults forwards snapshots',
      () async {
        final r = _rig();
        addTearDown(r.manager.dispose);

        final Future<void> expectation = expectLater(
          r.manager.scanResults,
          emits(<ScanHit>[_hitA, _hitB]),
        );
        await r.manager.startScan(timeout: const Duration(seconds: 8));
        expect(r.manager.phase.value, ConnectPhase.scanning);
        expect(r.scanner.scanning, isTrue);

        r.scanner.emit(<ScanHit>[_hitA, _hitB]);
        await expectation;
      },
    );

    test('stopScan → phase back to idle; scanner stopped', () async {
      final r = _rig();
      addTearDown(r.manager.dispose);

      await r.manager.startScan();
      await r.manager.stopScan();

      expect(r.manager.phase.value, ConnectPhase.idle);
      expect(r.scanner.scanning, isFalse);
      expect(r.scanner.stopScanCount, greaterThanOrEqualTo(1));
    });
  });

  group('A-22 ConnectionManager — connect / disconnect', () {
    test(
      'connect publishes a board and tracks connecting → connected',
      () async {
        final r = _rig();
        addTearDown(r.manager.dispose);

        final Object facadeBefore = r.manager.connection;

        await r.manager.connect(_hitA.id);
        expect(
          r.factoryIds,
          <String>[_hitA.id],
          reason: 'the factory builds the live board from the chosen id',
        );
        expect(r.manager.selected?.id, _hitA.id);
        // The board is mid-handshake → the facade reads connecting.
        expect(r.manager.phase.value, ConnectPhase.connecting);
        expect(r.manager.connection.state.value, ConnState.connecting);

        // HELLO completes on the board → phase resolves to connected.
        r.board.emit(ConnState.ready);
        await pumpEventQueue();
        expect(r.manager.phase.value, ConnectPhase.connected);
        expect(r.manager.connection.state.value, ConnState.ready);

        // The facade is ONE object across the whole session (FR-CONN-6).
        expect(identical(facadeBefore, r.manager.connection), isTrue);
      },
    );

    test('a connected facade delegates verbs to the live board', () async {
      final r = _rig();
      addTearDown(r.manager.dispose);

      await r.manager.connect(_hitA.id);
      r.board.emit(ConnState.ready);
      await pumpEventQueue();

      final DeviceInfo info = await r.manager.connection.deviceInfo();
      expect(info.chip, 'esp32-s3');
      expect(info.freeMem, 48000);
    });

    test(
      'disconnect tears the session back down to idle/disconnected',
      () async {
        final r = _rig();
        addTearDown(r.manager.dispose);

        await r.manager.connect(_hitA.id);
        r.board.emit(ConnState.ready);
        await pumpEventQueue();

        await r.manager.disconnect();
        await pumpEventQueue();
        expect(r.manager.connection.state.value, ConnState.disconnected);
        expect(r.manager.phase.value, ConnectPhase.idle);
      },
    );

    test('local session stamp changes on every detach and reattach', () async {
      final FakeConnection first = FakeConnection(
        initial: ConnState.connecting,
      );
      final FakeConnection second = FakeConnection(initial: ConnState.ready);
      int connectionCount = 0;
      final r = _rig(
        board: first,
        factory: (String id) async => connectionCount++ == 0 ? first : second,
      );
      addTearDown(r.manager.dispose);
      final Connection facade = r.manager.connection;
      final Object idleStamp = connectionSessionStampOf(facade);

      await r.manager.connect(_hitA.id);
      final Object firstAttachStamp = connectionSessionStampOf(facade);
      expect(identical(firstAttachStamp, idleStamp), isFalse);

      first.emit(ConnState.ready);
      await pumpEventQueue();
      expect(
        identical(connectionSessionStampOf(facade), firstAttachStamp),
        isTrue,
        reason: 'ordinary state changes stay inside the same attachment',
      );

      await r.manager.disconnect();
      final Object detachedStamp = connectionSessionStampOf(facade);
      expect(identical(detachedStamp, firstAttachStamp), isFalse);

      await r.manager.connect(_hitA.id);
      expect(
        identical(connectionSessionStampOf(facade), detachedStamp),
        isFalse,
        reason: 'reattaching the same device id is a new local session',
      );
    });

    test(
      'local session stamp rotates once when an attached link reconnects',
      () async {
        final r = _rig();
        addTearDown(r.manager.dispose);
        final Connection facade = r.manager.connection;

        await r.manager.connect(_hitA.id);
        r.board.emit(ConnState.ready);
        await pumpEventQueue();
        final Object establishedStamp = connectionSessionStampOf(facade);

        r.board.emit(ConnState.running);
        r.board.emit(ConnState.ready);
        await pumpEventQueue();
        expect(
          identical(connectionSessionStampOf(facade), establishedStamp),
          isTrue,
          reason: 'ordinary ready/running transitions retain one link session',
        );

        r.board.emit(ConnState.connecting);
        await pumpEventQueue();
        final Object successorStamp = connectionSessionStampOf(facade);
        expect(identical(successorStamp, establishedStamp), isFalse);

        r.board.emit(ConnState.disconnected);
        r.board.emit(ConnState.connecting);
        r.board.emit(ConnState.ready);
        await pumpEventQueue();
        expect(
          identical(connectionSessionStampOf(facade), successorStamp),
          isTrue,
          reason: 'one departure rotates once for the complete reconnect',
        );

        r.board.emit(ConnState.disconnected);
        await pumpEventQueue();
        expect(
          identical(connectionSessionStampOf(facade), successorStamp),
          isFalse,
          reason: 'a later established-session departure rotates again',
        );
      },
    );
  });

  group('A-22 ConnectionManager — not-connected + failure', () {
    test('facade verbs throw a typed not-connected error while idle', () async {
      final r = _rig();
      addTearDown(r.manager.dispose);

      // Never a silent success: reading device info off a disconnected facade
      // surfaces a TYPED error (frozen stable-facade rule).
      await expectLater(
        r.manager.connection.deviceInfo(),
        throwsA(isA<NotConnectedException>()),
      );
      await expectLater(
        r.manager.connection.runFile('/main.py'),
        throwsA(isA<NotConnectedException>()),
      );
    });

    test(
      'a factory failure → phase failed + lastError (no throw swallowed)',
      () async {
        final r = _rig(
          factory: (String id) async => throw const BleLinkException('boom'),
        );
        addTearDown(r.manager.dispose);

        // Whether connect() rethrows or reports via state, the FAILURE must land.
        try {
          await r.manager.connect('dev-x');
        } on Object {
          // tolerated — the observable outcome is asserted below
        }
        expect(r.manager.phase.value, ConnectPhase.failed);
        expect(r.manager.lastError, isA<BleLinkException>());
      },
    );
  });

  group('A-22 ConnectionManager — readiness stream', () {
    test(
      'reflects adapterOff / unauthorized / unsupported transitions',
      () async {
        final r = _rig();
        addTearDown(r.manager.dispose);

        r.readiness.emit(BleReadiness.unauthorized);
        await pumpEventQueue();
        expect(r.manager.readiness.current, BleReadiness.unauthorized);

        r.readiness.emit(BleReadiness.unsupported);
        await pumpEventQueue();
        expect(r.manager.readiness.current, BleReadiness.unsupported);

        r.readiness.emit(BleReadiness.ready);
        await pumpEventQueue();
        expect(r.manager.readiness.current, BleReadiness.ready);
      },
    );
  });
}
