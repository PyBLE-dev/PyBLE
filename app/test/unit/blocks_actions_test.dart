// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

PutFileCall _pythonPut(RecordingConnection connection) => connection
    .putFileCalls
    .singleWhere((PutFileCall call) => call.path == kBlocksGeneratedPath);

PutFileCall _companionPut(RecordingConnection connection) =>
    connection.putFileCalls.singleWhere(
      (PutFileCall call) =>
          call.path == blocksCompanionPathFor(kBlocksGeneratedPath),
    );

String _snapshot(int revision, String source, {int? requestId}) => jsonEncode(
  <String, Object?>{
    'version': kBlocksBridgeVersion,
    'type': 'snapshot',
    'revision': revision,
    'source': source,
    'workspace': <String, Object?>{
      'blocks': <String, Object?>{'languageVersion': 0, 'blocks': <Object?>[]},
    },
    'requestId': ?requestId,
  },
);

int _attachHost(
  BlocksDocumentController controller, {
  required int revision,
  required String source,
}) {
  int nextRevision = revision + 1;
  late final int hostId;
  hostId = controller.beginHost(
    requestSnapshot: (int requestId) async {
      controller.receiveBridgeMessage(
        _snapshot(nextRevision++, source, requestId: requestId),
        hostId: hostId,
      );
    },
  );
  controller.markHostLoading(hostId);
  controller.receiveBridgeMessage(_snapshot(revision, source), hostId: hostId);
  return hostId;
}

