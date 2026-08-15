// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: conformant fakes for the `lib/ble` seam (A-01/A-02). These are
// the "mocked transport (Fake board)" the BLE-adapter DoR calls for — no radio,
// no ESP32.
//
// They MODEL the contract every conformant [BleAdapter]/[BleLink] must satisfy
// (filtered scan, stop-before-connect, MTU 247 with graceful fallback, byte
// pass-through with NO frame interpretation) so higher suites can reuse them and
// so the seam's observable behaviour is locked. Deep verification of the
// production `FbpBleAdapter`'s flutter_blue_plus mapping (against a mocked
// platform channel) is app-ble-engineer's [green] obligation; this scaffold
// pins the seam that FbpBleAdapter must honour.
//
// Until `lib/ble` defines the abstract seam, importers compile-fail — the
// intended A-01/A-02 [red]. HAND-OFF: `lib/ble/**` → app-ble-engineer.

import 'dart:async';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;

import 'package:pyble/ble/ble.dart';
import 'package:pyble/pble/pble_constants.dart';

/// A recording [BleLink] double. Captures every [write] verbatim (no parsing)
/// and lets a test push raw TX notifications and script the negotiated MTU.
class FakeBleLink implements BleLink {
  FakeBleLink({this.mtu = Pble.mtuRequest});

  final StreamController<List<int>> _inbound =
      StreamController<List<int>>.broadcast();
  final ValueNotifier<BleLinkState> _linkState = ValueNotifier<BleLinkState>(
    BleLinkState.connected,
  );

  /// Every payload written to RX, byte-for-byte (pass-through proof, FR-BLE-3).
  final List<List<int>> writes = <List<int>>[];

  /// The low-level GATT mode paired with each payload in [writes].
  final List<bool> writesWithoutResponse = <bool>[];

  @override
  Stream<List<int>> get inbound => _inbound.stream;

  @override
  Future<void> write(List<int> bytes, {bool withoutResponse = true}) async {
    writes.add(List<int>.of(bytes));
    writesWithoutResponse.add(withoutResponse);
  }

  @override
  final int mtu;

  @override
  ValueListenable<BleLinkState> get linkState => _linkState;

  @override
  Future<void> disconnect() async =>
      _linkState.value = BleLinkState.disconnected;

  /// Scripts an inbound TX notification (raw bytes, unparsed).
  void emitInbound(List<int> bytes) => _inbound.add(bytes);

  /// Scripts a link-state transition through any of the four states (drives the
  /// A-03 reconnect + ConnState-mapping suites). [disconnect] is the
  /// user-initiated teardown; this is the raw state driver.
  void emitLinkState(BleLinkState state) => _linkState.value = state;

  Future<void> dispose() async {
    await _inbound.close();
    _linkState.dispose();
  }
}

/// A conformant [BleAdapter] double modelling the A-01/A-02 seam contract.
class FakeBleAdapter implements BleAdapter {
  FakeBleAdapter({this.negotiatedMtu = Pble.mtuRequest});

  /// The MTU the fake GATT link reports after [connect]. Set to a lower value
  /// (e.g. the BLE default 23) to exercise the fallback path (FR-BLE-2).
  final int negotiatedMtu;

  /// The RAW advertisements the radio "sees" (a deliberate mix of PyBLE boards
  /// and unrelated devices). [scan] must surface ONLY the PyBLE hits (CON-1).
  final List<BleScanResult> rawAdvertisements = <BleScanResult>[];

  /// Ordered log of adapter calls, so a test can assert stop-before-connect.
  final List<String> callLog = <String>[];

  FakeBleLink? lastLink;

  @override
  Stream<BleScanResult> scan() {
    callLog.add('scan');
    // CONTRACT: filter to the PyBLE service / name prefix; never a raw list.
    return Stream<BleScanResult>.fromIterable(
      rawAdvertisements.where((r) => r.name.startsWith(Pble.namePrefix)),
    );
  }

  @override
  Future<void> stopScan() async => callLog.add('stopScan');

  @override
  Future<BleLink> connect(String id) async {
    // CONTRACT: scanning is stopped BEFORE a connection is initiated (FR-BLE-5).
    await stopScan();
    callLog.add('connect');
    return lastLink = FakeBleLink(mtu: negotiatedMtu);
  }
}
