// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/editor/board_target_guard.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/pble/pble.dart';
import '../support/recording_connection.dart';

class SessionConnection extends RecordingConnection
    implements ConnectionSessionStampSource {
  SessionConnection() : super(initial: ConnState.ready);
  Object stamp = Object();
  @override
  Object get connectionSessionStamp => stamp;
}

void main() {
  ProviderContainer setup(
    SessionConnection connection,
    Future<bool> Function(BoardTargetRequest)? confirm,
  ) {
    final c = ProviderContainer(
      overrides: [
        connectionProvider.overrideWithValue(connection),
        boardTargetConfirmationProvider.overrideWithValue(confirm),
      ],
    );
    addTearDown(c.dispose);
    c
        .read(editorDocumentProvider.notifier)
        .openGenerated(name: 'restored.py', content: 'print(1)');
    c.read(editorRecoveredDraftProvider.notifier).state = true;
    return c;
  }

  test('missing or declined consent sends no Save or Run board verb', () async {
    for (final confirm in <Future<bool> Function(BoardTargetRequest)?>[
      null,
      (_) async => false,
    ]) {
      final connection = SessionConnection();
      final c = setup(connection, confirm);
      await expectLater(
        c.read(saveControllerProvider).save(),
        throwsA(isA<BoardActionCancelled>()),
      );
      await expectLater(
        c.read(runControllerProvider).run(),
        throwsA(isA<BoardActionCancelled>()),
      );
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
    }
  });
  test(
    'Save confirms actual path; Run confirms write and execution separately',
    () async {
      final requests = <BoardTargetRequest>[];
      final connection = SessionConnection();
      final c = setup(connection, (request) async {
        requests.add(request);
        return true;
      });
      await c.read(saveControllerProvider).save();
      await c.read(runControllerProvider).run();
      expect(requests.map((r) => r.path), ['/restored.py', '/restored.py']);
      expect(requests.map((r) => r.run), [false, true]);
      expect(connection.runFileCalls, ['/restored.py']);
    },
  );
  test(
    'session or edit-away/back while confirmation is open revokes consent',
    () async {
      for (final changeSession in [true, false]) {
        final choice = Completer<bool>();
        final asked = Completer<void>();
        final connection = SessionConnection();
        final c = setup(connection, (_) {
          asked.complete();
          return choice.future;
        });
        final save = c.read(saveControllerProvider).save();
        final result = expectLater(save, throwsA(isA<BoardActionCancelled>()));
        await asked.future;
        if (changeSession) {
          connection.stamp = Object();
        } else {
          final doc = c.read(editorDocumentProvider.notifier);
          doc.setContent('changed');
          doc.setContent('print(1)');
        }
        choice.complete(true);
        await result;
        expect(connection.putFileCalls, isEmpty);
      }
    },
  );
  test(
    'Files Upload previews cwd destination and declining sends no PUT',
    () async {
      final requests = <BoardTargetRequest>[];
      final connection = SessionConnection();
      final c = setup(connection, (request) async {
        requests.add(request);
        return false;
      });
      final files = c.read(fileExplorerProvider.notifier);
      await pumpEventQueue();
      await connection.mkdir('/lib');
      await files.into('lib');
      await files.uploadCurrentBuffer();
      expect(requests.single.path, '/lib/restored.py');
      expect(requests.single.run, isFalse);
      expect(connection.putFileCalls, isEmpty);
    },
  );
  test(
    'changing Files destination while consent is pending cancels the upload',
    () async {
      final choice = Completer<bool>();
      final asked = Completer<void>();
      final connection = SessionConnection();
      final c = setup(connection, (_) {
        asked.complete();
        return choice.future;
      });
      final files = c.read(fileExplorerProvider.notifier);
      await pumpEventQueue();
      await connection.mkdir('/other');
      final upload = files.uploadCurrentBuffer();
      await asked.future;
      await files.into('other');
      choice.complete(true);
      await upload;
      expect(connection.putFileCalls, isEmpty);
    },
  );
}
