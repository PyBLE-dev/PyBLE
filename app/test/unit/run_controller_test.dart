// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-16 [red] — the working-loop run-control providers (ADR-0010, TDD §11.6b/e,
// specs.md FR-RUN §4.8). Availability derives from ConnState + RunState; the
// controller runs the current buffer / a board file, stops, and soft-reboots
// through the Connection seam ONLY (FR-RUN-4), so it is exercisable against a
// FakeConnection with no board.
//
// Pins the frozen contract:
//   RunAvailability { bool canRun, canStop, canSoftReboot, isRunning }
//   runAvailabilityProvider = Provider<RunAvailability>
//     canRun        = ConnState.ready
//     canStop       = ConnState.running
//     canSoftReboot = ConnState.ready || ConnState.running
//     isRunning     = ConnState.running
//   runControllerProvider = Provider<RunController>
//     run()             -> putFile(currentDocument.path, content)
//                       -> runFile(currentDocument.path)
//     runFile(path)     -> runFile(path)
//     stop()            -> stop()
//     softReboot()      -> softReboot()
//   EBusy from run()/runFile() is NEVER swallowed (surfaced by the shell as
//   runBusyMessage — FR-RUN-3).
//   runStateProvider = StreamProvider<RunState> off Connection.runState (seam).
//
// CURRENTLY RED: lib/editor exports no RunAvailability / runAvailabilityProvider
// / RunController / runControllerProvider; lib/app/providers.dart has no
// runStateProvider. HAND-OFF: lib/editor/run_controller.dart ->
// app-editor-console-engineer; lib/app/providers.dart (runStateProvider) ->
// app-architect.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

class _HeldRunConnection extends RecordingConnection {
  _HeldRunConnection() : super(initial: ConnState.ready);

  final Completer<void> release = Completer<void>();

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    await super.putFile(path, bytes, onProgress: onProgress);
    await release.future;
  }
}

