// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Native Flutter chrome around the offline Blockly platform view (A-31).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/pages/surface_placeholder.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'blocks_document.dart';
import 'blocks_examples.dart';
import 'blocks_examples_view.dart';
import 'blockly_webview.dart';

/// Widget factory that keeps the platform WebView fakeable in host tests.
typedef BlocksWorkspaceBuilder = Widget Function(Key key);

/// Production builds the real WebView; widget/golden tests replace it with an
/// inert Flutter widget so no platform channel is initialized.
final Provider<BlocksWorkspaceBuilder> blocksWorkspaceBuilderProvider =
    Provider<BlocksWorkspaceBuilder>(
      (Ref ref) =>
          (Key key) => BlocklyWebView(key: key),
    );

const Key kBlocksPreviewButtonKey = ValueKey<String>('blocksPreviewButton');
const Key kBlocksOpenEditorButtonKey = ValueKey<String>(
  'blocksOpenEditorButton',
);
const Key kBlocksSaveButtonKey = ValueKey<String>('blocksSaveButton');
const Key kBlocksRunButtonKey = ValueKey<String>('blocksRunButton');
const Key kBlocksRetryButtonKey = ValueKey<String>('blocksRetryButton');
const Key kBlocksStartFreshButtonKey = ValueKey<String>(
  'blocksStartFreshButton',
);
const Key kBlocksExamplesButtonKey = ValueKey<String>('blocksExamplesButton');
const Key kBlocksActionsOverflowButtonKey = ValueKey<String>(
  'blocksActionsOverflowButton',
);
const Key kBlocksEmptyExamplesButtonKey = ValueKey<String>(
  'blocksEmptyExamplesButton',
);

enum _BlocksOverflowAction { examples, openEditor }

const double _kInspectorMinWidth = 360;
const double _kInspectorMaxWidth = 420;
const double _kInspectorWidthFraction = 0.32;
const double _kWorkspaceMinWidthWithInspector = 720;
const double _kWorkspaceMinShareWithInspector = 0.60;

/// The visual programming surface: native actions + a lazy offline WebView.
class BlocksView extends ConsumerWidget {
  const BlocksView({super.key, this.onRunStarted});

