// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: the A-05 shell harness — drives the app shell against a
// scripted FakeConnection through the frozen Connection seam, and the
// device-surface matrix for responsive widget + platform-parity golden tests.
//
// Owner: app-test-author. This is the SCAFFOLD that SCRIPTS FakeConnection; the
// FakeConnection class itself is production (`lib/pble/fake_connection.dart`,
// owner app-protocol-engineer). The shell + providers are `lib/app/**` (owner
// app-architect). Until both land, importers of this file compile-fail — the
// intended A-05 [red].

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/pble/pble.dart';

import 'fake_readiness_seam.dart';

/// A named device surface (logical size + DPR) for responsive + golden tests.
/// Platform parity rides every milestone: iPad AND Android, landscape AND
/// portrait, plus a phone breakpoint (NFR-COMPAT-1, FR-UI-1/2/5).
class ShellSurface {
  const ShellSurface(this.name, this.size, this.devicePixelRatio);
  final String name;
  final Size size;
  final double devicePixelRatio;
}

const ShellSurface ipadLandscape = ShellSurface(
  'ipad_landscape',
  Size(1366, 1024),
  2.0,
);
const ShellSurface ipadPortrait = ShellSurface(
  'ipad_portrait',
  Size(1024, 1366),
  2.0,
);
const ShellSurface androidTabletLandscape = ShellSurface(
  'android_tablet_landscape',
  Size(1280, 800),
  2.0,
);
const ShellSurface androidTabletPortrait = ShellSurface(
  'android_tablet_portrait',
  Size(800, 1280),
  2.0,
);
const ShellSurface phonePortrait = ShellSurface(
  'phone_portrait',
  Size(390, 844),
  3.0,
);

/// The full platform-parity golden matrix (en).
const List<ShellSurface> parityMatrix = <ShellSurface>[
  ipadLandscape,
  ipadPortrait,
  androidTabletLandscape,
  androidTabletPortrait,
  phonePortrait,
];

/// The four shell navigation destinations (FR-UI). Frozen shell contract.
const List<String> navDestinations = <String>[
  'Connect',
  'Editor',
  'Console',
  'Files',
  'Blocks',
];

/// Builds a scriptable [DeviceInfo]. `deviceId`/`label` are DISPLAY-ONLY and
/// never gate access (SEC-9) — the shell must render with them empty.
DeviceInfo fakeDeviceInfo({
  String chip = 'esp32-s3',
  String mpyVersion = '1.28.0',
  int freeMem = 48000,
  String fsRoot = '/',
  String deviceId = '',
  String label = '',
}) => DeviceInfo(
  chip: chip,
  mpyVersion: mpyVersion,
  freeMem: freeMem,
  fsRoot: fsRoot,
  deviceId: deviceId,
  label: label,
);

/// A scripted [FakeConnection] in a given initial [ConnState].
FakeConnection fakeConnection({
  ConnState initial = ConnState.disconnected,
  DeviceInfo? info,
}) => FakeConnection(initial: initial, deviceInfo: info);

/// Pumps the real [PybleApp] shell at [surface], with the Connection seam
/// overridden by a scripted [connection]. Resets the view on teardown.
///
/// A-22 runtime-manager shift: the shell's Connect surface (in the layout's
/// `IndexedStack`) is now the real `ConnectScreen`, which reads
/// [connectionManagerProvider]. So the harness ALSO injects a runtime
/// [PbleConnectionManager] built from pure neutral fakes (a [FakeScanner] +
/// seam-clean readiness + a factory returning the same [connection]) — still NO
/// radio, NO BleLink. The chrome (pill/toolbar/nav) keeps reading the scripted
/// [connection] via the [connectionProvider] override, so every existing shell
/// assertion holds unchanged.
Future<void> pumpShell(
  WidgetTester tester, {
  required FakeConnection connection,
  ShellSurface surface = ipadLandscape,
}) async {
  tester.view.devicePixelRatio = surface.devicePixelRatio;
  tester.view.physicalSize = surface.size * surface.devicePixelRatio;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final PbleConnectionManager manager = PbleConnectionManager(
    scanner: FakeScanner(),
    readiness: FakeSeamReadiness(),
    connectionFactory: (String id) async => connection,
  );
  addTearDown(manager.dispose);

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        connectionManagerProvider.overrideWithValue(manager),
        // The chrome binds to the scripted state directly; this override wins for
        // connectionProvider (and its derived connStateProvider).
        connectionProvider.overrideWithValue(connection),
        // Host/golden tests exercise native chrome, not an Android/iOS platform
        // view. Real WebView parity belongs to on-device integration coverage.
        blocksWorkspaceBuilderProvider.overrideWithValue(
          (Key key) => SizedBox.expand(key: key),
        ),
      ],
      child: const PybleApp(),
    ),
  );
  await tester.pumpAndSettle();
}
