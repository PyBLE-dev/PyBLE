// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-30 (ADR-0010, TDD §11.6d, specs.md FR-FILES §4.5) — the [FilesView]: a real
/// board file explorer over the [Connection] file verbs.
///
/// Two ConnState-keyed treatments, read through the seam ([connStateProvider]):
///   * **Disconnected** — a quiet `folder_off` [EmptyState] with guidance and NO
///     destructive actions (nothing to act on).
///   * **Connected** — a breadcrumb + action bar (Up / Refresh / New file / New
///     folder / Upload / GitHub import) over the live listing. Tapping a folder
///     descends; tapping
///     a file opens it in the editor. Each row carries rename/delete affordances.
///     A determinate transfer bar shows during a transfer; a typed failure is
///     surfaced as an ARB-localized message (FR-FILES-3), never a raw code.
///
/// Binds through the seam ONLY (CON-8). The `files -> editor` /
/// `files -> selectedSurface` reads happen inside the controller (app-layer
/// cross-imports, allowed); no display literal is authored here — every string is
/// read verbatim from [AppLocalizations].
library;

import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show TextInputFormatter;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/pages/surface_placeholder.dart' show EmptyState;
import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart'
    show pythonBlocksFlowBusyProvider, showBoardFileAsBlocksConversion;
import 'package:pyble/editor/editor.dart' show SmartPunctuationFormatter;
import 'package:pyble/github_import/github_import.dart'
    show showGithubImportBrowser;
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'file_explorer_controller.dart';

/// The Files surface: an [EmptyState] while disconnected, the live explorer when
/// connected. A [ConsumerWidget] because its treatment depends on the live
/// [ConnState], read only through the seam.
class FilesView extends ConsumerWidget {
  const FilesView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ValueListenable<ConnState> listenable = ref.watch(connStateProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);
    return ValueListenableBuilder<ConnState>(
      valueListenable: listenable,
      builder: (BuildContext context, ConnState connState, _) {
        if (connState == ConnState.disconnected) {
          // No board → no filesystem to browse: guidance, no destructive actions.
          return EmptyState(
            icon: Icons.folder_off_outlined,
            title: l10n.filesDisconnectedTitle,
            detail: l10n.filesDisconnectedDetail,
          );
        }
        return _Explorer(connState: connState);
      },
    );
  }
}

/// The connected explorer body: action bar + transfer progress + error banner +
/// the live listing. Reads (and thereby builds) the [fileExplorerProvider].
class _Explorer extends ConsumerStatefulWidget {
  const _Explorer({required this.connState});

  final ConnState connState;

  @override
  ConsumerState<_Explorer> createState() => _ExplorerState();
}

class _ExplorerState extends ConsumerState<_Explorer> {
  final FocusNode _githubImportFocus = FocusNode(
    debugLabel: 'Files GitHub import action',
  );

  @override
  void dispose() {
    _githubImportFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final FileExplorerState state = ref.watch(fileExplorerProvider);
    final FileExplorerController ctrl = ref.read(fileExplorerProvider.notifier);
    final bool pythonBlocksBusy = ref.watch(pythonBlocksFlowBusyProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        _ActionBar(
          state: state,
          ctrl: ctrl,
          l10n: l10n,
          githubImportFocus: _githubImportFocus,
          githubImportEnabled: widget.connState == ConnState.ready,
          openGithubImport: () async {
            await showGithubImportBrowser(
              context,
              ref,
              cwd: state.cwd,
              refreshFiles: ctrl.refresh,
            );
            if (mounted) _githubImportFocus.requestFocus();
          },
        ),
        if (state.progress != null)
          _TransferBar(
            progress: state.progress!,
            speedBps: state.speedBps,
            l10n: l10n,
          ),
        if (state.error != null)
          _ErrorBanner(message: fileErrorMessage(l10n, state.error!)),
        const Divider(height: 1),
        Expanded(
          child: _EntryList(
            state: state,
            ctrl: ctrl,
            l10n: l10n,
            pythonBlocksBusy: pythonBlocksBusy,
          ),
        ),
      ],
    );
  }
}

/// The breadcrumb + action bar. Actions live in a [Wrap] so they never overflow
/// a narrow pane.
class _ActionBar extends StatelessWidget {
  const _ActionBar({
    required this.state,
    required this.ctrl,
    required this.l10n,
    required this.githubImportFocus,
    required this.githubImportEnabled,
    required this.openGithubImport,
  });

