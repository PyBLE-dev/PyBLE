// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:typed_data';

import '../pble/pble.dart';
import 'github_models.dart';

const int _maxGithubImportFileBytes = 256 * 1024;
const int _maxGithubImportBatchBytes = 1024 * 1024;
const int _maxBoardPathBytes = 128;

/// One reviewed mapping from an immutable Git blob to a board file.
class ImportTarget {
  const ImportTarget({
    required this.source,
    required this.boardPath,
    required this.overwrites,
  });

  final GithubEntry source;
  final String boardPath;
  final bool overwrites;
}

/// Immutable board preflight presented before any Git blob is downloaded.
class GithubImportReview {
  GithubImportReview._({
    required this.repository,
    required this.cwd,
    required List<ImportTarget> targets,
    required List<String> conflictPaths,
    required List<String> blockingPaths,
    required Map<String, _BoardConflictKind> conflictSnapshot,
  }) : targets = List<ImportTarget>.unmodifiable(targets),
       conflictPaths = List<String>.unmodifiable(conflictPaths),
       blockingPaths = List<String>.unmodifiable(blockingPaths),
       _conflictSnapshot = Map<String, _BoardConflictKind>.unmodifiable(
         conflictSnapshot,
       );

  final PinnedRepository repository;
  final String cwd;
  final List<ImportTarget> targets;
  final List<String> conflictPaths;
  final List<String> blockingPaths;

  final Map<String, _BoardConflictKind> _conflictSnapshot;
}

/// Truthful terminal state of one non-atomic board import attempt.
enum GithubImportOutcome { complete, failed, partial, cancelled }

/// Result paths are exact board paths in the stable review order.
class GithubImportResult {
  GithubImportResult({
    required this.outcome,
    required List<String> succeeded,
    required this.failedOrCancelled,
    required List<String> unattempted,
    this.failure,
  }) : succeeded = List<String>.unmodifiable(succeeded),
       unattempted = List<String>.unmodifiable(unattempted);

  final GithubImportOutcome outcome;
  final List<String> succeeded;
  final String? failedOrCancelled;
  final List<String> unattempted;
  final GithubFailure? failure;
}

/// Coarse phases useful to an adaptive view without leaking HTTP/PBLE detail.
enum GithubImportPhase { fetching, recheckingBoard, uploading }

/// Monotonic import progress. [transfer] is present only during one board PUT.
class GithubImportProgress {
  const GithubImportProgress({
    required this.phase,
    required this.completedFiles,
    required this.totalFiles,
    required this.boardPath,
    this.transfer,
  });

  final GithubImportPhase phase;
  final int completedFiles;
  final int totalFiles;
  final String boardPath;
  final TransferProgress? transfer;
}

typedef GithubImportPhaseCallback = void Function(GithubImportPhase phase);
typedef GithubImportProgressCallback =
    void Function(GithubImportProgress progress);

enum _BoardConflictKind { absent, regularFile, blocking }

final class _ImportCandidate {
  const _ImportCandidate(this.target, this.bytes);

  final ImportTarget target;
  final Uint8List bytes;
}

/// Applies the connected subset frozen by ADR-0040.
///
/// This class knows no widget, BLE transport, editor, or persistence type. It
/// reads public immutable blobs through [GithubApi] and mutates the board only
/// through [Connection.listDir] and sequential [Connection.putFile] calls.
final class GithubBoardImporter {
  factory GithubBoardImporter({
    required GithubApi api,
    required Connection connection,
    required Object capturedSessionStamp,
    required String fsRoot,
    required String cwd,
    required Future<void> Function() refreshFiles,
  }) => GithubBoardImporter._(
    api,
    connection,
    capturedSessionStamp,
    fsRoot,
    cwd,
    refreshFiles,
  );

  GithubBoardImporter._(
    this._api,
    this._connection,
    this._capturedSessionStamp,
    this._fsRoot,
    this._cwd,
    this._refreshFiles,
  );

  final GithubApi _api;
  final Connection _connection;
  final Object _capturedSessionStamp;
  final String _fsRoot;
  final String _cwd;
  final Future<void> Function() _refreshFiles;

  int _generation = 0;
  bool _committing = false;
  GithubCancellation? _activeCancellation;

