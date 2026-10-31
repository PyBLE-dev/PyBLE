// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Startup and lifecycle adapter for the local recovery coordinator.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/localization/localization.dart';

import 'draft_recovery.dart';
import 'editor_document.dart';
import 'recovery_panel.dart';

/// Keeps connection workflows unmounted until the local startup decision is
/// resolved. The callback is scheduled after mounting, outside provider build.
class RecoveryGate extends ConsumerStatefulWidget {
  const RecoveryGate({super.key, required this.child});
  final Widget child;

  @override
  ConsumerState<RecoveryGate> createState() => _RecoveryGateState();
}

class _RecoveryGateState extends ConsumerState<RecoveryGate>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    scheduleMicrotask(() {
      if (mounted) unawaited(ref.read(draftRecoveryProvider.notifier).start());
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      final DraftRecoveryState recovery = ref.read(draftRecoveryProvider);
      if (recovery.status == DraftRecoveryStatus.pending ||
          recovery.status == DraftRecoveryStatus.saving) {
        unawaited(ref.read(draftRecoveryProvider.notifier).saveRecoveryCopy());
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final DraftRecoveryState recovery = ref.watch(draftRecoveryProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);
    if (!recovery.enabled) return widget.child;
    final DraftRecoveryController controller = ref.read(
      draftRecoveryProvider.notifier,
    );
    if (recovery.blocksStartup) {
      final DraftSnapshot? candidate = recovery.candidate;
      final EditorDocument current = ref.watch(editorDocumentProvider);
      if (candidate != null && recovery.status != DraftRecoveryStatus.loading) {
        return Scaffold(
          body: PopScope(
            canPop: false,
            child: RecoveryPanel(
              currentContent: current.content.isNotEmpty
                  ? current.content
                  : null,
              name: candidate.name,
              content: candidate.content,
              checkpointTime: candidate.checkpointTime,
              onRestore: () async {
                controller.restore();
              },
              onDiscard: () async {
                await controller.discard();
              },
              busy: recovery.busy,
              failure: recovery.failure == null
                  ? null
                  : recoveryFailureMessage(l10n, recovery.failure!),
            ),
          ),
        );
      }
      return Scaffold(
        body: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Semantics(
                  header: true,
                  child: Text(
                    l10n.recoveryTitle,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                ),
                const SizedBox(height: 16),
                if (recovery.status == DraftRecoveryStatus.loading &&
                    !recovery.timedOut) ...<Widget>[
                  LinearProgressIndicator(semanticsLabel: l10n.recoveryLoading),
                  const SizedBox(height: 16),
                  Text(l10n.recoveryLoading),
                ] else ...<Widget>[
                  Text(
                    recovery.timedOut
                        ? l10n.recoveryTimeout
                        : l10n.recoveryUnavailable,
                  ),
                  if (recovery.failure != null) ...<Widget>[
                    const SizedBox(height: 12),
                    Text(recoveryFailureMessage(l10n, recovery.failure!)),
                  ],
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 12,
                    runSpacing: 8,
                    children: <Widget>[
                      FilledButton(
                        key: kRecoveryRetryKey,
                        onPressed: () => controller.retry(),
                        child: Text(l10n.recoveryRetry),
                      ),
                      OutlinedButton(
                        key: kRecoveryContinueKey,
                        onPressed: controller.continueWithoutRecovery,
                        child: Text(l10n.recoveryContinue),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      );
    }
    if (recovery.status == DraftRecoveryStatus.volatile) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          SafeArea(
            bottom: false,
            child: Material(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 6,
                ),
                child: Wrap(
                  spacing: 12,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text(l10n.recoveryVolatile),
                    TextButton(
                      key: kRecoveryRetryKey,
                      onPressed: () => controller.retry(),
                      child: Text(l10n.recoveryRetry),
                    ),
                  ],
                ),
              ),
            ),
          ),
          Expanded(child: widget.child),
        ],
      );
    }
    return widget.child;
  }
}

