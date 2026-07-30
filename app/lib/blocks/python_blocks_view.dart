// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Native, guarded Editor → Blocks conversion flow.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'blocks_companion.dart';
import 'blocks_document.dart';
import 'blocks_examples.dart';
import 'python_blocks_preparation.dart';
import 'python_to_blocks.dart';

const Key kPythonBlocksDiagnosticDialogKey = ValueKey<String>(
  'pythonBlocksDiagnosticDialog',
);
const Key kPythonBlocksReviewKey = ValueKey<String>('pythonBlocksReview');
const Key kPythonBlocksConfirmKey = ValueKey<String>('pythonBlocksConfirm');
const Key kPythonBlocksCancelKey = ValueKey<String>('pythonBlocksCancel');

final StateProvider<bool> pythonBlocksFlowBusyProvider = StateProvider<bool>(
  (Ref ref) => false,
);

/// Runs one explicit, source-captured, all-or-nothing conversion.
Future<void> showPythonToBlocksConversion(BuildContext context) {
  final ProviderContainer container = ProviderScope.containerOf(
    context,
    listen: false,
  );
  return _showPythonDocumentToBlocksConversion(
    context,
    captured: container.read(editorDocumentProvider),
    capturedEditorEpoch: container.read(editorDocumentEpochProvider),
    guardCurrentEditor: true,
  );
}

/// Previews one already-downloaded board file without replacing the Editor.
Future<void> showBoardFileAsBlocksConversion(
  BuildContext context, {
  required EditorDocument captured,
}) => _showPythonDocumentToBlocksConversion(
  context,
  captured: captured,
  capturedEditorEpoch: null,
  guardCurrentEditor: false,
);

Future<void> _showPythonDocumentToBlocksConversion(
  BuildContext context, {
  required EditorDocument captured,
  required int? capturedEditorEpoch,
  required bool guardCurrentEditor,
}) async {
  final ProviderContainer container = ProviderScope.containerOf(
    context,
    listen: false,
  );
  if (container.read(pythonBlocksFlowBusyProvider)) return;
  container.read(pythonBlocksFlowBusyProvider.notifier).state = true;

  final NavigatorState navigator = Navigator.of(context);
  final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
  final AppLocalizations l10n = AppLocalizations.of(context);
  final BlocksDocument before = container.read(blocksDocumentProvider);
  final AppSurface surfaceBefore = container.read(selectedSurfaceProvider);
  final bool replace = !isSemanticallyEmptyBlocksWorkspace(
    before.retainedWorkspaceJson,
  );
  final BlocksDocumentController controller = container.read(
    blocksDocumentProvider.notifier,
  );
  bool movedToBlocksForPreview = false;
  bool stageStarted = false;
  bool committed = false;

  try {
    final PythonBlocksPreparation preparation = await container
        .read(pythonBlocksPreparationProvider)
        .prepare(captured, readCompanion: !guardCurrentEditor);
    if (!navigator.mounted || !messenger.mounted) return;
    if (!_capturedEditorIsCurrent(
      container,
      captured: captured,
      capturedEditorEpoch: capturedEditorEpoch,
      guardCurrentEditor: guardCurrentEditor,
    )) {
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.pythonBlocksSourceChanged)),
      );
      return;
    }
    if (!preparation.canPreview) {
      await _showDiagnostics(
        navigator.context,
        preparation.diagnostics,
        source: captured.content,
        targetPath: preparation.targetPath,
        companionIssue: preparation.companionIssue,
      );
      return;
    }

    // The production Blockly host is lazy. Focus it only when necessary, then
    // use its disposable scratch workspace; the retained Blocks document is
    // still byte-for-byte unchanged while Preview is open.
    if (!controller.hasActiveReadyHost) {
      movedToBlocksForPreview = surfaceBefore != AppSurface.blocks;
      container.read(selectedSurfaceProvider.notifier).state =
          AppSurface.blocks;
      await controller.waitForPreviewHost();
    }
    final BlocksExamplePreview scratch = await controller.previewExample(
      preparation.workspaceJson!,
    );
    final GeneratedProgram generated = GeneratedProgram(
      source: scratch.source,
      workspaceJson: scratch.workspaceJson,
      revision: 0,
    );
    if (!navigator.mounted || !messenger.mounted) return;
    if (preparation.origin == PythonBlocksPreparationOrigin.exactCompanion) {
      if (generated.source != preparation.expectedSource ||
          !_jsonDocumentsEqual(
            preparation.workspaceJson!,
            generated.workspaceJson,
          )) {
        throw const BlocksGenerationFailed(
          'Exact Blocks companion did not survive production restoration',
        );
      }
    } else {
      final PythonBlocksConversion selfCheck = const PythonToBlocksConverter()
          .convert(generated.source, productionGenerated: true);
      if (selfCheck.hasErrors ||
          preparation.semanticFingerprint == null ||
          selfCheck.semanticFingerprint != preparation.semanticFingerprint) {
        throw const BlocksGenerationFailed(
          'Production-generated Python changed the imported program model',
        );
      }
    }
    if (!_capturedEditorIsCurrent(
      container,
      captured: captured,
      capturedEditorEpoch: capturedEditorEpoch,
      guardCurrentEditor: guardCurrentEditor,
    )) {
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.pythonBlocksSourceChanged)),
      );
      return;
    }

    final bool commit =
        await _showReview(
          navigator.context,
          preparation: preparation,
          generated: generated,
          replace: replace,
          captured: captured,
          capturedEditorEpoch: capturedEditorEpoch,
          guardCurrentEditor: guardCurrentEditor,
        ) ??
        false;
    if (!navigator.mounted || !messenger.mounted) return;
    if (!commit) {
      return;
    }
    if (!_capturedEditorIsCurrent(
      container,
      captured: captured,
      capturedEditorEpoch: capturedEditorEpoch,
      guardCurrentEditor: guardCurrentEditor,
    )) {
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.pythonBlocksSourceChanged)),
      );
      return;
    }

    stageStarted = true;
    await controller.stageWorkspaceReview(
      workspaceJson: generated.workspaceJson,
      expectedSource: generated.source,
      targetPath: preparation.targetPath,
      replace: replace,
    );
    if (!_capturedEditorIsCurrent(
      container,
      captured: captured,
      capturedEditorEpoch: capturedEditorEpoch,
      guardCurrentEditor: guardCurrentEditor,
    )) {
      controller.cancelWorkspaceReview();
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.pythonBlocksSourceChanged)),
      );
      return;
    }
    controller.commitWorkspaceReview();
    committed = true;
    messenger.showSnackBar(SnackBar(content: Text(l10n.pythonBlocksLoaded)));
  } catch (error) {
    if (stageStarted) controller.cancelWorkspaceReview();
    if (!messenger.mounted) return;
    messenger.showSnackBar(
      SnackBar(content: Text(l10n.pythonBlocksFailed(_reasonOf(error)))),
    );
  } finally {
    if (movedToBlocksForPreview && !committed) {
      controller.restoreAfterTransientPreviewHost(before);
      container.read(selectedSurfaceProvider.notifier).state = surfaceBefore;
    }
    container.read(pythonBlocksFlowBusyProvider.notifier).state = false;
  }
}

