// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Adaptive, localized presentation for the connected GitHub example importer
/// frozen by ADR-0040.
///
/// The widget owns presentation state only. Public repository reads cross the
/// injected [GithubApi] seam, and every board read/write crosses
/// [GithubBoardImporter]. No fetched source is displayed, logged, opened, or
/// executed.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import 'github_board_importer.dart';
import 'github_import_providers.dart';
import 'github_models.dart';

/// Stable widget-test and accessibility anchors for the public workflow.
const String kOfficialExamplesRepositoryUrl =
    'https://github.com/PyBLE-dev/examples';
const Key kGithubRepositoryFieldKey = ValueKey<String>('githubRepositoryField');
const Key kGithubRefFieldKey = ValueKey<String>('githubRefField');
const Key kGithubBranchDropdownKey = ValueKey<String>('githubBranchDropdown');
const Key kGithubLoadBranchesButtonKey = ValueKey<String>(
  'githubLoadBranchesButton',
);
const Key kGithubManualRefToggleKey = ValueKey<String>('githubManualRefToggle');
const Key kGithubBrowseButtonKey = ValueKey<String>('githubBrowseButton');
const Key kGithubReviewButtonKey = ValueKey<String>('githubReviewButton');
const Key kGithubCommitButtonKey = ValueKey<String>('githubCommitButton');

/// Opens one import action, capturing the Files directory and connection
/// session for the whole presentation.
///
/// The same stateful surface is a scroll-controlled bottom sheet below 600 dp
/// and a dialog at 600 dp or wider.
Future<void> showGithubImportBrowser(
  BuildContext context,
  WidgetRef ref, {
  required String cwd,
  required Future<void> Function() refreshFiles,
}) async {
  final Connection connection = ref.read(connectionProvider);
  final GithubApi api = ref.read(githubApiProvider);
  final GithubBoardImporter importer = GithubBoardImporter(
    api: api,
    connection: connection,
    capturedSessionStamp: connectionSessionStampOf(connection),
    cwd: cwd,
    refreshFiles: refreshFiles,
  );
  final Widget content = _GithubImportView(
    api: api,
    importer: importer,
    cwd: cwd,
  );

  if (MediaQuery.sizeOf(context).width < 600) {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      isDismissible: false,
      enableDrag: false,
      useSafeArea: true,
      builder: (BuildContext sheetContext) =>
          FractionallySizedBox(heightFactor: 0.92, child: content),
    );
    return;
  }

  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext dialogContext) => Dialog(
      insetPadding: const EdgeInsets.all(16),
      clipBehavior: Clip.antiAlias,
      child: SizedBox(
        width: 720,
        height: MediaQuery.sizeOf(dialogContext).height * 0.96,
        child: content,
      ),
    ),
  );
}

enum _SurfaceStep { browse, review, result }

enum _RefMode { branch, manual }

enum _NetworkPhase {
  loadingBranches,
  resolving,
  loadingDirectory,
  checkingBoardTargets,
}

final class _DirectoryFrame {
  const _DirectoryFrame(this.directory);

  final GithubDirectory directory;
}

class _GithubImportView extends StatefulWidget {
  const _GithubImportView({
    required this.api,
    required this.importer,
    required this.cwd,
  });

  final GithubApi api;
  final GithubBoardImporter importer;
  final String cwd;

  @override
  State<_GithubImportView> createState() => _GithubImportViewState();
}

class _GithubImportViewState extends State<_GithubImportView> {
  final TextEditingController _repositoryController = TextEditingController(
    text: kOfficialExamplesRepositoryUrl,
  );
  final TextEditingController _branchController = TextEditingController();
  final TextEditingController _refController = TextEditingController();
  final FocusNode _repositoryFocus = FocusNode();
  final FocusNode _branchFocus = FocusNode();
  final FocusNode _refFocus = FocusNode();
  final FocusNode _failureFocus = FocusNode();
  final ScrollController _scrollController = ScrollController();
  Timer? _rateRetryTimer;

  _SurfaceStep _step = _SurfaceStep.browse;
  _RefMode _refMode = _RefMode.branch;
  GithubBranchCatalog? _branchCatalog;
  String? _selectedBranch;
  PinnedRepository? _repository;
  final List<_DirectoryFrame> _directories = <_DirectoryFrame>[];
  final Set<String> _selectedPaths = <String>{};
  GithubImportReview? _review;
  GithubImportResult? _result;
  GithubImportProgress? _progress;
  GithubFailure? _failure;
  GithubFailure? _rateRetryFailure;
  Future<void> Function()? _retry;
  bool _busy = false;
  bool _committing = false;
  bool _cancelled = false;
  bool _rateRetryReady = true;
  _NetworkPhase? _networkPhase;
  GithubCancellation? _networkCancellation;
  bool _updatingBranchController = false;
  int _epoch = 0;

  GithubDirectory? get _directory =>
      _directories.isEmpty ? null : _directories.last.directory;

  bool get _isLoadingBranches =>
      _busy && _networkPhase == _NetworkPhase.loadingBranches;

  bool get _canBrowseRef => switch (_refMode) {
    _RefMode.branch =>
      _branchCatalog != null &&
          _selectedBranch != null &&
          _branchController.text == _selectedBranch,
    _RefMode.manual => true,
  };

