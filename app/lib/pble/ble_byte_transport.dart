// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;

// The ONE sanctioned lib/pble -> lib/ble edge (import-boundary exempt, CON-8):
// `lib/pble` is the only package permitted to import `lib/ble`, and this is the
// only file that does it. It NEVER imports flutter_blue_plus — it binds to the
// neutral BleLink seam that app-ble-engineer owns.
import 'package:pyble/ble/ble.dart';

import 'byte_transport.dart';

/// Adapts a [BleLink] (the `lib/ble` byte seam) to a [ByteTransport].
///
/// A pure byte pass-through (FR-BLE-3): it forwards TX notifications and RX
/// writes verbatim and mirrors the link's up/down state. It does NOT interpret
/// frame contents — all framing/CRC/correlation lives above it in the engine.
class BleByteTransport implements ByteTransport {
  BleByteTransport(this._link)
    : _connected = ValueNotifier<bool>(
        _link.linkState.value == BleLinkState.connected,
      ) {
    _link.linkState.addListener(_onLinkState);
  }

  final BleLink _link;
  final ValueNotifier<bool> _connected;

  void _onLinkState() {
    _connected.value = _link.linkState.value == BleLinkState.connected;
  }

  @override
  Stream<Uint8List> get inbound => _link.inbound.map(
    (List<int> bytes) => bytes is Uint8List ? bytes : Uint8List.fromList(bytes),
  );

  @override
  Future<void> send(Uint8List packet, {required bool acknowledged}) =>
      _link.write(packet, withoutResponse: !acknowledged);

  @override
  int get mtu => _link.mtu;

  @override
  ValueListenable<bool> get connected => _connected;

  /// Detaches the link-state listener and releases the notifier.
  void dispose() {
    _link.linkState.removeListener(_onLinkState);
    _connected.dispose();
  }
}
