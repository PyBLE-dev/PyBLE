// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-02 [red] — BleByteTransport is a pure byte pass-through (FR-BLE-3).
//
// BleByteTransport is the ONE sanctioned lib/pble → lib/ble edge: it adapts a
// [BleLink] to the [ByteTransport] the engine runs over. It MUST NOT interpret
// frame contents — it only moves bytes:
//   • send(packet) writes those exact bytes to RX (Write-Without-Response);
//   • inbound surfaces TX notifications byte-for-byte;
//   • mtu reflects the link's negotiated MTU;
//   • connected tracks the link's up/down state.
//
// This drives REAL production code (`lib/pble/ble_byte_transport.dart`) over the
// FakeBleLink double, so the "adapter never interprets bytes" guarantee is
// genuinely exercised.
//
// CURRENTLY RED: `lib/pble/ble_byte_transport.dart` (BleByteTransport) does not
// exist yet, and `lib/ble` does not define BleLink. HAND-OFF:
// `lib/pble/ble_byte_transport.dart` → app-protocol-engineer;
// `lib/ble/**` → app-ble-engineer.

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/ble_byte_transport.dart';

import '../support/fake_ble.dart';

void main() {
  group('A-02 BleByteTransport pass-through (FR-BLE-3)', () {
    test('send() writes the exact bytes to RX (no interpretation)', () async {
      final FakeBleLink link = FakeBleLink(mtu: 247);
      addTearDown(link.dispose);
      final BleByteTransport transport = BleByteTransport(link);

      final Uint8List packet = Uint8List.fromList(<int>[
        0x80,
        0x01,
        0x01,
        0x01,
        0x07,
        0x00,
        0x00,
      ]);
      await transport.send(packet);

      expect(link.writes, hasLength(1));
      expect(
        link.writes.single,
        equals(packet),
        reason: 'the transport moves bytes verbatim; it never parses frames',
      );
    });

    test('inbound surfaces TX notifications byte-for-byte', () async {
      final FakeBleLink link = FakeBleLink(mtu: 247);
      addTearDown(link.dispose);
      final BleByteTransport transport = BleByteTransport(link);

      final Future<Uint8List> first = transport.inbound.first;
      final List<int> notification = <int>[0x01, 0x03, 0x30, 0x00, 0x03, 0x00];
      link.emitInbound(notification);

      expect(await first, equals(notification));
    });

    test('mtu reflects the link MTU', () {
      final FakeBleLink link = FakeBleLink(mtu: 23);
      addTearDown(link.dispose);
      expect(BleByteTransport(link).mtu, 23);
    });

    test('connected tracks the link up/down state', () async {
      final FakeBleLink link = FakeBleLink(mtu: 247);
      addTearDown(link.dispose);
      final BleByteTransport transport = BleByteTransport(link);

      expect(transport.connected.value, isTrue);
      await link.disconnect();
      expect(transport.connected.value, isFalse);
    });
  });
}