  @override
  void initState() {
    super.initState();
    _branchController.addListener(_onBranchTextChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(_loadBranches());
    });
  }

  @override
  void dispose() {
    _epoch += 1;
    _networkCancellation?.cancel();
    _rateRetryTimer?.cancel();
    widget.importer.cancel();
    _repositoryController.dispose();
    _branchController
      ..removeListener(_onBranchTextChanged)
      ..dispose();
    _refController.dispose();
    _repositoryFocus.dispose();
    _branchFocus.dispose();
    _refFocus.dispose();
    _failureFocus.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  bool _isCurrent(int epoch) => mounted && epoch == _epoch;

  GithubCancellation _beginNetworkOperation() {
    _networkCancellation?.cancel();
    final GithubCancellation cancellation = GithubCancellation();
    _networkCancellation = cancellation;
    return cancellation;
  }

  void _finishNetworkOperation(GithubCancellation cancellation) {
    if (identical(_networkCancellation, cancellation)) {
      _networkCancellation = null;
    }
  }

  void _clearSnapshotValues() {
    _repository = null;
    _directories.clear();
    _selectedPaths.clear();
    _review = null;
    _result = null;
    _progress = null;
    _step = _SurfaceStep.browse;
  }

  void _setBranchText(String value) {
    _updatingBranchController = true;
    _branchController.text = value;
    _updatingBranchController = false;
  }

  void _onBranchTextChanged() {
    if (_updatingBranchController || !mounted) return;
    final String? selected = _selectedBranch;
    if (selected == null || _branchController.text == selected) return;
    _epoch += 1;
    _networkCancellation?.cancel();
    setState(() {
      _selectedBranch = null;
      _clearSnapshotValues();
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  void _repositoryChanged() {
    _epoch += 1;
    _networkCancellation?.cancel();
    _setBranchText('');
    setState(() {
      _busy = false;
      _networkPhase = null;
      _branchCatalog = null;
      _selectedBranch = null;
      _clearSnapshotValues();
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  void _changeRefMode(bool manual) {
    final _RefMode next = manual ? _RefMode.manual : _RefMode.branch;
    if (_refMode == next) return;
    _epoch += 1;
    _networkCancellation?.cancel();
    setState(() {
      _refMode = next;
      if (_isLoadingBranches) {
        _busy = false;
        _networkPhase = null;
        _branchCatalog = null;
        _selectedBranch = null;
        _setBranchText('');
      }
      _clearSnapshotValues();
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  Future<void> _loadBranches() async {
    if (_busy || _rateRetryBlocked || _refMode != _RefMode.branch) return;

    late final RepositoryLocator locator;
    try {
      locator = RepositoryLocator.parse(_repositoryController.text);
    } on GithubFailure catch (failure) {
      _showFailure(failure, focus: _repositoryFocus);
      return;
    }

    final int epoch = ++_epoch;
    final GithubCancellation cancellation = _beginNetworkOperation();
    _setBranchText('');
    setState(() {
      _busy = true;
      _networkPhase = _NetworkPhase.loadingBranches;
      _branchCatalog = null;
      _selectedBranch = null;
      _clearSnapshotValues();
      _failure = null;
      _rateRetryFailure = null;
      _retry = null;
      _cancelled = false;
    });

    try {
      final GithubBranchCatalog catalog = await widget.api.listBranches(
        locator,
        cancellation: cancellation,
      );
      if (!_isCurrent(epoch) || catalog.locator != locator) return;
      final String? selected = catalog.branches.isEmpty
          ? null
          : catalog.defaultBranch;
      _setBranchText(selected ?? '');
      setState(() {
        _branchCatalog = catalog;
        _selectedBranch = selected;
        _busy = false;
        _networkPhase = null;
      });
    } on GithubFailure catch (failure) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        failure,
        retry: _loadBranches,
        focus: failure.kind == GithubFailureKind.invalidInput
            ? _repositoryFocus
            : null,
      );
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        const GithubFailure(GithubFailureKind.malformedResponse),
        retry: _loadBranches,
      );
    } finally {
      _finishNetworkOperation(cancellation);
    }
  }

  void _selectBranch(String? branch) {
    if (branch == null || branch == _selectedBranch) return;
    _epoch += 1;
    _networkCancellation?.cancel();
    _setBranchText(branch);
    setState(() {
      _selectedBranch = branch;
      _clearSnapshotValues();
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  Future<void> _browseRepository() async {
    if (_busy || _rateRetryBlocked) return;

    late final RepositoryLocator locator;
    try {
      locator = RepositoryLocator.parse(_repositoryController.text);
    } on GithubFailure catch (failure) {
      _showFailure(failure, focus: _repositoryFocus);
      return;
    }

    final String requestedRef;
    if (_refMode == _RefMode.branch) {
      final GithubBranchCatalog? catalog = _branchCatalog;
      final String? branch = _selectedBranch;
      if (catalog == null ||
          catalog.locator != locator ||
          branch == null ||
          _branchController.text != branch) {
        return;
      }
      requestedRef = branch;
    } else {
      requestedRef = _refController.text.trim();
    }

    final int epoch = ++_epoch;
    final GithubCancellation cancellation = _beginNetworkOperation();
    PinnedRepository? resolvedRepository;
    setState(() {
      _busy = true;
      _cancelled = false;
      _failure = null;
      _rateRetryFailure = null;
      _retry = null;
      _repository = null;
      _directories.clear();
      _selectedPaths.clear();
      _review = null;
      _result = null;
      _progress = null;
      _networkPhase = _NetworkPhase.resolving;
      _step = _SurfaceStep.browse;
    });

    try {
      final PinnedRepository repository = await widget.api.resolve(
        locator,
        ref: requestedRef,
        cancellation: cancellation,
      );
      resolvedRepository = repository;
      if (!_isCurrent(epoch)) return;
      setState(() {
        _repository = repository;
        _networkPhase = _NetworkPhase.loadingDirectory;
      });
      final GithubDirectory root = await widget.api.listDirectory(
        repository,
        treeSha: repository.rootTreeSha,
        remotePath: '',
        cancellation: cancellation,
      );
      if (!_isCurrent(epoch)) return;
      setState(() {
        _repository = repository;
        _directories
          ..clear()
          ..add(_DirectoryFrame(_sortedDirectory(root)));
        _busy = false;
        _networkPhase = null;
      });
    } on GithubFailure catch (failure) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        failure,
        retry: resolvedRepository == null
            ? _browseRepository
            : () => _retryRootDirectory(resolvedRepository!),
        focus:
            failure.kind == GithubFailureKind.invalidInput &&
                _refMode == _RefMode.manual
            ? _refFocus
            : null,
      );
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        const GithubFailure(GithubFailureKind.malformedResponse),
        retry: resolvedRepository == null
            ? _browseRepository
            : () => _retryRootDirectory(resolvedRepository!),
      );
    } finally {
      _finishNetworkOperation(cancellation);
    }
  }

  Future<void> _retryRootDirectory(PinnedRepository repository) async {
    if (_busy || _rateRetryBlocked || !identical(_repository, repository)) {
      return;
    }
    final int epoch = ++_epoch;
    final GithubCancellation cancellation = _beginNetworkOperation();
    setState(() {
      _busy = true;
      _cancelled = false;
      _failure = null;
      _rateRetryFailure = null;
      _retry = null;
      _networkPhase = _NetworkPhase.loadingDirectory;
    });
    try {
      final GithubDirectory root = await widget.api.listDirectory(
        repository,
        treeSha: repository.rootTreeSha,
        remotePath: '',
        cancellation: cancellation,
      );
      if (!_isCurrent(epoch) || !identical(_repository, repository)) return;
      setState(() {
        _directories
          ..clear()
          ..add(_DirectoryFrame(_sortedDirectory(root)));
        _selectedPaths.clear();
        _review = null;
        _busy = false;
        _networkPhase = null;
      });
    } on GithubFailure catch (failure) {
      if (!_isCurrent(epoch)) return;
      _showFailure(failure, retry: () => _retryRootDirectory(repository));
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        const GithubFailure(GithubFailureKind.malformedResponse),
        retry: () => _retryRootDirectory(repository),
      );
    } finally {
      _finishNetworkOperation(cancellation);
    }
  }

  GithubDirectory _sortedDirectory(GithubDirectory directory) {
    final List<GithubEntry> entries = List<GithubEntry>.of(directory.entries)
      ..sort((GithubEntry left, GithubEntry right) {
        final int leftGroup = left.kind == GithubEntryKind.directory ? 0 : 1;
        final int rightGroup = right.kind == GithubEntryKind.directory ? 0 : 1;
        final int group = leftGroup.compareTo(rightGroup);
        if (group != 0) return group;
        return left.name.compareTo(right.name);
      });
    return GithubDirectory(
      remotePath: directory.remotePath,
      treeSha: directory.treeSha,
      entries: entries,
    );
  }

  Future<void> _openDirectory(GithubEntry entry) async {
    final PinnedRepository? repository = _repository;
    if (_busy ||
        _rateRetryBlocked ||
        repository == null ||
        entry.kind != GithubEntryKind.directory) {
      return;
    }
    final int epoch = ++_epoch;
    final GithubCancellation cancellation = _beginNetworkOperation();
    setState(() {
      _busy = true;
      _cancelled = false;
      _failure = null;
      _rateRetryFailure = null;
      _retry = null;
      _networkPhase = _NetworkPhase.loadingDirectory;
    });
    try {
      final GithubDirectory directory = await widget.api.listDirectory(
        repository,
        treeSha: entry.objectSha,
        remotePath: entry.remotePath,
        cancellation: cancellation,
      );
      if (!_isCurrent(epoch)) return;
      setState(() {
        _directories.add(_DirectoryFrame(_sortedDirectory(directory)));
        _selectedPaths.clear();
        _review = null;
        _busy = false;
        _networkPhase = null;
      });
    } on GithubFailure catch (failure) {
      if (!_isCurrent(epoch)) return;
      _showFailure(failure, retry: () => _openDirectory(entry));
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        const GithubFailure(GithubFailureKind.malformedResponse),
        retry: () => _openDirectory(entry),
      );
    } finally {
      _finishNetworkOperation(cancellation);
    }
  }

  void _invalidateSnapshot() {
    if (_busy ||
        (_repository == null &&
            _directories.isEmpty &&
            _selectedPaths.isEmpty)) {
      return;
    }
    _epoch += 1;
    _networkCancellation?.cancel();
    setState(() {
      _repository = null;
      _directories.clear();
      _selectedPaths.clear();
      _review = null;
      _result = null;
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _progress = null;
      _cancelled = false;
      _networkPhase = null;
      _step = _SurfaceStep.browse;
    });
  }

  void _goUp() {
    if (_busy || _directories.length <= 1) return;
    _epoch += 1;
    setState(() {
      _directories.removeLast();
      _selectedPaths.clear();
      _review = null;
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  void _toggle(GithubEntry entry) {
    if (_busy || !entry.isSelectablePythonFile) return;
    setState(() {
      if (!_selectedPaths.add(entry.remotePath)) {
        _selectedPaths.remove(entry.remotePath);
      }
      _review = null;
      _failure = null;
      _retry = null;
      if (_rateRetryReady) _rateRetryFailure = null;
      _cancelled = false;
    });
  }

  List<GithubEntry> _selectedEntries() {
    final GithubDirectory? directory = _directory;
    if (directory == null) return const <GithubEntry>[];
    final List<GithubEntry> selected =
        <GithubEntry>[
          for (final GithubEntry entry in directory.entries)
            if (_selectedPaths.contains(entry.remotePath)) entry,
        ]..sort(
          (GithubEntry left, GithubEntry right) =>
              left.remotePath.compareTo(right.remotePath),
        );
    return selected;
  }

  Future<void> _reviewSelection() async {
    final PinnedRepository? repository = _repository;
    final List<GithubEntry> selected = _selectedEntries();
    if (_busy || repository == null || selected.isEmpty) return;
    final int epoch = ++_epoch;
    setState(() {
      _busy = true;
      _cancelled = false;
      _failure = null;
      _retry = null;
      _review = null;
      _progress = null;
      _networkPhase = _NetworkPhase.checkingBoardTargets;
    });
    try {
      final GithubImportReview review = await widget.importer.review(
        repository,
        selected,
      );
      if (!_isCurrent(epoch)) return;
      setState(() {
        _review = review;
        _step = _SurfaceStep.review;
        _busy = false;
        _networkPhase = null;
        if (review.blockingPaths.isNotEmpty) {
          _failure = GithubFailure(
            GithubFailureKind.blockingConflict,
            path: review.blockingPaths.first,
          );
        }
      });
      if (review.blockingPaths.isNotEmpty) _focusFailureAfterFrame();
    } on GithubFailure catch (failure) {
      if (!_isCurrent(epoch)) return;
      _showFailure(failure, retry: _reviewSelection);
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      _showFailure(
        const GithubFailure(GithubFailureKind.board),
        retry: _reviewSelection,
      );
    }
  }

  Future<void> _requestCommit() async {
    final GithubImportReview? review = _review;
    if (_busy || review == null || review.blockingPaths.isNotEmpty) return;

    bool overwriteConfirmed = false;
    if (review.conflictPaths.isNotEmpty) {
      overwriteConfirmed = await _confirmOverwrite(review.conflictPaths);
      if (!mounted || !overwriteConfirmed) return;
    }
    await _commit(review, overwriteConfirmed: overwriteConfirmed);
  }

  Future<bool> _confirmOverwrite(List<String> paths) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text(l10n.githubImportOverwriteTitle),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Text(l10n.githubImportOverwriteBody),
                  const SizedBox(height: 12),
                  for (final String path in paths)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Text(path),
                    ),
                ],
              ),
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(l10n.commonCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(l10n.githubImportOverwrite),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _commit(
    GithubImportReview review, {
    required bool overwriteConfirmed,
  }) async {
    if (_busy || _rateRetryBlocked) return;
    final int epoch = ++_epoch;
    setState(() {
      _busy = true;
      _committing = true;
      _cancelled = false;
      _failure = null;
      _rateRetryFailure = null;
      _retry = null;
      _progress = null;
      _result = null;
    });
    try {
      final GithubImportResult result = await widget.importer.commit(
        review,
        overwriteConfirmed: overwriteConfirmed,
        onPhase: (GithubImportPhase phase) {
          if (!_isCurrent(epoch)) return;
          setState(() {
            _progress = GithubImportProgress(
              phase: phase,
              completedFiles: _progress?.completedFiles ?? 0,
              totalFiles: review.targets.length,
              boardPath: _progress?.boardPath ?? review.cwd,
            );
          });
        },
        onProgress: (GithubImportProgress progress) {
          if (!_isCurrent(epoch)) return;
          setState(() => _progress = progress);
        },
      );
      if (!_isCurrent(epoch)) return;

      final GithubFailure? failure = result.failure;
      if (failure != null &&
          (failure.kind == GithubFailureKind.conflictChanged ||
              failure.kind == GithubFailureKind.blockingConflict ||
              failure.kind == GithubFailureKind.overwriteRequired)) {
        setState(() {
          _failure = failure;
          _retry = _reviewSelection;
          _step = _SurfaceStep.review;
          _busy = false;
          _committing = false;
          _progress = null;
        });
        _focusFailureAfterFrame();
        return;
      }

      if (failure != null &&
          result.succeeded.isEmpty &&
          _isRetryableNetworkFailure(failure.kind)) {
        _showFailure(
          failure,
          retry: () => _commit(review, overwriteConfirmed: overwriteConfirmed),
          step: _SurfaceStep.review,
        );
        return;
      }

      setState(() {
        _result = result;
        _failure = failure;
        _cancelled = result.outcome == GithubImportOutcome.cancelled;
        _step = _SurfaceStep.result;
        _busy = false;
        _committing = false;
        _progress = null;
      });
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      setState(() {
        _result = GithubImportResult(
          outcome: GithubImportOutcome.failed,
          succeeded: const <String>[],
          failedOrCancelled: null,
          unattempted: <String>[
            for (final ImportTarget target in review.targets) target.boardPath,
          ],
          failure: const GithubFailure(GithubFailureKind.board),
        );
        _failure = const GithubFailure(GithubFailureKind.board);
        _step = _SurfaceStep.result;
        _busy = false;
        _committing = false;
        _progress = null;
      });
    }
  }

  bool _isRetryableNetworkFailure(GithubFailureKind kind) => switch (kind) {
    GithubFailureKind.offline ||
    GithubFailureKind.notFound ||
    GithubFailureKind.privateOrForbidden ||
    GithubFailureKind.rateLimited ||
    GithubFailureKind.server ||
    GithubFailureKind.malformedResponse => true,
    _ => false,
  };

  void _cancelOperation() {
    _networkCancellation?.cancel();
    widget.importer.cancel();
    if (_committing) {
      setState(() => _cancelled = true);
      return;
    }
    _epoch += 1;
    setState(() {
      _busy = false;
      _cancelled = true;
      _failure = null;
      _retry = null;
      _progress = null;
      _networkPhase = null;
    });
  }

  void _focusFailureAfterFrame() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _failureFocus.requestFocus();
    });
  }

  void _showFailure(
    GithubFailure failure, {
    Future<void> Function()? retry,
    FocusNode? focus,
    _SurfaceStep? step,
  }) {
    if (!mounted) return;
    final Duration? retryDelay = _rateRetryDelay(failure);
    final bool blockRetry = retryDelay != null && retryDelay > Duration.zero;
    if (blockRetry) {
      _rateRetryTimer?.cancel();
      _rateRetryTimer = null;
    }
    setState(() {
      _failure = failure;
      if (blockRetry) _rateRetryFailure = failure;
      _retry = retry;
      if (step != null) _step = step;
      _busy = false;
      _committing = false;
      _progress = null;
      _networkPhase = null;
      _cancelled = failure.kind == GithubFailureKind.cancelled;
      if (blockRetry) _rateRetryReady = false;
    });
    if (blockRetry) {
      _rateRetryTimer = Timer(retryDelay, () {
        if (!mounted) return;
        setState(() {
          _rateRetryReady = true;
          _rateRetryTimer = null;
          if (!identical(_failure, _rateRetryFailure)) {
            _rateRetryFailure = null;
          }
        });
      });
    }
    final FocusNode target = focus ?? _failureFocus;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) target.requestFocus();
    });
  }

  void _close() {
    _epoch += 1;
    _networkCancellation?.cancel();
    _rateRetryTimer?.cancel();
    widget.importer.cancel();
    Navigator.of(context).maybePop();
  }

  bool get _rateRetryBlocked => !_rateRetryReady;

  Duration? _rateRetryDelay(GithubFailure failure) {
    if (failure.kind != GithubFailureKind.rateLimited) return null;
    final Duration? retryAfter = failure.retryAfter;
    if (retryAfter != null) return retryAfter;
    final DateTime? reset = failure.rateLimitReset;
    if (reset == null) return null;
    final Duration delay = reset.toUtc().difference(DateTime.now().toUtc());
    return delay.isNegative ? Duration.zero : delay;
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final double keyboardInset = MediaQuery.viewInsetsOf(context).bottom;
    return PopScope(
      canPop: !_committing,
      child: AnimatedPadding(
        duration: const Duration(milliseconds: 160),
        curve: Curves.easeOut,
        padding: EdgeInsets.only(bottom: keyboardInset),
        child: Material(
          color: Theme.of(context).colorScheme.surface,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              _Header(l10n: l10n, onClose: _committing ? null : _close),
              const Divider(height: 1),
              Expanded(
                child: Scrollbar(
                  controller: _scrollController,
                  child: SingleChildScrollView(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(20),
                    child: _buildBody(l10n),
                  ),
                ),
              ),
              const Divider(height: 1),
              _buildActions(l10n),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBody(AppLocalizations l10n) {
    return switch (_step) {
      _SurfaceStep.browse => _buildBrowse(l10n),
      _SurfaceStep.review => _buildReview(l10n),
      _SurfaceStep.result => _buildResult(l10n),
    };
  }

  Widget _buildRefControls(AppLocalizations l10n) {
    final GithubBranchCatalog? catalog = _branchCatalog;
    final bool refControlEnabled = !_busy && !_rateRetryBlocked;
    final Widget selector;
    if (_refMode == _RefMode.manual) {
      selector = TextField(
        key: kGithubRefFieldKey,
        controller: _refController,
        focusNode: _refFocus,
        enabled: !_busy,
        textInputAction: TextInputAction.done,
        decoration: InputDecoration(
          labelText: l10n.githubImportRefLabel,
          hintText: l10n.githubImportRefHint,
          border: const OutlineInputBorder(),
        ),
        onChanged: (_) => _invalidateSnapshot(),
        onSubmitted: (_) => unawaited(_browseRepository()),
      );
    } else if (catalog == null) {
      selector = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          OutlinedButton.icon(
            key: kGithubLoadBranchesButtonKey,
            onPressed: refControlEnabled ? _loadBranches : null,
            icon: const Icon(Icons.account_tree_outlined),
            label: Text(l10n.githubImportLoadBranches),
          ),
          if (!_isLoadingBranches) ...<Widget>[
            const SizedBox(height: 6),
            Text(l10n.githubImportBranchesNotLoaded),
          ],
        ],
      );
    } else if (catalog.branches.isEmpty) {
      selector = Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(child: Text(l10n.githubImportNoBranches)),
          IconButton.filledTonal(
            key: kGithubLoadBranchesButtonKey,
            tooltip: l10n.githubImportRefreshBranches,
            onPressed: refControlEnabled ? _loadBranches : null,
            icon: const Icon(Icons.refresh),
          ),
        ],
      );
    } else {
      selector = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: DropdownMenu<String>(
                  key: kGithubBranchDropdownKey,
                  controller: _branchController,
                  focusNode: _branchFocus,
                  enabled: refControlEnabled,
                  enableFilter: true,
                  enableSearch: true,
                  requestFocusOnTap: true,
                  expandedInsets: EdgeInsets.zero,
                  menuHeight: 320,
                  label: Text(l10n.githubImportBranchLabel),
                  dropdownMenuEntries: <DropdownMenuEntry<String>>[
                    for (final String branch in catalog.branches)
                      DropdownMenuEntry<String>(
                        value: branch,
                        label: branch,
                        labelWidget: branch == catalog.defaultBranch
                            ? Text(l10n.githubImportDefaultBranch(branch))
                            : null,
                      ),
                  ],
                  onSelected: _selectBranch,
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filledTonal(
                key: kGithubLoadBranchesButtonKey,
                tooltip: l10n.githubImportRefreshBranches,
                onPressed: refControlEnabled ? _loadBranches : null,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
        ],
      );
    }

    return selector;
  }

  Widget _buildBrowse(AppLocalizations l10n) {
    final PinnedRepository? repository = _repository;
    final GithubDirectory? directory = _directory;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        TextField(
          key: kGithubRepositoryFieldKey,
          controller: _repositoryController,
          focusNode: _repositoryFocus,
          enabled: !_busy || _isLoadingBranches,
          keyboardType: TextInputType.url,
          textInputAction: TextInputAction.next,
          decoration: InputDecoration(
            labelText: l10n.githubImportRepositoryLabel,
            hintText: l10n.githubImportRepositoryHint,
            errorText: _failure?.kind == GithubFailureKind.invalidInput
                ? _failureMessage(l10n, _failure!)
                : null,
            border: const OutlineInputBorder(),
          ),
          onChanged: (_) => _repositoryChanged(),
          onSubmitted: (_) {
            if (_refMode == _RefMode.manual) {
              _refFocus.requestFocus();
            } else if (_branchCatalog == null) {
              unawaited(_loadBranches());
            } else {
              _branchFocus.requestFocus();
            }
          },
        ),
        const SizedBox(height: 12),
        _buildRefControls(l10n),
        const SizedBox(height: 12),
        Wrap(
          alignment: WrapAlignment.end,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            TextButton.icon(
              key: kGithubManualRefToggleKey,
              onPressed: !_busy || _isLoadingBranches
                  ? () => _changeRefMode(_refMode != _RefMode.manual)
                  : null,
              icon: Icon(
                _refMode == _RefMode.manual
                    ? Icons.account_tree_outlined
                    : Icons.edit_outlined,
              ),
              label: Text(
                _refMode == _RefMode.manual
                    ? l10n.githubImportChooseBranch
                    : l10n.githubImportManualRef,
              ),
            ),
            FilledButton.icon(
              key: kGithubBrowseButtonKey,
              onPressed: _busy || _rateRetryBlocked || !_canBrowseRef
                  ? null
                  : _browseRepository,
              icon: const Icon(Icons.travel_explore_outlined),
              label: Text(l10n.githubImportBrowse),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Text(l10n.githubImportDestination(widget.cwd)),
        if (repository != null) ...<Widget>[
          const SizedBox(height: 8),
          SelectableText(l10n.githubImportPinnedCommit(repository.commitSha)),
        ],
        ..._buildFailureBanners(l10n),
        if (_cancelled) ...<Widget>[
          const SizedBox(height: 12),
          Text(l10n.githubImportCancelled),
        ],
        if (_busy) ...<Widget>[
          const SizedBox(height: 16),
          Text(_networkPhaseMessage(l10n)),
          const SizedBox(height: 6),
          LinearProgressIndicator(semanticsLabel: _networkPhaseMessage(l10n)),
        ],
        if (directory != null) ...<Widget>[
          const SizedBox(height: 16),
          Row(
            children: <Widget>[
              if (_directories.length > 1)
                IconButton(
                  tooltip: l10n.githubImportGoUp,
                  onPressed: _busy ? null : _goUp,
                  icon: const Icon(Icons.arrow_upward),
                ),
              Expanded(
                child: Text(
                  directory.remotePath.isEmpty
                      ? '/'
                      : '/${directory.remotePath}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          if (directory.entries.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Text(l10n.githubImportEmptyFolder),
            )
          else
            for (final GithubEntry entry in directory.entries)
              _GithubEntryRow(
                entry: entry,
                selected: _selectedPaths.contains(entry.remotePath),
                enabled: !_busy && !_rateRetryBlocked,
                l10n: l10n,
                onOpen: () => _openDirectory(entry),
                onToggle: () => _toggle(entry),
              ),
          const SizedBox(height: 12),
          Text(l10n.githubImportSelectedCount(_selectedPaths.length)),
        ],
      ],
    );
  }

  Widget _buildReview(AppLocalizations l10n) {
    final GithubImportReview? review = _review;
    if (review == null) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          l10n.githubImportReviewTitle,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        Text(l10n.githubImportDestination(review.cwd)),
        const SizedBox(height: 16),
        for (final ImportTarget target in review.targets)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Text(
                  l10n.githubImportMapping(
                    target.source.remotePath,
                    target.boardPath,
                  ),
                ),
                if (target.overwrites)
                  Text(
                    l10n.githubImportWillOverwrite,
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
              ],
            ),
          ),
        ..._buildFailureBanners(l10n),
        if (_cancelled) ...<Widget>[
          const SizedBox(height: 12),
          Text(l10n.githubImportCancelling),
        ],
        if (_busy && _progress != null) ...<Widget>[
          const SizedBox(height: 16),
          _ImportProgressView(progress: _progress!, l10n: l10n),
        ],
        const SizedBox(height: 16),
        Text(l10n.githubImportNoAutomaticRun),
      ],
    );
  }

  Widget _buildResult(AppLocalizations l10n) {
    final GithubImportResult? result = _result;
    if (result == null) return const SizedBox.shrink();
    final String summary = switch (result.outcome) {
      GithubImportOutcome.complete => l10n.githubImportComplete(
        result.succeeded.length,
      ),
      GithubImportOutcome.partial => l10n.githubImportPartial,
      GithubImportOutcome.cancelled => l10n.githubImportCancelled,
      GithubImportOutcome.failed =>
        result.failure == null
            ? l10n.githubImportPartial
            : _failureMessage(l10n, result.failure!),
    };
    return Semantics(
      key: const ValueKey<String>('githubImportResult'),
      liveRegion: true,
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(summary, style: Theme.of(context).textTheme.titleLarge),
          if (result.outcome == GithubImportOutcome.partial &&
              result.failure != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(_failureMessage(l10n, result.failure!)),
          ],
          if (result.succeeded.isNotEmpty) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              l10n.githubImportSucceededHeading,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            for (final String path in result.succeeded) Text(path),
          ],
          if (result.failedOrCancelled case final String path) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              l10n.githubImportFailedHeading,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            Text(path),
          ],
          if (result.unattempted.isNotEmpty) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              l10n.githubImportUnattemptedHeading,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            for (final String path in result.unattempted) Text(path),
          ],
          const SizedBox(height: 16),
          Text(l10n.githubImportNoAutomaticRun),
        ],
      ),
    );
  }

  List<Widget> _buildFailureBanners(AppLocalizations l10n) {
    final GithubFailure? cooldownFailure = _rateRetryBlocked
        ? _rateRetryFailure
        : null;
    final GithubFailure? primary = _failure ?? cooldownFailure;
    if (primary == null) return const <Widget>[];
    final bool showSeparateCooldown =
        cooldownFailure != null && !identical(primary, cooldownFailure);
    return <Widget>[
      const SizedBox(height: 12),
      Focus(
        key: const ValueKey<String>('githubImportFailure'),
        focusNode: _failureFocus,
        child: _FailureBanner(
          message: _failureMessage(
            l10n,
            primary,
            rateLimitReady: _rateRetryReady,
          ),
          retry: _rateRetryBlocked ? null : _retry,
          l10n: l10n,
        ),
      ),
      if (showSeparateCooldown) ...<Widget>[
        const SizedBox(height: 8),
        KeyedSubtree(
          key: const ValueKey<String>('githubImportRateLimitFailure'),
          child: _FailureBanner(
            message: _failureMessage(l10n, cooldownFailure),
            retry: null,
            l10n: l10n,
          ),
        ),
      ],
    ];
  }

  String _networkPhaseMessage(AppLocalizations l10n) => switch (_networkPhase) {
    _NetworkPhase.loadingBranches => l10n.githubImportLoadingBranches,
    _NetworkPhase.resolving => l10n.githubImportResolving,
    _NetworkPhase.loadingDirectory => l10n.githubImportLoadingFolder,
    _NetworkPhase.checkingBoardTargets => l10n.githubImportCheckingBoardTargets,
    null => l10n.githubImportBrowse,
  };

  Widget _buildActions(AppLocalizations l10n) {
    final List<Widget> actions = switch (_step) {
      _SurfaceStep.browse => <Widget>[
        if (_busy)
          TextButton(
            onPressed: _cancelOperation,
            child: Text(l10n.commonCancel),
          ),
        FilledButton(
          key: kGithubReviewButtonKey,
          onPressed: !_busy && _selectedPaths.isNotEmpty
              ? _reviewSelection
              : null,
          child: Text(l10n.githubImportReview),
        ),
      ],
      _SurfaceStep.review => <Widget>[
        if (_busy)
          TextButton(
            onPressed: _cancelOperation,
            child: Text(l10n.commonCancel),
          )
        else
          TextButton(
            onPressed: () => setState(() {
              _step = _SurfaceStep.browse;
              _failure = null;
              _retry = null;
              if (_rateRetryReady) _rateRetryFailure = null;
            }),
            child: Text(l10n.commonCancel),
          ),
        FilledButton(
          key: kGithubCommitButtonKey,
          onPressed:
              !_busy &&
                  !_rateRetryBlocked &&
                  (_review?.blockingPaths.isEmpty ?? false) &&
                  _failure?.kind != GithubFailureKind.conflictChanged
              ? _requestCommit
              : null,
          child: Text(l10n.githubImportDownload),
        ),
      ],
      _SurfaceStep.result => <Widget>[
        FilledButton(onPressed: _close, child: Text(l10n.githubImportClose)),
      ],
    };
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
        child: Align(
          alignment: AlignmentDirectional.centerEnd,
          child: Wrap(spacing: 8, runSpacing: 8, children: actions),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.l10n, required this.onClose});

  final AppLocalizations l10n;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(20, 12, 8, 8),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              l10n.githubImportTitle,
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          IconButton(
            tooltip: l10n.githubImportClose,
            onPressed: onClose,
            icon: const Icon(Icons.close),
          ),
        ],
      ),
    );
  }
}