/// Distinct from the board-dirty indicator and board Save feedback.
class RecoveryStatusBar extends ConsumerWidget {
  const RecoveryStatusBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final DraftRecoveryState recovery = ref.watch(draftRecoveryProvider);
    if (!recovery.enabled) return const SizedBox.shrink();
    final AppLocalizations l10n = AppLocalizations.of(context);
    final String label = switch (recovery.status) {
      DraftRecoveryStatus.saved => l10n.recoverySaved,
      DraftRecoveryStatus.saving => l10n.recoverySaving,
      DraftRecoveryStatus.pending => l10n.recoveryPending,
      DraftRecoveryStatus.volatile => l10n.recoveryVolatile,
      DraftRecoveryStatus.loading => l10n.recoveryLoading,
      DraftRecoveryStatus.decision => l10n.recoveryTitle,
      DraftRecoveryStatus.failed =>
        recovery.failure == null
            ? l10n.recoverySaveFailed
            : recoveryFailureMessage(l10n, recovery.failure!),
      DraftRecoveryStatus.disabled => '',
    };
    final bool canSave =
        !recovery.blocksStartup &&
        recovery.status != DraftRecoveryStatus.volatile &&
        recovery.status != DraftRecoveryStatus.saving;
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Wrap(
          spacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: <Widget>[
            Semantics(liveRegion: true, child: Text(label)),
            TextButton.icon(
              key: kRecoverySaveKey,
              onPressed: canSave
                  ? () async {
                      final ScaffoldMessengerState messenger =
                          ScaffoldMessenger.of(context);
                      final bool saved = await ref
                          .read(draftRecoveryProvider.notifier)
                          .saveRecoveryCopy();
                      if (!messenger.mounted) return;
                      messenger.showSnackBar(
                        SnackBar(
                          content: Text(
                            saved
                                ? l10n.recoverySavedFeedback
                                : l10n.recoverySaveFailed,
                          ),
                        ),
                      );
                    }
                  : null,
              icon: const Icon(Icons.save_alt),
              label: Text(l10n.recoverySave),
            ),
            TextButton(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                useSafeArea: true,
                builder: (BuildContext context) => const FractionallySizedBox(
                  heightFactor: 0.85,
                  child: CurrentDraftPreview(),
                ),
              ),
              child: Text(l10n.recoveryOpen),
            ),
          ],
        ),
      ),
    );
  }
}

String recoveryFailureMessage(
  AppLocalizations l10n,
  DraftStorageFailure failure,
) => switch (failure) {
  DraftStorageFailure.unavailable => l10n.recoveryErrorStorage,
  DraftStorageFailure.corrupt => l10n.recoveryErrorCorrupt,
  DraftStorageFailure.unsupportedVersion => l10n.recoveryErrorUnsupported,
  DraftStorageFailure.invalidMetadata ||
  DraftStorageFailure.invalidText => l10n.recoveryErrorInvalid,
  DraftStorageFailure.tooLarge => l10n.recoveryErrorTooLarge,
  DraftStorageFailure.conflict => l10n.recoveryErrorConflict,
};

/// Offline access to the restored text after the startup choice. Reading this
/// panel never authorizes a board action or mutates the document.
class CurrentDraftPreview extends ConsumerWidget {
  const CurrentDraftPreview({super.key, this.onContinue});
  final VoidCallback? onContinue;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final EditorDocument document = ref.watch(editorDocumentProvider);
    final DraftRecoveryState recovery = ref.watch(draftRecoveryProvider);
    return RecoveryPanel(
      name: document.name,
      content: document.content,
      checkpointTime: recovery.status == DraftRecoveryStatus.saved
          ? recovery.checkpointTime
          : null,
      restored: true,
      onRestore: () async {},
      onDiscard: () async {},
      onContinue: onContinue,
      failure: recovery.status == DraftRecoveryStatus.volatile
          ? AppLocalizations.of(context).recoveryVolatile
          : recovery.status == DraftRecoveryStatus.pending
          ? AppLocalizations.of(context).recoveryPending
          : recovery.status == DraftRecoveryStatus.saving
          ? AppLocalizations.of(context).recoverySaving
          : recovery.failure == null
          ? null
          : recoveryFailureMessage(
              AppLocalizations.of(context),
              recovery.failure!,
            ),
    );
  }
}
