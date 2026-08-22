// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-12 [red] — file operations + download streaming over the Fake board
// ([FakeByteTransport]), driving the REAL client stack against the FROZEN +
// HIL-verified wire of protocol.md §5.
//
//   • listDir decodes FILE_LIST [status][more][count]{etype,esize,nlen,name};
//     more==1 is a TRUNCATION indicator only — the client reads exactly `count`
//     and NEVER re-issues (no continuation cursor exists on the wire);
//   • getFile streams GET_BEGIN → GET_DATA events → GET_END, and verifies the
//     assembled length == total_size AND the whole-file CRC BEFORE reporting
//     success (FR-PBLE-9); a corrupted stream (or wrong length) FAILS with the
//     typed ECrc EVEN IF the board's status was OK; progress is monotonic to 1.0;
//   • putFile FRAMING is pinned here — PUT_BEGIN [total][crc][plen][path], each
//     PUT_DATA byte-exact for its offset, PUT_END [crc], success only on RSP OK
//     (a PUT_END ECRC surfaces typed, old file kept), progress reported. The
//     window/PACING (≤ W outstanding, cumulative-ACK advance, Go-Back-N, resume)
//     is the A-13 increment and is asserted in put_window_conformance_test.dart —
//     NOT here (the frozen A-13 slice supersedes the old depth-1 pacing test);
//   • delete/mkdir/rename encode their §5 requests and map §8 statuses;
//   • a 2nd concurrent transfer is refused client-side with EBusy (no 2nd BEGIN).
//
// The true W-bounded sliding window (Go-Back-N) + resume-on-reconnect via
// FILE_STAT are A-13 (put_window_conformance_test.dart) — NOT asserted here.
//
// CURRENTLY RED: Connection/PbleConnection have no listDir/getFile/putFile/
// delete/mkdir/rename, no RemoteEntry/TransferProgress/ProgressCb, and no ECrc/
// EBusy/EAcces/ENoEnt/EBadReq subtypes yet. HAND-OFF:
// `lib/pble/{pble_connection,connection,types,pble_exception}.dart` →
// app-protocol-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/connection.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
// pble_exception.dart types (EBadReq…EInternal) reach us via types.dart's re-export
// after the S3 exception-migration [green]; a direct import is now redundant.
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

