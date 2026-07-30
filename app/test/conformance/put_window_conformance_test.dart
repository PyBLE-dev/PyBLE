// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-13 [red] — the WINDOWED `putFile` uploader over the Fake board
// ([FakeByteTransport]), driving the REAL client stack against the FROZEN +
// window-agnostic wire of protocol.md §5 (`FILE_PUT_BEGIN` → windowed
// `FILE_PUT_DATA` → cumulative `FILE_PUT_ACK` → `FILE_PUT_END`).
//
// This supersedes the A-12 depth-1 (stop-and-wait) uploader in
// file_ops_conformance_test.dart. It pins the frozen A-13 acceptance criteria
// (App/specs.md "A-13 putFile sliding-window increment — FROZEN 2026-07-04",
// FR-PBLE-8/-10), which the reference agent's caps.window (ref 8, fallback 4)
// drives client-side:
//
//   • AC-1 window bound  — ≤ W FILE_PUT_DATA outstanding past the ACK watermark
//     at any instant; W = caps.window; the client does NOT await an ACK after
//     every chunk (it fills the window BEFORE the first ACK arrives).
//   • AC-2 advance on cumulative ACK — a single FILE_PUT_ACK{ack_offset} may
//     retire MULTIPLE chunks, advancing the base and releasing that many credits
//     (not one chunk per ACK).
//   • AC-3 Go-Back-N — a non-advancing (stale/duplicate) cumulative ACK after a
//     board drop/re-ack is a GAP signal: the client retransmits from the
//     watermark (every chunk at/after ack_offset, byte-exact offsets) and never
//     assumes a chunk past ack_offset arrived.
//   • AC-4 resume  — FILE_PUT_BEGIN resume_offset > 0 starts the window there.
//   • AC-5 progress — TransferProgress.sent is monotonic non-decreasing, driven
//     by the acked watermark; a Go-Back-N resend never moves the bar backward.
//   • AC-6 success gate — put succeeds ONLY on FILE_PUT_END RSP OK.
//   • Stall — no ACK progress within dataTimeout still fails typed
//     (PbleTimeoutException), AFTER the window was filled (not stop-and-wait).
//
// The wire is REFERENCED, never redefined: W is NOT a wire field (protocol.md §5
// is FROZEN, offset/watermark cumulative-ACK is window-agnostic); W is a
// client-side pacing parameter read from HELLO caps.window (§7).
//
// CURRENTLY RED against the shipped stop-and-wait uploader
// (`pble_connection.dart` putFile "effective window depth 1"): it sends exactly
// ONE FILE_PUT_DATA and awaits its ACK before the next, so it never fills the
// window, never retires multiple chunks per ACK, and does not Go-Back-N on a
// stale ACK. HAND-OFF (green): the A-13 putFile sliding-window state machine in
// `lib/pble/pble_connection.dart` (putFile + the FILE_PUT_ACK event route) →
// app-protocol-engineer (`lib/pble` owns the wire client).

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

/// Caps with an explicit `window` (W) and `chunk`, so a test can pin the exact
/// pacing the uploader must honour (ref agent advertises W=8; fallback 4).
String _capsText({required int window, required int chunk}) => <String>[
  'proto=1',
  'chip=esp32-s3',
  'mpy=1.28.0',
  'fs_root=/',
  'mtu=247',
  'window=$window',
  'chunk=$chunk',
  'free_mem=100000',
].join('\n');

