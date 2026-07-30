// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-11 [red] — the FROZEN protocol.md §8 status table maps to twelve DISTINCT
// outcomes: OK (no exception) + eleven distinct typed PbleException subtypes, one
// per non-OK code, so callers can branch on the failure (FR-PBLE-13, TDD §8.7/
// §14.1). The map is table-driven and SHARED by run + file ops.
//
// The mapping is asserted through the OBSERVABLE Connection surface (a FILE_DELETE
// round-trip over the Fake board) rather than a private factory, so it stays a
// black-box conformance check; a spot-check proves the SAME EBusy type surfaces
// from a RUN, i.e. the table is shared.
//
// CURRENTLY RED: pble_exception.dart still has the S2 catch-all
// PbleStatusException instead of the eleven §8 subtypes (EBadReq..EInternal) and
// BleLinkException. HAND-OFF: `lib/pble/{pble_exception,pble_connection}.dart` →
// app-protocol-engineer. (The S2 catch-all is REPLACED per the frozen contract;
// PbleCrcException stays until A-13/S4 rewires the codec drop to ECrc.)

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

/// Runs a FILE_DELETE and returns whatever it threw (or `null` on OK) after the
/// board replies [status].
Future<Object?> deleteWithStatus(PbleStatus status) async {
  final FakeByteTransport transport = FakeByteTransport(mtu: Pble.mtuRequest);
  final PbleEngine engine = PbleEngine(transport);
  final PbleConnection conn = PbleConnection(
    engine: engine,
    appName: 'PyBLE',
    appVersion: '0.1.0',
  );
  try {
    final Future<void> pending = conn.delete('/x.py');
    await pumpEventQueue();
    final PbleFrame sent = transport.sentFrames.single;
    expect(sent.opcode, PbleOpcode.fileDelete.code);
    transport.deliverFrame(statusRsp(PbleOpcode.fileDelete, sent.id, status));
    await pending;
    return null;
  } catch (e) {
    return e;
  } finally {
    await conn.dispose();
    await transport.dispose();
  }
}

void main() {
  group('A-11 §8 status → typed exception (protocol.md §8, TDD §14.1)', () {
    test('0x00 OK → no exception (the op succeeds)', () async {
      expect(await deleteWithStatus(PbleStatus.ok), isNull);
    });

    // One distinct final subtype per non-OK §8 code (TDD §14.1).
    final Map<PbleStatus, Matcher> cases = <PbleStatus, Matcher>{
      PbleStatus.eBadReq: isA<EBadReq>(),
      PbleStatus.eNoEnt: isA<ENoEnt>(),
      PbleStatus.eAcces: isA<EAcces>(),
      PbleStatus.eNoSpc: isA<ENoSpc>(),
      PbleStatus.eIo: isA<EIo>(),
      PbleStatus.eNoMem: isA<ENoMem>(),
      PbleStatus.eBusy: isA<EBusy>(),
      PbleStatus.eCrc: isA<ECrc>(),
      PbleStatus.eRange: isA<ERange>(),
      PbleStatus.eUnsupported: isA<EUnsupported>(),
      PbleStatus.eInternal: isA<EInternal>(),
    };

    cases.forEach((PbleStatus status, Matcher matcher) {
      test('0x${status.code.toRadixString(16).padLeft(2, '0')} ${status.name} '
          '→ its distinct typed exception', () async {
        final Object? thrown = await deleteWithStatus(status);
        expect(thrown, isNotNull);
        expect(thrown, isA<PbleException>());
        expect(thrown, matcher);
      });
    });

    test('every non-OK code maps to a DISTINCT type (11 unique)', () async {
      final Set<Type> types = <Type>{};
      for (final PbleStatus status in cases.keys) {
        final Object? thrown = await deleteWithStatus(status);
        types.add(thrown.runtimeType);
      }
      expect(
        types,
        hasLength(cases.length),
        reason: 'no two §8 codes may collapse to the same Dart type',
      );
    });
  });

  group('A-11 the table is SHARED by run + file ops (TDD §8.7)', () {
    test(
      'a RUN answering EBUSY throws the SAME EBusy type as a file op',
      () async {
        final FakeByteTransport transport = FakeByteTransport(
          mtu: Pble.mtuRequest,
        );
        final PbleEngine engine = PbleEngine(transport);
        final PbleConnection conn = PbleConnection(
          engine: engine,
          appName: 'PyBLE',
          appVersion: '0.1.0',
        );
        addTearDown(() async {
          await conn.dispose();
          await transport.dispose();
        });

        final Future<void> pending = conn.runFile('/main.py');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;
        transport.deliverFrame(
          statusRsp(PbleOpcode.run, sent.id, PbleStatus.eBusy),
        );
        await expectLater(pending, throwsA(isA<EBusy>()));
      },
    );
  });

  group('A-11 link/transport failure type (TDD §14.1)', () {
    test('BleLinkException is a neutral typed PbleException', () {
      expect(const BleLinkException('link dropped'), isA<PbleException>());
    });
  });
}
