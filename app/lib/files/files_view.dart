// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-30 (ADR-0010, TDD §11.6d, specs.md FR-FILES §4.5) — the [FilesView]: a real
/// board file explorer over the [Connection] file verbs.
///
/// Two ConnState-keyed treatments, read through the seam ([connStateProvider]):
///   * **Disconnected** — a quiet `folder_off` [EmptyState] with guidance and NO
///     destructive actions (nothing to act on).
///   * **Connected** — a breadcrumb + responsive, single-row action toolbar
///     (Select / Refresh / New file / New folder / Upload / GitHub import) over
///     the live listing. Lower-priority actions move into a labelled overflow
///     only when all six targets do not fit. Tapping a folder descends; tapping
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
import 'package:flutter/services.dart'
    show LogicalKeyboardKey, TextInputFormatter;
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

/// Stable interaction keys used by widget, golden, and hardware acceptance
/// tests for the normal toolbar and visible-file multi-delete workflow
/// (ADR-0043).
const Key kFilesSelectActionKey = ValueKey<String>('filesSelectAction');
const Key kFilesNormalActionsRowKey = ValueKey<String>('filesNormalActionsRow');
const Key kFilesActionsOverflowButtonKey = ValueKey<String>(
  'filesActionsOverflowButton',
);
const Key kFilesOverflowRefreshKey = ValueKey<String>('filesOverflowRefresh');
const Key kFilesOverflowNewFileKey = ValueKey<String>('filesOverflowNewFile');
const Key kFilesOverflowNewFolderKey = ValueKey<String>(
  'filesOverflowNewFolder',
);
const Key kFilesOverflowUploadKey = ValueKey<String>('filesOverflowUpload');
const Key kFilesSelectionBarKey = ValueKey<String>('filesSelectionBar');
const Key kFilesSelectAllShownKey = ValueKey<String>('filesSelectAllShown');
const Key kFilesBulkDeleteActionKey = ValueKey<String>('filesBulkDeleteAction');

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
  final FocusNode _selectFocus = FocusNode(debugLabel: 'Files Select action');
  final FocusNode _selectionCancelFocus = FocusNode(
    debugLabel: 'Files selection Cancel action',
  );
  final FocusNode _selectionResultFocus = FocusNode(
    debugLabel: 'Files multi-delete result',
  );

  final Set<String> _selectedNames = <String>{};
  bool _selectionMode = false;
  bool _deleting = false;
  bool _invalidationScheduled = false;
  bool _deleteReviewOpen = false;
  String? _selectionCwd;
  Object? _selectionSessionStamp;
  List<RemoteEntry>? _selectionListing;
  BuildContext? _deleteReviewContext;
  NavigatorState? _deleteReviewNavigator;
  Route<dynamic>? _deleteReviewRoute;
  FileDeleteBatchProgress? _deleteProgress;
  FileDeleteBatchResult? _deleteResult;

  @override
  void dispose() {
    final NavigatorState? navigator = _deleteReviewNavigator;
    final Route<dynamic>? reviewRoute = _deleteReviewRoute;
    if (_deleteReviewOpen && navigator != null && reviewRoute != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (navigator.mounted && reviewRoute.isActive) {
          navigator.removeRoute(reviewRoute, false);
        }
      });
    }
    _deleteReviewOpen = false;
    _deleteReviewContext = null;
    _deleteReviewNavigator = null;
    _deleteReviewRoute = null;
    _githubImportFocus.dispose();
    _selectFocus.dispose();
    _selectionCancelFocus.dispose();
    _selectionResultFocus.dispose();
    super.dispose();
  }

  List<RemoteEntry> _eligibleEntries(FileExplorerState state) => state.entries
      .where(
        (RemoteEntry entry) =>
            !entry.isDir &&
            isEditableBoardEntry(
              fsRoot: state.fsRoot,
              cwd: state.cwd,
              name: entry.name,
            ),
      )
      .toList(growable: false);

  Object get _currentSessionStamp =>
      connectionSessionStampOf(ref.read(connectionProvider));

  void _enterSelection(FileExplorerState state, [String? initiallySelected]) {
    if (_selectionMode || _deleting || state.loading) return;
    setState(() {
      _selectionMode = true;
      _selectionCwd = state.cwd;
      _selectionSessionStamp = _currentSessionStamp;
      _selectionListing = state.entries;
      _selectedNames
        ..clear()
        ..addAll(
          initiallySelected == null
              ? const <String>[]
              : <String>[initiallySelected],
        );
      _deleteProgress = null;
      _deleteResult = null;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _selectionCancelFocus.requestFocus();
    });
  }

  void _exitSelection({bool restoreSelectFocus = true}) {
    if (!_selectionMode || _deleting) return;
    setState(() {
      _selectionMode = false;
      _selectionCwd = null;
      _selectionSessionStamp = null;
      _selectionListing = null;
      _selectedNames.clear();
      _deleteProgress = null;
      _deleteResult = null;
    });
    if (restoreSelectFocus) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _selectFocus.requestFocus();
      });
    }
  }

  void _scheduleSelectionInvalidation(
    FileExplorerState state, {
    required bool presentationHidden,
  }) {
    if (!_selectionMode || _deleting || _invalidationScheduled) return;
    final bool invalid =
        presentationHidden ||
        state.cwd != _selectionCwd ||
        !identical(_currentSessionStamp, _selectionSessionStamp) ||
        !identical(state.entries, _selectionListing);
    if (!invalid) return;
    _invalidationScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _invalidationScheduled = false;
      if (mounted && _selectionMode && !_deleting) {
        final BuildContext? reviewContext = _deleteReviewContext;
        final bool dismissedReview =
            _deleteReviewOpen &&
            reviewContext != null &&
            reviewContext.mounted &&
            (ModalRoute.of(reviewContext)?.isCurrent ?? false);
        if (dismissedReview) Navigator.of(reviewContext).pop(false);
        _exitSelection(
          restoreSelectFocus: !presentationHidden && !dismissedReview,
        );
      }
    });
  }

  void _toggleSelection(String name) {
    if (!_selectionMode || _deleting) return;
    setState(() {
      _deleteResult = null;
      if (!_selectedNames.remove(name)) _selectedNames.add(name);
    });
  }

  void _toggleAllShown(List<RemoteEntry> eligible) {
    if (!_selectionMode || _deleting || eligible.isEmpty) return;
    final Set<String> shown = eligible
        .map((RemoteEntry entry) => entry.name)
        .toSet();
    setState(() {
      _deleteResult = null;
      if (_selectedNames.containsAll(shown)) {
        _selectedNames.clear();
      } else {
        _selectedNames
          ..clear()
          ..addAll(shown);
      }
    });
  }

  List<String> _orderedSelection(FileExplorerState state) => state.entries
      .where(
        (RemoteEntry entry) =>
            !entry.isDir && _selectedNames.contains(entry.name),
      )
      .map((RemoteEntry entry) => entry.name)
      .toList(growable: false);

  Future<void> _deleteSelected(
    FileExplorerState state,
    FileExplorerController ctrl,
    AppLocalizations l10n,
  ) async {
    if (_deleting ||
        _deleteReviewOpen ||
        !_selectionMode ||
        _selectedNames.isEmpty) {
      return;
    }
    final List<String> orderedNames = _orderedSelection(state);
    final String? capturedCwd = _selectionCwd;
    final Object? capturedSession = _selectionSessionStamp;
    if (orderedNames.isEmpty ||
        capturedCwd == null ||
        capturedSession == null) {
      return;
    }

    bool confirmed = false;
    _deleteReviewOpen = true;
    try {
      confirmed = await _confirmDeleteSelected(
        context,
        l10n,
        cwd: capturedCwd,
        orderedNames: orderedNames,
        onPresented: (BuildContext dialogContext) {
          if (mounted && _deleteReviewOpen) {
            _deleteReviewContext = dialogContext;
            _deleteReviewNavigator = Navigator.of(dialogContext);
            _deleteReviewRoute = ModalRoute.of(dialogContext);
          }
        },
      );
    } finally {
      _deleteReviewOpen = false;
      _deleteReviewContext = null;
      _deleteReviewNavigator = null;
      _deleteReviewRoute = null;
    }
    if (!mounted || !confirmed) {
      if (mounted && !_selectionMode && !_presentationIsHidden()) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _selectFocus.requestFocus();
        });
      }
      return;
    }

    final FileExplorerState beforeDelete = ref.read(fileExplorerProvider);
    if (!_selectionMode ||
        beforeDelete.cwd != capturedCwd ||
        !identical(beforeDelete.entries, _selectionListing) ||
        !identical(_currentSessionStamp, capturedSession)) {
      // The exact review became stale while its dialog was open. The normal
      // build-time invalidation clears the contextual mode; never execute a
      // confirmation against a replacement listing or board session.
      if (_selectionMode && !_deleting) {
        _exitSelection(restoreSelectFocus: true);
      }
      return;
    }

    setState(() {
      _deleting = true;
      _deleteResult = null;
      _deleteProgress = FileDeleteBatchProgress(
        completed: 0,
        total: orderedNames.length,
        currentPath: _joinBoardPath(capturedCwd, orderedNames.first),
      );
    });

    final FileDeleteBatchResult result = await ctrl.deleteMany(
      orderedNames,
      expectedCwd: capturedCwd,
      expectedSessionStamp: capturedSession,
      onProgress: (FileDeleteBatchProgress progress) {
        if (!mounted || !_deleting) return;
        setState(() => _deleteProgress = progress);
      },
    );
    if (!mounted) return;

    final FileExplorerState latest = ref.read(fileExplorerProvider);
    final bool presentationHidden = _presentationIsHidden();
    final bool scopeChanged =
        latest.cwd != capturedCwd ||
        !identical(_currentSessionStamp, capturedSession) ||
        presentationHidden;
    if (scopeChanged) {
      setState(() {
        _deleting = false;
        _selectionMode = false;
        _selectionCwd = null;
        _selectionSessionStamp = null;
        _selectionListing = null;
        _selectedNames.clear();
        _deleteProgress = null;
        _deleteResult = null;
      });
      _announceBatchResult(result, l10n, intendedCount: orderedNames.length);
      return;
    }

    if (result.outcome == FileDeleteBatchOutcome.complete) {
      final int deletedCount = result.succeededPaths.length;
      setState(() {
        _deleting = false;
        _selectionMode = false;
        _selectionCwd = null;
        _selectionSessionStamp = null;
        _selectionListing = null;
        _selectedNames.clear();
        _deleteProgress = null;
        _deleteResult = null;
      });
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          SnackBar(
            content: Text(l10n.filesDeleteSelectedComplete(deletedCount)),
          ),
        );
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _selectFocus.requestFocus();
      });
      return;
    }

    // A controller refusal can occur before it has a meaningful failed path
    // (for example a concurrent-batch `busy` result). In every non-complete
    // case, selection truth is therefore the original intent minus only paths
    // the controller explicitly confirmed as succeeded.
    final Set<String> unresolved = orderedNames.toSet()
      ..removeAll(result.succeededPaths.map(_leafOf));
    final Set<String> eligibleNow = _eligibleEntries(
      latest,
    ).map((RemoteEntry entry) => entry.name).toSet();
    unresolved.retainAll(eligibleNow);
    setState(() {
      _deleting = false;
      _deleteProgress = null;
      _deleteResult = result;
      _selectionListing = latest.entries;
      _selectedNames
        ..clear()
        ..addAll(unresolved);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _selectionResultFocus.requestFocus();
    });
  }

  bool _presentationIsHidden() {
    final Size viewport = MediaQuery.sizeOf(context);
    final bool wideLandscape =
        viewport.width >= 900 && viewport.width > viewport.height;
    final AppSurface selectedSurface = ref.read(selectedSurfaceProvider);
    return !wideLandscape &&
        selectedSurface != AppSurface.connect &&
        selectedSurface != AppSurface.files;
  }

  void _announceBatchResult(
    FileDeleteBatchResult result,
    AppLocalizations l10n, {
    required int intendedCount,
  }) {
    final String message;
    if (result.outcome == FileDeleteBatchOutcome.complete) {
      message = l10n.filesDeleteSelectedComplete(result.succeededPaths.length);
    } else {
      final int remaining = intendedCount - result.succeededPaths.length;
      final String accounting = l10n.filesDeleteSelectedStopped(
        result.succeededPaths.length,
        remaining,
      );
      message = switch (result.failure) {
        final FileErrorKind failure =>
          '$accounting ${fileErrorMessage(l10n, failure)}',
        null => accounting,
      };
    }
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final FileExplorerState state = ref.watch(fileExplorerProvider);
    final FileExplorerController ctrl = ref.read(fileExplorerProvider.notifier);
    final bool pythonBlocksBusy = ref.watch(pythonBlocksFlowBusyProvider);
    ref.watch(selectedSurfaceProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);
    final List<RemoteEntry> eligible = _eligibleEntries(state);
    // In the stacked shell, IndexedStack keeps Files mounted while another
    // destination is shown. `connect` is exempt so FilesView remains useful in
    // isolated feature/golden hosts whose navigation provider is not driven by
    // the shell. The wide text workbench keeps Files genuinely visible beside
    // Editor/Console, so changing centre focus there is not navigation away.
    final bool presentationHidden = _presentationIsHidden();
    _scheduleSelectionInvalidation(
      state,
      presentationHidden: presentationHidden,
    );

    return CallbackShortcuts(
      bindings: <ShortcutActivator, VoidCallback>{
        const SingleActivator(LogicalKeyboardKey.escape): () {
          if (_selectionMode && !_deleting) _exitSelection();
        },
      },
      child: PopScope(
        canPop: !_selectionMode,
        onPopInvokedWithResult: (bool didPop, Object? result) {
          if (!didPop && _selectionMode && !_deleting) _exitSelection();
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            if (_selectionMode)
              _SelectionBar(
                cwd: state.cwd,
                selectedCount: _selectedNames.length,
                eligibleCount: eligible.length,
                allShownSelected:
                    eligible.isNotEmpty &&
                    eligible.every(
                      (RemoteEntry entry) =>
                          _selectedNames.contains(entry.name),
                    ),
                deleting: _deleting,
                l10n: l10n,
                cancelFocus: _selectionCancelFocus,
                onCancel: () => _exitSelection(),
                onToggleAll: () => _toggleAllShown(eligible),
                onDelete: () => _deleteSelected(state, ctrl, l10n),
              )
            else
              _ActionBar(
                state: state,
                ctrl: ctrl,
                l10n: l10n,
                selectFocus: _selectFocus,
                canSelect: eligible.isNotEmpty && !state.loading,
                onSelect: () => _enterSelection(state),
                githubImportFocus: _githubImportFocus,
                githubImportEnabled:
                    widget.connState == ConnState.ready &&
                    state.hasReportedFsRoot,
                openGithubImport: () async {
                  await showGithubImportBrowser(
                    context,
                    ref,
                    fsRoot: state.fsRoot,
                    cwd: state.cwd,
                    refreshFiles: ctrl.refresh,
                  );
                  if (mounted) _githubImportFocus.requestFocus();
                },
              ),
            if (_deleting && _deleteProgress != null)
              _DeleteProgressBanner(progress: _deleteProgress!, l10n: l10n),
            if (!_selectionMode && state.progress != null)
              _TransferBar(
                progress: state.progress!,
                speedBps: state.speedBps,
                l10n: l10n,
              ),
            if (_deleteResult case final FileDeleteBatchResult result)
              _BatchResultBanner(
                result: result,
                remaining: _selectedNames.length,
                l10n: l10n,
                focusNode: _selectionResultFocus,
              )
            else if (state.error != null)
              _ErrorBanner(message: fileErrorMessage(l10n, state.error!)),
            const Divider(height: 1),
            Expanded(
              child: _EntryList(
                state: state,
                ctrl: ctrl,
                l10n: l10n,
                pythonBlocksBusy: pythonBlocksBusy,
                selectionMode: _selectionMode,
                deleting: _deleting,
                selectedNames: _selectedNames,
                onToggleSelection: _toggleSelection,
                onEnterSelection: (String name) => _enterSelection(state, name),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

enum _FilesOverflowAction { refresh, newFile, newFolder, upload }

/// The breadcrumb + responsive one-row action toolbar.
class _ActionBar extends StatelessWidget {
  const _ActionBar({
    required this.state,
    required this.ctrl,
    required this.l10n,
    required this.selectFocus,
    required this.canSelect,
    required this.onSelect,
    required this.githubImportFocus,
    required this.githubImportEnabled,
    required this.openGithubImport,
  });

  final FileExplorerState state;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final FocusNode selectFocus;
  final bool canSelect;
  final VoidCallback onSelect;
  final FocusNode githubImportFocus;
  final bool githubImportEnabled;
  final Future<void> Function() openGithubImport;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final Widget selectAction = IconButton(
      key: kFilesSelectActionKey,
      focusNode: selectFocus,
      tooltip: l10n.filesActionSelect,
      onPressed: canSelect ? onSelect : null,
      icon: const Icon(Icons.checklist_outlined),
    );
    final Widget githubAction = IconButton(
      focusNode: githubImportFocus,
      tooltip: githubImportEnabled
          ? l10n.githubImportAction
          : l10n.githubImportRequiresReady,
      icon: const Icon(Icons.cloud_download_outlined),
      onPressed: githubImportEnabled ? openGithubImport : null,
    );
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
            child: LayoutBuilder(
              builder: (BuildContext context, BoxConstraints constraints) {
                // Six direct Material targets need 288 dp. Below that exact
                // bound, keep the two priority actions visible and move the
                // remaining four into one labelled, accessible menu.
                final bool compact = constraints.maxWidth < 6 * 48;
                return SizedBox(
                  key: kFilesNormalActionsRowKey,
                  height: 48,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: compact
                        ? <Widget>[
                            selectAction,
                            githubAction,
                            PopupMenuButton<_FilesOverflowAction>(
                              key: kFilesActionsOverflowButtonKey,
                              tooltip: l10n.filesMoreActions,
                              constraints: const BoxConstraints(
                                minWidth: 220,
                                maxWidth: 320,
                              ),
                              icon: const Icon(Icons.more_vert),
                              onSelected: (_FilesOverflowAction action) {
                                switch (action) {
                                  case _FilesOverflowAction.refresh:
                                    ctrl.refresh();
                                    break;
                                  case _FilesOverflowAction.newFile:
                                    _promptNewFile(context, ctrl, l10n);
                                    break;
                                  case _FilesOverflowAction.newFolder:
                                    _promptNewFolder(context, ctrl, l10n);
                                    break;
                                  case _FilesOverflowAction.upload:
                                    ctrl.uploadCurrentBuffer();
                                    break;
                                }
                              },
                              itemBuilder: (BuildContext context) =>
                                  <PopupMenuEntry<_FilesOverflowAction>>[
                                    PopupMenuItem<_FilesOverflowAction>(
                                      key: kFilesOverflowRefreshKey,
                                      value: _FilesOverflowAction.refresh,
                                      child: _FilesOverflowLabel(
                                        icon: Icons.refresh,
                                        label: l10n.filesActionRefresh,
                                      ),
                                    ),
                                    PopupMenuItem<_FilesOverflowAction>(
                                      key: kFilesOverflowNewFileKey,
                                      value: _FilesOverflowAction.newFile,
                                      child: _FilesOverflowLabel(
                                        icon: Icons.note_add_outlined,
                                        label: l10n.filesEmptyCta,
                                      ),
                                    ),
                                    PopupMenuItem<_FilesOverflowAction>(
                                      key: kFilesOverflowNewFolderKey,
                                      value: _FilesOverflowAction.newFolder,
                                      child: _FilesOverflowLabel(
                                        icon: Icons.create_new_folder_outlined,
                                        label: l10n.filesActionNewFolder,
                                      ),
                                    ),
                                    PopupMenuItem<_FilesOverflowAction>(
                                      key: kFilesOverflowUploadKey,
                                      value: _FilesOverflowAction.upload,
                                      child: _FilesOverflowLabel(
                                        icon: Icons.upload_file_outlined,
                                        label: l10n.filesActionUpload,
                                      ),
                                    ),
                                  ],
                            ),
                          ]
                        : <Widget>[
                            selectAction,
                            IconButton(
                              tooltip: l10n.filesActionRefresh,
                              icon: const Icon(Icons.refresh),
                              onPressed: () => ctrl.refresh(),
                            ),
                            IconButton(
                              tooltip: l10n.filesEmptyCta,
                              icon: const Icon(Icons.note_add_outlined),
                              onPressed: () =>
                                  _promptNewFile(context, ctrl, l10n),
                            ),
                            IconButton(
                              tooltip: l10n.filesActionNewFolder,
                              icon: const Icon(
                                Icons.create_new_folder_outlined,
                              ),
                              onPressed: () =>
                                  _promptNewFolder(context, ctrl, l10n),
                            ),
                            IconButton(
                              tooltip: l10n.filesActionUpload,
                              icon: const Icon(Icons.upload_file_outlined),
                              onPressed: () => ctrl.uploadCurrentBuffer(),
                            ),
                            githubAction,
                          ],
                  ),
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _FilesOverflowLabel extends StatelessWidget {
  const _FilesOverflowLabel({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    children: <Widget>[
      Icon(icon, size: 20),
      const SizedBox(width: SignalSpacing.md),
      Expanded(child: Text(label)),
    ],
  );
}

/// Session-scoped replacement for the ordinary Files actions. It stays compact
/// on a wide tablet pane and deliberately reflows into two rows for a narrow
/// phone/pane or large text, preserving every 48 dp action target.
class _SelectionBar extends StatelessWidget {
  const _SelectionBar({
    required this.cwd,
    required this.selectedCount,
    required this.eligibleCount,
    required this.allShownSelected,
    required this.deleting,
    required this.l10n,
    required this.cancelFocus,
    required this.onCancel,
    required this.onToggleAll,
    required this.onDelete,
  });

  final String cwd;
  final int selectedCount;
  final int eligibleCount;
  final bool allShownSelected;
  final bool deleting;
  final AppLocalizations l10n;
  final FocusNode cancelFocus;
  final VoidCallback onCancel;
  final VoidCallback onToggleAll;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final double textScale = MediaQuery.textScalerOf(context).scale(1);
    return Material(
      key: kFilesSelectionBarKey,
      color: scheme.surfaceContainerHigh,
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final bool compact = constraints.maxWidth < 560 || textScale > 1.4;
          final Widget cancel = IconButton(
            focusNode: cancelFocus,
            tooltip: l10n.filesSelectionCancel,
            icon: const Icon(Icons.close),
            onPressed: deleting ? null : onCancel,
          );
          final Widget information = _SelectionInformation(
            cwd: cwd,
            countLabel: l10n.filesSelectionSelectedCount(selectedCount),
            l10n: l10n,
            showGuidance: !compact,
          );
          final List<Widget> actions = <Widget>[
            IconButton(
              key: kFilesSelectAllShownKey,
              tooltip: allShownSelected
                  ? l10n.filesSelectionClearAll
                  : l10n.filesSelectionSelectAllShown(eligibleCount),
              icon: Icon(
                allShownSelected
                    ? Icons.deselect_outlined
                    : Icons.select_all_outlined,
              ),
              onPressed: deleting || eligibleCount == 0 ? null : onToggleAll,
            ),
            IconButton(
              key: kFilesBulkDeleteActionKey,
              tooltip: l10n.filesSelectionDelete,
              color: scheme.error,
              disabledColor: scheme.onSurface.withValues(alpha: 0.38),
              icon: const Icon(Icons.delete_outline),
              onPressed: deleting || selectedCount == 0 ? null : onDelete,
            ),
          ];

          if (!compact) {
            return Padding(
              padding: const EdgeInsets.fromLTRB(
                SignalSpacing.xs,
                SignalSpacing.xs,
                SignalSpacing.xs,
                SignalSpacing.xs,
              ),
              child: Row(
                children: <Widget>[
                  cancel,
                  const SizedBox(width: SignalSpacing.xs),
                  Expanded(child: information),
                  ...actions,
                ],
              ),
            );
          }

          return Padding(
            padding: const EdgeInsets.fromLTRB(
              SignalSpacing.xs,
              SignalSpacing.xs,
              SignalSpacing.xs,
              SignalSpacing.sm,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    cancel,
                    const SizedBox(width: SignalSpacing.xs),
                    Expanded(child: information),
                  ],
                ),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.only(
                          left: SignalSpacing.sm,
                          right: SignalSpacing.xs,
                        ),
                        child: Text(
                          l10n.filesSelectionFilesOnly,
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: scheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                    ),
                    ...actions,
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SelectionInformation extends StatelessWidget {
  const _SelectionInformation({
    required this.cwd,
    required this.countLabel,
    required this.l10n,
    required this.showGuidance,
  });

  final String cwd;
  final String countLabel;
  final AppLocalizations l10n;
  final bool showGuidance;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Semantics(
          container: true,
          liveRegion: true,
          label: countLabel,
          child: ExcludeSemantics(
            child: Text(countLabel, style: theme.textTheme.titleMedium),
          ),
        ),
        Text(
          cwd,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: SignalType.codeOn(scheme),
        ),
        // Wide panes keep the contextual actions on one horizontal line, so
        // the files-only boundary remains here as a short third information
        // line. Narrow panes render the same guidance beside the second row of
        // actions instead.
        if (showGuidance)
          Text(
            l10n.filesSelectionFilesOnly,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.labelMedium?.copyWith(
              color: scheme.onSurfaceVariant,
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

/// Visible, live item-level feedback while the sequential, fail-fast batch is
/// locked. The controller reports completed items before each current path.
class _DeleteProgressBanner extends StatelessWidget {
  const _DeleteProgressBanner({required this.progress, required this.l10n});

  final FileDeleteBatchProgress progress;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final String message = l10n.filesDeleteSelectedProgress(
      _leafOf(progress.currentPath),
      progress.completed,
      progress.total,
    );
    return Semantics(
      container: true,
      liveRegion: true,
      label: message,
      child: ExcludeSemantics(
        child: Container(
          width: double.infinity,
          color: scheme.secondaryContainer,
          padding: const EdgeInsets.symmetric(
            horizontal: SignalSpacing.lg,
            vertical: SignalSpacing.sm,
          ),
          child: Row(
            children: <Widget>[
              SizedBox.square(
                dimension: 20,
                child: CircularProgressIndicator(
                  value: progress.total == 0
                      ? 0
                      : progress.completed / progress.total,
                  strokeWidth: 2,
                  color: scheme.onSecondaryContainer,
                ),
              ),
              const SizedBox(width: SignalSpacing.sm),
              Expanded(
                child: Text(
                  message,
                  style: TextStyle(color: scheme.onSecondaryContainer),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// One authoritative partial/failed result. It combines the exact batch
/// accounting with the controller's typed localized failure, avoiding a second
/// generic error banner for the same failure.
class _BatchResultBanner extends StatelessWidget {
  const _BatchResultBanner({
    required this.result,
    required this.remaining,
    required this.l10n,
    required this.focusNode,
  });

  final FileDeleteBatchResult result;
  final int remaining;
  final AppLocalizations l10n;
  final FocusNode focusNode;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final String accounting = l10n.filesDeleteSelectedStopped(
      result.succeededPaths.length,
      remaining,
    );
    final String? failure = switch (result.failure) {
      final FileErrorKind kind => fileErrorMessage(l10n, kind),
      null => null,
    };
    final String announcement = failure == null
        ? accounting
        : '$accounting $failure';
    return Focus(
      focusNode: focusNode,
      child: Semantics(
        container: true,
        liveRegion: true,
        label: announcement,
        child: ExcludeSemantics(
          child: Container(
            width: double.infinity,
            color: scheme.errorContainer,
            padding: const EdgeInsets.symmetric(
              horizontal: SignalSpacing.lg,
              vertical: SignalSpacing.sm,
            ),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 176),
              child: SingleChildScrollView(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Icon(
                      Icons.error_outline,
                      size: 20,
                      color: scheme.onErrorContainer,
                    ),
                    const SizedBox(width: SignalSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            accounting,
                            style: TextStyle(color: scheme.onErrorContainer),
                          ),
                          if (failure != null) ...<Widget>[
                            const SizedBox(height: SignalSpacing.xs),
                            Text(
                              failure,
                              style: TextStyle(color: scheme.onErrorContainer),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
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
    required this.selectionMode,
    required this.deleting,
    required this.selectedNames,
    required this.onToggleSelection,
    required this.onEnterSelection,
  });

  final FileExplorerState state;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final bool pythonBlocksBusy;
  final bool selectionMode;
  final bool deleting;
  final Set<String> selectedNames;
  final ValueChanged<String> onToggleSelection;
  final ValueChanged<String> onEnterSelection;

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
                  action: selectionMode
                      ? null
                      : FilledButton.icon(
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
            cwd: state.cwd,
            fsRoot: state.fsRoot,
            ctrl: ctrl,
            l10n: l10n,
            pythonBlocksBusy: pythonBlocksBusy,
            selectionMode: selectionMode,
            selected: selectedNames.contains(e.name),
            deleting: deleting,
            onToggleSelection: () => onToggleSelection(e.name),
            onEnterSelection: state.loading
                ? null
                : () => onEnterSelection(e.name),
          );
        },
      );
    }
    if (selectionMode) return body;
    return RefreshIndicator(onRefresh: ctrl.refresh, child: body);
  }
}

/// One listing row (design-system.md §7.10). Tapping the body descends (dir) or
/// opens (file); the trailing affordances rename/delete the entry.
class _EntryRow extends StatelessWidget {
  const _EntryRow({
    required this.entry,
    required this.cwd,
    required this.fsRoot,
    required this.ctrl,
    required this.l10n,
    required this.pythonBlocksBusy,
    required this.selectionMode,
    required this.selected,
    required this.deleting,
    required this.onToggleSelection,
    required this.onEnterSelection,
  });

  final RemoteEntry entry;
  final String cwd;
  final String fsRoot;
  final FileExplorerController ctrl;
  final AppLocalizations l10n;
  final bool pythonBlocksBusy;
  final bool selectionMode;
  final bool selected;
  final bool deleting;
  final VoidCallback onToggleSelection;
  final VoidCallback? onEnterSelection;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final bool isPy = !entry.isDir && entry.name.endsWith('.py');
    final bool editable = isEditableBoardEntry(
      fsRoot: fsRoot,
      cwd: cwd,
      name: entry.name,
    );
    final bool selectable = !entry.isDir && editable;
    return ListTile(
      key: ValueKey<String>('fileEntry_${entry.name}'),
      selected: selected,
      selectedTileColor: scheme.surfaceContainerHigh,
      leading: selectionMode && selectable
          ? Semantics(
              label: entry.name,
              child: Checkbox(
                key: ValueKey<String>('fileSelect_${entry.name}'),
                value: selected,
                onChanged: deleting ? null : (_) => onToggleSelection(),
              ),
            )
          : Icon(
              _iconFor(entry),
              color: isPy ? scheme.primary : scheme.onSurfaceVariant,
            ),
      title: Text(entry.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: entry.isDir ? null : Text(l10n.filesSizeBytes(entry.size)),
      onTap: selectionMode
          ? selectable && !deleting
                ? onToggleSelection
                : null
          : !editable
          ? null
          : () => entry.isDir
                ? ctrl.into(entry.name)
                : ctrl.openInEditor(entry.name),
      onLongPress: !selectionMode && selectable ? onEnterSelection : null,
      trailing: !editable
          ? SizedBox.square(
              dimension: 48,
              child: Tooltip(
                message: l10n.filesEntryProtected,
                child: Icon(Icons.lock_outline, color: scheme.onSurfaceVariant),
              ),
            )
          : selectionMode
          ? null
          : isPy
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

String _joinBoardPath(String cwd, String name) =>
    cwd == '/' ? '/$name' : '$cwd/$name';

String _leafOf(String path) {
  final int separator = path.lastIndexOf('/');
  return separator < 0 ? path : path.substring(separator + 1);
}

// --- dialogs -----------------------------------------------------------------

/// Reviews one immutable multi-delete intent. The folder and every selected
/// filename are visible in display order; the whole review scrolls on a narrow
/// pane/large text and the non-destructive choice receives initial focus.
Future<bool> _confirmDeleteSelected(
  BuildContext context,
  AppLocalizations l10n, {
  required String cwd,
  required List<String> orderedNames,
  required ValueChanged<BuildContext> onPresented,
}) async {
  final ColorScheme scheme = Theme.of(context).colorScheme;
  return await showDialog<bool>(
        context: context,
        builder: (BuildContext dialogContext) {
          onPresented(dialogContext);
          return AlertDialog(
            scrollable: true,
            title: Text(
              l10n.filesDeleteSelectedConfirmTitle(orderedNames.length),
            ),
            content: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(l10n.filesDeleteSelectedConfirmBody(cwd)),
                const SizedBox(height: SignalSpacing.lg),
                Text(
                  l10n.filesDeleteSelectedListLabel,
                  style: Theme.of(dialogContext).textTheme.titleSmall,
                ),
                const SizedBox(height: SignalSpacing.sm),
                DecoratedBox(
                  decoration: BoxDecoration(
                    color: scheme.surfaceContainerHigh,
                    borderRadius: const BorderRadius.all(
                      Radius.circular(SignalRadius.sm),
                    ),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: SignalSpacing.md,
                      vertical: SignalSpacing.sm,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        for (final String name in orderedNames)
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              vertical: SignalSpacing.xs,
                            ),
                            child: Text(name, style: SignalType.codeOn(scheme)),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            actions: <Widget>[
              TextButton(
                autofocus: true,
                style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                onPressed: () => Navigator.of(dialogContext).pop(false),
                child: Text(l10n.commonCancel),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  minimumSize: const Size(48, 48),
                  backgroundColor: scheme.error,
                  foregroundColor: scheme.onError,
                ),
                onPressed: () => Navigator.of(dialogContext).pop(true),
                child: Text(l10n.commonDelete),
              ),
            ],
          );
        },
      ) ??
      false;
}

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
