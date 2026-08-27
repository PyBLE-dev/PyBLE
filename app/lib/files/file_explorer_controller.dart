// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-30 (ADR-0010, TDD §11.6d, specs.md FR-FILES §4.5) — the working-loop file
/// explorer over the [Connection] file verbs.
///
/// [FileExplorerController] roots a listing at `DeviceInfo.fsRoot`, navigates
/// into/up (bounded at the root), and drives open-in-editor, upload-current-
/// buffer, new-file, mkdir, delete, and rename — each reporting continuous
/// [TransferProgress] on a transfer and mapping every typed [PbleException] to a
/// neutral [FileErrorKind] the widget layer localizes (FR-FILES-3, FR-I18N-3).
///
/// Binds through the seam ONLY (CON-8): it reads [connectionProvider] and never
/// imports `lib/ble` or a transport type. The `files -> editor` and
/// `files -> selectedSurface` reads are app-layer cross-imports (allowed).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart'
    show ValueChanged, ValueListenable, immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

/// The neutral, localizable classification of a file-operation failure
/// (FR-FILES-3). Each typed [PbleException] maps to exactly one kind; the widget
/// layer maps a kind to an ARB-sourced message (never a raw status code).
enum FileErrorKind {
  /// `ENOENT` — the item no longer exists on the board.
  notFound,

  /// `EACCES` — the board refused the operation (e.g. a non-empty directory).
  permission,

  /// `ENOSPC` — the board's filesystem is full.
  storageFull,

  /// `EIO` — a low-level storage error on the board.
  io,

  /// `ECRC` — a transfer failed its whole-file CRC check; nothing was changed.
  crc,

  /// `EBUSY` — an operation is already in progress (e.g. a running program).
  busy,

  /// `EUNSUPPORTED` — the board does not support the operation.
  unsupported,

  /// `ERANGE` — a value/length was out of range, or a transfer was incomplete.
  range,

  /// `EBADREQ` — the request was malformed.
  badRequest,

  /// No live board is attached to the [Connection] facade.
  notConnected,

  /// The transfer's data stream stalled past the inactivity ceiling
  /// ([PbleTimeoutException]) — dropped chunks, backpressure, or a dying link.
  timeout,

  /// Any other failure (internal/out-of-memory/protocol/link).
  generic,
}

/// The terminal truth reported by one visible-file delete batch.
enum FileDeleteBatchOutcome { complete, failed, partial }

/// Item-level progress emitted immediately before each delete attempt.
@immutable
class FileDeleteBatchProgress {
  const FileDeleteBatchProgress({
    required this.completed,
    required this.total,
    required this.currentPath,
  });

  /// The number of paths already deleted successfully.
  final int completed;

  /// The number of unique selected paths in the displayed batch order.
  final int total;

  /// The absolute board path about to be attempted.
  final String currentPath;
}

/// The immutable, non-transactional result of one delete batch.
@immutable
class FileDeleteBatchResult {
  FileDeleteBatchResult({
    required this.outcome,
    required List<String> succeededPaths,
    this.failedPath,
    required List<String> unattemptedPaths,
    this.failure,
  }) : succeededPaths = List<String>.unmodifiable(succeededPaths),
       unattemptedPaths = List<String>.unmodifiable(unattemptedPaths);

  final FileDeleteBatchOutcome outcome;
  final List<String> succeededPaths;
  final String? failedPath;
  final List<String> unattemptedPaths;
  final FileErrorKind? failure;
}

/// Whether [name] is one editable direct child of [cwd] in [fsRoot].
///
/// This pure predicate mirrors the case-sensitive PBLE/1 workspace jail for
/// Files presentation and batch preflight. It additionally rejects malformed
/// direct leaves and paths beyond PBLE/1's 128-byte UTF-8 wire ceiling.
bool isEditableBoardEntry({
  required String fsRoot,
  required String cwd,
  required String name,
}) => _boardEntryEditFailure(fsRoot: fsRoot, cwd: cwd, name: name) == null;

