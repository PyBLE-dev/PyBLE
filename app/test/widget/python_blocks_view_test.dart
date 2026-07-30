// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

class _ConversionLauncher extends ConsumerWidget {
  const _ConversionLauncher();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool busy = ref.watch(pythonBlocksFlowBusyProvider);
    return EditorView(
      convertingToBlocks: busy,
      onConvertToBlocks: busy
          ? null
          : () => unawaited(showPythonToBlocksConversion(context)),
    );
  }
}

String _snapshot({
  required int revision,
  required String source,
  required Map<String, dynamic> workspace,
}) => jsonEncode(<String, Object?>{
  'version': kBlocksBridgeVersion,
  'type': 'snapshot',
  'revision': revision,
  'source': source,
  'workspace': workspace,
});

const Map<String, Object?> _emptyWorkspace = <String, Object?>{
  'blocks': <String, Object?>{'languageVersion': 0, 'blocks': <Object?>[]},
};

void _attachScratchPreviewHost(
  ProviderContainer container, {
  required String generatedSource,
}) {
  final BlocksDocumentController controller = container.read(
    blocksDocumentProvider.notifier,
  );
  final int host = controller.beginHost(
    requestSnapshot: (int requestId) async {},
    previewExample: (String workspaceJson) async => BlocksExamplePreview(
      source: generatedSource,
      workspaceJson: workspaceJson,
    ),
  );
  controller.markHostLoading(host);
  controller.receiveBridgeMessage(
    _snapshot(revision: 1, source: '', workspace: _emptyWorkspace),
    hostId: host,
  );
}

void _ackStagedWorkspace(
  ProviderContainer container, {
  required String source,
}) {
  final BlocksDocumentController controller = container.read(
    blocksDocumentProvider.notifier,
  );
  final Map<String, dynamic> workspace =
      jsonDecode(container.read(blocksDocumentProvider).retainedWorkspaceJson!)!
          as Map<String, dynamic>;
  final int host = controller.beginHost(
    requestSnapshot: (int requestId) async {},
  );
  controller.markHostLoading(host);
  controller.receiveBridgeMessage(
    _snapshot(
      revision:
          (container.read(blocksDocumentProvider).retainedWorkspaceRevision ??
              0) +
          1,
      source: source,
      workspace: workspace,
    ),
    hostId: host,
  );
}

Future<void> _pumpUntilReviewPending(WidgetTester tester) async {
  for (int attempt = 0; attempt < 20; attempt += 1) {
    if (containerOf(
      tester,
    ).read(blocksDocumentProvider).workspaceReviewPending) {
      return;
    }
    await tester.pump();
  }
  fail('Python-to-Blocks flow did not stage a workspace');
}

Future<void> _pumpUntilReview(WidgetTester tester) async {
  for (int attempt = 0; attempt < 20; attempt += 1) {
    if (find.byKey(kPythonBlocksReviewKey).evaluate().isNotEmpty) return;
    await tester.pump();
  }
  fail('Python-to-Blocks flow did not show its review');
}

