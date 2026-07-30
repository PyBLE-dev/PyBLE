// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-21 [red] — the working-loop console buffer provider (ADR-0010, TDD §11.6c,
// specs.md FR-CONSOLE §4.7). A capped ring subscribed to Connection.console,
// alive independent of the console widget so output is captured even before the
// Console surface is first opened and survives tab/nav switches (FR-CONSOLE-5/7).
//
// Pins the frozen contract:
//   consoleBufferProvider = NotifierProvider<ConsoleBufferController, List<ConsoleEvent>>
//     build(): subscribes connectionProvider.console; appends; caps at
//              kConsoleMaxEvents (oldest-dropped ring).
//     clear()            -> empties the ring
//     sendInput(String)  -> connectionProvider.sendInput(text)  (fire-and-forget)
//   const int kConsoleMaxEvents = 4000;
//
// CURRENTLY RED: lib/console exports no consoleBufferProvider / kConsoleMaxEvents.
// HAND-OFF: lib/console/console_controller.dart -> app-editor-console-engineer.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

void main() {
  ProviderContainer bind(Connection c) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(c)],
    );
    addTearDown(container.dispose);
    // Keep the buffer alive + subscribed from an always-mounted point (as the
    // shell does), so it captures output before the Console surface is opened.
    container.listen(consoleBufferProvider, (_, _) {});
    return container;
  }

  group('A-21 consoleBufferProvider — captures the live console stream', () {
    test('appends stdout / stderr / system events in order', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = bind(fake);

      fake.emitConsole(ConsoleStream.stdout, utf8.encode('hello\n'));
      fake.emitConsole(ConsoleStream.stderr, utf8.encode('Traceback\n'));
      fake.emitConsole(ConsoleStream.system, utf8.encode('reconnected'));
      await pumpEventQueue();

      final List<ConsoleEvent> events = c.read(consoleBufferProvider);
      expect(events.map((ConsoleEvent e) => e.stream), <ConsoleStream>[
        ConsoleStream.stdout,
        ConsoleStream.stderr,
        ConsoleStream.system,
      ]);
      expect(utf8.decode(events.first.bytes), 'hello\n');
      expect(utf8.decode(events.last.bytes), 'reconnected');
    });

    test('caps at kConsoleMaxEvents, dropping the oldest (ring)', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = bind(fake);

      const int overflow = 5;
      final int total = kConsoleMaxEvents + overflow;
      for (int i = 0; i < total; i++) {
        fake.emitConsole(ConsoleStream.stdout, utf8.encode('e$i'));
      }
      await pumpEventQueue();

      final List<ConsoleEvent> events = c.read(consoleBufferProvider);
      expect(
        events.length,
        kConsoleMaxEvents,
        reason: 'the ring is capped at kConsoleMaxEvents',
      );
      // The first `overflow` events were dropped; the oldest retained is e#overflow.
      expect(utf8.decode(events.first.bytes), 'e$overflow');
      expect(utf8.decode(events.last.bytes), 'e${total - 1}');
    });

    test('clear() empties the ring', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = bind(fake);

      fake.emitConsole(ConsoleStream.stdout, utf8.encode('noise\n'));
      await pumpEventQueue();
      expect(c.read(consoleBufferProvider), isNotEmpty);

      c.read(consoleBufferProvider.notifier).clear();
      expect(c.read(consoleBufferProvider), isEmpty);
    });
  });

  group('A-21 consoleBufferProvider — stdin passthrough', () {
    test(
      'sendInput forwards to Connection.sendInput (fire-and-forget)',
      () async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer c = bind(rec);

        await c.read(consoleBufferProvider.notifier).sendInput('name\n');
        expect(rec.sendInputCalls, <String>['name\n']);
      },
    );
  });
}