String _capsText({required int chunk}) => <String>[
  'proto=1',
  'chip=esp32-s3',
  'mpy=1.28.0',
  'fs_root=/',
  'mtu=247',
  'window=4',
  'chunk=$chunk',
  'free_mem=100000',
].join('\n');

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
    );
  });

  tearDown(() async {
    await conn.dispose();
    await transport.dispose();
  });

  Future<void> handshake({required int chunk}) async {
    final Future<void> pending = conn.handshake();
    await pumpEventQueue();
    final PbleFrame hello = transport.sentFrames.single;
    transport.deliverFrame(
      rsp(PbleOpcode.hello, hello.id, <int>[
        PbleStatus.ok.code,
        ...utf8.encode(_capsText(chunk: chunk)),
      ]),
    );
    await pending;
  }

  List<PbleFrame> sentOf(PbleOpcode op) =>
      transport.sentFrames.where((f) => f.opcode == op.code).toList();

  group('A-12 listDir (protocol.md §5)', () {
    test(
      'decodes [more][count]{etype,esize,nlen,name} into RemoteEntry list',
      () async {
        final Future<List<RemoteEntry>> pending = conn.listDir('/');
        await pumpEventQueue();

        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.opcode, PbleOpcode.fileList.code);
        expect(decodePathPayload(sent.payload), '/');

        transport.deliverFrame(
          rsp(
            PbleOpcode.fileList,
            sent.id,
            fileListOkPayload(
              more: false,
              entries: <List<int>>[
                fileEntry(isDir: false, size: 123, name: 'main.py'),
                fileEntry(isDir: true, size: 0, name: 'lib'),
              ],
            ),
          ),
        );

        final List<RemoteEntry> entries = await pending;
        expect(entries, hasLength(2));
        expect(entries[0].name, 'main.py');
        expect(entries[0].isDir, isFalse);
        expect(entries[0].size, 123);
        expect(entries[1].name, 'lib');
        expect(entries[1].isDir, isTrue);
      },
    );

    test(
      'more==1 is truncation-only: reads exactly count, never re-issues',
      () async {
        final Future<List<RemoteEntry>> pending = conn.listDir('/big');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;

        transport.deliverFrame(
          rsp(
            PbleOpcode.fileList,
            sent.id,
            fileListOkPayload(
              more: true,
              entries: <List<int>>[
                fileEntry(isDir: false, size: 1, name: 'a.py'),
              ],
            ),
          ),
        );

        final List<RemoteEntry> entries = await pending;
        expect(
          entries,
          hasLength(1),
          reason:
              'exactly `count` entries; the wire has no continuation cursor',
        );
        expect(
          sentOf(PbleOpcode.fileList),
          hasLength(1),
          reason: 'more==1 must NOT trigger a re-issue (A-30/S7 surfaces it)',
        );
      },
    );

    test(
      'preserves more==1 through the neutral completeness capability',
      () async {
        final Future<DirectoryListing> pending =
            (conn as ConnectionDirectoryListingSource).listDirWithMetadata(
              '/big',
            );
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;

        transport.deliverFrame(
          rsp(
            PbleOpcode.fileList,
            sent.id,
            fileListOkPayload(
              more: true,
              entries: <List<int>>[
                fileEntry(isDir: false, size: 1, name: 'a.py'),
              ],
            ),
          ),
        );

        final DirectoryListing listing = await pending;
        expect(listing.truncated, isTrue);
        expect(listing.entries.single.name, 'a.py');
        expect(sentOf(PbleOpcode.fileList), hasLength(1));
      },
    );
  });

  group('A-12 getFile — CRC-verified download streaming (FR-PBLE-9)', () {
    final Uint8List data = Uint8List.fromList(utf8.encode('hello world!'));

    test(
      'streams GET_DATA, verifies size + whole-file CRC, reports progress',
      () async {
        final List<TransferProgress> progress = <TransferProgress>[];
        final Future<Uint8List> pending = conn.getFile(
          '/data.bin',
          onProgress: progress.add,
        );
        await pumpEventQueue();

        final PbleFrame begin = transport.sentFrames.single;
        expect(begin.opcode, PbleOpcode.fileGetBegin.code);
        final (int offset, String path) = decodeGetBeginPayload(begin.payload);
        expect(offset, 0);
        expect(path, '/data.bin');

        transport.deliverFrame(
          rsp(
            PbleOpcode.fileGetBegin,
            begin.id,
            getBeginOkPayload(data.length),
          ),
        );
        await pumpEventQueue();

        transport.deliverFrame(
          evt(PbleOpcode.fileGetData, getDataPayload(0, data.sublist(0, 6))),
        );
        transport.deliverFrame(
          evt(PbleOpcode.fileGetData, getDataPayload(6, data.sublist(6))),
        );
        transport.deliverFrame(
          evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(data))),
        );

        final Uint8List got = await pending;
        expect(got, equals(data));

        expect(progress, isNotEmpty);
        for (int i = 1; i < progress.length; i++) {
          expect(
            progress[i].sent,
            greaterThanOrEqualTo(progress[i - 1].sent),
            reason: 'progress.sent is monotonic non-decreasing',
          );
        }
        expect(progress.last.total, data.length);
        expect(progress.last.sent, data.length, reason: 'progress reaches 1.0');
      },
    );

    test(
      'a wrong whole-file CRC FAILS with ECrc even when the RSP was OK',
      () async {
        final Future<Uint8List> pending = conn.getFile('/data.bin');
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

        transport.deliverFrame(
          evt(PbleOpcode.fileGetData, getDataPayload(0, data)),
        );
        // GET_END carries a CRC that does NOT match the assembled bytes.
        transport.deliverFrame(
          evt(
            PbleOpcode.fileGetEnd,
            getEndPayload(pbleCrc32(data) ^ 0xffffffff),
          ),
        );

        await expectLater(
          pending,
          throwsA(isA<ECrc>()),
          reason:
              'a bad whole-file CRC is never reported as success (FR-PBLE-9)',
        );
      },
    );

    test('an assembled length != total_size FAILS with ECrc', () async {
      final Future<Uint8List> pending = conn.getFile('/data.bin');
      await pumpEventQueue();
      final PbleFrame begin = transport.sentFrames.single;
      // Board promises the full length…
      transport.deliverFrame(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(data.length)),
      );
      await pumpEventQueue();

      // …but only a short prefix arrives; its CRC matches the prefix, so the
      // LENGTH check (not the CRC) is what must reject the truncated download.
      final Uint8List prefix = data.sublist(0, 4);
      transport.deliverFrame(
        evt(PbleOpcode.fileGetData, getDataPayload(0, prefix)),
      );
      transport.deliverFrame(
        evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(prefix))),
      );

      await expectLater(pending, throwsA(isA<ECrc>()));
    });
  });

  group('A-12 putFile — wire framing at window W (pacing lives in '
      'put_window_conformance_test.dart)', () {
    test('BEGIN [total][crc][plen][path], byte-exact PUT_DATA, END [crc], '
        'success only on RSP OK', () async {
      await handshake(chunk: 4);
      final Uint8List data = Uint8List.fromList(<int>[
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
      ]);
      final int crc = pbleCrc32(data);
      final List<TransferProgress> progress = <TransferProgress>[];

      final Future<void> pending = conn.putFile(
        '/up.bin',
        data,
        onProgress: progress.add,
      );
      await pumpEventQueue();

      // FILE_PUT_BEGIN [total][crc][plen][path]. This request framing is unique
      // to this suite — put_window_conformance_test.dart pins the pacing but
      // never decodes the BEGIN payload — and is unchanged by the A-13 window.
      final PbleFrame begin = sentOf(PbleOpcode.filePutBegin).single;
      final (int total, int beginCrc, String path) = decodePutBeginPayload(
        begin.payload,
      );
      expect(total, 10);
      expect(beginCrc, crc);
      expect(path, '/up.bin');

      transport.deliverFrame(
        rsp(PbleOpcode.filePutBegin, begin.id, putBeginOkPayload(0)),
      );
      await pumpEventQueue();

      // Each FILE_PUT_DATA is byte-exact for its offset. We assert FRAMING only,
      // NOT how many are outstanding — the ≤ W window bound is the A-13
      // increment, verified in put_window_conformance_test.dart AC-1.
      for (final PbleFrame f in sentOf(PbleOpcode.filePutData)) {
        final (int off, Uint8List bytes) = decodePutDataPayload(f.payload);
        final int end = (off + 4) < data.length ? off + 4 : data.length;
        expect(
          bytes,
          equals(Uint8List.sublistView(data, off, end)),
          reason: 'DATA bytes match the file slice at offset $off',
        );
      }

      // A single cumulative ACK to `total` retires the whole file (cumulative-
      // ACK semantics are exercised in depth by put_window AC-2); here we only
      // need the transfer to reach END so the framing + success gate can run.
      transport.deliverFrame(evt(PbleOpcode.filePutAck, putAckPayload(10)));
      await pumpEventQueue();

      // FILE_PUT_END [crc]; the FIRST send of each offset reproduces the file.
      final PbleFrame end = sentOf(PbleOpcode.filePutEnd).single;
      expect(readU32le(end.payload, 0), crc);
      final Map<int, Uint8List> firstByOffset = <int, Uint8List>{};
      for (final PbleFrame c in sentOf(PbleOpcode.filePutData)) {
        final (int off, Uint8List bytes) = decodePutDataPayload(c.payload);
        firstByOffset.putIfAbsent(off, () => bytes);
      }
      final List<int> reassembled = <int>[
        for (final int off in (firstByOffset.keys.toList()..sort()))
          ...firstByOffset[off]!,
      ];
      expect(reassembled, orderedEquals(data));

      // Success gate (AC-6, unchanged by the window): ONLY on FILE_PUT_END RSP OK.
      expect(sentOf(PbleOpcode.filePutEnd), hasLength(1));
      transport.deliverFrame(
        statusRsp(PbleOpcode.filePutEnd, end.id, PbleStatus.ok),
      );
      await pending;

      expect(progress.last.total, 10);
      expect(progress.last.sent, 10, reason: 'progress reaches 1.0 on success');
    });

    test('a PUT_END ECRC surfaces as typed ECrc (old file kept)', () async {
      await handshake(chunk: 8);
      final Uint8List data = Uint8List.fromList(<int>[9, 9, 9]);

      final Future<void> pending = conn.putFile('/up.bin', data);
      await pumpEventQueue();
      final PbleFrame begin = sentOf(PbleOpcode.filePutBegin).single;
      transport.deliverFrame(
        rsp(PbleOpcode.filePutBegin, begin.id, putBeginOkPayload(0)),
      );
      await pumpEventQueue();

      transport.deliverFrame(
        evt(PbleOpcode.filePutAck, putAckPayload(data.length)),
      );
      await pumpEventQueue();

      final PbleFrame end = sentOf(PbleOpcode.filePutEnd).single;
      transport.deliverFrame(
        statusRsp(PbleOpcode.filePutEnd, end.id, PbleStatus.eCrc),
      );
      await expectLater(pending, throwsA(isA<ECrc>()));
    });
  });

  group('A-12 delete / mkdir / rename encoding + status (protocol.md §5)', () {
    test('delete encodes FILE_DELETE [plen][path]; EACCES → EAcces', () async {
      final Future<void> pending = conn.delete('/dir');
      await pumpEventQueue();
      final PbleFrame sent = transport.sentFrames.single;
      expect(sent.opcode, PbleOpcode.fileDelete.code);
      expect(decodePathPayload(sent.payload), '/dir');
      transport.deliverFrame(
        statusRsp(PbleOpcode.fileDelete, sent.id, PbleStatus.eAcces),
      );
      await expectLater(
        pending,
        throwsA(isA<EAcces>()),
        reason: 'a non-empty dir is EACCES (no recursive delete)',
      );
    });

    test(
      'mkdir encodes MKDIR [plen][path]; existing dir → OK (idempotent)',
      () async {
        final Future<void> pending = conn.mkdir('/newdir');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.opcode, PbleOpcode.mkdir.code);
        expect(decodePathPayload(sent.payload), '/newdir');
        transport.deliverFrame(
          statusRsp(PbleOpcode.mkdir, sent.id, PbleStatus.ok),
        );
        await pending;
      },
    );

    test('mkdir over an existing file → EBadReq', () async {
      final Future<void> pending = conn.mkdir('/main.py');
      await pumpEventQueue();
      final PbleFrame sent = transport.sentFrames.single;
      transport.deliverFrame(
        statusRsp(PbleOpcode.mkdir, sent.id, PbleStatus.eBadReq),
      );
      await expectLater(pending, throwsA(isA<EBadReq>()));
    });

    test(
      'rename encodes FILE_RENAME [slen][src][dlen][dst]; ENOENT → ENoEnt',
      () async {
        final Future<void> pending = conn.rename('/a.py', '/b.py');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.opcode, PbleOpcode.fileRename.code);
        final (String src, String dst) = decodeRenamePayload(sent.payload);
        expect(src, '/a.py');
        expect(dst, '/b.py');
        transport.deliverFrame(
          statusRsp(PbleOpcode.fileRename, sent.id, PbleStatus.eNoEnt),
        );
        await expectLater(pending, throwsA(isA<ENoEnt>()));
      },
    );
  });

  group('A-12 single active transfer honoured client-side', () {
    test(
      'a 2nd transfer while one is active is refused with EBusy (no 2nd BEGIN)',
      () async {
        await handshake(chunk: 4);

        // Start a download and leave it in-flight (no RSP delivered).
        final Future<Uint8List> download = conn.getFile('/first.bin');
        await pumpEventQueue();
        expect(sentOf(PbleOpcode.fileGetBegin), hasLength(1));

        // A concurrent upload must be refused BEFORE any FILE_PUT_BEGIN is sent.
        await expectLater(
          conn.putFile('/second.bin', Uint8List.fromList(<int>[1, 2, 3])),
          throwsA(isA<EBusy>()),
        );
        expect(
          sentOf(PbleOpcode.filePutBegin),
          isEmpty,
          reason: 'the client never opens a 2nd transfer while one is active',
        );

        download.ignore(); // abandoned; disposed in tearDown
      },
    );
  });
}