  final FileExplorerState state;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final FocusNode githubImportFocus;
  final bool githubImportEnabled;
  final Future<void> Function() openGithubImport;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(
            SignalSpacing.xs,
            SignalSpacing.xs,
            SignalSpacing.md,
            0,
          ),
          child: Row(
            children: <Widget>[
              IconButton(
                tooltip: l10n.filesGoUp,
                icon: const Icon(Icons.arrow_upward),
                onPressed: () => ctrl.up(),
              ),
              const SizedBox(width: SignalSpacing.xs),
              Expanded(
                // The cwd is a filesystem path — a verbatim technical identifier
                // (FR-I18N-4), rendered in the Signal monospace role.
                child: Text(
                  state.cwd,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: SignalType.codeOn(scheme),
                ),
              ),
            ],
          ),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: SignalSpacing.xs),
            child: Wrap(
              children: <Widget>[
                IconButton(
                  tooltip: l10n.filesActionRefresh,
                  icon: const Icon(Icons.refresh),
                  onPressed: () => ctrl.refresh(),
                ),
                IconButton(
                  tooltip: l10n.filesEmptyCta,
                  icon: const Icon(Icons.note_add_outlined),
                  onPressed: () => _promptNewFile(context, ctrl, l10n),
                ),
                IconButton(
                  tooltip: l10n.filesActionNewFolder,
                  icon: const Icon(Icons.create_new_folder_outlined),
                  onPressed: () => _promptNewFolder(context, ctrl, l10n),
                ),
                IconButton(
                  tooltip: l10n.filesActionUpload,
                  icon: const Icon(Icons.upload_file_outlined),
                  onPressed: () => ctrl.uploadCurrentBuffer(),
                ),
                IconButton(
                  focusNode: githubImportFocus,
                  tooltip: githubImportEnabled
                      ? l10n.githubImportAction
                      : l10n.githubImportRequiresReady,
                  icon: const Icon(Icons.cloud_download_outlined),
                  onPressed: githubImportEnabled ? openGithubImport : null,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// A determinate transfer progress bar (FR-FILES-4). Determinate so a settled
/// pump never spins forever; it clears when the transfer completes.
class _TransferBar extends StatelessWidget {
  const _TransferBar({
    required this.progress,
    required this.speedBps,
    required this.l10n,
  });

  final TransferProgress progress;
  final double? speedBps;
  final AppLocalizations l10n;

  /// Formats a byte count with an ASCII technical unit (B / kB / MB) — the
  /// values are numeric-technical and pass through ARB placeholders verbatim
  /// (FR-I18N-4).
  static String _fmtBytes(num bytes) {
    if (bytes >= 1000 * 1000) {
      return '${(bytes / (1000 * 1000)).toStringAsFixed(1)} MB';
    }
    if (bytes >= 1000) return '${(bytes / 1000).toStringAsFixed(1)} kB';
    return '${bytes.round()} B';
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final double? value = progress.total > 0
        ? progress.sent / progress.total
        : null;
    final String speed = speedBps == null ? '…' : '${_fmtBytes(speedBps!)}/s';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        LinearProgressIndicator(value: value),
        Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: SignalSpacing.md,
            vertical: SignalSpacing.xs,
          ),
          child: Text(
            l10n.filesTransferStatus(
              _fmtBytes(progress.sent),
              _fmtBytes(progress.total),
              speed,
            ),
            style: theme.textTheme.labelSmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    );
  }
}

/// An inline, dismissible banner surfacing a localized file-operation failure
/// (FR-FILES-3): an actionable message, never a raw status code.
class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: scheme.errorContainer,
      padding: const EdgeInsets.symmetric(
        horizontal: SignalSpacing.lg,
        vertical: SignalSpacing.sm,
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.error_outline, size: 20, color: scheme.onErrorContainer),
          const SizedBox(width: SignalSpacing.sm),
          Expanded(
            child: Text(
              message,
              style: TextStyle(color: scheme.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}

/// The live listing, or a folder-empty [EmptyState] once a listing settles empty.
class _EntryList extends StatelessWidget {
  const _EntryList({
    required this.state,
    required this.ctrl,
    required this.l10n,
    required this.pythonBlocksBusy,
  });

  final FileExplorerState state;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final bool pythonBlocksBusy;

  @override
  Widget build(BuildContext context) {
    // Pull-to-refresh re-lists the current directory (FR-FILES-1). Both branches
    // stay always-scrollable so the gesture works even in an empty folder.
    final Widget body;
    if (state.entries.isEmpty && !state.loading) {
      body = LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) =>
            SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: EmptyState(
                  icon: Icons.folder_open_outlined,
                  title: l10n.filesFolderEmpty,
                  action: FilledButton.icon(
                    onPressed: () => _promptNewFile(context, ctrl, l10n),
                    icon: const Icon(Icons.add),
                    label: Text(l10n.filesEmptyCta),
                  ),
                ),
              ),
            ),
      );
    } else {
      body = ListView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: state.entries.length,
        itemBuilder: (BuildContext context, int i) {
          final RemoteEntry e = state.entries[i];
          return _EntryRow(
            entry: e,
            ctrl: ctrl,
            l10n: l10n,
            pythonBlocksBusy: pythonBlocksBusy,
          );
        },
      );
    }
    return RefreshIndicator(onRefresh: ctrl.refresh, child: body);
  }
}