class _HeldPutConnection extends RecordingConnection {
  _HeldPutConnection() : super(initial: ConnState.ready);

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
  ProviderContainer bind(
    RecordingConnection connection, {
    List<Override> extra = const <Override>[],
  }) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        connectionProvider.overrideWithValue(connection),
        ...extra,
      ],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('A-31 Blocks actions use the editor file-backed program seam', () {
    test('Save uploads the displayed revision to /blocks.py', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      const String source = 'for i in range(3):\n    print(i)\n';
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      _attachHost(controller, revision: 3, source: source);

      final String path = await controller.save();

      expect(path, kBlocksGeneratedPath);
      expect(connection.putFileCalls, hasLength(2));
      expect(utf8.decode(_pythonPut(connection).bytes), source);
      final BlocksCompanion companion = BlocksCompanion.parse(
        utf8.decode(_companionPut(connection).bytes),
      );
      expect(
        companion.matchesPython(path: kBlocksGeneratedPath, source: source),
        isTrue,
      );
      expect(connection.runFileCalls, isEmpty);
      expect(connection.runSourceCalls, isEmpty);
    });

    test('Run uploads the displayed revision then runs /blocks.py', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      const String source = 'print("from blocks")\n';
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      _attachHost(controller, revision: 1, source: source);

      await controller.run();

      expect(utf8.decode(_pythonPut(connection).bytes), source);
      expect(connection.putFileCalls, hasLength(2));
      expect(connection.operationLog, <String>[
        'putFile:/blocks.py',
        'putFile:/blocks.py.pyble-blocks.json',
        'runFile:/blocks.py',
      ]);
      expect(connection.runFileCalls, <String>[kBlocksGeneratedPath]);
      expect(connection.runSourceCalls, isEmpty);
    });

    test(
      'an action captures one immutable revision while the workspace changes',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
          steppedProgress: true,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int hostId = _attachHost(
          controller,
          revision: 1,
          source: 'print(2)\n',
        );

        final Future<String> save = controller.save();
        controller.receiveBridgeMessage(
          _snapshot(3, 'print(3)\n'),
          hostId: hostId,
        );
        await save;

        expect(
          utf8.decode(_pythonPut(connection).bytes),
          'print(2)\n',
          reason: 'the action must first acknowledge the current workspace',
        );
        expect(
          container.read(blocksDocumentProvider).program?.source,
          'print(3)\n',
          reason: 'later workspace edits remain the current visual snapshot',
        );
      },
    );

    test('bridge recovery never clears an in-flight board mutation', () async {
      final _HeldPutConnection connection = _HeldPutConnection();
      addTearDown(() {
        if (!connection.release.isCompleted) connection.release.complete();
      });
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = _attachHost(
        controller,
        revision: 4,
        source: 'print("held")\n',
      );

      final Future<String> save = controller.save();
      while (connection.putFileCalls.isEmpty) {
        await Future<void>.delayed(Duration.zero);
      }
      expect(container.read(blocksDocumentProvider).busy, isTrue);

      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'generator failed during upload',
        }),
        hostId: hostId,
      );
      expect(container.read(blocksDocumentProvider).busy, isTrue);

      controller.reportHostError('host failed during upload', hostId: hostId);
      expect(container.read(blocksDocumentProvider).busy, isTrue);

      controller.retry();
      expect(container.read(blocksDocumentProvider).busy, isTrue);
      await expectLater(controller.save(), throwsA(isA<BlocksBusy>()));

      connection.release.complete();
      await save;
      expect(container.read(blocksDocumentProvider).busy, isFalse);
    });

    test('Open in editor refuses a silent dirty-buffer replacement', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      container
          .read(editorDocumentProvider.notifier)
          .setContent('unsaved_text = True\n');
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      _attachHost(controller, revision: 1, source: 'print("blocks")\n');

      await expectLater(
        controller.openInEditor(),
        throwsA(isA<BlocksEditorConflict>()),
      );
      expect(
        container.read(editorDocumentProvider).content,
        'unsaved_text = True\n',
      );

      await controller.openInEditor(replaceDirty: true);
      final EditorDocument document = container.read(editorDocumentProvider);
      expect(document.name, kBlocksGeneratedName);
      expect(document.content, 'print("blocks")\n');
      expect(document.dirty, isTrue);
      expect(document.boardPath, isNull);
    });

    test(
      'Preview and Open acknowledge fresh source before consuming it',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        int revision = 1;
        late final int hostId;
        hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {
            controller.receiveBridgeMessage(
              _snapshot(++revision, 'print($revision)\n', requestId: requestId),
              hostId: hostId,
            );
          },
        );
        controller.markHostLoading(hostId);
        controller.receiveBridgeMessage(
          _snapshot(revision, 'print(1)\n'),
          hostId: hostId,
        );

        expect(await controller.previewSource(), 'print(2)\n');
        await controller.openInEditor();

        expect(container.read(editorDocumentProvider).content, 'print(3)\n');
      },
    );

    test('a generator error makes last-good source non-actionable', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = _attachHost(
        controller,
        revision: 1,
        source: 'print("stale")\n',
      );
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'generator failed',
        }),
        hostId: hostId,
      );

      expect(
        container.read(blocksDocumentProvider).hasRunnableProgram,
        isFalse,
      );
      await expectLater(
        controller.previewSource(),
        throwsA(isA<BlocksNotReady>()),
      );
      await expectLater(
        controller.openInEditor(),
        throwsA(isA<BlocksNotReady>()),
      );
      expect(connection.putFileCalls, isEmpty);
    });

    test('a fresh empty snapshot cannot be consumed by any action', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      late final int hostId;
      hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {
          controller.receiveBridgeMessage(
            _snapshot(2, '', requestId: requestId),
            hostId: hostId,
          );
        },
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        _snapshot(1, 'print("last nonempty")\n'),
        hostId: hostId,
      );

      await expectLater(controller.save(), throwsA(isA<BlocksNotReady>()));
      await expectLater(controller.run(), throwsA(isA<BlocksNotReady>()));
      await expectLater(
        controller.previewSource(),
        throwsA(isA<BlocksNotReady>()),
      );
      await expectLater(
        controller.openInEditor(),
        throwsA(isA<BlocksNotReady>()),
      );

      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
      expect(container.read(editorDocumentProvider).content, isEmpty);
      expect(container.read(blocksDocumentProvider).busy, isFalse);
    });

    test('all fresh-source consumers share one action lock', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final Completer<void> releaseRequest = Completer<void>();
      addTearDown(() {
        if (!releaseRequest.isCompleted) releaseRequest.complete();
      });
      int? requestedId;
      late final int hostId;
      hostId = controller.beginHost(
        requestSnapshot: (int requestId) {
          requestedId = requestId;
          return releaseRequest.future;
        },
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        _snapshot(1, 'print(1)\n'),
        hostId: hostId,
      );

      final Future<String> firstPreview = controller.previewSource();
      await expectLater(controller.openInEditor(), throwsA(isA<BlocksBusy>()));
      controller.receiveBridgeMessage(
        _snapshot(2, 'print(2)\n', requestId: requestedId),
        hostId: hostId,
      );
      releaseRequest.complete();

      expect(await firstPreview, 'print(2)\n');
      expect(container.read(blocksDocumentProvider).busy, isFalse);
    });

    test('only the matching request snapshot authorizes an action', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final Completer<void> releaseRequest = Completer<void>();
      addTearDown(() {
        if (!releaseRequest.isCompleted) releaseRequest.complete();
      });
      int? requestedId;
      late final int hostId;
      hostId = controller.beginHost(
        requestSnapshot: (int requestId) {
          requestedId = requestId;
          return releaseRequest.future;
        },
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        _snapshot(1, 'print(1)\n'),
        hostId: hostId,
      );

      final Future<String> save = controller.save();
      expect(requestedId, isNotNull);
      controller.receiveBridgeMessage(
        _snapshot(2, 'print(2)\n'),
        hostId: hostId,
      );
      controller.receiveBridgeMessage(
        _snapshot(3, 'print(3)\n', requestId: requestedId! + 1),
        hostId: hostId,
      );
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'wrong request',
          'requestId': requestedId! + 2,
        }),
        hostId: hostId,
      );
      controller.receiveBridgeMessage(
        _snapshot(4, 'print("old host")\n', requestId: requestedId),
        hostId: hostId - 1,
      );
      controller.receiveBridgeMessage(
        _snapshot(6, 'print(6)\n'),
        hostId: hostId,
      );
      await Future<void>.delayed(Duration.zero);
      expect(connection.putFileCalls, isEmpty);
      expect(container.read(blocksDocumentProvider).busy, isTrue);

      controller.receiveBridgeMessage(
        _snapshot(5, 'print(5)\n', requestId: requestedId),
        hostId: hostId,
      );
      releaseRequest.complete();
      await save;

      expect(utf8.decode(_pythonPut(connection).bytes), 'print(5)\n');
      expect(
        container.read(blocksDocumentProvider).program?.source,
        'print(6)\n',
        reason: 'a newer live snapshot stays retained after the frozen ACK',
      );
      expect(container.read(blocksDocumentProvider).busy, isFalse);
    });

    test(
      'a synchronous bridge error wins even when JavaScript never returns',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final Completer<void> hungRequest = Completer<void>();
        addTearDown(() {
          if (!hungRequest.isCompleted) hungRequest.complete();
        });
        late final int hostId;
        hostId = controller.beginHost(
          requestSnapshot: (int requestId) {
            controller.receiveBridgeMessage(
              jsonEncode(<String, Object?>{
                'version': kBlocksBridgeVersion,
                'type': 'error',
                'message': 'generator failed synchronously',
                'requestId': requestId,
              }),
              hostId: hostId,
            );
            return hungRequest.future;
          },
        );
        controller.markHostLoading(hostId);
        controller.receiveBridgeMessage(
          _snapshot(1, 'print("old")\n'),
          hostId: hostId,
        );

        await expectLater(
          controller.save(),
          throwsA(isA<BlocksGenerationFailed>()),
        );
        expect(container.read(blocksDocumentProvider).busy, isFalse);
        expect(connection.putFileCalls, isEmpty);
      },
    );

    test('disposing the host interrupts a pending snapshot request', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final Completer<void> hungRequest = Completer<void>();
      addTearDown(() {
        if (!hungRequest.isCompleted) hungRequest.complete();
      });
      late final int hostId;
      hostId = controller.beginHost(
        requestSnapshot: (int requestId) => hungRequest.future,
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        _snapshot(1, 'print("old")\n'),
        hostId: hostId,
      );

      final Future<String> save = controller.save();
      await Future<void>.delayed(Duration.zero);
      controller.endHost(hostId);

      await expectLater(save, throwsA(isA<BlocksHostUnavailable>()));
      expect(container.read(blocksDocumentProvider).busy, isFalse);
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'the timeout covers a JavaScript request that never returns',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(
          connection,
          extra: <Override>[
            blocksSnapshotTimeoutProvider.overrideWithValue(
              const Duration(milliseconds: 10),
            ),
          ],
        );
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final Completer<void> hungRequest = Completer<void>();
        addTearDown(() {
          if (!hungRequest.isCompleted) hungRequest.complete();
        });
        late final int hostId;
        hostId = controller.beginHost(
          requestSnapshot: (int requestId) => hungRequest.future,
        );
        controller.markHostLoading(hostId);
        controller.receiveBridgeMessage(
          _snapshot(1, 'print("old")\n'),
          hostId: hostId,
        );

        await expectLater(
          controller.run(),
          throwsA(isA<BlocksSnapshotTimeout>()),
        );
        expect(container.read(blocksDocumentProvider).busy, isFalse);
        expect(connection.putFileCalls, isEmpty);
      },
    );

    test('Save and Run reject an empty generated program', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      )..receiveBridgeMessage(_snapshot(1, ''));

      await expectLater(controller.save(), throwsA(isA<BlocksNotReady>()));
      await expectLater(controller.run(), throwsA(isA<BlocksNotReady>()));
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'typed board errors propagate and the generated snapshot is retained',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        _attachHost(controller, revision: 8, source: 'print(8)\n');
        connection.injectError(const ENoSpc('filesystem full'));

        await expectLater(controller.save(), throwsA(isA<ENoSpc>()));

        final BlocksDocument state = container.read(blocksDocumentProvider);
        expect(state.program?.revision, 9);
        expect(state.program?.source, 'print(8)\n');
        expect(state.busy, isFalse);
      },
    );
  });
}
