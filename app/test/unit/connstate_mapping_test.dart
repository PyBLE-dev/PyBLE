// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-03 [red] — the lib/pble side of reconnect: PbleConnection observes
// BleLinkState and maps it onto the neutral ConnState (FR-CONN-5), re-running
// HELLO on EVERY (re)connect. Frozen mapping: TDD §7.3.
//
//   connecting / reconnecting  → ConnState.connecting
//   connected                  → run HELLO; on OK → ConnState.ready
//   disconnected               → ConnState.disconnected
//
// Driven over a FakeBleLink through the REAL BleByteTransport → PbleEngine →
// HelloNegotiator stack (no radio). Pins that PbleConnection can be constructed
// over a BleLink (proposed `PbleConnection.fromLink`) and re-negotiates on each
// reconnect (a 2nd HELLO CMD after the link comes back).
//
// CURRENTLY RED: PbleConnection has no BleLink-observing construction / link→
// ConnState mapping / re-HELLO-on-reconnect. HAND-OFF:
// `lib/pble/pble_connection.dart` → app-protocol-engineer (coordinate the
// constructor shape with app-ble-engineer's BleLink seam).

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/ble/ble.dart';
import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';

import '../support/fake_ble.dart';

String _capsText() => <String>[
  'proto=1',
  'chip=esp32-s3',
  'mpy=1.28.0',
  'fs_root=/',
  'mtu=247',
].join('\n');

/// Every complete frame the client has written to [link] so far.
List<PbleFrame> framesFromWrites(FakeBleLink link) {
  final PbleReassembler r = PbleReassembler();
  final List<PbleFrame> frames = <PbleFrame>[];
  for (final List<int> packet in link.writes) {
    final Uint8List? message = r.offer(Uint8List.fromList(packet));
    if (message != null) frames.add(decodeFrame(message));
  }
  return frames;
}

/// Scripts a Fake-board frame back over [link], re-fragmented at its MTU.
void deliverOverLink(FakeBleLink link, PbleFrame frame) {
  for (final Uint8List packet in PbleFragmenter(
    mtu: link.mtu,
  ).fragment(encodeFrame(frame))) {
    link.emitInbound(packet);
  }
}

void main() {
  group('A-03 BleLinkState → ConnState mapping + re-HELLO (TDD §7.3)', () {
    late FakeBleLink link;
    late PbleConnection conn;

    setUp(() {
      link = FakeBleLink()..emitLinkState(BleLinkState.disconnected);
      conn = PbleConnection.fromLink(
        link: link,
        appName: 'PyBLE',
        appVersion: '0.1.0',
      );
    });

    tearDown(() async {
      await conn.dispose();
      await link.dispose();
    });

    /// Answers the newest HELLO CMD the client wrote with an OK caps RSP.
    Future<void> answerHello() async {
      await pumpEventQueue();
      final PbleFrame hello = framesFromWrites(
        link,
      ).lastWhere((f) => f.opcode == PbleOpcode.hello.code);
      deliverOverLink(
        link,
        PbleFrame(
          type: Pble.typeRsp,
          opcode: PbleOpcode.hello.code,
          id: hello.id,
          payload: Uint8List.fromList(<int>[
            PbleStatus.ok.code,
            ...utf8.encode(_capsText()),
          ]),
        ),
      );
      await pumpEventQueue();
    }

    test('starts disconnected when the link is down', () {
      expect(conn.state.value, ConnState.disconnected);
    });

    test('connecting/reconnecting → ConnState.connecting', () async {
      link.emitLinkState(BleLinkState.connecting);
      await pumpEventQueue();
      expect(conn.state.value, ConnState.connecting);

      link.emitLinkState(BleLinkState.reconnecting);
      await pumpEventQueue();
      expect(
        conn.state.value,
        ConnState.connecting,
        reason: 'a reconnect-in-progress reads as connecting to the UI',
      );
    });

    test('connected runs HELLO and, on OK, → ConnState.ready', () async {
      link.emitLinkState(BleLinkState.connected);
      await answerHello();
      expect(conn.state.value, ConnState.ready);
      expect(
        framesFromWrites(link).where((f) => f.opcode == PbleOpcode.hello.code),
        hasLength(1),
        reason: 'HELLO is the first exchange after connect (FR-PBLE-5)',
      );
    });

    test('re-negotiates HELLO on every reconnect', () async {
      // First bring-up.
      link.emitLinkState(BleLinkState.connected);
      await answerHello();
      expect(conn.state.value, ConnState.ready);

      // Drop, then a reconnect cycle.
      link.emitLinkState(BleLinkState.reconnecting);
      await pumpEventQueue();
      expect(conn.state.value, ConnState.connecting);

      link.emitLinkState(BleLinkState.connected);
      await answerHello();
      expect(conn.state.value, ConnState.ready);

      expect(
        framesFromWrites(
          link,
        ).where((f) => f.opcode == PbleOpcode.hello.code).length,
        2,
        reason: 're-HELLO on every (re)connect (TDD §7.3)',
      );
    });

    test('disconnected → ConnState.disconnected', () async {
      link.emitLinkState(BleLinkState.connected);
      await answerHello();
      expect(conn.state.value, ConnState.ready);

      link.emitLinkState(BleLinkState.disconnected);
      await pumpEventQueue();
      expect(conn.state.value, ConnState.disconnected);
    });
  });
}