  /// Invalidates the active fetch/commit generation.
  ///
  /// A board PUT cannot be interrupted through the neutral Connection seam;
  /// cancellation therefore takes effect after that in-flight PUT settles.
  void cancel() {
    _generation += 1;
    _activeCancellation?.cancel();
  }

  /// Derives exact flat targets and snapshots their current board conflicts.
  Future<GithubImportReview> review(
    PinnedRepository repository,
    List<GithubEntry> selected,
  ) async {
    _requireUsableSession();
    final String fsRoot = _canonicalCwd(_fsRoot);
    final String cwd = _canonicalCwd(_cwd);
    if (!_isAtOrBelowRoot(cwd, fsRoot)) {
      throw GithubFailure(GithubFailureKind.invalidTarget, path: cwd);
    }
    final List<ImportTarget> targets = _deriveTargets(cwd, fsRoot, selected);
    final Map<String, _BoardConflictKind> conflicts = await _listConflicts(
      cwd,
      targets,
    );

    final List<ImportTarget> annotated = <ImportTarget>[
      for (final ImportTarget target in targets)
        ImportTarget(
          source: target.source,
          boardPath: target.boardPath,
          overwrites:
              conflicts[target.boardPath] == _BoardConflictKind.regularFile,
        ),
    ];
    final List<String> overwritePaths = <String>[
      for (final ImportTarget target in annotated)
        if (target.overwrites) target.boardPath,
    ];
    final List<String> blockingPaths = <String>[
      for (final ImportTarget target in annotated)
        if (conflicts[target.boardPath] == _BoardConflictKind.blocking)
          target.boardPath,
    ];

    return GithubImportReview._(
      repository: repository,
      cwd: cwd,
      targets: annotated,
      conflictPaths: overwritePaths,
      blockingPaths: blockingPaths,
      conflictSnapshot: conflicts,
    );
  }

  /// Fetches and validates the whole candidate before committing sequentially.
  Future<GithubImportResult> commit(
    GithubImportReview review, {
    required bool overwriteConfirmed,
    GithubImportPhaseCallback? onPhase,
    GithubImportProgressCallback? onProgress,
  }) async {
    final List<String> allPaths = _paths(review.targets);
    if (_committing) {
      return _failed(allPaths, GithubFailure(GithubFailureKind.board));
    }

    _committing = true;
    final int generation = ++_generation;
    final GithubCancellation cancellation = GithubCancellation();
    _activeCancellation = cancellation;
    try {
      final GithubFailure? initialFailure = _usableSessionFailure();
      if (initialFailure != null) return _failed(allPaths, initialFailure);
      if (review.blockingPaths.isNotEmpty) {
        return _failed(
          allPaths,
          GithubFailure(
            GithubFailureKind.blockingConflict,
            path: review.blockingPaths.first,
          ),
        );
      }
      if (review.conflictPaths.isNotEmpty && !overwriteConfirmed) {
        return _failed(
          allPaths,
          GithubFailure(
            GithubFailureKind.overwriteRequired,
            path: review.conflictPaths.first,
          ),
        );
      }

      onPhase?.call(GithubImportPhase.fetching);
      final List<_ImportCandidate> candidates = <_ImportCandidate>[];
      int totalBytes = 0;
      for (int index = 0; index < review.targets.length; index += 1) {
        if (_isCancelled(generation)) return _cancelled(allPaths);
        final ImportTarget target = review.targets[index];
        if (target.source.declaredSize > _maxGithubImportFileBytes) {
          return _failed(
            allPaths,
            GithubFailure(
              GithubFailureKind.fileTooLarge,
              path: target.source.remotePath,
            ),
          );
        }
        onProgress?.call(
          GithubImportProgress(
            phase: GithubImportPhase.fetching,
            completedFiles: index,
            totalFiles: review.targets.length,
            boardPath: target.boardPath,
          ),
        );

        late final Uint8List fetched;
        try {
          fetched = await _api.fetchFile(
            review.repository,
            target.source,
            cancellation: cancellation,
          );
        } on GithubFailure catch (failure) {
          if (_isCancelled(generation)) return _cancelled(allPaths);
          return _failed(allPaths, failure);
        } catch (_) {
          if (_isCancelled(generation)) return _cancelled(allPaths);
          return _failed(
            allPaths,
            GithubFailure(
              GithubFailureKind.malformedResponse,
              path: target.source.remotePath,
            ),
          );
        }
        if (_isCancelled(generation)) return _cancelled(allPaths);

        final Uint8List bytes = Uint8List.fromList(fetched);
        final GithubFailure? contentFailure = _validateContent(target, bytes);
        if (contentFailure != null) {
          return _failed(allPaths, contentFailure);
        }
        totalBytes += bytes.length;
        if (totalBytes > _maxGithubImportBatchBytes) {
          return _failed(
            allPaths,
            GithubFailure(
              GithubFailureKind.batchTooLarge,
              path: target.source.remotePath,
            ),
          );
        }
        candidates.add(_ImportCandidate(target, bytes));
      }

      if (_isCancelled(generation)) return _cancelled(allPaths);
      final GithubFailure? beforeRecheck = _usableSessionFailure();
      if (beforeRecheck != null) return _failed(allPaths, beforeRecheck);
      onPhase?.call(GithubImportPhase.recheckingBoard);

      late final Map<String, _BoardConflictKind> currentConflicts;
      try {
        currentConflicts = await _listConflicts(review.cwd, review.targets);
      } on GithubFailure catch (failure) {
        return _failed(allPaths, failure);
      }
      if (_isCancelled(generation)) return _cancelled(allPaths);
      final GithubFailure? afterRecheck = _usableSessionFailure();
      if (afterRecheck != null) return _failed(allPaths, afterRecheck);
      if (!_sameConflicts(review._conflictSnapshot, currentConflicts)) {
        return _failed(
          allPaths,
          GithubFailure(GithubFailureKind.conflictChanged),
        );
      }

      onPhase?.call(GithubImportPhase.uploading);
      return await _upload(
        candidates,
        generation: generation,
        onProgress: onProgress,
      );
    } finally {
      if (identical(_activeCancellation, cancellation)) {
        _activeCancellation = null;
      }
      _committing = false;
    }
  }

