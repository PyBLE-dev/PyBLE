// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

/// Literal responsive-layout keys: these are intentionally owned by the public
/// widget-test contract, so layout regressions cannot be hidden behind private
/// widget-type changes.
const ValueKey<String> _generatedPythonInspectorKey = ValueKey<String>(
  'blocksGeneratedPythonInspector',
);
const ValueKey<String> _workspaceStatusKey = ValueKey<String>(
  'blocksWorkspaceStatus',
);
const ValueKey<String> _workspaceHostKey = ValueKey<String>(
  'blocksWorkspaceHost-0',
);

String _snapshot(String source, {int revision = 1, int? requestId}) =>
    jsonEncode(<String, Object?>{
      'version': kBlocksBridgeVersion,
      'type': 'snapshot',
      'revision': revision,
      'source': source,
      'workspace': <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[],
        },
      },
      'requestId': ?requestId,
    });

Override _fakeWorkspace() => blocksWorkspaceBuilderProvider.overrideWithValue(
  (Key key) => SizedBox.expand(key: key),
);

int _attachHost(
  ProviderContainer container, {
  required String source,
  int revision = 1,
}) {
  final BlocksDocumentController controller = container.read(
    blocksDocumentProvider.notifier,
  );
  int nextRevision = revision + 1;
  late final int hostId;
  hostId = controller.beginHost(
    requestSnapshot: (int requestId) async {
      controller.receiveBridgeMessage(
        _snapshot(source, revision: nextRevision++, requestId: requestId),
        hostId: hostId,
      );
    },
  );
  controller.markHostLoading(hostId);
  controller.receiveBridgeMessage(
    _snapshot(source, revision: revision),
    hostId: hostId,
  );
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

final class _SessionChangedProgramActions extends ProgramActions {
  _SessionChangedProgramActions(super.ref, this.nextOperation);

  final ProgramBundleNextOperation nextOperation;

  Never _fail(String path, String companionPath) {
    throw ProgramBundleSessionChanged(
      sourcePath: path,
      companionPath: companionPath,
      nextOperation: nextOperation,
    );
  }

  @override
  Future<String> saveSourceBundle({
    required String path,
    required String source,
    required String companionPath,
    required String companionJson,
    ProgressCb? onProgress,
  }) async => _fail(path, companionPath);

  @override
  Future<void> runSourceBundle({
    required String path,
    required String source,
    required String companionPath,
    required String companionJson,
    ProgressCb? onProgress,
  }) async => _fail(path, companionPath);
}

void _expectStatusRowAboveWorkspace(
  WidgetTester tester, {
  Key statusKey = _workspaceStatusKey,
}) {
  final Finder status = find.byKey(statusKey);
  final Finder workspace = find.byKey(_workspaceHostKey);

  expect(status, findsOneWidget);
  expect(workspace, findsOneWidget);
  expect(
    find.ancestor(of: status, matching: find.byType(Positioned)),
    findsNothing,
    reason: 'workspace guidance is normal layout, never a canvas overlay',
  );

  final Rect statusRect = tester.getRect(status);
  final Rect workspaceRect = tester.getRect(workspace);
  expect(
    statusRect.bottom,
    lessThanOrEqualTo(workspaceRect.top),
    reason: 'the status row must end before the editable workspace begins',
  );
  expect(
    statusRect.overlaps(workspaceRect),
    isFalse,
    reason: 'empty and generator notices must not obscure Blockly controls',
  );
}

void main() {
  group('A-31 BlocksView', () {
    testWidgets(
      'shows a fakeable loading host without creating a platform view',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const BlocksView(),
          connection: connection,
          extra: <Override>[_fakeWorkspace()],
        );

        expect(
          find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
          findsOneWidget,
        );
        expect(find.text('Loading Blocks…'), findsOneWidget);
        expect(find.bySemanticsLabel('Loading Blocks…'), findsOneWidget);
        expect(
          find.bySemanticsLabel('Visual block workspace'),
          findsNothing,
          reason: 'blocked platform-view semantics must not leak through',
        );
        expect(find.byKey(kBlocksRunButtonKey), findsOneWidget);
        expect(
          tester.widget<IconButton>(find.byKey(kBlocksRunButtonKey)).onPressed,
          isNull,
        );
        _expectStatusRowAboveWorkspace(tester);
      },
    );

    testWidgets('ready empty workspace stays editable and shows its hint', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      containerOf(tester)
          .read(blocksDocumentProvider.notifier)
          .receiveBridgeMessage(_snapshot(''));
      await tester.pump();
      final AppLocalizations l10n = l10nOf(tester);

      expect(find.text(l10n.blocksExamplesEmptyTitle), findsOneWidget);
      expect(find.text(l10n.blocksExamplesEmptyDetail), findsOneWidget);
      expect(find.text(l10n.blocksExamplesOpen), findsOneWidget);
      expect(find.bySemanticsLabel('Visual block workspace'), findsOneWidget);
      expect(find.byKey(kBlocksRetryButtonKey), findsNothing);
      expect(
        tester.widget<IconButton>(find.byKey(kBlocksPreviewButtonKey)).tooltip,
        l10n.blocksEmptyHint,
      );
      _expectStatusRowAboveWorkspace(
        tester,
        statusKey: const ValueKey<String>('blocksEmptyExamplesPrompt'),
      );
    });

    testWidgets('previews the exact generated Python as selectable text', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      _attachHost(containerOf(tester), source: 'print("inspect me")\n');
      await tester.pump();

      await tester.tap(find.byKey(kBlocksPreviewButtonKey));
      await tester.pumpAndSettle();

      expect(find.text('Generated Python'), findsOneWidget);
      expect(
        find.byWidgetPredicate(
          (Widget widget) =>
              widget is SelectableText &&
              widget.data == 'print("inspect me")\n',
        ),
        findsOneWidget,
      );
    });

    testWidgets(
      'wide layout keeps the exact retained Python visible in an inspector',
      (WidgetTester tester) async {
        const String source = 'print("wide inspector")\n';
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const BlocksView(),
          connection: connection,
          extra: <Override>[_fakeWorkspace()],
          size: const Size(1280, 800),
        );
        _attachHost(containerOf(tester), source: source);
        await tester.pump();

        final Finder inspector = find.byKey(_generatedPythonInspectorKey);
        expect(inspector, findsOneWidget);
        expect(
          find.descendant(
            of: inspector,
            matching: find.byWidgetPredicate(
              (Widget widget) =>
                  widget is SelectableText && widget.data == source,
            ),
          ),
          findsOneWidget,
          reason:
              'the persistent inspector must show the exact retained bridge '
              'snapshot, including its trailing newline',
        );
        final Finder sourceView = find.descendant(
          of: inspector,
          matching: find.byWidgetPredicate(
            (Widget widget) =>
                widget is SelectableText && widget.data == source,
          ),
        );
        expect(
          find.ancestor(
            of: sourceView,
            matching: find.byWidgetPredicate(
              (Widget widget) =>
                  widget is SingleChildScrollView &&
                  widget.scrollDirection == Axis.horizontal,
            ),
          ),
          findsOneWidget,
          reason: 'generated Python must preserve long source lines',
        );

        final Rect inspectorRect = tester.getRect(inspector);
        final Rect workspaceRect = tester.getRect(
          find.byKey(_workspaceHostKey),
        );
        expect(
          inspectorRect.overlaps(workspaceRect),
          isFalse,
          reason: 'the generated-source inspector must not cover the canvas',
        );
      },
    );

    testWidgets(
      'wide generator error does not present stale Python as current output',
      (WidgetTester tester) async {
        const String staleSource = 'print("last valid")\n';
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const BlocksView(),
          connection: connection,
          extra: <Override>[_fakeWorkspace()],
          size: const Size(1280, 800),
        );
        final ProviderContainer container = containerOf(tester);
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        final int hostId = _attachHost(container, source: staleSource);
        controller.receiveBridgeMessage(
          jsonEncode(<String, Object?>{
            'version': kBlocksBridgeVersion,
            'type': 'error',
            'message': 'GPIO write requires a Pin input',
            'revision': 2,
            'workspace': <String, Object?>{
              'blocks': <String, Object?>{
                'languageVersion': 0,
                'blocks': <Object?>[
                  <String, Object?>{
                    'type': 'pyble_gpio_write',
                    'id': 'incomplete',
                  },
                ],
              },
            },
          }),
          hostId: hostId,
        );
        await tester.pump();

        final Finder inspector = find.byKey(_generatedPythonInspectorKey);
        expect(inspector, findsOneWidget);
        expect(
          find.descendant(
            of: inspector,
            matching: find.byWidgetPredicate(
              (Widget widget) =>
                  widget is SelectableText && widget.data == staleSource,
            ),
          ),
          findsNothing,
        );
        expect(
          find.descendant(
            of: inspector,
            matching: find.text('Generated Python will appear here.'),
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets('wide empty workspace does not duplicate its action hint', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
        size: const Size(1280, 800),
      );
      containerOf(tester)
          .read(blocksDocumentProvider.notifier)
          .receiveBridgeMessage(_snapshot(''));
      await tester.pump();
      final AppLocalizations l10n = l10nOf(tester);

      expect(find.text(l10n.blocksExamplesEmptyTitle), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(_generatedPythonInspectorKey),
          matching: find.text('Generated Python will appear here.'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('narrow layout omits the persistent Python inspector', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
        size: const Size(800, 600),
      );
      _attachHost(containerOf(tester), source: 'print("compact")\n');
      await tester.pump();

      expect(find.byKey(_generatedPythonInspectorKey), findsNothing);
      expect(find.byKey(_workspaceHostKey), findsOneWidget);
      expect(find.byKey(kBlocksPreviewButtonKey), findsOneWidget);
    });

    testWidgets('Save and Run use the displayed source through Connection', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      _attachHost(containerOf(tester), source: 'print("go")\n');
      await tester.pump();

      await tester.tap(find.byKey(kBlocksSaveButtonKey));
      await tester.pumpAndSettle();
      expect(
        connection.putFileCalls.map((PutFileCall call) => call.path),
        <String>[
          kBlocksGeneratedPath,
          '$kBlocksGeneratedPath.pyble-blocks.json',
        ],
      );
      expect(find.text('Saved /blocks.py'), findsOneWidget);

      await tester.tap(find.byKey(kBlocksRunButtonKey));
      await tester.pumpAndSettle();
      expect(
        connection.putFileCalls.map((PutFileCall call) => call.path),
        <String>[
          kBlocksGeneratedPath,
          '$kBlocksGeneratedPath.pyble-blocks.json',
          kBlocksGeneratedPath,
          '$kBlocksGeneratedPath.pyble-blocks.json',
        ],
      );
      expect(connection.runFileCalls, <String>[kBlocksGeneratedPath]);
    });

    for (final ({
          ProgramBundleNextOperation nextOperation,
          bool run,
          String name,
        })
        scenario
        in <
          ({ProgramBundleNextOperation nextOperation, bool run, String name})
        >[
          (
            nextOperation: ProgramBundleNextOperation.writeCompanion,
            run: false,
            name: 'localizes a board change before the companion write',
          ),
          (
            nextOperation: ProgramBundleNextOperation.runFile,
            run: true,
            name: 'localizes a board change before Run',
          ),
        ]) {
      testWidgets(scenario.name, (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const BlocksView(),
          connection: connection,
          extra: <Override>[
            _fakeWorkspace(),
            programActionsProvider.overrideWith(
              (Ref ref) =>
                  _SessionChangedProgramActions(ref, scenario.nextOperation),
            ),
          ],
        );
        _attachHost(containerOf(tester), source: 'print("session")\n');
        await tester.pump();
        final AppLocalizations l10n = l10nOf(tester);

        await tester.tap(
          find.byKey(scenario.run ? kBlocksRunButtonKey : kBlocksSaveButtonKey),
        );
        await tester.pumpAndSettle();

        final String reason = switch (scenario.nextOperation) {
          ProgramBundleNextOperation.writeCompanion =>
            l10n.blocksBundleSessionChangedBeforeCompanion(
              kBlocksGeneratedPath,
              '$kBlocksGeneratedPath.pyble-blocks.json',
            ),
          ProgramBundleNextOperation.runFile =>
            l10n.blocksBundleSessionChangedBeforeRun(kBlocksGeneratedPath),
        };
        expect(find.text(l10n.blocksActionFailed(reason)), findsOneWidget);
      });
    }

    testWidgets('focused host is notified after a successful Blocks Run', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      int runStarted = 0;
      await pumpSurface(
        tester,
        BlocksView(onRunStarted: () => runStarted++),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      _attachHost(containerOf(tester), source: 'print("focused")\n');
      await tester.pump();

      await tester.tap(find.byKey(kBlocksRunButtonKey));
      await tester.pumpAndSettle();

      expect(connection.runFileCalls, <String>[kBlocksGeneratedPath]);
      expect(runStarted, 1);
    });

    testWidgets('Open in editor confirms before replacing a dirty document', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      final ProviderContainer container = containerOf(tester);
      container
          .read(editorDocumentProvider.notifier)
          .setContent('keep_this = True\n');
      _attachHost(container, source: 'print("blocks")\n');
      await tester.pump();

      await tester.tap(find.byKey(kBlocksOpenEditorButtonKey));
      await tester.pumpAndSettle();
      expect(find.text('Replace unsaved changes?'), findsOneWidget);
      expect(
        container.read(editorDocumentProvider).content,
        'keep_this = True\n',
      );

      await tester.tap(find.text('Replace'));
      await tester.pumpAndSettle();
      expect(
        container.read(editorDocumentProvider).content,
        'print("blocks")\n',
      );
    });

    testWidgets('load failure is contained and Retry recreates the host', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      containerOf(tester)
          .read(blocksDocumentProvider.notifier)
          .reportHostError('platform view failed');
      await tester.pump();

      expect(find.text("Blocks couldn't load"), findsOneWidget);
      expect(find.textContaining('platform view failed'), findsOneWidget);
      expect(find.bySemanticsLabel('Retry'), findsOneWidget);

      await tester.tap(find.byKey(kBlocksRetryButtonKey));
      await tester.pump();
      expect(
        find.byKey(const ValueKey<String>('blocksWorkspaceHost-1')),
        findsOneWidget,
      );
      expect(find.text('Loading Blocks…'), findsOneWidget);
    });

    testWidgets('generator errors leave the workspace available for repair', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      final ProviderContainer container = containerOf(tester);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = _attachHost(container, source: 'print("last good")\n');
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'generator failed',
        }),
        hostId: hostId,
      );
      await tester.pump();

      expect(
        find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
        findsOneWidget,
      );
      expect(find.text("Blocks couldn't load"), findsNothing);
      expect(find.textContaining('generator failed'), findsOneWidget);
      expect(find.byKey(kBlocksRetryButtonKey), findsNothing);
      expect(
        tester
            .widget<IconButton>(find.byKey(kBlocksPreviewButtonKey))
            .onPressed,
        isNull,
      );
      expect(
        tester
            .widget<IconButton>(find.byKey(kBlocksOpenEditorButtonKey))
            .onPressed,
        isNull,
      );
      _expectStatusRowAboveWorkspace(tester);

      controller.receiveBridgeMessage(
        _snapshot('print("repaired")\n', revision: 2),
        hostId: hostId,
      );
      await tester.pump();
      expect(find.textContaining('generator failed'), findsNothing);
    });

    testWidgets('Start fresh confirms before clearing retained Blocks', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );
      final ProviderContainer container = containerOf(tester);
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      controller.receiveBridgeMessage(_snapshot('print("retained")\n'));
      controller.reportHostError('restore failed');
      await tester.pump();

      expect(find.byKey(kBlocksStartFreshButtonKey), findsOneWidget);
      await tester.tap(find.byKey(kBlocksStartFreshButtonKey));
      await tester.pumpAndSettle();
      expect(find.text('Discard the saved block workspace?'), findsOneWidget);
      expect(container.read(blocksDocumentProvider).program, isNotNull);

      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Start fresh'),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      expect(container.read(blocksDocumentProvider).program, isNull);
      expect(
        container.read(blocksDocumentProvider).status,
        BlocksStatus.loading,
      );
    });

    testWidgets('native action targets remain at least 48 dp', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const BlocksView(),
        connection: connection,
        extra: <Override>[_fakeWorkspace()],
      );

      for (final Key key in <Key>[
        kBlocksExamplesButtonKey,
        kBlocksPreviewButtonKey,
        kBlocksOpenEditorButtonKey,
        kBlocksSaveButtonKey,
        kBlocksRunButtonKey,
      ]) {
        final Size size = tester.getSize(find.byKey(key));
        expect(size.width, greaterThanOrEqualTo(48), reason: '$key width');
        expect(size.height, greaterThanOrEqualTo(48), reason: '$key height');
      }
    });

    testWidgets(
      'compact action bar keeps primary actions and an accessible overflow',
      (WidgetTester tester) async {
        final _HeldPutConnection connection = _HeldPutConnection();
        addTearDown(() {
          if (!connection.release.isCompleted) connection.release.complete();
        });
        await pumpSurface(
          tester,
          const BlocksView(),
          connection: connection,
          extra: <Override>[_fakeWorkspace()],
          size: const Size(220, 480),
        );
        final ProviderContainer container = containerOf(tester);
        _attachHost(container, source: 'print("compact")\n');
        await tester.pump();
        final AppLocalizations l10n = l10nOf(tester);

        unawaited(container.read(blocksDocumentProvider.notifier).save());
        await tester.pump();

        expect(
          tester.takeException(),
          isNull,
          reason: 'busy feedback must not consume horizontal action space',
        );
        for (final Key key in <Key>[
          kBlocksPreviewButtonKey,
          kBlocksSaveButtonKey,
          kBlocksRunButtonKey,
          kBlocksActionsOverflowButtonKey,
        ]) {
          expect(tester.getSize(find.byKey(key)), const Size(48, 48));
        }
        expect(find.byKey(kBlocksExamplesButtonKey), findsNothing);
        expect(find.byKey(kBlocksOpenEditorButtonKey), findsNothing);
        expect(find.byTooltip(l10n.blocksMoreActions), findsOneWidget);
        await tester.tap(find.byKey(kBlocksActionsOverflowButtonKey));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));

        expect(find.byKey(kBlocksExamplesButtonKey), findsOneWidget);
        expect(find.byKey(kBlocksOpenEditorButtonKey), findsOneWidget);
        expect(find.text(l10n.blocksExamples), findsOneWidget);
        expect(find.text(l10n.blocksOpenInEditor), findsOneWidget);
        for (final Key key in <Key>[
          kBlocksExamplesButtonKey,
          kBlocksOpenEditorButtonKey,
        ]) {
          expect(
            tester.getSize(find.byKey(key)).height,
            greaterThanOrEqualTo(48),
            reason: '$key menu target height',
          );
        }
        expect(tester.takeException(), isNull);
      },
    );
  });
}