bool _capturedEditorIsCurrent(
  ProviderContainer container, {
  required EditorDocument captured,
  required int? capturedEditorEpoch,
  required bool guardCurrentEditor,
}) {
  if (!guardCurrentEditor) return true;
  return container.read(editorDocumentProvider) == captured &&
      container.read(editorDocumentEpochProvider) == capturedEditorEpoch;
}

bool _jsonDocumentsEqual(String left, String right) {
  try {
    return _jsonValuesEqual(jsonDecode(left), jsonDecode(right));
  } on FormatException {
    return false;
  }
}

bool _jsonValuesEqual(Object? left, Object? right) {
  if (identical(left, right)) return true;
  if (left is num && right is num) return left == right;
  if (left is List<dynamic> && right is List<dynamic>) {
    if (left.length != right.length) return false;
    for (int index = 0; index < left.length; index += 1) {
      if (!_jsonValuesEqual(left[index], right[index])) return false;
    }
    return true;
  }
  if (left is Map<String, dynamic> && right is Map<String, dynamic>) {
    if (left.length != right.length) return false;
    for (final MapEntry<String, dynamic> entry in left.entries) {
      if (!right.containsKey(entry.key) ||
          !_jsonValuesEqual(entry.value, right[entry.key])) {
        return false;
      }
    }
    return true;
  }
  return left == right;
}

