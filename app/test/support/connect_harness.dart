// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support (A-22): the "make Connect real" harness. Builds a runtime
// ConnectionManager from PURE NEUTRAL FAKES (no radio, no BleLink) and pumps the
// lib/connect ConnectScreen against it through the seam ONLY.
//
// Owner: app-test-author. This SCRIPTS the shipped doubles (FakeScanner,
// FakeConnection) and the seam-clean FakeSeamReadiness; it does NOT implement any
// production type. Every import here resolves through `package:pyble/pble/…`,
// `package:pyble/connect/…`, `package:pyble/localization/…`, and
// `package:pyble/theme/…` — never `lib/ble` (HARD INVARIANT #1, CON-8).
//
// CURRENTLY RED until the A-22 seam + UI land:
//   * lib/pble: ScanHit, Scanner/FakeScanner, ConnectionManager/
//     PbleConnectionManager, ConnectPhase, ConnectionFactory, and the barrel
//     re-export of BleReadinessSource → app-protocol-engineer;
//   * lib/connect: ConnectScreen + connectControllerProvider → app-connect-engineer;
//   * lib/app: connectionManagerProvider → app-architect.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/connect/connect.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'fake_readiness_seam.dart';

/// A representative advertised board (label else PyBLE-XXXX + RSSI, retyped 1:1
/// off a BLE advertisement).
ScanHit hit({
  String id = 'dev-1',
  String name = 'PyBLE-8F3A',
  int rssi = -52,
}) => ScanHit(id: id, name: name, rssi: rssi);

/// A scripted [DeviceInfo] used as the PROOF payload on the connected card.
DeviceInfo connectedBoardInfo({
  String chip = 'esp32-s3',
  String mpyVersion = '1.28.0',
  int freeMem = 48000,
  String fsRoot = '/',
  String deviceId = '5646',
  String agentVersion = '0.6.0',
}) => DeviceInfo(
  chip: chip,
  mpyVersion: mpyVersion,
  freeMem: freeMem,
  fsRoot: fsRoot,
  deviceId: deviceId,
  agentVersion: agentVersion,
);

/// The neutral fakes bound into one runtime [ConnectionManager], so a test can
/// drive scan/readiness/board transitions and observe the UI react.
class ConnectRig {
  ConnectRig({
    BleReadiness readiness = BleReadiness.ready,
    FakeConnection? board,
    ConnectionFactory? connectionFactory,
  }) : scanner = FakeScanner(),
       readinessSource = FakeSeamReadiness(readiness),
       board =
           board ??
           FakeConnection(
             initial: ConnState.connecting,
             deviceInfo: connectedBoardInfo(),
           ) {
    manager = PbleConnectionManager(
      scanner: scanner,
      readiness: readinessSource,
      connectionFactory:
          connectionFactory ??
          (String id) async {
            connectCalls++;
            lastConnectId = id;
            return this.board;
          },
    );
  }

  final FakeScanner scanner;
  final FakeSeamReadiness readinessSource;
  final FakeConnection board;
  late final PbleConnectionManager manager;

  int connectCalls = 0;
  String? lastConnectId;

  Future<void> dispose() async {
    await manager.dispose();
    await readinessSource.dispose();
  }
}

/// Pumps the real [ConnectScreen] against [rig]'s manager through the seam.
///
/// Uses a plain [MaterialApp] (localization delegates + the Signal theme) and
/// overrides ONLY [connectionManagerProvider] — the connect controller + every
/// derived provider is exercised for real. NEVER call `pumpAndSettle` here: a
/// scanning/connecting progress indicator animates forever and would time out;
/// use explicit `pump()` frames after each scripted transition.
Future<void> pumpConnect(WidgetTester tester, ConnectRig rig) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        connectionManagerProvider.overrideWithValue(rig.manager),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: PybleTheme.light,
        home: const Scaffold(body: ConnectScreen()),
      ),
    ),
  );
  await tester.pump();
}