  Future<GithubImportResult> _upload(
    List<_ImportCandidate> candidates, {
    required int generation,
    GithubImportProgressCallback? onProgress,
  }) async {
    final List<String> allPaths = <String>[
      for (final _ImportCandidate candidate in candidates)
        candidate.target.boardPath,
    ];
    final List<String> succeeded = <String>[];
    bool putBegan = false;

    try {
      for (int index = 0; index < candidates.length; index += 1) {
        if (_isCancelled(generation)) {
          return GithubImportResult(
            outcome: GithubImportOutcome.cancelled,
            succeeded: succeeded,
            failedOrCancelled: null,
            unattempted: allPaths.sublist(index),
            failure: GithubFailure(GithubFailureKind.cancelled),
          );
        }

        final GithubFailure? sessionFailure = _usableSessionFailure();
        if (sessionFailure != null) {
          return GithubImportResult(
            outcome: succeeded.isEmpty
                ? GithubImportOutcome.failed
                : GithubImportOutcome.partial,
            succeeded: succeeded,
            failedOrCancelled: null,
            unattempted: allPaths.sublist(index),
            failure: sessionFailure,
          );
        }

        final _ImportCandidate candidate = candidates[index];
        putBegan = true;
        onProgress?.call(
          GithubImportProgress(
            phase: GithubImportPhase.uploading,
            completedFiles: index,
            totalFiles: candidates.length,
            boardPath: candidate.target.boardPath,
          ),
        );
        try {
          await _connection.putFile(
            candidate.target.boardPath,
            candidate.bytes,
            onProgress: (TransferProgress transfer) {
              onProgress?.call(
                GithubImportProgress(
                  phase: GithubImportPhase.uploading,
                  completedFiles: index,
                  totalFiles: candidates.length,
                  boardPath: candidate.target.boardPath,
                  transfer: transfer,
                ),
              );
            },
          );
        } catch (_) {
          return GithubImportResult(
            outcome: succeeded.isEmpty
                ? GithubImportOutcome.failed
                : GithubImportOutcome.partial,
            succeeded: succeeded,
            failedOrCancelled: candidate.target.boardPath,
            unattempted: allPaths.sublist(index + 1),
            failure: GithubFailure(
              GithubFailureKind.board,
              path: candidate.target.boardPath,
            ),
          );
        }
        succeeded.add(candidate.target.boardPath);

        if (_isCancelled(generation)) {
          return GithubImportResult(
            outcome: GithubImportOutcome.cancelled,
            succeeded: succeeded,
            failedOrCancelled: null,
            unattempted: allPaths.sublist(index + 1),
            failure: GithubFailure(GithubFailureKind.cancelled),
          );
        }
      }

      return GithubImportResult(
        outcome: GithubImportOutcome.complete,
        succeeded: succeeded,
        failedOrCancelled: null,
        unattempted: const <String>[],
      );
    } finally {
      if (putBegan) {
        try {
          await _refreshFiles();
        } catch (_) {
          // A stale Files repaint cannot make a verified board PUT un-happen.
          // The view can retry its ordinary refresh independently.
        }
      }
    }
  }