  /// Landscape focus mode keeps Blocks selected and expands its console after a
  /// successful Run. Stacked mode omits this callback and navigates to Console.
  final VoidCallback? onRunStarted;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen<BlocksExampleCatalogRequest>(
      blocksExampleCatalogRequestProvider,
      (
        BlocksExampleCatalogRequest? previous,
        BlocksExampleCatalogRequest next,
      ) {
        if (next.serial <= (previous?.serial ?? 0)) return;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!context.mounted) return;
          unawaited(
            showBlocksExampleCatalog(
              context,
              ref,
              initialExampleId: next.initialExampleId,
            ),
          );
        });
      },
    );
    final BlocksDocument state = ref.watch(blocksDocumentProvider);
    final RunAvailability availability = ref.watch(runAvailabilityProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final BlocksWorkspaceBuilder buildWorkspace = ref.watch(
      blocksWorkspaceBuilderProvider,
    );
    final BlocksDocumentController controller = ref.read(
      blocksDocumentProvider.notifier,
    );
    final String targetName = state.targetPath.substring(
      state.targetPath.lastIndexOf('/') + 1,
    );
    final bool hasProgram =
        state.hasRunnableProgram && controller.hasActiveReadyHost;
    final bool actionsIdle = !state.busy && !state.workspaceReviewPending;
    final bool examplesReady =
        state.status == BlocksStatus.ready && actionsIdle;
    final bool readySemanticallyEmpty =
        state.status == BlocksStatus.ready &&
        state.workspaceError == null &&
        isSemanticallyEmptyBlocksWorkspace(state.retainedWorkspaceJson);
    final String unavailableActionLabel = state.workspaceError != null
        ? l10n.blocksGenerationFailed(state.workspaceError!)
        : readySemanticallyEmpty
        ? l10n.blocksEmptyHint
        : l10n.blocksNotReady;
    final bool hostBlocked =
        state.status == BlocksStatus.loading ||
        state.status == BlocksStatus.error;
    final VoidCallback? openExamples = examplesReady
        ? () => showBlocksExampleCatalog(context, ref)
        : null;
    final VoidCallback? openEditor = hasProgram && actionsIdle
        ? () => _openInEditor(context, ref)
        : null;
    final IconButton examplesAction = IconButton(
      key: kBlocksExamplesButtonKey,
      icon: const Icon(Icons.school_outlined),
      tooltip: l10n.blocksExamples,
      onPressed: openExamples,
    );
    final IconButton previewAction = IconButton(
      key: kBlocksPreviewButtonKey,
      icon: const Icon(Icons.code),
      tooltip: hasProgram ? l10n.blocksPreview : unavailableActionLabel,
      onPressed: hasProgram && actionsIdle
          ? () => _preview(context, ref)
          : null,
    );
    final IconButton openEditorAction = IconButton(
      key: kBlocksOpenEditorButtonKey,
      icon: const Icon(Icons.edit_note),
      tooltip: hasProgram ? l10n.blocksOpenInEditor : unavailableActionLabel,
      onPressed: openEditor,
    );
    final IconButton saveAction = IconButton(
      key: kBlocksSaveButtonKey,
      icon: const Icon(Icons.save_outlined),
      tooltip: !hasProgram
          ? unavailableActionLabel
          : availability.canSoftReboot
          ? l10n.blocksSave
          : l10n.editorSaveDisconnectedHint,
      onPressed: hasProgram && actionsIdle && availability.canSoftReboot
          ? () => _save(context, ref)
          : null,
    );
    final IconButton runAction = IconButton(
      key: kBlocksRunButtonKey,
      icon: const Icon(Icons.play_arrow),
      tooltip: !hasProgram
          ? unavailableActionLabel
          : availability.canRun
          ? l10n.blocksRun
          : availability.isRunning
          ? l10n.runBusyMessage
          : l10n.runDisconnectedHint,
      onPressed: hasProgram && actionsIdle && availability.canRun
          ? () => _run(context, ref, onRunStarted)
          : null,
    );
    final List<Widget> actions = <Widget>[
      examplesAction,
      previewAction,
      openEditorAction,
      saveAction,
      runAction,
    ];

    final String? workspaceNotice = state.status == BlocksStatus.loading
        ? l10n.blocksLoading
        : state.status == BlocksStatus.ready && state.workspaceError != null
        ? l10n.blocksGenerationFailed(state.workspaceError!)
        : null;

    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints outerConstraints) {
        final double availableWidth = outerConstraints.maxWidth;
        final double inspectorWidth =
            (availableWidth * _kInspectorWidthFraction)
                .clamp(_kInspectorMinWidth, _kInspectorMaxWidth)
                .toDouble();
        final double workspaceWidthWithInspector =
            availableWidth - inspectorWidth - 1;
        final bool showInspector =
            availableWidth.isFinite &&
            workspaceWidthWithInspector >= _kWorkspaceMinWidthWithInspector &&
            workspaceWidthWithInspector / availableWidth >=
                _kWorkspaceMinShareWithInspector;
        final double emptyPromptMaxHeight = outerConstraints.maxHeight.isFinite
            ? (outerConstraints.maxHeight * 0.45).clamp(120, 240).toDouble()
            : 240;

        return ColoredBox(
          color: scheme.surface,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Material(
                color: SignalElevation.tier(scheme, 2),
                child: LayoutBuilder(
                  builder: (BuildContext context, BoxConstraints constraints) {
                    // Action targets remain 48 dp. At very narrow widths
                    // Examples and Open-in-editor move into a named menu.
                    final bool compact = constraints.maxWidth < 320;
                    return Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        ConstrainedBox(
                          constraints: const BoxConstraints(minHeight: 48),
                          child: compact
                              ? Row(
                                  children: <Widget>[
                                    previewAction,
                                    saveAction,
                                    runAction,
                                    PopupMenuButton<_BlocksOverflowAction>(
                                      key: kBlocksActionsOverflowButtonKey,
                                      tooltip: l10n.blocksMoreActions,
                                      constraints: const BoxConstraints(
                                        minWidth: 200,
                                        maxWidth: 280,
                                      ),
                                      icon: const Icon(Icons.more_vert),
                                      onSelected:
                                          (_BlocksOverflowAction action) {
                                            switch (action) {
                                              case _BlocksOverflowAction
                                                  .examples:
                                                openExamples?.call();
                                                break;
                                              case _BlocksOverflowAction
                                                  .openEditor:
                                                openEditor?.call();
                                                break;
                                            }
                                          },
                                      itemBuilder: (BuildContext context) =>
                                          <
                                            PopupMenuEntry<
                                              _BlocksOverflowAction
                                            >
                                          >[
                                            PopupMenuItem<
                                              _BlocksOverflowAction
                                            >(
                                              key: kBlocksExamplesButtonKey,
                                              value: _BlocksOverflowAction
                                                  .examples,
                                              enabled: openExamples != null,
                                              child: _OverflowActionLabel(
                                                icon: Icons.school_outlined,
                                                label: l10n.blocksExamples,
                                              ),
                                            ),
                                            PopupMenuItem<
                                              _BlocksOverflowAction
                                            >(
                                              key: kBlocksOpenEditorButtonKey,
                                              value: _BlocksOverflowAction
                                                  .openEditor,
                                              enabled: openEditor != null,
                                              child: _OverflowActionLabel(
                                                icon: Icons.edit_note,
                                                label: l10n.blocksOpenInEditor,
                                              ),
                                            ),
                                          ],
                                    ),
                                  ],
                                )
                              : Padding(
                                  padding: const EdgeInsets.only(
                                    left: SignalSpacing.md,
                                  ),
                                  child: Row(
                                    children: <Widget>[
                                      Icon(
                                        Icons.account_tree_outlined,
                                        size: 18,
                                        color: scheme.onSurfaceVariant,
                                      ),
                                      const SizedBox(width: SignalSpacing.sm),
                                      Expanded(
                                        child: Text(
                                          targetName,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: SignalType.code.copyWith(
                                            color: scheme.onSurface,
                                          ),
                                        ),
                                      ),
                                      ...actions,
                                    ],
                                  ),
                                ),
                        ),
                        if (state.busy)
                          const LinearProgressIndicator(minHeight: 2),
                      ],
                    );
                  },
                ),
              ),
              const Divider(height: 1),
              if (readySemanticallyEmpty)
                ConstrainedBox(
                  constraints: BoxConstraints(maxHeight: emptyPromptMaxHeight),
                  child: EmptyStateBanner(
                    key: const ValueKey<String>('blocksEmptyExamplesPrompt'),
                    icon: Icons.school_outlined,
                    tone: SurfaceTone.action,
                    title: l10n.blocksExamplesEmptyTitle,
                    detail: l10n.blocksExamplesEmptyDetail,
                    action: FilledButton.icon(
                      key: kBlocksEmptyExamplesButtonKey,
                      onPressed: openExamples,
                      icon: const Icon(Icons.school_outlined),
                      label: Text(l10n.blocksExamplesOpen),
                    ),
                  ),
                )
              else if (workspaceNotice != null)
                _WorkspaceNotice(
                  key: const ValueKey<String>('blocksWorkspaceStatus'),
                  message: workspaceNotice,
                  isError: state.workspaceError != null,
                  isLoading: state.status == BlocksStatus.loading,
                ),
              Expanded(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Expanded(
                      child: state.status == BlocksStatus.error
                          ? _ErrorOverlay(
                              title: l10n.blocksLoadFailedTitle,
                              detail: l10n.blocksLoadFailed(
                                state.error ?? l10n.blocksNotReady,
                              ),
                              retryLabel: l10n.blocksRetry,
                              startFreshLabel:
                                  state.retainedWorkspaceJson == null
                                  ? null
                                  : l10n.blocksStartFresh,
                              onRetry: state.busy
                                  ? null
                                  : () => ref
                                        .read(blocksDocumentProvider.notifier)
                                        .retry(),
                              onStartFresh:
                                  state.busy ||
                                      state.retainedWorkspaceJson == null
                                  ? null
                                  : () => _confirmStartFresh(context, ref),
                            )
                          : ExcludeSemantics(
                              excluding: hostBlocked,
                              child: AbsorbPointer(
                                absorbing:
                                    hostBlocked ||
                                    state.busy ||
                                    state.workspaceReviewPending,
                                child: Semantics(
                                  label: l10n.blocksWorkspaceSemantics,
                                  container: true,
                                  child: buildWorkspace(
                                    ValueKey<String>(
                                      'blocksWorkspaceHost-${state.loadAttempt}',
                                    ),
                                  ),
                                ),
                              ),
                            ),
                    ),
                    if (showInspector) ...<Widget>[
                      const VerticalDivider(width: 1),
                      SizedBox(
                        key: const ValueKey<String>(
                          'blocksGeneratedPythonInspector',
                        ),
                        width: inspectorWidth,
                        child: _GeneratedPythonInspector(
                          targetPath: state.targetPath,
                          source: state.hasRunnableProgram
                              ? state.program?.source
                              : null,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  static Future<void> _preview(BuildContext context, WidgetRef ref) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    try {
      final String source = await ref
          .read(blocksDocumentProvider.notifier)
          .previewSource();
      if (!context.mounted) return;
      await _showPreview(context, source);
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l10n.blocksActionFailed(_reasonOf(error, l10n))),
        ),
      );
    }
  }

  static Future<void> _showPreview(BuildContext context, String source) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => AlertDialog(
        title: Text(l10n.blocksCodePreviewTitle),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640, maxHeight: 520),
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: scheme.surfaceContainerLowest,
              borderRadius: BorderRadius.circular(SignalRadius.sm),
            ),
            child: _SourceCodeView(
              source: source,
              style: SignalType.codeOn(scheme),
            ),
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(
              MaterialLocalizations.of(dialogContext).closeButtonLabel,
            ),
          ),
        ],
      ),
    );
  }

  static Future<void> _openInEditor(BuildContext context, WidgetRef ref) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final BlocksDocumentController controller = ref.read(
      blocksDocumentProvider.notifier,
    );
    try {
      try {
        await controller.openInEditor();
      } on BlocksEditorConflict catch (conflict) {
        if (!context.mounted) return;
        final bool replace =
            await showDialog<bool>(
              context: context,
              builder: (BuildContext dialogContext) => AlertDialog(
                title: Text(l10n.blocksReplaceEditorTitle),
                content: Text(
                  l10n.blocksReplaceEditorDetail(conflict.documentName),
                ),
                actions: <Widget>[
                  TextButton(
                    onPressed: () => Navigator.of(dialogContext).pop(false),
                    child: Text(l10n.commonCancel),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.of(dialogContext).pop(true),
                    child: Text(l10n.blocksReplaceEditorConfirm),
                  ),
                ],
              ),
            ) ??
            false;
        if (!replace || !context.mounted) return;
        await controller.openInEditor(replaceDirty: true);
      }
      if (!context.mounted) return;
      ref.read(selectedSurfaceProvider.notifier).state = AppSurface.editor;
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l10n.blocksActionFailed(_reasonOf(error, l10n))),
        ),
      );
    }
  }

  static Future<void> _save(BuildContext context, WidgetRef ref) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    try {
      final String path = await ref
          .read(blocksDocumentProvider.notifier)
          .save();
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.blocksSaved(path))));
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l10n.blocksActionFailed(_reasonOf(error, l10n))),
        ),
      );
    }
  }

  static Future<void> _run(
    BuildContext context,
    WidgetRef ref,
    VoidCallback? onRunStarted,
  ) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    try {
      await ref.read(blocksDocumentProvider.notifier).run();
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            l10n.blocksRunStarted(ref.read(blocksDocumentProvider).targetPath),
          ),
        ),
      );
      if (onRunStarted case final callback?) {
        callback();
      } else {
        ref.read(selectedSurfaceProvider.notifier).state = AppSurface.console;
      }
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l10n.blocksActionFailed(_reasonOf(error, l10n))),
        ),
      );
    }
  }

  static Future<void> _confirmStartFresh(
    BuildContext context,
    WidgetRef ref,
  ) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final bool discard =
        await showDialog<bool>(
          context: context,
          builder: (BuildContext dialogContext) => AlertDialog(
            title: Text(l10n.blocksStartFreshTitle),
            content: Text(l10n.blocksStartFreshDetail),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(false),
                child: Text(l10n.commonCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.of(dialogContext).pop(true),
                child: Text(l10n.blocksStartFresh),
              ),
            ],
          ),
        ) ??
        false;
    if (!discard || !context.mounted) return;
    ref.read(blocksDocumentProvider.notifier).startFresh();
  }

  static String _reasonOf(Object error, AppLocalizations l10n) {
    if (error is ProgramBundleIncomplete) {
      return l10n.blocksBundleIncomplete(error.sourcePath, error.companionPath);
    }
    if (error is ProgramBundleSessionChanged) {
      return switch (error.nextOperation) {
        ProgramBundleNextOperation.writeCompanion =>
          l10n.blocksBundleSessionChangedBeforeCompanion(
            error.sourcePath,
            error.companionPath,
          ),
        ProgramBundleNextOperation.runFile =>
          l10n.blocksBundleSessionChangedBeforeRun(error.sourcePath),
      };
    }
    if (error is ProgramBundlePathTooLong) {
      return l10n.blocksTargetPathTooLong(error.path);
    }
    if (error is BlocksNotReady) return 'BlocksNotReady';
    if (error is PbleException) return error.runtimeType.toString();
    return error.toString();
  }
}