class _GithubEntryRow extends StatelessWidget {
  const _GithubEntryRow({
    required this.entry,
    required this.selected,
    required this.enabled,
    required this.l10n,
    required this.onOpen,
    required this.onToggle,
  });

  final GithubEntry entry;
  final bool selected;
  final bool enabled;
  final AppLocalizations l10n;
  final VoidCallback onOpen;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final Key rowKey = ValueKey<String>('githubEntry_${entry.remotePath}');
    if (entry.kind == GithubEntryKind.directory) {
      return Semantics(
        button: true,
        label: entry.remotePath,
        child: ListTile(
          key: rowKey,
          minTileHeight: 48,
          leading: const Icon(Icons.folder_outlined),
          title: Text(entry.name),
          trailing: const Icon(Icons.chevron_right),
          enabled: enabled,
          onTap: enabled ? onOpen : null,
        ),
      );
    }
    if (entry.isSelectablePythonFile) {
      return Semantics(
        label: l10n.githubImportSelectFile(entry.name),
        child: CheckboxListTile(
          key: ValueKey<String>('githubSelect_${entry.remotePath}'),
          secondary: const Icon(Icons.description_outlined),
          title: Text(entry.name, key: rowKey),
          value: selected,
          enabled: enabled,
          controlAffinity: ListTileControlAffinity.leading,
          onChanged: enabled ? (_) => onToggle() : null,
        ),
      );
    }
    return Semantics(
      label: l10n.githubImportIneligibleFile(entry.name),
      child: ListTile(
        key: rowKey,
        minTileHeight: 48,
        enabled: false,
        leading: const Icon(Icons.block_outlined),
        title: Text(entry.name),
        subtitle: Text(l10n.githubImportIneligibleFile(entry.name)),
      ),
    );
  }
}

