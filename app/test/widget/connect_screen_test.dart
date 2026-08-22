// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-22 [red] — the lib/connect ConnectScreen flow, driven end-to-end against the
// runtime ConnectionManager through the SEAM ONLY (FakeScanner + FakeSeamReadiness
// + a ConnectionFactory → FakeConnection). This test imports NO `lib/ble` type,
// directly or transitively (HARD INVARIANT #1, CON-8, FR-BLE-8): the compile path
// proves the Connect surface binds only to the neutral seam.
//
// Renders (Signal design system, frozen contract ADR-0009 §3):
//   readiness banner (adapter-off/unauthorized/unsupported + localized rationale)
//   → scan CTA → live ScanHit list (name + RSSI) → connecting indicator →
//   connected Board-info card (board ID / PyBLE firmware / chip / MicroPython /
//   free-mem = the PROOF) → disconnect; an error state; and a live diagnostics
//   panel for HIL debugging.
//
// NEVER pumpAndSettle: a scanning/connecting progress indicator animates forever
// and would time out; pump explicit frames after each scripted transition.
//
// CURRENTLY RED: lib/connect has no ConnectScreen / connectControllerProvider;
// lib/pble has no scan/manager seam; lib/app has no connectionManagerProvider.
// Pinned interactive KEYS the connect UI must expose (for tests + HIL):
//   ValueKey('connectScanButton'), ValueKey('connectStopButton'),
//   ValueKey('connectHit_<id>')   (one per listed board),
//   ValueKey('connectDisconnectButton').
// HAND-OFF: lib/connect → app-connect-engineer; lib/pble → app-protocol-engineer;
// lib/app → app-architect.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/connect_harness.dart';

const ScanHit _hitA = ScanHit(id: 'dev-a', name: 'PyBLE-A', rssi: -48);
const ScanHit _hitB = ScanHit(id: 'dev-b', name: 'PyBLE-B', rssi: -73);

const Key _scanKey = ValueKey<String>('connectScanButton');
const Key _stopKey = ValueKey<String>('connectStopButton');
const Key _disconnectKey = ValueKey<String>('connectDisconnectButton');
Key _hitKey(String id) => ValueKey<String>('connectHit_$id');

/// The `en` strings under test — resolved once the widget tree exists.
AppLocalizations _l10n(WidgetTester tester) =>
    AppLocalizations.of(tester.element(find.byType(Scaffold)));

