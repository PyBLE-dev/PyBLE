// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-11 [red] — RUN / STOP / SOFT_REBOOT / RUN_STATE / CONSOLE wire ops and the
// status→typed-exception map, driven over an in-memory [FakeByteTransport] (the
// Fake board). This exercises the REAL client stack (frame codec → fragmentation
// → PbleEngine → PbleConnection) end-to-end and asserts the client speaks the
// FROZEN + HIL-verified wire of protocol.md §6 (run/console) and §8 (status).
//
//   • runFile/runSource encode RUN 0x20 [mode][data] exactly (mode 0=file/1=src);
//   • a non-OK RUN RSP (EBUSY/EBADREQ/ERANGE) surfaces as the typed exception;
//   • a program-level failure is NOT a RSP error — the run Future still completes
//     OK; the failure arrives async as a stderr ConsoleEvent + RUN_STATE(error);
//   • RUN_STATE 0x40 EVTs drive Connection.runState idle→running→done, and once
//     the session is up ConnState collapses to `running` while runState==running;
//   • STOP 0x21 awaits an always-OK RSP; SOFT_REBOOT 0x22 is fire-then-expect-
//     disconnect (it MUST return without awaiting a guaranteed RSP);
//   • CONSOLE_DATA 0x30 stream 0/1 → stdout/stderr ConsoleEvents; the `system`
//     tag is client-synthesized and NEVER comes off the wire;
//   • CONSOLE_INPUT 0x31 is fire-and-forget — sendInput MUST NOT await a reply.
//
// CURRENTLY RED: PbleConnection has no runFile/runSource/stop/softReboot/
// runState/console/sendInput, no RunState/ConsoleEvent/ConsoleStream types, and
// pble_exception.dart has no per-status subtypes yet. HAND-OFF:
// `lib/pble/{pble_connection,connection,types,pble_exception}.dart` →
// app-protocol-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