Future<void> _showDiagnostics(
  BuildContext context,
  List<PythonBlocksDiagnostic> diagnostics, {
  required String source,
  required String targetPath,
  required PythonBlocksCompanionIssue? companionIssue,
}) {
  final AppLocalizations l10n = AppLocalizations.of(context);
  final String? companionNotice = _companionIssueMessage(l10n, companionIssue);
  final List<PythonBlocksDiagnostic> errors = diagnostics
      .where(
        (PythonBlocksDiagnostic diagnostic) => diagnostic.severity == 'error',
      )
      .toList(growable: false);
  final List<String> sourceLines = source
      .replaceAll('\r\n', '\n')
      .replaceAll('\r', '\n')
      .split('\n');

  Widget buildBody(BuildContext modalContext) => Semantics(
    liveRegion: true,
    container: true,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 560),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(l10n.pythonBlocksErrorCount(errors.length)),
            const SizedBox(height: SignalSpacing.xs),
            Text(
              targetPath,
              style: SignalType.code.copyWith(
                color: Theme.of(modalContext).colorScheme.onSurfaceVariant,
              ),
            ),
            if (companionNotice != null) ...<Widget>[
              const SizedBox(height: SignalSpacing.md),
              Text(companionNotice),
            ],
            const SizedBox(height: SignalSpacing.md),
            for (int index = 0; index < errors.length; index += 1) ...<Widget>[
              if (index > 0) const SizedBox(height: SignalSpacing.sm),
              Focus(
                autofocus: index == 0,
                child: Semantics(
                  container: true,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      border: Border.all(
                        color: Theme.of(
                          modalContext,
                        ).colorScheme.outlineVariant,
                      ),
                      borderRadius: BorderRadius.circular(SignalRadius.sm),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(SignalSpacing.md),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: <Widget>[
                          Text(
                            _diagnosticMessage(l10n, errors[index], targetPath),
                          ),
                          const SizedBox(height: SignalSpacing.xs),
                          SelectableText(
                            '${errors[index].line}: '
                            '${_diagnosticSourceLine(sourceLines, errors[index].line)}',
                            style: SignalType.code,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    ),
  );

  if (MediaQuery.sizeOf(context).width < 600) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (BuildContext sheetContext) => FractionallySizedBox(
        heightFactor: 0.94,
        child: Material(
          key: kPythonBlocksDiagnosticDialogKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  SignalSpacing.xl,
                  SignalSpacing.lg,
                  SignalSpacing.md,
                  SignalSpacing.sm,
                ),
                child: Text(
                  l10n.pythonBlocksCannotConvertTitle,
                  style: Theme.of(sheetContext).textTheme.titleLarge,
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(SignalSpacing.xl),
                  child: buildBody(sheetContext),
                ),
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.all(SignalSpacing.md),
                child: Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: TextButton(
                    style: TextButton.styleFrom(minimumSize: const Size(0, 48)),
                    onPressed: () => Navigator.of(sheetContext).pop(),
                    child: Text(
                      MaterialLocalizations.of(sheetContext).closeButtonLabel,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  return showDialog<void>(
    context: context,
    builder: (BuildContext dialogContext) => AlertDialog(
      key: kPythonBlocksDiagnosticDialogKey,
      title: Text(l10n.pythonBlocksCannotConvertTitle),
      content: buildBody(dialogContext),
      actions: <Widget>[
        TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(0, 48)),
          onPressed: () => Navigator.of(dialogContext).pop(),
          child: Text(MaterialLocalizations.of(dialogContext).closeButtonLabel),
        ),
      ],
    ),
  );
}

String _diagnosticSourceLine(List<String> sourceLines, int oneBasedLine) {
  final int index = oneBasedLine - 1;
  if (index < 0 || index >= sourceLines.length) return '';
  return sourceLines[index];
}

String _diagnosticMessage(
  AppLocalizations l10n,
  PythonBlocksDiagnostic diagnostic,
  String targetPath,
) {
  if (diagnostic.messageKey == 'pythonBlocksInvalidTargetPath') {
    return l10n.pythonBlocksInvalidTargetPath(targetPath);
  }
  return l10n.pythonBlocksDiagnostic(
    diagnostic.line,
    diagnostic.column,
    diagnostic.code,
  );
}

String? _companionIssueMessage(
  AppLocalizations l10n,
  PythonBlocksCompanionIssue? issue,
) => switch (issue) {
  PythonBlocksCompanionIssue.invalid => l10n.pythonBlocksCompanionInvalid,
  PythonBlocksCompanionIssue.sourceMismatch => l10n.pythonBlocksCompanionStale,
  PythonBlocksCompanionIssue.unreadable => l10n.pythonBlocksCompanionUnreadable,
  null => null,
};

Future<bool?> _showReview(
  BuildContext context, {
  required PythonBlocksPreparation preparation,
  required GeneratedProgram generated,
  required bool replace,
  required EditorDocument captured,
  required int? capturedEditorEpoch,
  required bool guardCurrentEditor,
}) {
  final Widget content = _PythonBlocksReview(
    preparation: preparation,
    generated: generated,
    replace: replace,
    captured: captured,
    capturedEditorEpoch: capturedEditorEpoch,
    guardCurrentEditor: guardCurrentEditor,
  );
  if (MediaQuery.sizeOf(context).width < 600) {
    return showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (BuildContext sheetContext) =>
          FractionallySizedBox(heightFactor: 0.94, child: content),
    );
  }
  return showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext dialogContext) => Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720, maxHeight: 680),
        child: content,
      ),
    ),
  );
}

class _PythonBlocksReview extends ConsumerWidget {
  const _PythonBlocksReview({
    required this.preparation,
    required this.generated,
    required this.replace,
    required this.captured,
    required this.capturedEditorEpoch,
    required this.guardCurrentEditor,
  });

