// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE app entry point — the `ProviderScope` root and the single runtime-
/// session injection site (A-05 / A-22, ADR-0009, D1/D3, CON-8).
///
/// Production wires the REAL BLE stack: [PbleConnectionManager.production] builds
/// the `flutter_blue_plus` adapter (scan + connect) + platform readiness INSIDE
/// `lib/pble`, so `main.dart` names no `lib/ble` transport type (the import-
/// boundary gate scans this file too). Every surface below binds only to the
/// neutral [Connection] / [ConnectionManager] seam via the app providers — no
/// widget knows the radio.
///
/// Tests never reach this file: the shell/connect harnesses override
/// `connectionManagerProvider` (and, for chrome, `connectionProvider`) with a
/// manager wired from neutral fakes — no radio, no `BleLink`.
library;

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/app.dart';
import 'package:pyble/app/app_info.dart';
import 'package:pyble/app/licenses.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

void main() {
  // The production manager constructs the fbp stack whose readiness/scan/connect
  // touch platform channels the moment the UI reads them; ensure the binding is
  // up first (defensive — construction itself is channel-free).
  WidgetsFlutterBinding.ensureInitialized();
  registerBundledLicenses();
  runApp(
    ProviderScope(
      overrides: <Override>[
        // The REAL runtime session (ADR-0009). `.production` builds
        // FbpBleAdapter + FbpBleReadinessSource + the accumulating Scanner and
        // the `PbleConnection.fromLink` connect factory internally, so the
        // transport stays sealed inside lib/pble. HELLO carries the ASCII wire
        // ids (FR-I18N-4). connectionProvider/connStateProvider derive from this
        // manager's stable facade and now reflect the LIVE connection state.
        connectionManagerProvider.overrideWithValue(
          PbleConnectionManager.production(
            appName: kAppName,
            appVersion: kAppVersion,
          ),
        ),
      ],
      child: const PybleApp(),
    ),
  );
}