class _FailureBanner extends StatelessWidget {
  const _FailureBanner({
    required this.message,
    required this.retry,
    required this.l10n,
  });

  final String message;
  final Future<void> Function()? retry;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: Container(
        color: colors.errorContainer,
        padding: const EdgeInsets.all(12),
        child: Row(
          children: <Widget>[
            Icon(Icons.error_outline, color: colors.onErrorContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: TextStyle(color: colors.onErrorContainer),
              ),
            ),
            if (retry != null)
              TextButton(
                onPressed: () => unawaited(retry!()),
                child: Text(l10n.githubImportRetry),
              ),
          ],
        ),
      ),
    );
  }
}

class _ImportProgressView extends StatelessWidget {
  const _ImportProgressView({required this.progress, required this.l10n});

  final GithubImportProgress progress;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final TransferProgress? transfer = progress.transfer;
    final double? value = transfer != null && transfer.total > 0
        ? transfer.sent / transfer.total
        : progress.totalFiles > 0
        ? progress.completedFiles / progress.totalFiles
        : null;
    final String phaseLabel = switch (progress.phase) {
      GithubImportPhase.fetching => l10n.githubImportFetching,
      GithubImportPhase.recheckingBoard => l10n.githubImportRecheckingBoard,
      GithubImportPhase.uploading => l10n.githubImportUploading,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(phaseLabel),
        const SizedBox(height: 4),
        Text(progress.boardPath),
        const SizedBox(height: 6),
        LinearProgressIndicator(
          value: value?.clamp(0, 1),
          semanticsLabel: phaseLabel,
        ),
      ],
    );
  }
}

