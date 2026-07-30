// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

const Map<String, Object?> _oldWorkspace = <String, Object?>{
  'blocks': <String, Object?>{
    'languageVersion': 0,
    'blocks': <Object?>[
      <String, Object?>{'type': 'text_print', 'id': 'old-print'},
    ],
  },
};

const Map<String, Object?> _candidateWorkspace = <String, Object?>{
  'blocks': <String, Object?>{
    'languageVersion': 0,
    'blocks': <Object?>[
      <String, Object?>{
        'type': 'text_print',
        'id': 'candidate-print',
        'x': 48,
        'y': 48,
      },
    ],
  },
};

String _snapshot(int revision, String source, Map<String, Object?> workspace) =>
    jsonEncode(<String, Object?>{
      'version': kBlocksBridgeVersion,
      'type': 'snapshot',
      'revision': revision,
      'source': source,
      'workspace': workspace,
    });

int _attach(
  BlocksDocumentController controller, {
  required int revision,
  required String source,
  required Map<String, Object?> workspace,
}) {
  final int host = controller.beginHost(
    requestSnapshot: (int requestId) async {},
  );
  controller.markHostLoading(host);
  controller.receiveBridgeMessage(
    _snapshot(revision, source, workspace),
    hostId: host,
  );
  return host;
}

void main() {
  ProviderContainer bind(RecordingConnection connection) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(connection)],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('Python candidate production-host review', () {
    test(
      'preview is provisional, non-actionable, and cancel restores prior data',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        _attach(
          controller,
          revision: 1,
          source: "print('old')\n",
          workspace: _oldWorkspace,
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);

        final Future<GeneratedProgram> staged = controller.stageWorkspaceReview(
          workspaceJson: jsonEncode(_candidateWorkspace),
          targetPath: '/main.py',
          replace: true,
        );
        expect(
          container.read(blocksDocumentProvider).workspaceReviewPending,
          isTrue,
        );
        expect(
          container.read(blocksDocumentProvider).hasRunnableProgram,
          isFalse,
        );

        final int candidateHost = _attach(
          controller,
          revision: 2,
          source: "print('candidate')\n",
          workspace: _candidateWorkspace,
        );
        final GeneratedProgram preview = await staged;
        expect(preview.source, "print('candidate')\n");
        expect(container.read(blocksDocumentProvider).targetPath, '/main.py');
        await expectLater(
          controller.previewSource(),
          throwsA(isA<BlocksBusy>()),
        );
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);

        controller.cancelWorkspaceReview();
        final BlocksDocument restored = container.read(blocksDocumentProvider);
        expect(restored.targetPath, before.targetPath);
        expect(restored.program, same(before.program));
        expect(restored.retainedWorkspaceJson, before.retainedWorkspaceJson);
        expect(
          restored.retainedWorkspaceRevision,
          before.retainedWorkspaceRevision,
        );
        expect(restored.workspaceReviewPending, isFalse);
        expect(restored.status, BlocksStatus.loading);
        expect(connection.putFileCalls, isEmpty);

        controller.receiveBridgeMessage(
          _snapshot(3, "print('late')\n", _candidateWorkspace),
          hostId: candidateHost,
        );
        expect(
          container.read(blocksDocumentProvider).retainedWorkspaceJson,
          before.retainedWorkspaceJson,
          reason: 'the cancelled host epoch must be ignored',
        );
      },
    );

    test(
      'commit adopts target and exact production-generated snapshot',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        _attach(
          controller,
          revision: 1,
          source: "print('old')\n",
          workspace: _oldWorkspace,
        );

        final Future<GeneratedProgram> staged = controller.stageWorkspaceReview(
          workspaceJson: jsonEncode(_candidateWorkspace),
          targetPath: '/lib/lesson.py',
          replace: true,
        );
        _attach(
          controller,
          revision: 2,
          source: "print('generated')\n",
          workspace: _candidateWorkspace,
        );
        final GeneratedProgram preview = await staged;
        controller.commitWorkspaceReview();

        final BlocksDocument committed = container.read(blocksDocumentProvider);
        expect(committed.targetPath, '/lib/lesson.py');
        expect(committed.program, same(preview));
        expect(committed.workspaceReviewPending, isFalse);
        expect(committed.hasRunnableProgram, isTrue);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.getFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
      },
    );

    test(
      'exact-sidecar source mismatch rolls back and refuses commit',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        _attach(
          controller,
          revision: 1,
          source: "print('old')\n",
          workspace: _oldWorkspace,
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);

        final Future<GeneratedProgram> staged = controller.stageWorkspaceReview(
          workspaceJson: jsonEncode(_candidateWorkspace),
          expectedSource: "print('exact')\n",
          targetPath: '/main.py',
          replace: true,
        );
        _attach(
          controller,
          revision: 2,
          source: "print('different')\n",
          workspace: _candidateWorkspace,
        );

        await expectLater(staged, throwsA(isA<BlocksGenerationFailed>()));
        expect(
          container.read(blocksDocumentProvider).retainedWorkspaceJson,
          before.retainedWorkspaceJson,
        );
        expect(
          () => controller.commitWorkspaceReview(),
          throwsA(isA<BlocksNotReady>()),
        );
        expect(connection.putFileCalls, isEmpty);
      },
    );

    test(
      'non-empty workspace requires explicit replacement even for preview',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        _attach(
          controller,
          revision: 1,
          source: "print('old')\n",
          workspace: _oldWorkspace,
        );

        expect(
          () => controller.stageWorkspaceReview(
            workspaceJson: jsonEncode(_candidateWorkspace),
            targetPath: '/main.py',
            replace: false,
          ),
          throwsA(isA<BlocksWorkspaceNotEmpty>()),
        );
        expect(connection.putFileCalls, isEmpty);
      },
    );
  });
}
