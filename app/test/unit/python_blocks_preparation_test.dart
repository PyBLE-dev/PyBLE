// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

const Map<String, Object?> _workspace = <String, Object?>{
  'blocks': <String, Object?>{
    'languageVersion': 0,
    'blocks': <Object?>[
      <String, Object?>{
        'type': 'text_print',
        'id': 'exact-print',
        'x': 48,
        'y': 48,
      },
    ],
  },
};

void main() {
  ProviderContainer bind(RecordingConnection connection) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(connection)],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('Python Blocks preparation', () {
    test('unsaved source imports locally with zero board I/O', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      container
          .read(editorDocumentProvider.notifier)
          .setContent('x = 1\nprint(x)\n');
      final EditorDocument captured = container.read(editorDocumentProvider);

      final PythonBlocksPreparation result = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(captured, readCompanion: true);

      expect(result.origin, PythonBlocksPreparationOrigin.importedPython);
      expect(result.workspaceJson, isNotNull);
      expect(result.expectedSource, isNull);
      expect(result.semanticFingerprint, isNotNull);
      expect(result.targetPath, '/untitled.py');
      expect(result.capturedDocument, same(captured));
      expect(result.diagnostics, isEmpty);
      expect(connection.getFileCalls, isEmpty);
      expect(connection.putFileCalls, isEmpty);
    });

    test('valid adjacent companion wins and binds exact source', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      const String source = "print('exact')\n";
      const String path = '/main.py';
      final BlocksCompanion companion = BlocksCompanion.create(
        pythonPath: path,
        pythonSource: source,
        workspaceJson: jsonEncode(_workspace),
      );
      await connection.putFile(
        blocksCompanionPathFor(path),
        Uint8List.fromList(utf8.encode(companion.encode())),
      );
      connection.putFileCalls.clear();
      connection.operationLog.clear();
      container
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: path, content: source);
      final EditorDocument captured = container.read(editorDocumentProvider);

      final PythonBlocksPreparation result = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(captured, readCompanion: true);

      expect(result.origin, PythonBlocksPreparationOrigin.exactCompanion);
      expect(result.expectedSource, source);
      expect(result.semanticFingerprint, isNull);
      expect(result.targetPath, path);
      expect(jsonDecode(result.workspaceJson!), _workspace);
      expect(result.companionIssue, isNull);
      expect(connection.getFileCalls, <String>['/main.py.pyble-blocks.json']);
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'stale companion is reported and falls back to strict local import',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        const String path = '/main.py';
        final BlocksCompanion companion = BlocksCompanion.create(
          pythonPath: path,
          pythonSource: 'print("old")\n',
          workspaceJson: jsonEncode(_workspace),
        );
        await connection.putFile(
          blocksCompanionPathFor(path),
          Uint8List.fromList(utf8.encode(companion.encode())),
        );
        connection.putFileCalls.clear();
        container
            .read(editorDocumentProvider.notifier)
            .openFromBoard(path: path, content: 'print("new")\n');
        final EditorDocument captured = container.read(editorDocumentProvider);

        final PythonBlocksPreparation result = await container
            .read(pythonBlocksPreparationProvider)
            .prepare(captured, readCompanion: true);

        expect(result.origin, PythonBlocksPreparationOrigin.importedPython);
        expect(result.expectedSource, isNull);
        expect(result.workspaceJson, isNotNull);
        expect(
          result.companionIssue,
          PythonBlocksCompanionIssue.sourceMismatch,
        );
        expect(connection.putFileCalls, isEmpty);
      },
    );

    test('unsupported Python yields diagnostics and no candidate', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      container
          .read(editorDocumentProvider.notifier)
          .setContent('import machine\n');
      final EditorDocument captured = container.read(editorDocumentProvider);

      final PythonBlocksPreparation result = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(captured);

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'unsupported_import');
      expect(connection.getFileCalls, isEmpty);
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'oversized companion is rejected before UTF-8 decoding and imports locally',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        const String path = '/main.py';
        await connection.putFile(
          blocksCompanionPathFor(path),
          Uint8List(kMaxBlocksCompanionBytes + 1)
            ..fillRange(0, kMaxBlocksCompanionBytes + 1, 0xff),
        );
        connection.putFileCalls.clear();
        container
            .read(editorDocumentProvider.notifier)
            .openFromBoard(path: path, content: 'print("safe")\n');
        final EditorDocument captured = container.read(editorDocumentProvider);

        final PythonBlocksPreparation result = await container
            .read(pythonBlocksPreparationProvider)
            .prepare(captured, readCompanion: true);

        expect(result.origin, PythonBlocksPreparationOrigin.importedPython);
        expect(result.workspaceJson, isNotNull);
        expect(result.semanticFingerprint, isNotNull);
        expect(result.companionIssue, PythonBlocksCompanionIssue.invalid);
        expect(connection.putFileCalls, isEmpty);
      },
    );

    test('Editor conversion never reads an adjacent companion', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      container
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: 'print("local")\n');
      final EditorDocument captured = container.read(editorDocumentProvider);

      final PythonBlocksPreparation result = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(captured);

      expect(result.origin, PythonBlocksPreparationOrigin.importedPython);
      expect(result.workspaceJson, isNotNull);
      expect(connection.getFileCalls, isEmpty);
    });

    test('invalid target fails before parsing or board I/O', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      const EditorDocument captured = EditorDocument(
        name: 'main.py',
        content: 'print("never parsed")\n',
        dirty: false,
        boardPath: '/../main.py',
      );

      final PythonBlocksPreparation result = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(captured, readCompanion: true);

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'invalid_target_path');
      expect(connection.getFileCalls, isEmpty);
    });
  });
}