  List<ImportTarget> _deriveTargets(
    String cwd,
    String fsRoot,
    List<GithubEntry> selected,
  ) {
    if (selected.isEmpty) {
      throw GithubFailure(GithubFailureKind.invalidTarget);
    }
    final List<GithubEntry> ordered = List<GithubEntry>.of(selected)
      ..sort(
        (GithubEntry left, GithubEntry right) =>
            left.remotePath.compareTo(right.remotePath),
      );
    final Set<String> boardPaths = <String>{};
    final Set<String> remoteParents = <String>{};
    final List<ImportTarget> targets = <ImportTarget>[];

    for (final GithubEntry entry in ordered) {
      final String name = _validatedLeaf(entry);
      final String boardPath = cwd == '/' ? '/$name' : '$cwd/$name';
      if (utf8.encode(boardPath).length > _maxBoardPathBytes) {
        throw GithubFailure(GithubFailureKind.pathTooLong, path: boardPath);
      }
      if (cwd == fsRoot && _isProtectedRootName(name)) {
        throw GithubFailure(
          GithubFailureKind.protectedRootTarget,
          path: boardPath,
        );
      }
      if (!boardPaths.add(boardPath)) {
        throw GithubFailure(GithubFailureKind.duplicateTarget, path: boardPath);
      }
      remoteParents.add(_parentOfRemotePath(entry.remotePath));
      targets.add(
        ImportTarget(source: entry, boardPath: boardPath, overwrites: false),
      );
    }
    if (remoteParents.length != 1) {
      throw GithubFailure(GithubFailureKind.invalidTarget);
    }
    return targets;
  }

  String _parentOfRemotePath(String path) {
    final int separator = path.lastIndexOf('/');
    return separator < 0 ? '' : path.substring(0, separator);
  }

  String _validatedLeaf(GithubEntry entry) {
    final String name = entry.name;
    if (entry.kind != GithubEntryKind.regularFile ||
        entry.declaredSize < 0 ||
        !name.endsWith('.py') ||
        name.isEmpty ||
        name == '.' ||
        name == '..' ||
        name.contains('/') ||
        name.contains('\\') ||
        name.contains('\u0000')) {
      throw GithubFailure(
        GithubFailureKind.invalidTarget,
        path: entry.remotePath,
      );
    }

    final String remotePath = entry.remotePath;
    if (remotePath.isEmpty ||
        remotePath.startsWith('/') ||
        remotePath.endsWith('/') ||
        remotePath.contains('\\') ||
        remotePath.contains('\u0000')) {
      throw GithubFailure(GithubFailureKind.invalidTarget, path: remotePath);
    }
    final List<String> segments = remotePath.split('/');
    if (segments.any(
          (String segment) =>
              segment.isEmpty || segment == '.' || segment == '..',
        ) ||
        segments.last != name) {
      throw GithubFailure(GithubFailureKind.invalidTarget, path: remotePath);
    }
    return name;
  }

  String _canonicalCwd(String cwd) {
    if (cwd.isEmpty ||
        !cwd.startsWith('/') ||
        cwd.contains('\\') ||
        cwd.contains('\u0000')) {
      throw GithubFailure(GithubFailureKind.invalidTarget, path: cwd);
    }
    final List<String> segments = cwd.split('/');
    if (segments
        .skip(1)
        .any(
          (String segment) =>
              segment == '.' || segment == '..' || segment.isEmpty,
        )) {
      if (cwd != '/') {
        throw GithubFailure(GithubFailureKind.invalidTarget, path: cwd);
      }
    }
    return cwd == '/' ? '/' : cwd;
  }