/// One listing row (design-system.md §7.10). Tapping the body descends (dir) or
/// opens (file); the trailing affordances rename/delete the entry.
class _EntryRow extends StatelessWidget {
  const _EntryRow({
    required this.entry,
    required this.ctrl,
    required this.l10n,
    required this.pythonBlocksBusy,
  });

  final RemoteEntry entry;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final bool pythonBlocksBusy;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final bool isPy = !entry.isDir && entry.name.endsWith('.py');
    return ListTile(
      key: ValueKey<String>('fileEntry_${entry.name}'),
      leading: Icon(
        _iconFor(entry),
        color: isPy ? scheme.primary : scheme.onSurfaceVariant,
      ),
      title: Text(entry.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: entry.isDir ? null : Text(l10n.filesSizeBytes(entry.size)),
      onTap: () =>
          entry.isDir ? ctrl.into(entry.name) : ctrl.openInEditor(entry.name),
      trailing: isPy
          ? Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                IconButton(
                  key: ValueKey<String>('fileOpenBlocks_${entry.name}'),
                  tooltip: l10n.filesOpenAsBlocks,
                  icon: const Icon(Icons.account_tree_outlined),
                  onPressed: pythonBlocksBusy
                      ? null
                      : () async {
                          final captured = await ctrl.downloadForBlocks(
                            entry.name,
                          );
                          if (captured == null || !context.mounted) return;
                          await showBoardFileAsBlocksConversion(
                            context,
                            captured: captured,
                          );
                        },
                ),
                PopupMenuButton<_EntryAction>(
                  key: ValueKey<String>('fileMore_${entry.name}'),
                  tooltip: MaterialLocalizations.of(context).moreButtonTooltip,
                  onSelected: (_EntryAction action) {
                    switch (action) {
                      case _EntryAction.rename:
                        _promptRename(context, ctrl, l10n, entry.name);
                      case _EntryAction.delete:
                        _promptDelete(context, ctrl, l10n, entry.name);
                    }
                  },
                  itemBuilder: (BuildContext context) =>
                      <PopupMenuEntry<_EntryAction>>[
                        PopupMenuItem<_EntryAction>(
                          key: ValueKey<String>('fileRename_${entry.name}'),
                          value: _EntryAction.rename,
                          child: ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(
                              Icons.drive_file_rename_outline,
                            ),
                            title: Text(l10n.commonRename),
                          ),
                        ),
                        PopupMenuItem<_EntryAction>(
                          key: ValueKey<String>('fileDelete_${entry.name}'),
                          value: _EntryAction.delete,
                          child: ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.delete_outline),
                            title: Text(l10n.commonDelete),
                          ),
                        ),
                      ],
                ),
              ],
            )
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                IconButton(
                  key: ValueKey<String>('fileRename_${entry.name}'),
                  tooltip: l10n.commonRename,
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.drive_file_rename_outline),
                  onPressed: () =>
                      _promptRename(context, ctrl, l10n, entry.name),
                ),
                IconButton(
                  key: ValueKey<String>('fileDelete_${entry.name}'),
                  tooltip: l10n.commonDelete,
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () =>
                      _promptDelete(context, ctrl, l10n, entry.name),
                ),
              ],
            ),
    );
  }

  IconData _iconFor(RemoteEntry e) {
    if (e.isDir) return Icons.folder;
    if (e.name.endsWith('.py')) return Icons.description;
    return Icons.insert_drive_file;
  }
}

enum _EntryAction { rename, delete }

/// Maps a neutral [FileErrorKind] to its ARB-sourced, actionable message
/// (FR-FILES-3, FR-I18N-3). This is the widget-layer half of the mapping.
String fileErrorMessage(AppLocalizations l10n, FileErrorKind kind) {
  return switch (kind) {
    FileErrorKind.notFound => l10n.filesErrorNotFound,
    FileErrorKind.permission => l10n.filesErrorPermission,
    FileErrorKind.storageFull => l10n.filesErrorStorageFull,
    FileErrorKind.io => l10n.filesErrorIo,
    FileErrorKind.crc => l10n.filesErrorCrc,
    FileErrorKind.busy => l10n.filesErrorBusy,
    FileErrorKind.unsupported => l10n.filesErrorUnsupported,
    FileErrorKind.range => l10n.filesErrorRange,
    FileErrorKind.badRequest => l10n.filesErrorBadRequest,
    FileErrorKind.notConnected => l10n.filesErrorNotConnected,
    FileErrorKind.timeout => l10n.filesErrorTimeout,
    FileErrorKind.generic => l10n.filesErrorGeneric,
  };
}