void main() {
  group('A-22 ConnectScreen — readiness banners', () {
    testWidgets(
      'adapter-off shows the enable-Bluetooth rationale, no scan CTA',
      (WidgetTester tester) async {
        final ConnectRig rig = ConnectRig(readiness: BleReadiness.adapterOff);
        addTearDown(rig.dispose);
        await pumpConnect(tester, rig);

        final AppLocalizations l10n = _l10n(tester);
        expect(find.text(l10n.connectAdapterOffTitle), findsOneWidget);
        expect(find.text(l10n.connectAdapterOffDetail), findsOneWidget);
        expect(
          find.byKey(_scanKey),
          findsNothing,
          reason: 'cannot scan while the adapter is off',
        );
      },
    );

    testWidgets('unauthorized shows the permission rationale', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig(readiness: BleReadiness.unauthorized);
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      expect(find.text(_l10n(tester).connectUnauthorizedTitle), findsOneWidget);
    });

    testWidgets('unsupported shows the no-radio rationale', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig(readiness: BleReadiness.unsupported);
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      expect(find.text(_l10n(tester).connectUnsupportedTitle), findsOneWidget);
    });
  });

  group('A-22 ConnectScreen — scan', () {
    testWidgets('ready+idle offers the scan CTA; tapping starts a scan', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      expect(find.byKey(_scanKey), findsOneWidget);
      expect(find.text(_l10n(tester).connectScanCta), findsOneWidget);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();

      expect(
        rig.scanner.scanning,
        isTrue,
        reason: 'the CTA drives ConnectionManager.startScan → Scanner.scan',
      );
      expect(find.text(_l10n(tester).connectScanning), findsOneWidget);
      expect(find.byKey(_stopKey), findsOneWidget);
    });

    testWidgets('live scan results render each board name + RSSI', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();

      rig.scanner.emit(<ScanHit>[_hitA, _hitB]);
      await tester.pump();

      final AppLocalizations l10n = _l10n(tester);
      expect(find.text(_hitA.name), findsOneWidget);
      expect(find.text(_hitB.name), findsOneWidget);
      expect(find.text(l10n.connectRssiDbm(_hitA.rssi)), findsOneWidget);
      expect(find.text(l10n.connectRssiDbm(_hitB.rssi)), findsOneWidget);
      expect(find.byKey(_hitKey(_hitA.id)), findsOneWidget);
    });
  });

  group('A-22 ConnectScreen — connect / connected / disconnect', () {
    testWidgets('tapping a board connects and shows the connecting indicator', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA]);
      await tester.pump();

      await tester.tap(find.byKey(_hitKey(_hitA.id)));
      await tester.pump();

      expect(
        rig.connectCalls,
        1,
        reason: 'tapping a board drives ConnectionManager.connect(id)',
      );
      expect(rig.lastConnectId, _hitA.id);
      expect(
        find.text(_l10n(tester).connectConnecting(_hitA.name)),
        findsOneWidget,
      );
    });

    testWidgets('a completed handshake shows the Board-info PROOF card', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA]);
      await tester.pump();
      await tester.tap(find.byKey(_hitKey(_hitA.id)));
      await tester.pump();

      // HELLO completes on the board → the live DeviceInfo proves the round-trip.
      rig.board.emit(ConnState.ready);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      final AppLocalizations l10n = _l10n(tester);
      expect(find.text(l10n.connectDeviceInfoTitle), findsOneWidget);
      expect(find.text(l10n.connectDeviceBoardId), findsOneWidget);
      expect(
        find.text('5646'),
        findsOneWidget,
        reason: 'the PBLE/1 board ID is rendered verbatim',
      );
      expect(
        find.text(_hitA.id),
        findsNothing,
        reason: 'the platform scan identifier is never exposed as Board ID',
      );
      expect(find.text(l10n.connectDeviceAgentVersion), findsOneWidget);
      expect(
        find.text('0.6.0'),
        findsOneWidget,
        reason: 'the PyBLE agent firmware version is rendered verbatim',
      );
      expect(
        find.text('esp32-s3'),
        findsOneWidget,
        reason: 'chip is a technical identifier, rendered verbatim',
      );
      expect(find.text('1.28.0'), findsOneWidget);
      expect(find.text(l10n.connectFreeMemBytes(48000)), findsOneWidget);
      expect(find.byKey(_disconnectKey), findsOneWidget);
    });

    testWidgets('missing identity metadata is reported without gating use', (
      WidgetTester tester,
    ) async {
      final FakeConnection board = FakeConnection(
        initial: ConnState.connecting,
        deviceInfo: connectedBoardInfo(deviceId: '', agentVersion: ''),
      );
      final ConnectRig rig = ConnectRig(board: board);
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA]);
      await tester.pump();
      await tester.tap(find.byKey(_hitKey(_hitA.id)));
      await tester.pump();

      board.emit(ConnState.ready);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      final AppLocalizations l10n = _l10n(tester);
      expect(find.text(l10n.connectDeviceBoardId), findsOneWidget);
      expect(find.text(l10n.connectDeviceAgentVersion), findsOneWidget);
      expect(find.text(l10n.connectDeviceNotReported), findsNWidgets(2));
      expect(
        find.byKey(_disconnectKey),
        findsOneWidget,
        reason: 'missing additive metadata must not gate the connection',
      );
    });

    testWidgets('disconnect returns to the scan state', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA]);
      await tester.pump();
      await tester.tap(find.byKey(_hitKey(_hitA.id)));
      await tester.pump();
      rig.board.emit(ConnState.ready);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      await tester.tap(find.byKey(_disconnectKey));
      await tester.pump();

      expect(rig.manager.connection.state.value, ConnState.disconnected);
      expect(find.byKey(_disconnectKey), findsNothing);
      expect(find.byKey(_scanKey), findsOneWidget);
    });
  });

  group('A-22 ConnectScreen — failure + diagnostics', () {
    testWidgets('a connect failure surfaces the localized error + details', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig(
        connectionFactory: (String id) async =>
            throw const BleLinkException('link dropped mid-handshake'),
      );
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA]);
      await tester.pump();
      await tester.tap(find.byKey(_hitKey(_hitA.id)));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      final AppLocalizations l10n = _l10n(tester);
      expect(find.text(l10n.connectFailed), findsOneWidget);
      expect(find.text(l10n.connectErrorDetailLabel), findsOneWidget);
    });

    testWidgets('the diagnostics panel shows adapter state + hit count', (
      WidgetTester tester,
    ) async {
      final ConnectRig rig = ConnectRig();
      addTearDown(rig.dispose);
      await pumpConnect(tester, rig);

      final AppLocalizations l10n = _l10n(tester);
      expect(find.text(l10n.connectDiagnosticsTitle), findsOneWidget);
      expect(
        find.text(l10n.connectDiagAdapterOn),
        findsOneWidget,
        reason: 'ready adapter reads On in diagnostics',
      );

      await tester.tap(find.byKey(_scanKey));
      await tester.pump();
      rig.scanner.emit(<ScanHit>[_hitA, _hitB]);
      await tester.pump();

      expect(
        find.text(l10n.connectDiagHitCount(2)),
        findsOneWidget,
        reason: 'diagnostics counts the boards seen this scan',
      );
    });
  });
}