  bool _isAtOrBelowRoot(String cwd, String fsRoot) =>
      fsRoot == '/' || cwd == fsRoot || cwd.startsWith('$fsRoot/');

  bool _isProtectedRootName(String name) =>
      name.startsWith('pyble') ||
      name.startsWith('pble') ||
      name == '_boot.py' ||
      name == 'boot.py';

  GithubFailure? _validateContent(ImportTarget target, Uint8List bytes) {
    if (bytes.length > _maxGithubImportFileBytes) {
      return GithubFailure(
        GithubFailureKind.fileTooLarge,
        path: target.source.remotePath,
      );
    }
    if (bytes.contains(0)) {
      return GithubFailure(
        GithubFailureKind.nulByte,
        path: target.source.remotePath,
      );
    }
    try {
      utf8.decode(bytes, allowMalformed: false);
    } on FormatException {
      return GithubFailure(
        GithubFailureKind.invalidUtf8,
        path: target.source.remotePath,
      );
    }
    return null;
  }

  Future<Map<String, _BoardConflictKind>> _listConflicts(
    String cwd,
    List<ImportTarget> targets,
  ) async {
    _requireUsableSession();
    final Connection connection = _connection;
    final ConnectionDirectoryListingSource source;
    if (connection case final ConnectionDirectoryListingSource value) {
      source = value;
    } else {
      throw GithubFailure(GithubFailureKind.incompleteBoardListing, path: cwd);
    }
    late final DirectoryListing listing;
    try {
      listing = await source.listDirWithMetadata(cwd);
    } catch (_) {
      throw GithubFailure(GithubFailureKind.board, path: cwd);
    }
    _requireUsableSession();
    if (listing.truncated) {
      throw GithubFailure(GithubFailureKind.incompleteBoardListing, path: cwd);
    }

    final Map<String, List<RemoteEntry>> byName = <String, List<RemoteEntry>>{};
    for (final RemoteEntry entry in listing.entries) {
      (byName[entry.name] ??= <RemoteEntry>[]).add(entry);
    }
    return <String, _BoardConflictKind>{
      for (final ImportTarget target in targets)
        target.boardPath: _classifyConflict(
          byName[_leafOfBoardPath(target.boardPath)],
        ),
    };
  }

  _BoardConflictKind _classifyConflict(List<RemoteEntry>? entries) {
    if (entries == null || entries.isEmpty) return _BoardConflictKind.absent;
    if (entries.length != 1 || entries.single.isDir) {
      return _BoardConflictKind.blocking;
    }
    return _BoardConflictKind.regularFile;
  }

  bool _sameConflicts(
    Map<String, _BoardConflictKind> expected,
    Map<String, _BoardConflictKind> actual,
  ) {
    if (expected.length != actual.length) return false;
    for (final MapEntry<String, _BoardConflictKind> entry in expected.entries) {
      if (actual[entry.key] != entry.value) return false;
    }
    return true;
  }

  String _leafOfBoardPath(String path) =>
      path.substring(path.lastIndexOf('/') + 1);

  List<String> _paths(List<ImportTarget> targets) => <String>[
    for (final ImportTarget target in targets) target.boardPath,
  ];

  bool _isCancelled(int generation) => generation != _generation;

  void _requireUsableSession() {
    final GithubFailure? failure = _usableSessionFailure();
    if (failure != null) throw failure;
  }

  GithubFailure? _usableSessionFailure() {
    if (!identical(
      connectionSessionStampOf(_connection),
      _capturedSessionStamp,
    )) {
      return GithubFailure(GithubFailureKind.staleSession);
    }
    if (_connection.state.value != ConnState.ready) {
      return GithubFailure(GithubFailureKind.board, path: _cwd);
    }
    return null;
  }

  GithubImportResult _failed(List<String> allPaths, GithubFailure failure) =>
      GithubImportResult(
        outcome: GithubImportOutcome.failed,
        succeeded: const <String>[],
        failedOrCancelled: null,
        unattempted: allPaths,
        failure: failure,
      );

  GithubImportResult _cancelled(List<String> allPaths) => GithubImportResult(
    outcome: GithubImportOutcome.cancelled,
    succeeded: const <String>[],
    failedOrCancelled: null,
    unattempted: allPaths,
    failure: GithubFailure(GithubFailureKind.cancelled),
  );
}