String _failureMessage(
  AppLocalizations l10n,
  GithubFailure failure, {
  bool rateLimitReady = false,
}) {
  return switch (failure.kind) {
    GithubFailureKind.invalidInput => l10n.githubImportErrorInvalidInput,
    GithubFailureKind.offline => l10n.githubImportErrorOffline,
    GithubFailureKind.notFound => l10n.githubImportErrorNotFound,
    GithubFailureKind.privateOrForbidden => l10n.githubImportErrorForbidden,
    GithubFailureKind.rateLimited =>
      rateLimitReady &&
              (failure.retryAfter != null || failure.rateLimitReset != null)
          ? l10n.githubImportErrorRateLimitedReady
          : _rateLimitMessage(l10n, failure),
    GithubFailureKind.server => l10n.githubImportErrorServer,
    GithubFailureKind.malformedResponse => l10n.githubImportErrorMalformed,
    GithubFailureKind.tooManyBranches => l10n.githubImportErrorTooManyBranches,
    GithubFailureKind.invalidTarget ||
    GithubFailureKind.duplicateTarget ||
    GithubFailureKind.pathTooLong ||
    GithubFailureKind.invalidUtf8 ||
    GithubFailureKind.nulByte =>
      failure.path == null
          ? l10n.githubImportErrorUnsafe
          : l10n.githubImportErrorUnsafePath(failure.path!),
    GithubFailureKind.fileTooLarge || GithubFailureKind.batchTooLarge =>
      failure.path == null
          ? l10n.githubImportErrorTooLarge
          : l10n.githubImportErrorTooLargePath(failure.path!),
    GithubFailureKind.staleSession => l10n.githubImportErrorStaleSession,
    GithubFailureKind.board => l10n.githubImportErrorBoard,
    GithubFailureKind.incompleteBoardListing =>
      l10n.githubImportErrorIncompleteBoardListing,
    GithubFailureKind.blockingConflict =>
      failure.path == null
          ? l10n.githubImportErrorBlockingConflict
          : l10n.githubImportErrorBlockingConflictPath(failure.path!),
    GithubFailureKind.overwriteRequired =>
      l10n.githubImportErrorOverwriteRequired,
    GithubFailureKind.conflictChanged => l10n.githubImportErrorConflictChanged,
    GithubFailureKind.cancelled => l10n.githubImportCancelled,
  };
}

String _rateLimitMessage(AppLocalizations l10n, GithubFailure failure) {
  final Duration? retryAfter = failure.retryAfter;
  if (retryAfter != null) {
    return l10n.githubImportErrorRateLimitedRetry(retryAfter.inSeconds);
  }
  final DateTime? reset = failure.rateLimitReset;
  if (reset != null) {
    return l10n.githubImportErrorRateLimitedReset(
      reset.toUtc().toIso8601String(),
    );
  }
  final int? remaining = failure.rateLimitRemaining;
  if (remaining != null) {
    return l10n.githubImportErrorRateLimitedRemaining(remaining);
  }
  return l10n.githubImportErrorRateLimited;
}