FileErrorKind? _boardEntryEditFailure({
  required String fsRoot,
  required String cwd,
  required String name,
}) {
  if (!_isCanonicalAbsoluteDirectory(fsRoot) ||
      !_isCanonicalAbsoluteDirectory(cwd) ||
      !_isWithinBoardRoot(fsRoot: fsRoot, path: cwd) ||
      !_isSafeDirectLeaf(name)) {
    return FileErrorKind.badRequest;
  }

  final String path = cwd == '/' ? '/$name' : '$cwd/$name';
  if (utf8.encode(path).length > 128) return FileErrorKind.range;

  final String relativeDirectory;
  if (cwd == fsRoot) {
    relativeDirectory = '';
  } else if (fsRoot == '/') {
    relativeDirectory = cwd.substring(1);
  } else {
    relativeDirectory = cwd.substring(fsRoot.length + 1);
  }
  final List<String> relativeComponents = <String>[
    if (relativeDirectory.isNotEmpty) ...relativeDirectory.split('/'),
    name,
  ];
  if (relativeComponents.any(
    (String component) => component.endsWith('.pbltmp'),
  )) {
    return FileErrorKind.permission;
  }

  final String topLevel = relativeComponents.first;
  if (topLevel.startsWith('pyble') ||
      topLevel.startsWith('pble') ||
      topLevel == 'boot.py' ||
      topLevel == '_boot.py') {
    return FileErrorKind.permission;
  }
  return null;
}