/// A minimal HIL-shaped caps text so `handshake()` reaches `ConnState.ready`.
String _capsText({int chunk = 8}) => <String>[
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

  /// Drives HELLO to completion so the session is `ready`.
  Future<void> handshake({int chunk = 8}) async {
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

  group('A-11 RUN encoding + RSP status (protocol.md §6/§8)', () {
    test(
      'runFile encodes RUN [mode=0][UTF-8 path] and completes on RSP OK',
      () async {
        final Future<void> pending = conn.runFile('/main.py');
        await pumpEventQueue();

        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.type, Pble.typeCmd);
        expect(sent.opcode, PbleOpcode.run.code);
        final (int mode, Uint8List data) = decodeRunPayload(sent.payload);
        expect(mode, 0, reason: 'mode 0 = file (protocol.md §6)');
        expect(utf8.decode(data), '/main.py');

        transport.deliverFrame(
          statusRsp(PbleOpcode.run, sent.id, PbleStatus.ok),
        );
        await pending; // completes without error
      },
    );

    test('runSource encodes RUN [mode=1][UTF-8 snippet]', () async {
      final Future<void> pending = conn.runSource('print(1)');
      await pumpEventQueue();

      final PbleFrame sent = transport.sentFrames.single;
      expect(sent.opcode, PbleOpcode.run.code);
      final (int mode, Uint8List data) = decodeRunPayload(sent.payload);
      expect(mode, 1, reason: 'mode 1 = source snippet (protocol.md §6)');
      expect(utf8.decode(data), 'print(1)');

      transport.deliverFrame(statusRsp(PbleOpcode.run, sent.id, PbleStatus.ok));
      await pending;
    });

    test(
      'a RUN RSP of EBUSY surfaces as the typed EBusy (one already running)',
      () async {
        final Future<void> pending = conn.runFile('/main.py');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;
        transport.deliverFrame(
          statusRsp(PbleOpcode.run, sent.id, PbleStatus.eBusy),
        );
        await expectLater(pending, throwsA(isA<EBusy>()));
      },
    );

    test('a RUN RSP of EBADREQ (bad mode) surfaces as EBadReq', () async {
      final Future<void> pending = conn.runSource('x');
      await pumpEventQueue();
      final PbleFrame sent = transport.sentFrames.single;
      transport.deliverFrame(
        statusRsp(PbleOpcode.run, sent.id, PbleStatus.eBadReq),
      );
      await expectLater(pending, throwsA(isA<EBadReq>()));
    });

    test('a RUN RSP of ERANGE (over-length) surfaces as ERange', () async {
      final Future<void> pending = conn.runFile('/main.py');
      await pumpEventQueue();
      final PbleFrame sent = transport.sentFrames.single;
      transport.deliverFrame(
        statusRsp(PbleOpcode.run, sent.id, PbleStatus.eRange),
      );
      await expectLater(pending, throwsA(isA<ERange>()));
    });

    test(
      'a program-level failure is async, not a RSP error: run completes OK',
      () async {
        final List<RunState> states = <RunState>[];
        final List<ConsoleEvent> console = <ConsoleEvent>[];
        conn.runState.listen(states.add);
        conn.console.listen(console.add);

        final Future<void> pending = conn.runFile('/missing.py');
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;

        // The board accepts the RUN — the RSP is OK even for a file that will fail.
        transport.deliverFrame(
          statusRsp(PbleOpcode.run, sent.id, PbleStatus.ok),
        );
        await pending; // the run Future STILL completes OK (protocol.md §6)

        // The failure then arrives asynchronously (stderr traceback + error state).
        transport.deliverFrame(
          evt(
            PbleOpcode.consoleData,
            consoleDataPayload(1, utf8.encode('Traceback')),
          ),
        );
        transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(3)));
        await pumpEventQueue();

        expect(console.any((e) => e.stream == ConsoleStream.stderr), isTrue);
        expect(states, contains(RunState.error));
      },
    );
  });

  group('A-11 RUN_STATE stream + ConnState derivation (protocol.md §6)', () {
    test('RUN_STATE EVTs drive runState idle→running→done', () async {
      final List<RunState> states = <RunState>[];
      conn.runState.listen(states.add);

      transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(0)));
      transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(1)));
      transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(2)));
      await pumpEventQueue();

      expect(states, <RunState>[
        RunState.idle,
        RunState.running,
        RunState.done,
      ]);
    });

    test(
      'once the session is up, ConnState collapses to running iff runState==running',
      () async {
        await handshake();
        expect(conn.state.value, ConnState.ready);

        transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(1)));
        await pumpEventQueue();
        expect(
          conn.state.value,
          ConnState.running,
          reason:
              'ConnState.running is DERIVED from runState==running (TDD §5.1)',
        );

        transport.deliverFrame(evt(PbleOpcode.runState, runStatePayload(2)));
        await pumpEventQueue();
        expect(
          conn.state.value,
          ConnState.ready,
          reason:
              'done/idle collapse back to ready — ConnState never shows '
              'idle/done/error (that granularity lives on runState)',
        );
      },
    );
  });

  group('A-11 STOP / SOFT_REBOOT (protocol.md §6)', () {
    test(
      'stop() sends STOP with no payload and awaits an always-OK RSP',
      () async {
        final Future<void> pending = conn.stop();
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.opcode, PbleOpcode.stop.code);
        expect(sent.payload, isEmpty);
        transport.deliverFrame(
          statusRsp(PbleOpcode.stop, sent.id, PbleStatus.ok),
        );
        await pending;
      },
    );

    test(
      'softReboot() is fire-then-expect-disconnect: it does NOT await a RSP',
      () async {
        // No RSP is ever delivered. If softReboot awaited the engine RSP it would
        // hang until the 5 s engine timeout; the 500 ms guard then fails the test.
        await expectLater(
          conn.softReboot().timeout(const Duration(milliseconds: 500)),
          completes,
          reason:
              'the reset may preempt the RSP — softReboot must not await one',
        );
        await pumpEventQueue();
        expect(
          transport.sentFrames.any(
            (f) => f.opcode == PbleOpcode.softReboot.code,
          ),
          isTrue,
          reason: 'SOFT_REBOOT 0x22 is still sent (fire), just not awaited',
        );
      },
    );
  });

  group('A-11 CONSOLE stream + sendInput (protocol.md §6)', () {
    test('CONSOLE_DATA stream 0/1 → stdout/stderr ConsoleEvents', () async {
      final List<ConsoleEvent> events = <ConsoleEvent>[];
      conn.console.listen(events.add);

      transport.deliverFrame(
        evt(PbleOpcode.consoleData, consoleDataPayload(0, utf8.encode('out'))),
      );
      transport.deliverFrame(
        evt(PbleOpcode.consoleData, consoleDataPayload(1, utf8.encode('err'))),
      );
      await pumpEventQueue();

      expect(events, hasLength(2));
      expect(events[0].stream, ConsoleStream.stdout);
      expect(utf8.decode(events[0].bytes), 'out');
      expect(events[1].stream, ConsoleStream.stderr);
      expect(utf8.decode(events[1].bytes), 'err');
    });

    test(
      'the `system` console tag exists but NEVER comes off the wire',
      () async {
        // ConsoleStream carries a client-synthesized `system` tag for app-side
        // notices (TDD §5.2) — but CONSOLE_DATA only ever carries stdout(0)/stderr(1).
        expect(ConsoleStream.values, contains(ConsoleStream.system));

        final List<ConsoleEvent> events = <ConsoleEvent>[];
        conn.console.listen(events.add);
        transport.deliverFrame(
          evt(PbleOpcode.consoleData, consoleDataPayload(0, utf8.encode('x'))),
        );
        transport.deliverFrame(
          evt(PbleOpcode.consoleData, consoleDataPayload(1, utf8.encode('y'))),
        );
        await pumpEventQueue();

        expect(
          events.any((e) => e.stream == ConsoleStream.system),
          isFalse,
          reason:
              'system is client-synthesized, never decoded from CONSOLE_DATA',
        );
      },
    );

    test(
      'sendInput sends CONSOLE_INPUT and is fire-and-forget (no RSP awaited)',
      () async {
        await expectLater(
          conn.sendInput('name\n').timeout(const Duration(milliseconds: 500)),
          completes,
          reason:
              'CONSOLE_INPUT 0x31 has no reply frame — sendInput must not await',
        );
        await pumpEventQueue();

        final PbleFrame sent = transport.sentFrames.firstWhere(
          (f) => f.opcode == PbleOpcode.consoleInput.code,
        );
        expect(sent.type, Pble.typeCmd);
        expect(utf8.decode(sent.payload), 'name\n');
      },
    );
  });
}