class _ErrorOverlay extends StatelessWidget {
  const _ErrorOverlay({
    required this.title,
    required this.detail,
    required this.retryLabel,
    required this.startFreshLabel,
    required this.onRetry,
    required this.onStartFresh,
  });

  final String title;
  final String detail;
  final String retryLabel;
  final String? startFreshLabel;
  final VoidCallback? onRetry;
  final VoidCallback? onStartFresh;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Semantics(
      container: true,
      liveRegion: true,
      explicitChildNodes: true,
      label: '$title. $detail',
      child: ColoredBox(
        color: scheme.surface,
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(SignalSpacing.xl),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  ExcludeSemantics(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Icon(
                          Icons.error_outline,
                          color: scheme.error,
                          size: 40,
                        ),
                        const SizedBox(height: SignalSpacing.md),
                        Text(
                          title,
                          style: Theme.of(context).textTheme.titleMedium,
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: SignalSpacing.sm),
                        Text(
                          detail,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: scheme.onSurfaceVariant),
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: SignalSpacing.lg),
                  Wrap(
                    alignment: WrapAlignment.center,
                    spacing: SignalSpacing.sm,
                    runSpacing: SignalSpacing.sm,
                    children: <Widget>[
                      if (startFreshLabel != null)
                        OutlinedButton.icon(
                          key: kBlocksStartFreshButtonKey,
                          onPressed: onStartFresh,
                          icon: const Icon(Icons.delete_outline),
                          label: Text(startFreshLabel!),
                        ),
                      FilledButton.icon(
                        key: kBlocksRetryButtonKey,
                        onPressed: onRetry,
                        icon: const Icon(Icons.refresh),
                        label: Text(retryLabel),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _OverflowActionLabel extends StatelessWidget {
  const _OverflowActionLabel({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    children: <Widget>[
      Icon(icon),
      const SizedBox(width: SignalSpacing.md),
      Flexible(
        child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
    ],
  );
}

class _WorkspaceNotice extends StatelessWidget {
  const _WorkspaceNotice({
    super.key,
    required this.message,
    required this.isError,
    this.isLoading = false,
  });

  final String message;
  final bool isError;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final Color background = isError
        ? scheme.errorContainer
        : scheme.surfaceContainerHigh;
    final Color foreground = isError
        ? scheme.onErrorContainer
        : scheme.onSurfaceVariant;
    return Semantics(
      container: true,
      liveRegion: true,
      label: isLoading ? message : null,
      excludeSemantics: isLoading,
      child: Material(
        color: background,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: SignalSpacing.md,
            vertical: SignalSpacing.sm,
          ),
          child: Row(
            children: <Widget>[
              if (isLoading)
                SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: foreground,
                  ),
                )
              else
                Icon(
                  isError ? Icons.error_outline : Icons.info_outline,
                  size: 18,
                  color: foreground,
                ),
              const SizedBox(width: SignalSpacing.sm),
              Expanded(
                child: Text(
                  message,
                  style: theme.textTheme.bodySmall?.copyWith(color: foreground),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _GeneratedPythonInspector extends StatelessWidget {
  const _GeneratedPythonInspector({
    required this.targetPath,
    required this.source,
  });

  final String targetPath;
  final String? source;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final String? retainedSource = source;

    return ColoredBox(
      color: scheme.surfaceContainerLowest,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: SignalSpacing.md,
                vertical: SignalSpacing.sm,
              ),
              child: Row(
                children: <Widget>[
                  Icon(Icons.code, size: 18, color: scheme.onSurfaceVariant),
                  const SizedBox(width: SignalSpacing.sm),
                  Expanded(
                    child: Text(
                      l10n.blocksCodePreviewTitle,
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                  Text(
                    targetPath,
                    style: SignalType.code.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: retainedSource == null || retainedSource.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(SignalSpacing.lg),
                      child: Text(
                        l10n.blocksInspectorEmptyHint,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  )
                : _SourceCodeView(
                    source: retainedSource,
                    style: SignalType.codeOn(scheme),
                  ),
          ),
        ],
      ),
    );
  }
}

class _SourceCodeView extends StatelessWidget {
  const _SourceCodeView({required this.source, required this.style});

  final String source;
  final TextStyle style;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(SignalSpacing.lg),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SelectableText(source, style: style),
      ),
    );
  }
}