// --- dialogs -----------------------------------------------------------------

Future<void> _promptNewFile(
  BuildContext context,
  FileExplorerController ctrl,
  AppLocalizations l10n,
) async {
  final String? name = await _promptName(
    context,
    l10n,
    title: l10n.filesNewFileTitle,
    confirmLabel: l10n.commonCreate,
  );
  if (name != null && name.isNotEmpty) {
    await ctrl.newFile(name);
  }
}

Future<void> _promptNewFolder(
  BuildContext context,
  FileExplorerController ctrl,
  AppLocalizations l10n,
) async {
  final String? name = await _promptName(
    context,
    l10n,
    title: l10n.filesNewFolderTitle,
    confirmLabel: l10n.commonCreate,
  );
  if (name != null && name.isNotEmpty) {
    await ctrl.mkdir(name);
  }
}

Future<void> _promptRename(
  BuildContext context,
  FileExplorerController ctrl,
  AppLocalizations l10n,
  String from,
) async {
  final String? to = await _promptName(
    context,
    l10n,
    title: l10n.filesRenameTitle(from),
    confirmLabel: l10n.commonRename,
    initial: from,
  );
  if (to != null && to.isNotEmpty && to != from) {
    await ctrl.rename(from, to);
  }
}

Future<void> _promptDelete(
  BuildContext context,
  FileExplorerController ctrl,
  AppLocalizations l10n,
  String name,
) async {
  final bool confirmed =
      await showDialog<bool>(
        context: context,
        builder: (BuildContext ctx) => AlertDialog(
          title: Text(l10n.filesDeleteConfirmTitle(name)),
          content: Text(l10n.filesDeleteConfirmBody),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(l10n.commonCancel),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(l10n.commonDelete),
            ),
          ],
        ),
      ) ??
      false;
  if (confirmed) {
    await ctrl.delete(name);
  }
}

/// A single-field name dialog shared by new-file / new-folder / rename. Returns
/// the trimmed entry name, or `null` if cancelled. The value is a technical
/// identifier (filename) and is never localized (FR-I18N-4).
Future<String?> _promptName(
  BuildContext context,
  AppLocalizations l10n, {
  required String title,
  required String confirmLabel,
  String initial = '',
}) async {
  return showDialog<String>(
    context: context,
    builder: (BuildContext ctx) => _NameDialog(
      title: title,
      confirmLabel: confirmLabel,
      initial: initial,
      fieldLabel: l10n.filesNameFieldLabel,
      cancelLabel: l10n.commonCancel,
    ),
  );
}

/// The single-field name dialog body. Owns its [TextEditingController] in
/// [State] so it is disposed only after the route is fully removed — disposing
/// it inline right after `showDialog` returns crashes the still-running exit
/// transition (it re-listens to a disposed controller).
class _NameDialog extends StatefulWidget {
  const _NameDialog({
    required this.title,
    required this.confirmLabel,
    required this.initial,
    required this.fieldLabel,
    required this.cancelLabel,
  });

  final String title;
  final String confirmLabel;
  final String initial;
  final String fieldLabel;
  final String cancelLabel;

  @override
  State<_NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<_NameDialog> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.initial,
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: TextField(
        controller: _controller,
        autofocus: true,
        // Filenames are ASCII technical identifiers (FR-I18N-4). Left to the
        // platform defaults, iPadOS would auto-capitalize `main.py` to `Main.py`
        // and autocorrect would rewrite the stem outright.
        smartQuotesType: SmartQuotesType.disabled,
        smartDashesType: SmartDashesType.disabled,
        autocorrect: false,
        enableSuggestions: false,
        textCapitalization: TextCapitalization.none,
        // The flags above only affect iOS; the formatter is what actually keeps
        // a curly quote or a non-breaking space out of a board filename.
        inputFormatters: const <TextInputFormatter>[
          SmartPunctuationFormatter(),
        ],
        decoration: InputDecoration(labelText: widget.fieldLabel),
        onSubmitted: (String value) => Navigator.of(context).pop(value.trim()),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(widget.cancelLabel),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text.trim()),
          child: Text(widget.confirmLabel),
        ),
      ],
    );
  }
}
