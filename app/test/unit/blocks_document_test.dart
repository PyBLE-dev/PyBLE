// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/pble/pble.dart';

String snapshot({
  int revision = 1,
  String source = 'print("hello")\n',
  Object workspace = const <String, Object?>{
    'blocks': <String, Object?>{'languageVersion': 0, 'blocks': <Object?>[]},
  },
}) => jsonEncode(<String, Object?>{
  'version': kBlocksBridgeVersion,
  'type': 'snapshot',
  'revision': revision,
  'source': source,
  'workspace': workspace,
});

String workspaceGenerationError({
  required int revision,
  required Object workspace,
  String message = 'generator failed',
}) => jsonEncode(<String, Object?>{
  'version': kBlocksBridgeVersion,
  'type': 'error',
  'message': message,
  'revision': revision,
  'workspace': workspace,
});

void main() {
  ProviderContainer bind() {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        connectionProvider.overrideWithValue(
          FakeConnection(initial: ConnState.ready),
        ),
      ],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('A-31 Blocks bridge snapshot boundary', () {
    test('starts loading and adopts a valid versioned snapshot', () {
      final ProviderContainer container = bind();
      expect(
        container.read(blocksDocumentProvider).status,
        BlocksStatus.loading,
      );

      container
          .read(blocksDocumentProvider.notifier)
          .receiveBridgeMessage(snapshot(revision: 7));

      final BlocksDocument state = container.read(blocksDocumentProvider);
      expect(state.status, BlocksStatus.ready);
      expect(state.program?.revision, 7);
      expect(state.program?.source, 'print("hello")\n');
      expect(
        jsonDecode(state.program!.workspaceJson),
        isA<Map<String, Object?>>(),
      );
      expect(state.error, isNull);
    });

    test('ignores stale snapshots after a newer revision', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );

      controller.receiveBridgeMessage(
        snapshot(revision: 4, source: 'print(4)\n'),
      );
      controller.receiveBridgeMessage(
        snapshot(revision: 3, source: 'print(3)\n'),
      );

      expect(
        container.read(blocksDocumentProvider).program?.source,
        'print(4)\n',
      );
    });

    test(
      'contains malformed, unknown-version, and non-object workspace data',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );

        for (final String message in <String>[
          '{',
          jsonEncode(<String, Object?>{
            'version': 99,
            'type': 'snapshot',
            'revision': 1,
            'source': '',
            'workspace': <String, Object?>{},
          }),
          snapshot(workspace: <Object?>[]),
        ]) {
          controller.retry();
          expect(
            () => controller.receiveBridgeMessage(message),
            returnsNormally,
            reason: 'platform messages are an untrusted boundary',
          );
          expect(
            container.read(blocksDocumentProvider).status,
            BlocksStatus.error,
          );
          expect(container.read(blocksDocumentProvider).error, isNotEmpty);
        }
      },
    );

    test('rejects an oversized bridge message without throwing', () {
      final ProviderContainer container = bind();
      final String tooLarge = List<String>.filled(
        kMaxBlocksBridgeMessageBytes + 1,
        'x',
      ).join();

      expect(
        () => container
            .read(blocksDocumentProvider.notifier)
            .receiveBridgeMessage(tooLarge),
        returnsNormally,
      );
      expect(container.read(blocksDocumentProvider).status, BlocksStatus.error);
    });

    test('a bridge error retains the last valid generated snapshot', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      controller.receiveBridgeMessage(snapshot(revision: 2));

      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'generator failed',
        }),
      );

      final BlocksDocument state = container.read(blocksDocumentProvider);
      expect(state.status, BlocksStatus.ready);
      expect(state.program?.revision, 2);
      expect(state.error, isNull);
      expect(state.workspaceError, contains('generator failed'));
    });

    test(
      'a first generation error is ready, retained, and later repairable',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);
        const Map<String, Object?> incompleteWorkspace = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'pyble_gpio_write', 'id': 'write'},
            ],
          },
        };

        final BlocksBridgeResult result = controller.receiveBridgeMessage(
          workspaceGenerationError(
            revision: 7,
            workspace: incompleteWorkspace,
            message: 'GPIO write requires a Pin input',
          ),
          hostId: hostId,
        );

        final BlocksDocument state = container.read(blocksDocumentProvider);
        expect(result, BlocksBridgeResult.workspaceError);
        expect(state.status, BlocksStatus.ready);
        expect(state.program, isNull);
        expect(state.error, isNull);
        expect(state.workspaceError, contains('requires a Pin'));
        expect(state.hasRunnableProgram, isFalse);
        expect(controller.hasActiveReadyHost, isTrue);

        expect(state.retainedWorkspaceRevision, 7);
        expect(jsonDecode(state.retainedWorkspaceJson!), incompleteWorkspace);

        const Map<String, Object?> repairedWorkspace = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[],
          },
        };
        expect(
          controller.receiveBridgeMessage(
            snapshot(
              revision: 8,
              source: 'print("repaired")\n',
              workspace: repairedWorkspace,
            ),
            hostId: hostId,
          ),
          BlocksBridgeResult.snapshotAccepted,
        );

        final BlocksDocument repaired = container.read(blocksDocumentProvider);
        expect(repaired.workspaceError, isNull);
        expect(repaired.program?.source, 'print("repaired")\n');
        expect(repaired.retainedWorkspaceRevision, 8);
        expect(jsonDecode(repaired.retainedWorkspaceJson!), repairedWorkspace);
      },
    );

    test(
      'generation errors retain repair JSON apart from last valid source',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);
        const Map<String, Object?> validWorkspace = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[],
          },
        };
        controller.receiveBridgeMessage(
          snapshot(
            revision: 10,
            source: 'print("last valid")\n',
            workspace: validWorkspace,
          ),
          hostId: hostId,
        );
        final GeneratedProgram lastValid = container
            .read(blocksDocumentProvider)
            .program!;
        const Map<String, Object?> incompleteWorkspace = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'pyble_gpio_read', 'id': 'read'},
            ],
          },
        };

        expect(
          controller.receiveBridgeMessage(
            workspaceGenerationError(
              revision: 11,
              workspace: incompleteWorkspace,
              message: 'GPIO read requires a Pin input',
            ),
            hostId: hostId,
          ),
          BlocksBridgeResult.workspaceError,
        );

        final BlocksDocument invalid = container.read(blocksDocumentProvider);
        expect(
          invalid.program,
          same(lastValid),
          reason:
              'inspectable source must keep representing its matching valid '
              'workspace, not the newer invalid composition',
        );
        expect(invalid.hasRunnableProgram, isFalse);
        expect(invalid.workspaceError, contains('requires a Pin'));
        expect(invalid.retainedWorkspaceRevision, 11);
        expect(jsonDecode(invalid.retainedWorkspaceJson!), incompleteWorkspace);

        expect(
          controller.receiveBridgeMessage(
            snapshot(
              revision: 11,
              source: 'print("same revision must stay stale")\n',
            ),
            hostId: hostId,
          ),
          BlocksBridgeResult.staleSnapshot,
          reason: 'a repair must be newer than the retained invalid workspace',
        );
        expect(
          container.read(blocksDocumentProvider).workspaceError,
          isNotNull,
        );

        expect(
          controller.receiveBridgeMessage(
            snapshot(
              revision: 12,
              source: 'print("fixed")\n',
              workspace: validWorkspace,
            ),
            hostId: hostId,
          ),
          BlocksBridgeResult.snapshotAccepted,
        );
        final BlocksDocument repaired = container.read(blocksDocumentProvider);
        expect(repaired.workspaceError, isNull);
        expect(repaired.program?.source, 'print("fixed")\n');
        expect(repaired.retainedWorkspaceRevision, 12);
        expect(jsonDecode(repaired.retainedWorkspaceJson!), validWorkspace);
      },
    );

    test('a stale workspace error does not replace a newer valid revision', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        snapshot(revision: 10, source: 'print("current")\n'),
        hostId: hostId,
      );

      final BlocksBridgeResult result = controller.receiveBridgeMessage(
        workspaceGenerationError(
          revision: 9,
          workspace: const <String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[
                <String, Object?>{'type': 'pyble_gpio_write', 'id': 'stale'},
              ],
            },
          },
        ),
        hostId: hostId,
      );

      final BlocksDocument state = container.read(blocksDocumentProvider);
      expect(result, BlocksBridgeResult.staleSnapshot);
      expect(state.program?.source, 'print("current")\n');
      expect(state.retainedWorkspaceRevision, 10);
      expect(state.workspaceError, isNull);
      expect(state.hasRunnableProgram, isTrue);
      expect(controller.hasActiveReadyHost, isTrue);
    });

    test(
      'an error before the first host snapshot is a retryable load error',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);

        final BlocksBridgeResult result = controller.receiveBridgeMessage(
          jsonEncode(<String, Object?>{
            'version': kBlocksBridgeVersion,
            'type': 'error',
            'message': 'Blockly failed to initialise',
          }),
          hostId: hostId,
        );

        final BlocksDocument state = container.read(blocksDocumentProvider);
        expect(result, BlocksBridgeResult.hostError);
        expect(state.status, BlocksStatus.error);
        expect(state.error, contains('failed to initialise'));
        expect(state.workspaceError, isNull);
        expect(controller.hasActiveReadyHost, isFalse);
      },
    );

    test(
      'a new host is loading and ignores delayed messages from an old host',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int oldHost = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(oldHost);
        controller.receiveBridgeMessage(
          snapshot(revision: 8, source: 'print("old retained")\n'),
          hostId: oldHost,
        );
        expect(
          container.read(blocksDocumentProvider).status,
          BlocksStatus.ready,
        );

        final int newHost = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(newHost);
        expect(
          container.read(blocksDocumentProvider).status,
          BlocksStatus.loading,
          reason: 'retained source must not enable actions before restore',
        );

        controller.receiveBridgeMessage(
          snapshot(revision: 9, source: 'print("late old host")\n'),
          hostId: oldHost,
        );
        expect(
          container.read(blocksDocumentProvider).status,
          BlocksStatus.loading,
        );

        final BlocksBridgeResult result = controller.receiveBridgeMessage(
          snapshot(revision: 9, source: 'print("restored new host")\n'),
          hostId: newHost,
        );
        final BlocksDocument state = container.read(blocksDocumentProvider);
        expect(result, BlocksBridgeResult.snapshotAccepted);
        expect(state.status, BlocksStatus.ready);
        expect(state.program?.source, 'print("restored new host")\n');
        expect(controller.hasActiveReadyHost, isTrue);
      },
    );

    test('same-host reload clears readiness but retains restore state', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        snapshot(revision: 8, source: 'print("retained")\n'),
        hostId: hostId,
      );
      expect(controller.hasActiveReadyHost, isTrue);

      controller.markHostLoading(hostId);

      final BlocksDocument loading = container.read(blocksDocumentProvider);
      expect(loading.status, BlocksStatus.loading);
      expect(loading.retainedWorkspaceRevision, 8);
      expect(loading.program?.source, 'print("retained")\n');
      expect(
        controller.hasActiveReadyHost,
        isFalse,
        reason: 'preview actions must wait for the reloaded renderer snapshot',
      );

      expect(
        controller.receiveBridgeMessage(
          snapshot(revision: 8, source: 'print("stale")\n'),
          hostId: hostId,
        ),
        BlocksBridgeResult.staleSnapshot,
      );
      expect(controller.hasActiveReadyHost, isFalse);
      expect(
        container.read(blocksDocumentProvider).status,
        BlocksStatus.loading,
      );

      expect(
        controller.receiveBridgeMessage(
          snapshot(revision: 9, source: 'print("restored")\n'),
          hostId: hostId,
        ),
        BlocksBridgeResult.snapshotAccepted,
      );
      expect(controller.hasActiveReadyHost, isTrue);
      expect(
        container.read(blocksDocumentProvider).program?.source,
        'print("restored")\n',
      );
    });

    test(
      'a dismissed transient preview host restores the exact prior document',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);
        final int transientHost = controller.beginHost(
          requestSnapshot: (int requestId) async {},
          previewExample: (String workspaceJson) async => BlocksExamplePreview(
            source: 'print("preview")\n',
            workspaceJson: workspaceJson,
          ),
        );
        controller.markHostLoading(transientHost);
        controller.receiveBridgeMessage(
          snapshot(revision: 1, source: 'print("host initialised")\n'),
          hostId: transientHost,
        );
        expect(container.read(blocksDocumentProvider), isNot(same(before)));

        controller.restoreAfterTransientPreviewHost(before);

        expect(container.read(blocksDocumentProvider), same(before));
        expect(controller.hasActiveReadyHost, isFalse);
        expect(
          controller.receiveBridgeMessage(
            snapshot(revision: 2, source: 'print("late")\n'),
            hostId: transientHost,
          ),
          BlocksBridgeResult.ignored,
        );
        controller.endHost(transientHost);
        expect(container.read(blocksDocumentProvider), same(before));
      },
    );

    test('a retained-revision first message stays loading for restore', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int oldHost = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(oldHost);
      controller.receiveBridgeMessage(snapshot(revision: 42), hostId: oldHost);

      final int restoredHost = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(restoredHost);
      final BlocksBridgeResult stale = controller.receiveBridgeMessage(
        snapshot(revision: 1, source: 'print("unrestored")\n'),
        hostId: restoredHost,
      );

      expect(stale, BlocksBridgeResult.staleSnapshot);
      expect(
        container.read(blocksDocumentProvider).status,
        BlocksStatus.loading,
      );
      expect(controller.hasActiveReadyHost, isFalse);
    });

    test('rejects revisions outside the cross-language safe bound', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );

      controller.receiveBridgeMessage(
        snapshot(revision: kMaxBlocksRevision + 1),
      );

      expect(container.read(blocksDocumentProvider).status, BlocksStatus.error);
      expect(
        container.read(blocksDocumentProvider).error,
        contains('revision'),
      );
    });

    test(
      'retry returns to loading and increments the platform-host attempt',
      () {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        controller.reportHostError('WebView failed');
        final int firstAttempt = container
            .read(blocksDocumentProvider)
            .loadAttempt;

        controller.retry();

        final BlocksDocument state = container.read(blocksDocumentProvider);
        expect(state.status, BlocksStatus.loading);
        expect(state.error, isNull);
        expect(state.loadAttempt, firstAttempt + 1);
      },
    );

    test('Start fresh clears an unrecoverable retained workspace', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      controller.receiveBridgeMessage(snapshot(revision: 7));
      final int hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'retained workspace cannot be restored',
        }),
        hostId: hostId,
      );
      final int failedAttempt = container
          .read(blocksDocumentProvider)
          .loadAttempt;

      controller.startFresh();

      final BlocksDocument cleared = container.read(blocksDocumentProvider);
      expect(cleared.status, BlocksStatus.loading);
      expect(cleared.program, isNull);
      expect(cleared.error, isNull);
      expect(cleared.loadAttempt, failedAttempt + 1);

      final int freshHost = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(freshHost);
      controller.receiveBridgeMessage(
        snapshot(revision: 1, source: ''),
        hostId: freshHost,
      );
      expect(container.read(blocksDocumentProvider).status, BlocksStatus.ready);
    });
  });
}
