// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Transfer robustness [red] — a stalled or dying transfer must FAIL TYPED, not
// hang (FR-PBLE-9 honesty, NFR-REL-4). Root cause of the field report "open an
// 11.9 kB file from the board → the app hangs": the GET data phase awaited its
// completer with NO timeout, and a link drop mid-transfer orphaned it forever
// (the reconnect quietly re-HELLOs while the old await never resolves).
//
// Pins the frozen contract:
//   • PbleConnection(dataTimeout:) bounds the transfer DATA phase — GET_DATA /
//     GET_END silence past the ceiling fails the download with the typed
//     PbleTimeoutException; the watchdog RE-ARMS on every chunk (a slow-but-
//     flowing transfer never times out);
//   • a PUT chunk's ACK wait is bounded by the same ceiling (typed timeout);
//   • a BleLinkState.disconnected mid-transfer aborts the in-flight download
//     IMMEDIATELY with NotConnectedException (no waiting out the watchdog).

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/ble/ble_link.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/fake_ble.dart';
import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

/// Short enough to keep the suite fast, long enough to be unambiguous.
const Duration kTestDataTimeout = Duration(milliseconds: 80);

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
  late FakeByteTransport transport;
  late PbleEngine engine;
  late PbleConnection conn;

  setUp(() {
    transport = FakeByteTransport(mtu: Pble.mtuRequest);
    engine = PbleEngine(transport);
    conn = PbleConnection(
      engine: engine,
      appName: 'PyBLE',
      appVersion: '0.1.0',
      dataTimeout: kTestDataTimeout,
    );
  });

  tearDown(() async {
    await conn.dispose();
    await transport.dispose();
  });

  group('download stall watchdog (dataTimeout)', () {
    test('silence after GET_BEGIN fails typed — never hangs', () async {
      final Future<Uint8List> pending = conn.getFile('/big.py');
      await pumpEventQueue();
      final PbleFrame begin = transport.sentFrames.single;
      // The board answers BEGIN OK (total 12000)… and then goes silent — the
      // dropped-chunk / saturated-link case observed on hardware.
      transport.deliverFrame(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(12000)),
      );

      await expectLater(
        pending,
        throwsA(isA<PbleTimeoutException>()),
        reason: 'the data phase must be bounded by dataTimeout',
      );
    });

    test(
      'silence MID-stream fails typed; the watchdog re-arms per chunk',
      () async {
        final Uint8List data = Uint8List.fromList(utf8.encode('x' * 64));
        final Future<Uint8List> pending = conn.getFile('/part.py');
        await pumpEventQueue();
        final PbleFrame begin = transport.sentFrames.single;
        transport.deliverFrame(
          rsp(
            PbleOpcode.fileGetBegin,
            begin.id,
            getBeginOkPayload(data.length),
          ),
        );
        await pumpEventQueue();

        // Two chunks arrive spaced past HALF the ceiling each — the re-armed
        // watchdog must NOT fire while data is flowing…
        transport.deliverFrame(
          evt(PbleOpcode.fileGetData, getDataPayload(0, data.sublist(0, 16))),
        );
        await Future<void>.delayed(kTestDataTimeout ~/ 2);
        transport.deliverFrame(
          evt(PbleOpcode.fileGetData, getDataPayload(16, data.sublist(16, 32))),
        );
        await Future<void>.delayed(kTestDataTimeout ~/ 2);

        // …and then the stream dies with bytes still owed (no GET_END).
        await expectLater(
          pending,
          throwsA(isA<PbleTimeoutException>()),
          reason: 'a mid-stream stall fails typed after dataTimeout of silence',
        );
      },
    );
  });

  group('upload ACK wait is bounded (dataTimeout)', () {
    test('a never-ACKed PUT chunk fails typed — never hangs', () async {
      final Uint8List bytes = Uint8List.fromList(utf8.encode('y' * 32));
      final Future<void> pending = conn.putFile('/up.py', bytes);
      await pumpEventQueue();
      final PbleFrame begin = transport.sentFrames.single;
      // BEGIN OK, resume offset 0 — then the board never ACKs the chunk.
      transport.deliverFrame(
        rsp(PbleOpcode.filePutBegin, begin.id, <int>[
          PbleStatus.ok.code,
          0,
          0,
          0,
          0,
        ]),
      );

      await expectLater(
        pending,
        throwsA(isA<PbleTimeoutException>()),
        reason: 'the ACK wait must be bounded by dataTimeout',
      );
    });
  });

  group('link drop mid-transfer aborts immediately', () {
    test(
      'BleLinkState.disconnected fails an in-flight download typed',
      () async {
        final FakeBleLink link = FakeBleLink();
        addTearDown(link.dispose);
        link.emitLinkState(BleLinkState.connected);
        final PbleConnection linked = PbleConnection.fromLink(
          link: link,
          appName: 'PyBLE',
          appVersion: '0.1.0',
          // A LONG ceiling: proves the abort is the LINK observer, not the
          // stall watchdog winning a race.
          dataTimeout: const Duration(seconds: 30),
        );
        addTearDown(linked.dispose);
        await pumpEventQueue();

        // Answer the auto-HELLO so the connection is usable.
        PbleFrame lastWrite() => framesFromWrites(link).last;
        final PbleFrame hello = framesFromWrites(
          link,
        ).lastWhere((PbleFrame f) => f.opcode == PbleOpcode.hello.code);
        deliverOverLink(
          link,
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: hello.id,
            payload: Uint8List.fromList(<int>[
              PbleStatus.ok.code,
              ...utf8.encode('proto_version=1\nchunk=512\n'),
            ]),
          ),
        );
        await pumpEventQueue();

        final Future<Uint8List> pending = linked.getFile('/gone.py');
        await pumpEventQueue();
        final PbleFrame begin = lastWrite();
        expect(begin.opcode, PbleOpcode.fileGetBegin.code);
        deliverOverLink(
          link,
          rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(9999)),
        );
        await pumpEventQueue();

        // The link dies mid-download (e.g. burst → supervision timeout). The
        // orphaned await must fail NOW — this was the "hang" on hardware.
        link.emitLinkState(BleLinkState.disconnected);

        await expectLater(
          pending,
          throwsA(isA<NotConnectedException>()),
          reason: 'a dropped link aborts the in-flight transfer immediately',
        );
      },
    );
  });
}
