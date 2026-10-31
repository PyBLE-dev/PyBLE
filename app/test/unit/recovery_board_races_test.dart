// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/pble/pble.dart';
import '../support/recording_connection.dart';

class HeldConnection extends RecordingConnection
    implements ConnectionSessionStampSource {
  HeldConnection() : super(initial: ConnState.ready);
  Object stamp = Object();
  @override
  Object get connectionSessionStamp => stamp;
  final entered = Completer<void>();
  final release = Completer<void>();
  bool holdPut = true;
  bool holdGet = false;
  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    await super.putFile(path, bytes, onProgress: onProgress);
    if (holdPut) {
      if (!entered.isCompleted) entered.complete();
      await release.future;
    }
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async {
    final result = await super.getFile(path, onProgress: onProgress);
    if (holdGet) {
      if (!entered.isCompleted) entered.complete();
      await release.future;
    }
    return result;
  }
}

void main() {
  ProviderContainer bind(HeldConnection connection) {
    final c = ProviderContainer(
      overrides: [connectionProvider.overrideWithValue(connection)],
    );
    addTearDown(c.dispose);
    addTearDown(() {
      if (!connection.release.isCompleted) connection.release.complete();
    });
    return c;
  }

  test('Save completion cannot clear an edit-away/back revision', () async {
    final connection = HeldConnection();
    final c = bind(connection);
    final doc = c.read(editorDocumentProvider.notifier)..setContent('original');
    final save = c.read(saveControllerProvider).save();
    await connection.entered.future;
    doc.setContent('newer');
    doc.setContent('original');
    connection.release.complete();
    await save;
    expect(c.read(editorDocumentProvider).dirty, isTrue);
    expect(c.read(editorDocumentProvider).boardPath, isNull);
  });
  test('Run never dispatches second verb on a replaced attachment', () async {
    final connection = HeldConnection();
    final c = bind(connection);
    c.read(editorDocumentProvider.notifier).setContent('print(1)');
    final run = c.read(runControllerProvider).run();
    final result = expectLater(run, throwsA(isA<Exception>()));
    await connection.entered.future;
    connection.stamp = Object();
    connection.release.complete();
    await result;
    expect(connection.runFileCalls, isEmpty);
    expect(c.read(editorDocumentProvider).dirty, isTrue);
  });
  test(
    'Board Open refuses old GET after stable facade changes attachment',
    () async {
      final connection = HeldConnection()..holdPut = false;
      await connection.putFile(
        '/board.py',
        Uint8List.fromList(utf8.encode('old board')),
      );
      connection.holdGet = true;
      final c = bind(connection);
      final files = c.read(fileExplorerProvider.notifier);
      await pumpEventQueue();
      final open = files.openInEditor('board.py');
      await connection.entered.future;
      connection.stamp = Object();
      connection.release.complete();
      await open;
      expect(c.read(editorDocumentProvider).content, isEmpty);
      expect(c.read(editorDocumentProvider).boardPath, isNull);
    },
  );
  test(
    'Files upload completion cannot bind an edit-away/back revision',
    () async {
      final connection = HeldConnection();
      final c = bind(connection);
      final files = c.read(fileExplorerProvider.notifier);
      await pumpEventQueue();
      final doc = c.read(editorDocumentProvider.notifier)
        ..setContent('original');
      final upload = files.uploadCurrentBuffer();
      await connection.entered.future;
      doc.setContent('newer');
      doc.setContent('original');
      connection.release.complete();
      await upload;
      expect(c.read(editorDocumentProvider).dirty, isTrue);
      expect(c.read(editorDocumentProvider).boardPath, isNull);
    },
  );
}
