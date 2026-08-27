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

import 'package:flutter/foundation.dart' show ValueListenable, immutable;
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

/// The immutable snapshot the [FileExplorerController] publishes.
@immutable
class FileExplorerState {
  const FileExplorerState({
    required this.fsRoot,
    required this.hasReportedFsRoot,
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

  /// Serializes explicit Open-as-Blocks source downloads. The native row stays
  /// responsive, but a rapid second activation cannot start a duplicate GET
  /// or a competing preview flow.
  bool _blocksDownloadInFlight = false;

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
    ref.onDispose(() => connState.removeListener(_onConnState));

    if (_isAttached(connState.value)) {
      // Already connected at first build (the gated shell's normal path):
      // root-init (fsRoot -> initial listing) asynchronously.
      scheduleMicrotask(_init);
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
    state = state.copyWith(
      loading: true,
      hasReportedFsRoot: false,
      clearError: true,
    );
    try {
      final DeviceInfo info = await _conn.deviceInfo();
      _fsRoot = info.fsRoot;
      state = state.copyWith(
        fsRoot: _fsRoot,
        hasReportedFsRoot: true,
        cwd: _fsRoot,
      );
      await refresh();
    } on PbleException catch (e) {
      state = state.copyWith(
        loading: false,
        error: _kindOf(e),
        errorPath: _fsRoot,
      );
    }
  }

  /// Re-lists [FileExplorerState.cwd] (FR-FILES-1).
  Future<void> refresh() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final List<RemoteEntry> entries = await _conn.listDir(state.cwd);
      entries.sort(_entryOrder);
      state = state.copyWith(entries: entries, loading: false);
    } on PbleException catch (e) {
      state = state.copyWith(
        loading: false,
        error: _kindOf(e),
        errorPath: state.cwd,
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