  final PythonBlocksPreparation preparation;
  final GeneratedProgram generated;
  final bool replace;
  final EditorDocument captured;
  final int? capturedEditorEpoch;
  final bool guardCurrentEditor;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final bool exact =
        preparation.origin == PythonBlocksPreparationOrigin.exactCompanion;
    final String? companionNotice = _companionIssueMessage(
      l10n,
      preparation.companionIssue,
    );
    final bool editorStale =
        guardCurrentEditor &&
        (ref.watch(editorDocumentProvider) != captured ||
            ref.watch(editorDocumentEpochProvider) != capturedEditorEpoch);

    return Semantics(
      key: kPythonBlocksReviewKey,
      container: true,
      explicitChildNodes: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(
              SignalSpacing.xl,
              SignalSpacing.lg,
              SignalSpacing.md,
              SignalSpacing.sm,
            ),
            child: Row(
              children: <Widget>[
                Icon(
                  exact ? Icons.restore_outlined : Icons.account_tree_outlined,
                  color: scheme.primary,
                ),
                const SizedBox(width: SignalSpacing.md),
                Expanded(
                  child: Text(
                    exact
                        ? l10n.pythonBlocksExactTitle
                        : l10n.pythonBlocksImportTitle,
                    style: theme.textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  key: kPythonBlocksCancelKey,
                  tooltip: MaterialLocalizations.of(context).closeButtonTooltip,
                  onPressed: () => Navigator.of(context).pop(false),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(SignalSpacing.xl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Text(
                    exact
                        ? l10n.pythonBlocksExactDetail
                        : l10n.pythonBlocksImportDetail,
                  ),
                  if (companionNotice != null) ...<Widget>[
                    const SizedBox(height: SignalSpacing.md),
                    _ReviewNotice(
                      icon: Icons.info_outline,
                      message: companionNotice,
                    ),
                  ],
                  for (final PythonBlocksDiagnostic diagnostic
                      in preparation.diagnostics.where(
                        (PythonBlocksDiagnostic value) =>
                            value.severity == 'warning',
                      )) ...<Widget>[
                    const SizedBox(height: SignalSpacing.md),
                    _ReviewNotice(
                      icon: Icons.info_outline,
                      message: _diagnosticMessage(
                        l10n,
                        diagnostic,
                        preparation.targetPath,
                      ),
                    ),
                  ],
                  const SizedBox(height: SignalSpacing.md),
                  Text(
                    preparation.targetPath,
                    style: SignalType.code.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                  Text(
                    blocksCompanionPathFor(preparation.targetPath),
                    style: SignalType.code.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: SignalSpacing.md),
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: scheme.surfaceContainerLowest,
                      borderRadius: BorderRadius.circular(SignalRadius.sm),
                      border: Border.all(color: scheme.outlineVariant),
                    ),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(
                        minHeight: 160,
                        maxHeight: 320,
                      ),
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.all(SignalSpacing.lg),
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: SelectableText(
                            generated.source,
                            style: SignalType.codeOn(scheme),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: SignalSpacing.md),
                  _ReviewNotice(
                    icon: Icons.shield_outlined,
                    message: l10n.pythonBlocksNoBoardAction,
                  ),
                  if (editorStale) ...<Widget>[
                    const SizedBox(height: SignalSpacing.md),
                    _ReviewNotice(
                      icon: Icons.warning_amber_outlined,
                      message: l10n.pythonBlocksSourceChanged,
                    ),
                  ],
                ],
              ),
            ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(SignalSpacing.md),
            child: OverflowBar(
              alignment: MainAxisAlignment.end,
              overflowAlignment: OverflowBarAlignment.end,
              spacing: SignalSpacing.sm,
              overflowSpacing: SignalSpacing.sm,
              children: <Widget>[
                TextButton(
                  style: TextButton.styleFrom(minimumSize: const Size(0, 48)),
                  onPressed: () => Navigator.of(context).pop(false),
                  child: Text(l10n.commonCancel),
                ),
                FilledButton.icon(
                  key: kPythonBlocksConfirmKey,
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 48)),
                  onPressed: editorStale
                      ? null
                      : () => Navigator.of(context).pop(true),
                  icon: Icon(
                    replace ? Icons.swap_horiz : Icons.account_tree_outlined,
                  ),
                  label: Text(
                    replace
                        ? l10n.pythonBlocksReplace
                        : l10n.pythonBlocksCreate,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ReviewNotice extends StatelessWidget {
  const _ReviewNotice({required this.icon, required this.message});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(icon, size: 18, color: scheme.onSurfaceVariant),
        const SizedBox(width: SignalSpacing.sm),
        Expanded(
          child: Text(
            message,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
          ),
        ),
      ],
    );
  }
}

String _reasonOf(Object error) {
  if (error is PbleException) return error.runtimeType.toString();
  return error.runtimeType.toString();
}
