// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: an in-memory [ByteTransport] double — the "Fake board" the
// A-10 conformance + engine/HELLO suites run over (no BLE, no ESP32).
//
// This is the SCAFFOLD the app-test-author owns; it drives the REAL production
// codec/fragmentation/engine stack (`lib/pble/{frame,fragment,byte_transport}`)
// end-to-end over a scriptable byte pipe. Outbound packets are reassembled and
// decoded so a test can assert exactly which frame the client sent; inbound
// responses are re-fragmented at the negotiated MTU exactly as a real GATT link
// would deliver them (protocol.md §3.2).
//
// Until the `lib/pble` codec lands, importers of this file compile-fail — the
// intended A-10 [red]. HAND-OFF: `lib/pble/**` → app-protocol-engineer.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;

import 'package:pyble/pble/byte_transport.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/pble_constants.dart';

/// A scriptable in-memory [ByteTransport] (the Fake board transport).
class FakeByteTransport implements ByteTransport {
  FakeByteTransport({this.mtu = Pble.mtuRequest});

  @override
  final int mtu;

  final StreamController<Uint8List> _inbound =
      StreamController<Uint8List>.broadcast();
  final ValueNotifier<bool> _connected = ValueNotifier<bool>(true);
  final PbleReassembler _outboundReassembler = PbleReassembler();

  /// Every raw GATT packet the client wrote (in order), for structural checks.
  final List<Uint8List> sentPackets = <Uint8List>[];

  /// Every COMPLETE frame the client sent (reassembled + decoded), for
  /// request/response assertions.
  final List<PbleFrame> sentFrames = <PbleFrame>[];

  @override
  Stream<Uint8List> get inbound => _inbound.stream;

  @override
  ValueListenable<bool> get connected => _connected;

  @override
  Future<void> send(Uint8List packet) async {
    sentPackets.add(Uint8List.fromList(packet));
    final Uint8List? full = _outboundReassembler.offer(packet);
    if (full != null) sentFrames.add(decodeFrame(full));
  }

  /// Scripts a response frame back to the client, re-fragmented at [mtu] and
  /// scheduled on a microtask so it lands AFTER the awaiting caller has
  /// registered its completer.
  void deliverFrame(PbleFrame frame) {
    final List<Uint8List> packets = PbleFragmenter(
      mtu: mtu,
    ).fragment(encodeFrame(frame));
    scheduleMicrotask(() {
      for (final Uint8List p in packets) {
        if (!_inbound.isClosed) _inbound.add(p);
      }
    });
  }

  /// Scripts a raw inbound packet verbatim (for corrupt-frame / error paths).
  void deliverRawPacket(Uint8List packet) => scheduleMicrotask(() {
    if (!_inbound.isClosed) _inbound.add(packet);
  });

  /// Scripts a link up/down transition.
  void setConnected(bool value) => _connected.value = value;

  Future<void> dispose() async {
    await _inbound.close();
    _connected.dispose();
  }
}