/// A `[a, a+chunk, a+2*chunk, …)` byte ramp of [len] bytes (deterministic, so a
/// resent chunk can be byte-compared to the original slice).
Uint8List _ramp(int len) =>
    Uint8List.fromList(<int>[for (int i = 0; i < len; i++) i & 0xff]);

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
      // Short data-phase ceiling so the STALL test is fast; the window/GBN
      // tests never rely on it firing.
      dataTimeout: const Duration(milliseconds: 120),
    );
  });

  tearDown(() async {
    await conn.dispose();
    await transport.dispose();
  });

  Future<void> handshake({required int window, required int chunk}) async {
    final Future<void> pending = conn.handshake();
    await pumpEventQueue();
    final PbleFrame hello = transport.sentFrames.single;
    transport.deliverFrame(
      rsp(PbleOpcode.hello, hello.id, <int>[
        PbleStatus.ok.code,
        ...utf8.encode(_capsText(window: window, chunk: chunk)),
      ]),
    );
    await pending;
  }

  List<PbleFrame> dataFrames() => transport.sentFrames
      .where((f) => f.opcode == PbleOpcode.filePutData.code)
      .toList();

  List<int> dataOffsets() =>
      dataFrames().map((f) => decodePutDataPayload(f.payload).$1).toList();

  PbleFrame theBegin() => transport.sentFrames.firstWhere(
    (f) => f.opcode == PbleOpcode.filePutBegin.code,
  );

  List<PbleFrame> endFrames() => transport.sentFrames
      .where((f) => f.opcode == PbleOpcode.filePutEnd.code)
      .toList();

  /// Answers FILE_PUT_BEGIN with `resume_offset` and settles the microtask.
  Future<void> ackBegin(int resumeOffset) async {
    transport.deliverFrame(
      rsp(
        PbleOpcode.filePutBegin,
        theBegin().id,
        putBeginOkPayload(resumeOffset),
      ),
    );
    await pumpEventQueue();
  }

  /// Delivers a cumulative FILE_PUT_ACK{ackOffset} and settles the microtask.
  Future<void> deliverAck(int ackOffset) async {
    transport.deliverFrame(
      evt(PbleOpcode.filePutAck, putAckPayload(ackOffset)),
    );
    await pumpEventQueue();
  }

  void expectMonotonic(List<TransferProgress> p) {
    for (int i = 1; i < p.length; i++) {
      expect(
        p[i].sent,
        greaterThanOrEqualTo(p[i - 1].sent),
        reason: 'progress.sent is monotonic non-decreasing (never backward)',
      );
    }
  }

  group('A-13 AC-1 — window bound: ≤ W outstanding, no ACK-per-chunk', () {
    test(
      'fills W=4 FILE_PUT_DATA before the FIRST ACK, and never exceeds W',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(40); // 10 chunks

        final Future<void> pending = conn.putFile('/up.bin', data);
        await pumpEventQueue();
        await ackBegin(0);

        // No ACK has been delivered yet. A windowed uploader MUST have sent the
        // full window; a stop-and-wait uploader sends exactly one and blocks.
        expect(
          dataFrames().length,
          greaterThanOrEqualTo(2),
          reason: 'not stop-and-wait: ≥2 FILE_PUT_DATA before the first ACK',
        );
        expect(
          dataFrames().length,
          4,
          reason: 'exactly W=caps.window chunks outstanding, never more',
        );
        expect(
          dataOffsets(),
          <int>[0, 4, 8, 12],
          reason: 'the first W chunks, back-to-back, offsets 0..(W-1)*chunk',
        );

        pending.ignore(); // left in-flight; disposed in tearDown
      },
    );

    test('window stays capped at W even when the board acks slowly', () async {
      await handshake(window: 3, chunk: 5);
      final Uint8List data = _ramp(100); // 20 chunks, far more than W

      final Future<void> pending = conn.putFile('/slow.bin', data);
      await pumpEventQueue();
      await ackBegin(0);

      // Pump repeatedly WITHOUT delivering any ACK: outstanding must plateau at
      // W and never creep past it.
      for (int i = 0; i < 5; i++) {
        await pumpEventQueue();
      }
      expect(
        dataFrames().length,
        3,
        reason: 'capped at W=3 with no ACK credit',
      );

      pending.ignore();
    });
  });

  group('A-13 AC-2 — cumulative ACK advances base + releases credit', () {
    test(
      'one FILE_PUT_ACK retires MULTIPLE chunks and refills the window',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(40);

        final Future<void> pending = conn.putFile('/up.bin', data);
        await pumpEventQueue();
        await ackBegin(0);
        expect(dataOffsets(), <int>[0, 4, 8, 12]); // window filled

        // A single cumulative ACK at 8 retires TWO chunks (0..4, 4..8). Base → 8,
        // 2 credits released → the next TWO chunks go out (offsets 16, 20).
        await deliverAck(8);
        expect(
          dataFrames().length,
          6,
          reason: 'one ACK retired 2 chunks → 2 fresh chunks sent (not 1)',
        );
        expect(dataOffsets(), <int>[0, 4, 8, 12, 16, 20]);

        pending.ignore();
      },
    );
  });

  group('A-13 AC-3 — Go-Back-N: stale ACK retransmits from the watermark', () {
    test(
      'a dropped chunk (non-advancing re-ACK) resends every chunk ≥ watermark',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(16); // exactly 4 chunks: 0,4,8,12
        final List<TransferProgress> progress = <TransferProgress>[];

        final Future<void> pending = conn.putFile(
          '/gbn.bin',
          data,
          onProgress: progress.add,
        );
        await pumpEventQueue();
        await ackBegin(0);
        expect(dataOffsets(), <int>[
          0,
          4,
          8,
          12,
        ], reason: 'window filled with all 4');

        // Board received 0..4 and 4..8, then DROPPED chunk@8; chunk@12 arrived
        // past the gap and was discarded → the board re-acks its watermark, 8.
        await deliverAck(8); // legit advance 0 → 8 (retires 0..4, 4..8)

        // Watermark of the send history at the instant the base advanced to 8.
        // The Go-Back-N assertions below scope to the RESEND phase — the frames
        // sent AFTER this advancing ACK. Offsets 0 and 4 legitimately precede the
        // watermark (the initial window fill sent them once); they are done, so
        // they must NOT count against the "never dip below the watermark" rule,
        // which is about what the client RE-SENDS on a gap, per AC-3.
        final int sentBeforeResends = dataOffsets().length;

        // The board keeps re-acking 8 for the dropped/out-of-order chunks. A
        // non-advancing cumulative ACK is a GAP signal → Go-Back-N. Deliver a few
        // so any reasonable dup-ACK threshold trips (thresholdless assertion).
        for (int i = 0; i < 4; i++) {
          await deliverAck(8);
        }

        final List<int> offs = dataOffsets();
        final List<int> resent = offs.sublist(sentBeforeResends);
        expect(
          offs.where((o) => o == 8).length,
          greaterThanOrEqualTo(2),
          reason: 'chunk@8 retransmitted from the watermark',
        );
        expect(
          offs.where((o) => o == 12).length,
          greaterThanOrEqualTo(2),
          reason:
              'chunk@12 (past the gap) is NOT assumed received — resent too',
        );
        expect(
          resent,
          isNotEmpty,
          reason: 'a non-advancing cumulative ACK triggers Go-Back-N resend',
        );
        expect(
          resent.where((o) => o < 8),
          isEmpty,
          reason:
              'resent chunks never dip BELOW the acked watermark 8 (0 and 4 '
              'are already done — only the initial fill ever sent them)',
        );
        expect(
          offs.where((o) => o >= 16),
          isEmpty,
          reason: 'never invent a chunk past the file end',
        );

        // Every FILE_PUT_DATA (original or resent) is byte-exact for its offset.
        for (final PbleFrame f in dataFrames()) {
          final (int off, Uint8List bytes) = decodePutDataPayload(f.payload);
          final int end = (off + 4) < 16 ? off + 4 : 16;
          expect(
            bytes,
            equals(Uint8List.sublistView(data, off, end)),
            reason: 'resent bytes match the original slice at offset $off',
          );
        }

        // AC-5: a Go-Back-N resend never moved the progress bar backward.
        expectMonotonic(progress);

        pending.ignore();
      },
    );
  });

  group('A-13 AC-4 — resume: window starts at resume_offset', () {
    test(
      'BEGIN resume_offset>0 fills the window from there, none below it',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(40); // 10 chunks; resume past the first 2
        final List<TransferProgress> progress = <TransferProgress>[];

        final Future<void> pending = conn.putFile(
          '/resume.bin',
          data,
          onProgress: progress.add,
        );
        await pumpEventQueue();
        // Board already holds a verified 8-byte prefix (FR-PBLE-10).
        await ackBegin(8);

        expect(
          dataOffsets(),
          <int>[8, 12, 16, 20],
          reason: 'the window starts at resume_offset, W chunks, none below it',
        );
        expect(
          dataOffsets().where((o) => o < 8),
          isEmpty,
          reason: 'a resumed put never re-sends the verified prefix',
        );
        expect(
          progress.first.sent,
          greaterThanOrEqualTo(8),
          reason: 'progress starts at the resume watermark, not 0',
        );

        pending.ignore();
      },
    );
  });

  group('A-13 AC-5/AC-6 — happy path: monotonic progress, END only on OK', () {
    test('windowed drive to completion: cumulative ACKs → END → RSP OK', () async {
      await handshake(window: 4, chunk: 4);
      final Uint8List data = _ramp(40); // 10 chunks
      final int crc = pbleCrc32(data);
      final List<TransferProgress> progress = <TransferProgress>[];

      final Future<void> pending = conn.putFile(
        '/done.bin',
        data,
        onProgress: progress.add,
      );
      await pumpEventQueue();
      await ackBegin(0);
      expect(dataOffsets(), <int>[0, 4, 8, 12]);

      await deliverAck(4); // base→4, send @16
      await deliverAck(8); // base→8, send @20
      await deliverAck(20); // retires 3 (8,12,16), send @24,@28,@32
      expect(dataOffsets(), <int>[0, 4, 8, 12, 16, 20, 24, 28, 32]);
      await deliverAck(36); // base→36, send the last chunk @36
      expect(dataOffsets(), <int>[0, 4, 8, 12, 16, 20, 24, 28, 32, 36]);

      // AC-6: END is NOT sent until the whole file is acked (watermark==total).
      expect(
        endFrames(),
        isEmpty,
        reason: 'no FILE_PUT_END before the last byte is acked',
      );
      await deliverAck(40); // base→40==total

      final List<PbleFrame> ends = endFrames();
      expect(
        ends,
        hasLength(1),
        reason: 'FILE_PUT_END sent once, after full ACK',
      );
      expect(
        readU32le(ends.single.payload, 0),
        crc,
        reason: 'FILE_PUT_END carries the whole-file CRC',
      );

      // The concatenation of the FIRST send of each offset reproduces the file.
      final Map<int, Uint8List> firstByOffset = <int, Uint8List>{};
      for (final PbleFrame f in dataFrames()) {
        final (int off, Uint8List bytes) = decodePutDataPayload(f.payload);
        firstByOffset.putIfAbsent(off, () => bytes);
      }
      final List<int> reassembled = <int>[
        for (final int off in (firstByOffset.keys.toList()..sort()))
          ...firstByOffset[off]!,
      ];
      expect(reassembled, orderedEquals(data));

      // AC-6: success ONLY on RSP OK.
      transport.deliverFrame(
        statusRsp(PbleOpcode.filePutEnd, ends.single.id, PbleStatus.ok),
      );
      await pending;

      // AC-5: monotonic, watermark-driven, reaches total.
      expectMonotonic(progress);
      expect(progress.last.sent, 40);
      expect(progress.last.total, 40);
    });

    test(
      'FILE_PUT_END ECRC surfaces typed (old file kept) — no false success',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(8); // 2 chunks

        final Future<void> pending = conn.putFile('/bad.bin', data);
        await pumpEventQueue();
        await ackBegin(0);
        expect(
          dataFrames().length,
          greaterThanOrEqualTo(2),
          reason: 'both chunks are in flight before the ACK (windowed)',
        );
        await deliverAck(8); // full file acked

        final PbleFrame end = endFrames().single;
        transport.deliverFrame(
          statusRsp(PbleOpcode.filePutEnd, end.id, PbleStatus.eCrc),
        );
        await expectLater(
          pending,
          throwsA(isA<ECrc>()),
          reason: 'a PUT_END CRC mismatch is never reported as success',
        );
      },
    );
  });

  group('A-13 stall — no ACK progress within dataTimeout fails typed', () {
    test(
      'a filled window that is NEVER acked fails typed after dataTimeout',
      () async {
        await handshake(window: 4, chunk: 4);
        final Uint8List data = _ramp(40);

        final Future<void> pending = conn.putFile('/stall.bin', data);
        await pumpEventQueue();
        await ackBegin(0);

        // Window filled (proves it is NOT stop-and-wait), then the board goes
        // silent — no ACK ever. The upload MUST fail typed, not hang.
        expect(
          dataFrames().length,
          greaterThanOrEqualTo(2),
          reason: 'the window was filled before the stall',
        );
        await expectLater(
          pending,
          throwsA(isA<PbleTimeoutException>()),
          reason:
              'no ACK progress within dataTimeout fails typed (never hangs)',
        );
      },
    );
  });
}
