// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueListenable;

/// The byte pipe the PBLE/1 engine runs over.
///
/// This is the seam that keeps `lib/pble` transport-agnostic: the engine speaks
/// only in whole GATT packets, never in `flutter_blue_plus` types. Production
/// wires it to a real BLE link via [BleByteTransport]; conformance and unit
/// suites drive it with an in-memory fake. It moves BYTES only — it never
/// interprets a frame.
abstract interface class ByteTransport {
  /// Inbound GATT packets (each a single TX notification), in arrival order.
  Stream<Uint8List> get inbound;

  /// Sends one outbound GATT packet (a single RX write).
  Future<void> send(Uint8List packet);

  /// The negotiated ATT MTU; the fragmenter sizes packets to `mtu - 4`.
  int get mtu;

  /// Whether the underlying link is up. The engine observes this for teardown.
  ValueListenable<bool> get connected;
}
