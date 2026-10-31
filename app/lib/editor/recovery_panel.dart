// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Local-only recovery preview and explicit confirmations. These widgets have
/// no transport, repository or network dependency: callbacks own the decision.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'package:pyble/localization/localization.dart';

const Key kRecoveryRestoreKey = ValueKey<String>('recoveryRestore');
const Key kRecoveryDiscardKey = ValueKey<String>('recoveryDiscard');
const Key kRecoveryConfirmDiscardKey = ValueKey<String>(
  'recoveryConfirmDiscard',
);
const Key kRecoveryCopyKey = ValueKey<String>('recoveryCopy');
const Key kRecoveryRetryKey = ValueKey<String>('recoveryRetry');
const Key kRecoveryContinueKey = ValueKey<String>('recoveryContinue');
const Key kRecoverySaveKey = ValueKey<String>('recoverySave');

/// A scrollable, selectable source preview. Merely mounting or dismissing it
/// never restores, discards, copies, connects to a board, or runs code.
class RecoveryPanel extends StatelessWidget {
  const RecoveryPanel({
    super.key,
    required this.name,
    required this.content,
    required this.checkpointTime,
    required this.onRestore,
    required this.onDiscard,
    this.restored = false,
    this.busy = false,
    this.failure,
    this.onContinue,
  });

  final String name;
  final String content;
  final DateTime checkpointTime;
  final Future<void> Function() onRestore;
  final Future<void> Function() onDiscard;
  final bool restored;
  final bool busy;
  final String? failure;
  final VoidCallback? onContinue;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ThemeData theme = Theme.of(context);
    final MaterialLocalizations material = MaterialLocalizations.of(context);
    final DateTime localTime = checkpointTime.toLocal();
    final String when =
        '${material.formatMediumDate(localTime)} '
        '${material.formatTimeOfDay(TimeOfDay.fromDateTime(localTime))}';
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Semantics(
              header: true,
              child: Text(
                restored ? l10n.recoveryRestoredTitle : l10n.recoveryTitle,
                style: theme.textTheme.headlineSmall,
              ),
            ),
            const SizedBox(height: 12),
            Text(l10n.recoveryLocalOnly),
            const SizedBox(height: 12),
            SelectableText(name, style: theme.textTheme.titleMedium),
            Text(l10n.recoveryCheckpointTime(when)),
            const SizedBox(height: 12),
            Container(
              constraints: const BoxConstraints(maxHeight: 240),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerLow,
                border: Border.all(color: theme.colorScheme.outlineVariant),
                borderRadius: BorderRadius.circular(8),
              ),
              padding: const EdgeInsets.all(12),
              child: SingleChildScrollView(
                child: SelectableText(
                  content,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(l10n.recoveryScope),
            if (failure != null) ...<Widget>[
              const SizedBox(height: 12),
              Semantics(liveRegion: true, child: Text(failure!)),
            ],
            const SizedBox(height: 16),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: <Widget>[
                if (!restored)
                  FilledButton.icon(
                    key: kRecoveryRestoreKey,
                    onPressed: busy ? null : onRestore,
                    icon: const Icon(Icons.restore),
                    label: Text(l10n.recoveryRestore),
                  ),
                OutlinedButton.icon(
                  key: kRecoveryCopyKey,
                  onPressed: busy
                      ? null
                      : () async {
                          final ScaffoldMessengerState? messenger =
                              ScaffoldMessenger.maybeOf(context);
                          await Clipboard.setData(ClipboardData(text: content));
                          messenger?.showSnackBar(
                            SnackBar(content: Text(l10n.recoveryCopied)),
                          );
                        },
                  icon: const Icon(Icons.copy_outlined),
                  label: Text(l10n.recoveryCopy),
                ),
                if (!restored)
                  TextButton(
                    key: kRecoveryDiscardKey,
                    onPressed: busy
                        ? null
                        : () async {
                            if (await _confirmDiscard(context))
                              await onDiscard();
                          },
                    child: Text(l10n.recoveryDiscard),
                  ),
                if (onContinue != null)
                  FilledButton(
                    onPressed: busy ? null : onContinue,
                    child: Text(l10n.recoveryConnect),
                  ),
              ],
            ),
            if (busy) ...<Widget>[
              const SizedBox(height: 12),
              LinearProgressIndicator(semanticsLabel: l10n.recoverySaving),
            ],
          ],
        ),
      ),
    );
  }

  Future<bool> _confirmDiscard(BuildContext context) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext ctx) => AlertDialog(
            scrollable: true,
            title: Text(l10n.recoveryDiscardTitle),
            content: Text(l10n.recoveryDiscardDetail),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(false),
                child: Text(l10n.commonCancel),
              ),
              TextButton(
                key: kRecoveryConfirmDiscardKey,
                onPressed: () => Navigator.of(ctx).pop(true),
                child: Text(l10n.recoveryDiscard),
              ),
            ],
          ),
        ) ??
        false;
  }
}

/// Confirmation for a current-session board action on recovered text. The
/// caller must recheck document, target and attachment after this future.
Future<bool> confirmRecoveryBoardTarget(
  BuildContext context, {
  required String path,
  required bool run,
}) async {
  final AppLocalizations l10n = AppLocalizations.of(context);
  return await showDialog<bool>(
        context: context,
        builder: (BuildContext ctx) => AlertDialog(
          scrollable: true,
          title: Text(l10n.recoveryBoardTargetTitle),
          content: Text(
            run
                ? l10n.recoveryBoardTargetRunDetail(path)
                : l10n.recoveryBoardTargetSaveDetail(path),
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(l10n.commonCancel),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(
                run
                    ? l10n.recoveryBoardTargetRun
                    : l10n.recoveryBoardTargetSave,
              ),
            ),
          ],
        ),
      ) ??
      false;
}

/// Consent to replace the single current draft. Epoch/session fencing belongs
/// to the caller because an editor can change while a dialog is open.
Future<bool> confirmRecoveryReplacement(BuildContext context) async {
  final AppLocalizations l10n = AppLocalizations.of(context);
  return await showDialog<bool>(
        context: context,
        builder: (BuildContext ctx) => AlertDialog(
          scrollable: true,
          title: Text(l10n.recoveryReplaceTitle),
          content: Text(l10n.recoveryReplaceDetail),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(l10n.commonCancel),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(l10n.recoveryReplace),
            ),
          ],
        ),
      ) ??
      false;
}