void main() {
  ProviderContainer bind(Connection c) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(c)],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('A-16 runAvailabilityProvider — derived from ConnState', () {
    void expectAvailability(
      ConnState state, {
      required bool canRun,
      required bool canStop,
      required bool canSoftReboot,
      required bool isRunning,
    }) {
      final ProviderContainer c = bind(FakeConnection(initial: state));
      final RunAvailability a = c.read(runAvailabilityProvider);
      expect(a.canRun, canRun, reason: 'canRun @ $state');
      expect(a.canStop, canStop, reason: 'canStop @ $state');
      expect(a.canSoftReboot, canSoftReboot, reason: 'canSoftReboot @ $state');
      expect(a.isRunning, isRunning, reason: 'isRunning @ $state');
    }

    test('disconnected disables every run action', () {
      expectAvailability(
        ConnState.disconnected,
        canRun: false,
        canStop: false,
        canSoftReboot: false,
        isRunning: false,
      );
    });

    test('connecting disables every run action', () {
      expectAvailability(
        ConnState.connecting,
        canRun: false,
        canStop: false,
        canSoftReboot: false,
        isRunning: false,
      );
    });

    test('ready enables Run + Soft-reboot, not Stop', () {
      expectAvailability(
        ConnState.ready,
        canRun: true,
        canStop: false,
        canSoftReboot: true,
        isRunning: false,
      );
    });

    test('running enables Stop + Soft-reboot, disables Run', () {
      expectAvailability(
        ConnState.running,
        canRun: false,
        canStop: true,
        canSoftReboot: true,
        isRunning: true,
      );
    });

    test(
      'reacts live: ready -> running (Run off, Stop on) -> done (Run on)',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        final ProviderContainer c = bind(fake);
        // Keep the derived provider subscribed so it recomputes on run events.
        c.listen(runAvailabilityProvider, (_, _) {});

        expect(c.read(runAvailabilityProvider).canRun, isTrue);

        fake.emitRunState(RunState.running);
        await pumpEventQueue();
        final RunAvailability running = c.read(runAvailabilityProvider);
        expect(
          running.canRun,
          isFalse,
          reason: 'Run disabled while running (FR-RUN-3)',
        );
        expect(running.canStop, isTrue);
        expect(running.isRunning, isTrue);

        fake.emitRunState(RunState.done);
        await pumpEventQueue();
        expect(
          c.read(runAvailabilityProvider).canRun,
          isTrue,
          reason: 'done collapses back to ready → Run re-enabled',
        );
      },
    );
  });

  group('A-16 RunController — verbs go through the Connection seam', () {
    test(
      'run() uploads and executes the current editor buffer as a file',
      () async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer c = bind(rec);
        c.read(editorDocumentProvider.notifier).newDocument();
        c.read(editorDocumentProvider.notifier).setContent('print(42)\n');

        await c.read(runControllerProvider).run();

        expect(rec.putFileCalls.single.path, '/untitled.py');
        expect(
          String.fromCharCodes(rec.putFileCalls.single.bytes),
          'print(42)\n',
        );
        expect(rec.runFileCalls, <String>['/untitled.py']);
        expect(rec.runSourceCalls, isEmpty);
      },
    );

    test('runFile(path) runs a board file directly', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      await c.read(runControllerProvider).runFile('/main.py');

      expect(rec.runFileCalls, <String>['/main.py']);
      expect(rec.runSourceCalls, isEmpty);
    });

    test(
      'run completion cannot clear or rebind a document opened mid-upload',
      () async {
        final _HeldRunConnection rec = _HeldRunConnection();
        addTearDown(() {
          if (!rec.release.isCompleted) rec.release.complete();
        });
        final ProviderContainer c = bind(rec);
        c
            .read(editorDocumentProvider.notifier)
            .setContent('print("uploaded")\n');

        final Future<void> run = c.read(runControllerProvider).run();
        while (rec.putFileCalls.isEmpty) {
          await Future<void>.delayed(Duration.zero);
        }
        c
            .read(editorDocumentProvider.notifier)
            .openGenerated(name: 'other.py', content: 'print("keep dirty")\n');
        rec.release.complete();
        await run;

        final EditorDocument current = c.read(editorDocumentProvider);
        expect(current.name, 'other.py');
        expect(current.content, 'print("keep dirty")\n');
        expect(current.dirty, isTrue);
        expect(current.boardPath, isNull);
        expect(rec.runFileCalls, <String>['/untitled.py']);
      },
    );

    test('stop() and softReboot() delegate to the seam', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.running,
      );
      final ProviderContainer c = bind(rec);

      await c.read(runControllerProvider).stop();
      await c.read(runControllerProvider).softReboot();

      expect(rec.stopCalls, 1);
      expect(rec.softRebootCalls, 1);
    });

    test('run() never swallows EBusy (surfaced honestly, FR-RUN-3)', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);
      c.read(editorDocumentProvider.notifier).setContent('while True: pass\n');
      rec.injectError(const EBusy('a program is already running'));

      await expectLater(
        c.read(runControllerProvider).run(),
        throwsA(isA<EBusy>()),
        reason: 'EBusy must propagate so the shell can show runBusyMessage',
      );
    });
  });

  group('A-16 runStateProvider — seam stream (lib/app/providers.dart)', () {
    test('mirrors Connection.runState events', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = bind(fake);
      c.listen(runStateProvider, (_, _) {});

      fake.emitRunState(RunState.running);
      await pumpEventQueue();
      expect(c.read(runStateProvider).value, RunState.running);

      fake.emitRunState(RunState.error);
      await pumpEventQueue();
      expect(c.read(runStateProvider).value, RunState.error);
    });
  });

  group('A-25 RunController — normalizes before sending to the board', () {
    test('curly quotes in the buffer are converted before upload', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      c
          .read(editorDocumentProvider.notifier)
          .setContent('print(\u201cHello\u201d)\n');
      await c.read(runControllerProvider).run();

      expect(
        String.fromCharCodes(rec.putFileCalls.single.bytes),
        'print("Hello")\n',
        reason: 'Run must never ship bytes MicroPython cannot tokenize',
      );
      expect(
        c.read(editorDocumentProvider).content,
        'print("Hello")\n',
        reason: 'the buffer is corrected too, so screen and board agree',
      );
    });

    test('clean ASCII is passed through unchanged', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      c.read(editorDocumentProvider.notifier).setContent('print(1)\n');
      await c.read(runControllerProvider).run();

      expect(String.fromCharCodes(rec.putFileCalls.single.bytes), 'print(1)\n');
      expect(rec.runFileCalls, <String>['/untitled.py']);
    });
  });
}