void main() {
  group('guarded Python to Blocks native flow', () {
    testWidgets(
      'unsupported source shows localized diagnostics and mutates nothing',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const _ConversionLauncher(),
          connection: connection,
        );
        final ProviderContainer container = containerOf(tester);
        container
            .read(editorDocumentProvider.notifier)
            .setContent('import machine\n');
        final BlocksDocument before = container.read(blocksDocumentProvider);
        await tester.pump();

        await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        final AppLocalizations l10n = l10nOf(tester);
        expect(find.byKey(kPythonBlocksDiagnosticDialogKey), findsOneWidget);
        expect(find.text(l10n.pythonBlocksCannotConvertTitle), findsOneWidget);
        expect(find.textContaining('unsupported_import'), findsOneWidget);
        expect(container.read(blocksDocumentProvider).program, before.program);
        expect(
          container.read(blocksDocumentProvider).retainedWorkspaceJson,
          before.retainedWorkspaceJson,
        );
        expect(connection.getFileCalls, isEmpty);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        await tester.tap(
          find.text(
            MaterialLocalizations.of(
              tester.element(find.byType(AlertDialog)),
            ).closeButtonLabel,
          ),
        );
        await tester.pumpAndSettle();
      },
    );

    testWidgets('compact diagnostics use a scroll-safe bottom sheet', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const _ConversionLauncher(),
        connection: connection,
        size: const Size(390, 640),
      );
      containerOf(
        tester,
      ).read(editorDocumentProvider.notifier).setContent('import machine\n');
      await tester.pump();

      await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byKey(kPythonBlocksDiagnosticDialogKey), findsOneWidget);
      expect(tester.takeException(), isNull);
      final BuildContext modalContext = tester.element(
        find.byKey(kPythonBlocksDiagnosticDialogKey),
      );
      await tester.tap(
        find.text(MaterialLocalizations.of(modalContext).closeButtonLabel),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(kPythonBlocksDiagnosticDialogKey), findsNothing);
      expect(connection.getFileCalls, isEmpty);
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
    });

    testWidgets('production preview commits only after explicit confirmation', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpSurface(
        tester,
        const _ConversionLauncher(),
        connection: connection,
      );
      final ProviderContainer container = containerOf(tester);
      container
          .read(editorDocumentProvider.notifier)
          .setContent('print("hello")\n');
      _attachScratchPreviewHost(container, generatedSource: "print('hello')\n");
      final BlocksDocument before = container.read(blocksDocumentProvider);
      await tester.pump();

      await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
      await tester.pump();
      await _pumpUntilReview(tester);
      expect(
        container.read(blocksDocumentProvider).hasRunnableProgram,
        isFalse,
      );
      expect(
        container.read(blocksDocumentProvider).retainedWorkspaceJson,
        before.retainedWorkspaceJson,
        reason: 'scratch Preview must not replace the active workspace',
      );

      final AppLocalizations l10n = l10nOf(tester);
      expect(find.byKey(kPythonBlocksReviewKey), findsOneWidget);
      expect(find.text(l10n.pythonBlocksImportTitle), findsOneWidget);
      expect(find.text("print('hello')\n"), findsOneWidget);
      expect(find.text(l10n.pythonBlocksCreate), findsOneWidget);
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);

      await tester.tap(find.byKey(kPythonBlocksConfirmKey));
      await tester.pump();
      await _pumpUntilReviewPending(tester);
      _ackStagedWorkspace(container, source: "print('hello')\n");
      await tester.pumpAndSettle();

      final BlocksDocument committed = container.read(blocksDocumentProvider);
      expect(committed.workspaceReviewPending, isFalse);
      expect(committed.hasRunnableProgram, isTrue);
      expect(committed.targetPath, '/untitled.py');
      expect(committed.program?.source, "print('hello')\n");
      expect(connection.getFileCalls, isEmpty);
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
    });

    testWidgets(
      'production semantic mismatch fails closed before active workspace staging',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const _ConversionLauncher(),
          connection: connection,
        );
        final ProviderContainer container = containerOf(tester);
        container
            .read(editorDocumentProvider.notifier)
            .setContent('print("one")\n');
        _attachScratchPreviewHost(container, generatedSource: "print('two')\n");
        final BlocksDocument before = container.read(blocksDocumentProvider);
        await tester.pump();

        await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        expect(find.byKey(kPythonBlocksReviewKey), findsNothing);
        expect(
          container.read(blocksDocumentProvider).retainedWorkspaceJson,
          before.retainedWorkspaceJson,
        );
        expect(
          container.read(blocksDocumentProvider).workspaceReviewPending,
          isFalse,
        );
        expect(connection.getFileCalls, isEmpty);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
      },
    );

    testWidgets(
      'editing away and back stales Preview and disables confirmation',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const _ConversionLauncher(),
          connection: connection,
        );
        final ProviderContainer container = containerOf(tester);
        container
            .read(editorDocumentProvider.notifier)
            .setContent('print("captured")\n');
        _attachScratchPreviewHost(
          container,
          generatedSource: "print('captured')\n",
        );
        await tester.pump();

        await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
        await tester.pump();
        await _pumpUntilReview(tester);

        final EditorDocumentController editor = container.read(
          editorDocumentProvider.notifier,
        );
        editor.setContent('print("temporary")\n');
        editor.setContent('print("captured")\n');
        await tester.pump();

        final AppLocalizations l10n = l10nOf(tester);
        expect(find.text(l10n.pythonBlocksSourceChanged), findsOneWidget);
        expect(
          tester
              .widget<FilledButton>(find.byKey(kPythonBlocksConfirmKey))
              .onPressed,
          isNull,
        );
        await tester.tap(find.byKey(kPythonBlocksCancelKey));
        await tester.pump(const Duration(milliseconds: 500));
        expect(connection.getFileCalls, isEmpty);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
      },
    );

    testWidgets(
      'compact review is scroll-safe and Cancel restores empty Blocks',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpSurface(
          tester,
          const _ConversionLauncher(),
          connection: connection,
          size: const Size(390, 640),
        );
        final ProviderContainer container = containerOf(tester);
        container
            .read(editorDocumentProvider.notifier)
            .setContent('print("compact")\n');
        _attachScratchPreviewHost(
          container,
          generatedSource: "print('compact')\n",
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);
        await tester.pump();

        await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
        await tester.pump();
        await _pumpUntilReview(tester);
        await tester.pump(const Duration(milliseconds: 500));

        expect(find.byType(BottomSheet), findsOneWidget);
        final Rect closeRect = tester.getRect(
          find.byKey(kPythonBlocksCancelKey),
        );
        expect(closeRect.top, greaterThanOrEqualTo(0));
        expect(closeRect.bottom, lessThanOrEqualTo(640));
        expect(
          find.byKey(kPythonBlocksCancelKey).hitTestable(),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        await tester.tap(find.byKey(kPythonBlocksCancelKey));
        await tester.pumpAndSettle();

        final BlocksDocument restored = container.read(blocksDocumentProvider);
        expect(restored.workspaceReviewPending, isFalse);
        expect(restored.retainedWorkspaceJson, before.retainedWorkspaceJson);
        expect(restored.targetPath, kBlocksGeneratedPath);
        expect(connection.putFileCalls, isEmpty);
      },
    );
  });
}