bool _isCanonicalAbsoluteDirectory(String path) {
  if (path == '/') return true;
  if (!path.startsWith('/') || path.endsWith('/') || path.contains(r'\')) {
    return false;
  }
  if (_hasControlCharacter(path)) return false;
  return path
      .split('/')
      .skip(1)
      .every(
        (String component) =>
            component.isNotEmpty && component != '.' && component != '..',
      );
}

bool _isWithinBoardRoot({required String fsRoot, required String path}) =>
    fsRoot == '/' || path == fsRoot || path.startsWith('$fsRoot/');

bool _isSafeDirectLeaf(String name) =>
    name.isNotEmpty &&
    name != '.' &&
    name != '..' &&
    !name.contains('/') &&
    !name.contains(r'\') &&
    !_hasControlCharacter(name);

bool _hasControlCharacter(String value) =>
    value.runes.any((int rune) => rune < 0x20 || rune == 0x7f);

/// The immutable snapshot the [FileExplorerController] publishes.
@immutable
class FileExplorerState {
  const FileExplorerState({
    this.fsRoot = '/',
    this.hasReportedFsRoot = false,
    required this.cwd,
    required this.entries,
    required this.loading,
    this.progress,
    this.speedBps,
    this.error,
    this.errorPath,
  });

  /// The filesystem root reported by the connected board.
  final String fsRoot;

  /// Whether [fsRoot] came from the current board session's DEVICE_INFO.
  final bool hasReportedFsRoot;

  /// The current directory being listed, rooted at `DeviceInfo.fsRoot`.
  final String cwd;

  /// The entries listed in [cwd] (directories first, then files, name order).
  final List<RemoteEntry> entries;

  /// Whether a listing/refresh is in flight.
  final bool loading;

  /// The live transfer progress, or `null` when no transfer is active.
  final TransferProgress? progress;

  /// The smoothed live transfer throughput in bytes/second, or `null` before
  /// the first measurable interval. Cleared with [progress].
  final double? speedBps;

  /// The last operation's error kind, or `null` when the last op succeeded.
  final FileErrorKind? error;

  /// The board path the last [error] refers to (for the localized message).
  final String? errorPath;

  FileExplorerState copyWith({
    String? fsRoot,
    bool? hasReportedFsRoot,
    String? cwd,
    List<RemoteEntry>? entries,
    bool? loading,
    TransferProgress? progress,
    double? speedBps,
    bool clearProgress = false,
    FileErrorKind? error,
    String? errorPath,
    bool clearError = false,
  }) {
    return FileExplorerState(
      fsRoot: fsRoot ?? this.fsRoot,
      hasReportedFsRoot: hasReportedFsRoot ?? this.hasReportedFsRoot,
      cwd: cwd ?? this.cwd,
      entries: entries ?? this.entries,
      loading: loading ?? this.loading,
      progress: clearProgress ? null : (progress ?? this.progress),
      speedBps: clearProgress ? null : (speedBps ?? this.speedBps),
      error: clearError ? null : (error ?? this.error),
      errorPath: clearError ? null : (errorPath ?? this.errorPath),
    );
  }
}

/// The working-loop file explorer (A-30). See the library doc for the contract.
class FileExplorerController extends Notifier<FileExplorerState> {
  /// The filesystem root reported by `DeviceInfo.fsRoot`; navigation is bounded
  /// here (`up()` never escapes it).
  String _fsRoot = '/';

  /// The previous [ConnState], to tell a NEW connection (disconnected/connecting
  /// → ready ⇒ re-init) from a program finishing (running → ready ⇒ keep cwd).
  ConnState _lastConnState = ConnState.disconnected;

  /// Invalidates late file-open completions when a newer open starts.
  int _openEpoch = 0;

  /// Invalidates filesystem-root discovery when its initiating attachment is
  /// replaced, the controller is disposed, or a newer initialization starts.
  int _initEpoch = 0;

  /// Makes directory listings latest-request-wins within one board session.
  int _listingEpoch = 0;

  /// Prevents queued or in-flight asynchronous work from reading a dead ref.
  bool _disposed = false;

  /// Serializes explicit Open-as-Blocks source downloads. The native row stays
  /// responsive, but a rapid second activation cannot start a duplicate GET
  /// or a competing preview flow.
  bool _blocksDownloadInFlight = false;

  /// PBLE/1 has one serialized mutation stream; a second local delete batch is
  /// refused before it can send a board verb.
  bool _deleteBatchInFlight = false;

  @override
  FileExplorerState build() {
    // The Connection facade is STABLE (ADR-0009) — its identity never changes
    // across connect/disconnect — so watching it would run this exactly once.
    // Auto-load is driven off the OBSERVABLE ConnState instead: each NEW
    // connection (disconnected/connecting -> ready) re-roots and re-lists,
    // while running -> ready (a program finishing) keeps the user's cwd.
    final ValueListenable<ConnState> connState = ref.watch(connStateProvider);
    _lastConnState = connState.value;
    connState.addListener(_onConnState);
    ref.onDispose(() {
      _disposed = true;
      _initEpoch += 1;
      _listingEpoch += 1;
      connState.removeListener(_onConnState);
    });

    if (_isAttached(connState.value)) {
      // Already connected at first build (the gated shell's normal path):
      // root-init (fsRoot -> initial listing) asynchronously.
      final int scheduledEpoch = _initEpoch;
      scheduleMicrotask(() {
        if (_disposed ||
            scheduledEpoch != _initEpoch ||
            !_isAttached(connState.value)) {
          return;
        }
        _init();
      });
    }
    return FileExplorerState(
      fsRoot: '/',
      hasReportedFsRoot: false,
      cwd: '/',
      entries: const <RemoteEntry>[],
      loading: _isAttached(connState.value),
    );
  }

  static bool _isAttached(ConnState s) =>
      s == ConnState.ready || s == ConnState.running;

  void _onConnState() {
    final ConnState prev = _lastConnState;
    final ConnState now = ref.read(connStateProvider).value;
    _lastConnState = now;
    if (now == ConnState.ready && !_isAttached(prev)) {
      // A NEW board session became ready: auto-load its listing (FR-FILES-1).
      _init();
    } else if (now == ConnState.disconnected) {
      // DEVICE_INFO and the initial listing belong to the attachment that
      // started them. Prevent either completion from publishing after detach.
      _initEpoch += 1;
      _listingEpoch += 1;
      // The board went away: drop the stale listing (the view shows the
      // disconnected guidance); the next connection re-roots via _init.
      state = state.copyWith(
        entries: <RemoteEntry>[],
        loading: false,
        hasReportedFsRoot: false,
        clearProgress: true,
        clearError: true,
      );
    }
  }

  Connection get _conn => ref.read(connectionProvider);

  /// Reads `fsRoot` from the board and lists the root directory.
  Future<void> _init() async {
    if (_disposed) return;
    final Connection connection = _conn;
    if (!_isAttached(connection.state.value)) return;

    final int epoch = ++_initEpoch;
    _listingEpoch += 1;
    final Object sessionStamp = connectionSessionStampOf(connection);
    String? reportedRoot;
    int? initialListingEpoch;
    state = state.copyWith(
      loading: true,
      hasReportedFsRoot: false,
      clearError: true,
    );
    try {
      final DeviceInfo info = await connection.deviceInfo();
      if (!_isInitContextCurrent(
        epoch: epoch,
        connection: connection,
        stamp: sessionStamp,
      )) {
        return;
      }

      reportedRoot = info.fsRoot;
      _fsRoot = reportedRoot;
      initialListingEpoch = ++_listingEpoch;
      state = state.copyWith(
        fsRoot: _fsRoot,
        hasReportedFsRoot: true,
        cwd: _fsRoot,
      );

      final List<RemoteEntry> entries = await connection.listDir(reportedRoot);
      if (!_isListingContextCurrent(
        epoch: initialListingEpoch,
        connection: connection,
        stamp: sessionStamp,
        path: reportedRoot,
      )) {
        return;
      }
      entries.sort(_entryOrder);
      state = state.copyWith(entries: entries, loading: false);
    } on PbleException catch (e) {
      final bool isCurrent = reportedRoot == null
          ? _isInitContextCurrent(
              epoch: epoch,
              connection: connection,
              stamp: sessionStamp,
            )
          : _isListingContextCurrent(
              epoch: initialListingEpoch!,
              connection: connection,
              stamp: sessionStamp,
              path: reportedRoot,
            );
      if (!isCurrent) {
        return;
      }
      state = state.copyWith(
        loading: false,
        error: _kindOf(e),
        errorPath: reportedRoot ?? _fsRoot,
      );
    }
  }

  /// Re-lists [FileExplorerState.cwd] (FR-FILES-1).
  Future<void> refresh() async {
    if (_disposed) return;
    final Connection connection = _conn;
    final Object sessionStamp = connectionSessionStampOf(connection);
    final String path = state.cwd;
    final int epoch = ++_listingEpoch;
    state = state.copyWith(loading: true, clearError: true);
    try {
      final List<RemoteEntry> entries = await connection.listDir(path);
      if (!_isListingContextCurrent(
        epoch: epoch,
        connection: connection,
        stamp: sessionStamp,
        path: path,
      )) {
        return;
      }
      entries.sort(_entryOrder);
      state = state.copyWith(entries: entries, loading: false);
    } on PbleException catch (e) {
      if (!_isListingContextCurrent(
        epoch: epoch,
        connection: connection,
        stamp: sessionStamp,
        path: path,
      )) {
        return;
      }
      state = state.copyWith(
        loading: false,
        error: _kindOf(e),
        errorPath: path,
      );
    }
  }

  /// Descends into the child directory [dirName] of the current directory.
  Future<void> into(String dirName) async {
    state = state.copyWith(cwd: _join(state.cwd, dirName));
    await refresh();
  }

  /// Returns to the parent directory, bounded at [_fsRoot] (FR-FILES).
  Future<void> up() async {
    if (state.cwd == _fsRoot) return;
    final String parent = _parentOf(state.cwd);
    final String next = parent.length < _fsRoot.length ? _fsRoot : parent;
    state = state.copyWith(cwd: next);
    await refresh();
  }

  /// Downloads [fileName] and opens it in the editor, focusing that surface.
  Future<void> openInEditor(String fileName) async {
    final String path = _join(state.cwd, fileName);
    final int epoch = ++_openEpoch;
    final EditorDocument before = ref.read(editorDocumentProvider);
    try {
      final Uint8List bytes = await _conn.getFile(
        path,
        onProgress: (TransferProgress progress) {
          if (epoch == _openEpoch) _onProgress(progress);
        },
      );
      if (epoch != _openEpoch || ref.read(editorDocumentProvider) != before) {
        return;
      }
      state = state.copyWith(clearProgress: true);
      final String content = utf8.decode(bytes, allowMalformed: true);
      ref
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: path, content: content);
      ref.read(selectedSurfaceProvider.notifier).state = AppSurface.editor;
    } on PbleException catch (e) {
      if (epoch == _openEpoch) _fail(e, path);
    }
  }

  /// Downloads one Python source snapshot for the guarded Open-as-Blocks flow.
  ///
  /// This is read-only and does not replace the Editor, Blocks, or navigation.
  /// A newer open invalidates a late result.
  Future<EditorDocument?> downloadForBlocks(String fileName) async {
    if (_blocksDownloadInFlight) return null;
    _blocksDownloadInFlight = true;
    final String path = _join(state.cwd, fileName);
    final int epoch = ++_openEpoch;
    try {
      final Uint8List bytes = await _conn.getFile(
        path,
        onProgress: (TransferProgress progress) {
          if (epoch == _openEpoch) _onProgress(progress);
        },
      );
      if (epoch != _openEpoch) return null;
      final String content = utf8.decode(bytes);
      state = state.copyWith(clearProgress: true, clearError: true);
      return EditorDocument(
        name: fileName,
        content: content,
        dirty: false,
        boardPath: path,
      );
    } on PbleException catch (error) {
      if (epoch == _openEpoch) _fail(error, path);
      return null;
    } on FormatException {
      if (epoch == _openEpoch) {
        state = state.copyWith(
          clearProgress: true,
          error: FileErrorKind.badRequest,
          errorPath: path,
        );
      }
      return null;
    } finally {
      _blocksDownloadInFlight = false;
    }
  }

  /// Uploads the current editor buffer to `cwd/<document name>` and marks the
  /// buffer saved (FR-FILES-4; success is CRC-verified by the seam).
  Future<void> uploadCurrentBuffer() async {
    final EditorDocument doc = ref.read(editorDocumentProvider);
    final String path = _join(state.cwd, doc.name);
    try {
      await _conn.putFile(
        path,
        Uint8List.fromList(utf8.encode(doc.content)),
        onProgress: _onProgress,
      );
      state = state.copyWith(clearProgress: true);
      if (ref.read(editorDocumentProvider) == doc) {
        ref.read(editorDocumentProvider.notifier).markSaved(boardPath: path);
      }
      await refresh();
    } on PbleException catch (e) {
      _fail(e, path);
    }
  }

  /// Creates an empty board file [name] in the current directory and opens it.
  Future<void> newFile(String name) async {
    final String path = _join(state.cwd, name);
    try {
      await _conn.putFile(path, Uint8List(0));
      await refresh();
      await openInEditor(name);
    } on PbleException catch (e) {
      _fail(e, path);
    }
  }

  /// Creates a directory [name] in the current directory.
  Future<void> mkdir(String name) async {
    final String path = _join(state.cwd, name);
    try {
      await _conn.mkdir(path);
      await refresh();
    } on PbleException catch (e) {
      _fail(e, path);
    }
  }

  /// Deletes the entry [name] in the current directory.
  Future<void> delete(String name) async {
    final String path = _join(state.cwd, name);
    try {
      await _conn.delete(path);
      await refresh();
    } on PbleException catch (e) {
      _fail(e, path);
    }
  }

  /// Deletes eligible shown regular files sequentially in displayed order.
  ///
  /// One invocation is bound to its captured folder and opaque connection
  /// session. It stops on the first failure or context replacement, never
  /// rolls back, and performs at most one same-session reconciliation listing.
  Future<FileDeleteBatchResult> deleteMany(
    Iterable<String> names, {
    String? expectedCwd,
    Object? expectedSessionStamp,
    ValueChanged<FileDeleteBatchProgress>? onProgress,
  }) async {
    final Connection connection = _conn;
    final Object capturedStamp = connectionSessionStampOf(connection);
    final String capturedCwd = state.cwd;
    final String capturedRoot = state.fsRoot;
    final List<RemoteEntry> displayed = List<RemoteEntry>.of(state.entries);
    final List<String> requestedNames = List<String>.of(names);

    if (requestedNames.isEmpty) {
      return _preflightDeleteFailure(FileErrorKind.badRequest);
    }

    final Set<String> selectedNames = <String>{};
    for (final String name in requestedNames) {
      if (!selectedNames.add(name)) {
        return _preflightDeleteFailure(FileErrorKind.badRequest);
      }
    }

    final Map<String, RemoteEntry> displayedByName = <String, RemoteEntry>{
      for (final RemoteEntry entry in displayed) entry.name: entry,
    };
    for (final String name in selectedNames) {
      final FileErrorKind? editFailure = _boardEntryEditFailure(
        fsRoot: capturedRoot,
        cwd: capturedCwd,
        name: name,
      );
      if (editFailure != null) {
        return _preflightDeleteFailure(editFailure);
      }
      final RemoteEntry? entry = displayedByName[name];
      if (entry == null || entry.isDir) {
        return _preflightDeleteFailure(FileErrorKind.badRequest);
      }
    }

    final List<String> orderedPaths = <String>[
      for (final RemoteEntry entry in displayed)
        if (selectedNames.contains(entry.name)) _join(capturedCwd, entry.name),
    ];
    if (orderedPaths.length != selectedNames.length) {
      return _preflightDeleteFailure(FileErrorKind.badRequest);
    }

    if (expectedCwd != null && expectedCwd != capturedCwd) {
      return _preflightDeleteFailure(FileErrorKind.badRequest);
    }
    if (expectedSessionStamp != null &&
        !identical(expectedSessionStamp, capturedStamp)) {
      return _preflightDeleteFailure(
        FileErrorKind.notConnected,
        unattemptedPaths: orderedPaths,
      );
    }
    if (_deleteBatchInFlight) {
      return _preflightDeleteFailure(
        FileErrorKind.busy,
        unattemptedPaths: orderedPaths,
      );
    }
    _deleteBatchInFlight = true;

    try {
      FileErrorKind? failure = _capturedContextFailure(
        connection: connection,
        stamp: capturedStamp,
        cwd: capturedCwd,
      );
      if (failure != null) {
        return _preflightDeleteFailure(failure, unattemptedPaths: orderedPaths);
      }

      state = state.copyWith(clearError: true);
      final List<String> succeeded = <String>[];
      String? failedPath;
      int attempted = 0;
      int currentIndex = 0;

      for (; currentIndex < orderedPaths.length; currentIndex += 1) {
        final String path = orderedPaths[currentIndex];
        failure = _capturedContextFailure(
          connection: connection,
          stamp: capturedStamp,
          cwd: capturedCwd,
        );
        if (failure != null) {
          failedPath = path;
          break;
        }

        onProgress?.call(
          FileDeleteBatchProgress(
            completed: succeeded.length,
            total: orderedPaths.length,
            currentPath: path,
          ),
        );
        attempted += 1;
        try {
          await connection.delete(path);
          succeeded.add(path);
        } on PbleException catch (error) {
          failure = _kindOf(error);
          failedPath = path;
          break;
        }
      }

      PbleException? reconciliationError;
      List<RemoteEntry>? reconciledEntries;
      if (attempted > 0 &&
          _isCapturedSessionCurrent(
            connection: connection,
            stamp: capturedStamp,
          )) {
        try {
          reconciledEntries = await connection.listDir(capturedCwd);
          reconciledEntries.sort(_entryOrder);
        } on PbleException catch (error) {
          reconciliationError = error;
        }
      }

      final bool sameSession = _isCapturedSessionCurrent(
        connection: connection,
        stamp: capturedStamp,
      );
      if (sameSession) {
        FileExplorerState next = state;
        if (reconciledEntries != null && state.cwd == capturedCwd) {
          next = next.copyWith(entries: reconciledEntries, loading: false);
        }
        if (failure != null && failedPath != null) {
          next = next.copyWith(
            clearProgress: true,
            error: failure,
            errorPath: failedPath,
          );
        } else if (reconciliationError != null) {
          next = next.copyWith(
            clearProgress: true,
            error: _kindOf(reconciliationError),
            errorPath: capturedCwd,
          );
        } else {
          next = next.copyWith(clearProgress: true, clearError: true);
        }
        state = next;
      }

      if (failure == null) {
        return FileDeleteBatchResult(
          outcome: FileDeleteBatchOutcome.complete,
          succeededPaths: succeeded,
          unattemptedPaths: const <String>[],
        );
      }

      return FileDeleteBatchResult(
        outcome: succeeded.isEmpty
            ? FileDeleteBatchOutcome.failed
            : FileDeleteBatchOutcome.partial,
        succeededPaths: succeeded,
        failedPath: failedPath,
        unattemptedPaths: failedPath == null
            ? orderedPaths.sublist(currentIndex)
            : orderedPaths.sublist(currentIndex + 1),
        failure: failure,
      );
    } finally {
      _deleteBatchInFlight = false;
    }
  }

  /// Renames the entry [from] to [to], both within the current directory.
  Future<void> rename(String from, String to) async {
    final String src = _join(state.cwd, from);
    final String dst = _join(state.cwd, to);
    try {
      await _conn.rename(src, dst);
      await refresh();
    } on PbleException catch (e) {
      _fail(e, src);
    }
  }

  // --- helpers ---------------------------------------------------------------

  FileDeleteBatchResult _preflightDeleteFailure(
    FileErrorKind failure, {
    List<String> unattemptedPaths = const <String>[],
  }) => FileDeleteBatchResult(
    outcome: FileDeleteBatchOutcome.failed,
    succeededPaths: const <String>[],
    unattemptedPaths: unattemptedPaths,
    failure: failure,
  );

  FileErrorKind? _capturedContextFailure({
    required Connection connection,
    required Object stamp,
    required String cwd,
  }) {
    if (!_isCapturedSessionCurrent(connection: connection, stamp: stamp)) {
      return FileErrorKind.notConnected;
    }
    return state.cwd == cwd ? null : FileErrorKind.badRequest;
  }

  bool _isCapturedSessionCurrent({
    required Connection connection,
    required Object stamp,
  }) {
    final Connection current = _conn;
    return identical(current, connection) &&
        identical(connectionSessionStampOf(current), stamp);
  }

  bool _isInitContextCurrent({
    required int epoch,
    required Connection connection,
    required Object stamp,
  }) =>
      !_disposed &&
      epoch == _initEpoch &&
      _isCapturedSessionCurrent(connection: connection, stamp: stamp) &&
      _isAttached(connection.state.value);

  bool _isListingContextCurrent({
    required int epoch,
    required Connection connection,
    required Object stamp,
    required String path,
  }) =>
      !_disposed &&
      epoch == _listingEpoch &&
      state.cwd == path &&
      _isCapturedSessionCurrent(connection: connection, stamp: stamp) &&
      _isAttached(connection.state.value);

  /// Wall-clock for the transfer in flight; restarted per transfer.
  Stopwatch? _txClock;
  int _lastSent = 0;
  double? _emaBps;

  void _onProgress(TransferProgress p) {
    // A fresh transfer: state.progress was cleared by the previous verb, or the
    // byte counter went backwards (a new file). Restart the meters.
    if (_txClock == null || state.progress == null || p.sent < _lastSent) {
      _txClock = Stopwatch()..start();
      _emaBps = null;
    }
    _lastSent = p.sent;
    final double secs = _txClock!.elapsedMicroseconds / 1e6;
    if (secs > 0 && p.sent > 0) {
      // Whole-transfer average blended with an EMA: stable to read, still
      // responsive to a stall (the average decays as the clock keeps running).
      final double avg = p.sent / secs;
      _emaBps = _emaBps == null ? avg : (0.7 * _emaBps! + 0.3 * avg);
    }
    state = state.copyWith(progress: p, speedBps: _emaBps);
  }

  void _fail(PbleException e, String path) {
    state = state.copyWith(
      clearProgress: true,
      error: _kindOf(e),
      errorPath: path,
    );
  }

  /// Joins a directory [cwd] and a leaf [name] into an absolute board path,
  /// keeping the root un-doubled (`/` + `x` -> `/x`, not `//x`).
  String _join(String cwd, String name) => cwd == '/' ? '/$name' : '$cwd/$name';

  String _parentOf(String path) {
    final int i = path.lastIndexOf('/');
    return i <= 0 ? '/' : path.substring(0, i);
  }

  int _entryOrder(RemoteEntry a, RemoteEntry b) {
    if (a.isDir != b.isDir) return a.isDir ? -1 : 1;
    return a.name.toLowerCase().compareTo(b.name.toLowerCase());
  }

  /// Maps a typed [PbleException] to its neutral [FileErrorKind] (FR-FILES-3).
  FileErrorKind _kindOf(PbleException e) {
    return switch (e) {
      ENoEnt() => FileErrorKind.notFound,
      EAcces() => FileErrorKind.permission,
      ENoSpc() => FileErrorKind.storageFull,
      EIo() => FileErrorKind.io,
      ECrc() => FileErrorKind.crc,
      PbleCrcException() => FileErrorKind.crc,
      EBusy() => FileErrorKind.busy,
      EUnsupported() => FileErrorKind.unsupported,
      ERange() => FileErrorKind.range,
      EBadReq() => FileErrorKind.badRequest,
      NotConnectedException() => FileErrorKind.notConnected,
      PbleTimeoutException() => FileErrorKind.timeout,
      _ => FileErrorKind.generic,
    };
  }
}

/// The working-loop file explorer provider (A-30).
final NotifierProvider<FileExplorerController, FileExplorerState>
fileExplorerProvider =
    NotifierProvider<FileExplorerController, FileExplorerState>(
      FileExplorerController.new,
    );
