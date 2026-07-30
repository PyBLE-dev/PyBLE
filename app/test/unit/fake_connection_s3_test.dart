// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-11 / A-12 [red] — the shipped no-BLE FakeConnection gains the S3 Connection
// members and their scripting surface (FR-CONN-7, TDD §5.3), so every new verb
// is exercisable in widget/unit suites without a board. S3 adds only what
// A-11/A-12 need; the identity verbs + full error-injection/progress POLISH are
// the A-14/S4 shipped-FakeConnection freeze.
//
//   • a driveable runState (emitRunState) with ConnState.running DERIVED so
//     widget tests see the collapse;
//   • a programmable console script (emitConsole) incl. the client-synthesized
//     `system` tag;
//   • an in-memory file tree backing putFile/getFile/listDir/mkdir/rename/delete
//     with monotonic ProgressCb;
//   • an error-injection hook so any method can throw a chosen PbleException;
//   • runFile completes OK even when the scripted program then fails async;
//   • softReboot scripts a disconnect → reconnect (fire-then-expect-disconnect).
//
// CURRENTLY RED: FakeConnection has none of the S3 members/scripting, and the
// RunState / ConsoleEvent / ConsoleStream / RemoteEntry / TransferProgress types
// and the §8 exception subtypes do not exist. HAND-OFF:
// `lib/pble/{fake_connection,connection,types,pble_exception}.dart` →
// app-protocol-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/pble.dart';

void main() {
  group('A-11 FakeConnection — run state + ConnState derivation', () {
    test(
      'emitRunState drives runState and collapses ConnState.running',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        final List<RunState> states = <RunState>[];
        fake.runState.listen(states.add);

        fake.emitRunState(RunState.running);
        await pumpEventQueue();
        expect(
          fake.state.value,
          ConnState.running,
          reason: 'ConnState.running is derived while runState==running',
        );

        fake.emitRunState(RunState.done);
        await pumpEventQueue();
        expect(
          fake.state.value,
          ConnState.ready,
          reason: 'done collapses back to ready — ConnState never shows done',
        );

        expect(states, <RunState>[RunState.running, RunState.done]);
      },
    );
  });

  group('A-11 FakeConnection — console script', () {
    test(
      'emitConsole pushes stdout/stderr AND the synthesized system tag',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        final List<ConsoleEvent> events = <ConsoleEvent>[];
        fake.console.listen(events.add);

        fake.emitConsole(ConsoleStream.stdout, utf8.encode('hi\n'));
        fake.emitConsole(ConsoleStream.stderr, utf8.encode('Traceback\n'));
        fake.emitConsole(ConsoleStream.system, utf8.encode('run finished'));
        await pumpEventQueue();

        expect(events.map((e) => e.stream), <ConsoleStream>[
          ConsoleStream.stdout,
          ConsoleStream.stderr,
          ConsoleStream.system,
        ]);
        expect(utf8.decode(events.last.bytes), 'run finished');
      },
    );

    test(
      'a run completes OK even when the program then fails asynchronously',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        final List<RunState> states = <RunState>[];
        final List<ConsoleEvent> console = <ConsoleEvent>[];
        fake.runState.listen(states.add);
        fake.console.listen(console.add);

        await fake.runFile('/missing.py'); // completes OK (the RSP was OK)

        // The failure arrives asynchronously (scripted stderr + error state).
        fake.emitConsole(ConsoleStream.stderr, utf8.encode('Traceback'));
        fake.emitRunState(RunState.error);
        await pumpEventQueue();

        expect(states, contains(RunState.error));
        expect(console.any((e) => e.stream == ConsoleStream.stderr), isTrue);
      },
    );
  });

  group('A-12 FakeConnection — in-memory file tree', () {
    test(
      'putFile → getFile round-trips and listDir reflects the write',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        final Uint8List bytes = Uint8List.fromList(utf8.encode('print(1)\n'));

        await fake.putFile('/main.py', bytes);
        final Uint8List got = await fake.getFile('/main.py');
        expect(got, equals(bytes));

        final List<RemoteEntry> entries = await fake.listDir('/');
        expect(entries.map((e) => e.name), contains('main.py'));
        final RemoteEntry entry = entries.firstWhere(
          (e) => e.name == 'main.py',
        );
        expect(entry.isDir, isFalse);
        expect(entry.size, bytes.length);
      },
    );

    test('mkdir / rename / delete mutate the tree', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);

      await fake.mkdir('/lib');
      await fake.putFile('/a.py', Uint8List.fromList(<int>[1]));
      await fake.rename('/a.py', '/b.py');
      await fake.delete('/lib');

      final List<RemoteEntry> entries = await fake.listDir('/');
      final Set<String> names = entries.map((e) => e.name).toSet();
      expect(names, contains('b.py'));
      expect(names, isNot(contains('a.py')));
      expect(names, isNot(contains('lib')));
    });

    test('getFile / putFile report monotonic progress to completion', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      final Uint8List bytes = Uint8List.fromList(List<int>.filled(64, 7));

      final List<TransferProgress> up = <TransferProgress>[];
      await fake.putFile('/big.bin', bytes, onProgress: up.add);
      expect(up, isNotEmpty);
      for (int i = 1; i < up.length; i++) {
        expect(up[i].sent, greaterThanOrEqualTo(up[i - 1].sent));
      }
      expect(up.last.sent, up.last.total);
      expect(up.last.total, bytes.length);

      final List<TransferProgress> down = <TransferProgress>[];
      await fake.getFile('/big.bin', onProgress: down.add);
      expect(down.last.sent, down.last.total);
    });
  });

  group('A-11/A-12 FakeConnection — error injection + fire-and-forget', () {
    test(
      'injectError makes the next op throw the chosen PbleException',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);

        fake.injectError(const EBusy('a program is already running'));
        await expectLater(fake.runFile('/main.py'), throwsA(isA<EBusy>()));

        // One-shot: the next call succeeds again.
        await fake.runFile('/main.py');
      },
    );

    test('sendInput is fire-and-forget (completes, never throws)', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await expectLater(fake.sendInput('name\n'), completes);
    });

    test('softReboot scripts a disconnect → reconnect', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      final List<ConnState> seen = <ConnState>[];
      fake.state.addListener(() => seen.add(fake.state.value));

      await fake.softReboot();
      for (int i = 0; i < 8; i++) {
        await pumpEventQueue();
      }

      expect(
        seen,
        contains(ConnState.disconnected),
        reason: 'the board resets and the link drops',
      );
      expect(
        fake.state.value,
        ConnState.ready,
        reason: 'the A-03 reconnect path brings it back up',
      );
    });
  });
}
