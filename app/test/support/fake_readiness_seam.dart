// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support (A-22): a SEAM-CLEAN scriptable BleReadinessSource double.
//
// Unlike test/support/fake_readiness.dart (A-04) — which reaches BleReadiness /
// BleReadinessSource through `package:pyble/ble/ble.dart` — this double resolves
// both types EXCLUSIVELY through the `lib/pble` barrel. That is the whole point:
// the "make Connect real" ConnectionManager + ConnectScreen suites must prove
// they bind to the neutral seam ONLY, so nothing they import (transitively
// included) may reach `lib/ble` (HARD INVARIANT #1, CON-8, FR-BLE-8).
//
// CURRENTLY RED: the barrel re-exports `BleReadiness` but NOT yet
// `BleReadinessSource`. The frozen A-22 contract adds
//   export '../ble/ble_readiness.dart' show BleReadiness, BleReadinessSource;
// to lib/pble/pble.dart. Until that lands this file compile-fails — the intended
// [red]. HAND-OFF: `lib/pble/pble.dart` barrel → app-protocol-engineer.

import 'dart:async';

import 'package:pyble/pble/pble.dart';

/// A scriptable [BleReadinessSource] resolved through the neutral seam. Drive it
/// with [emit]; seed the starting value via the constructor.
class FakeSeamReadiness implements BleReadinessSource {
  FakeSeamReadiness([this._current = BleReadiness.ready]);

  final StreamController<BleReadiness> _controller =
      StreamController<BleReadiness>.broadcast();
  BleReadiness _current;

  @override
  BleReadiness get current => _current;

  @override
  Stream<BleReadiness> get readiness => _controller.stream;

  /// Scripts a readiness transition (updates [current] and notifies listeners).
  void emit(BleReadiness value) {
    _current = value;
    _controller.add(value);
  }

  Future<void> dispose() => _controller.close();
}
