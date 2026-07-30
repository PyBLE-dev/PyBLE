// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Shared file-backed program actions (ADR-0013).
///
/// The text editor and visual Blocks surface both delegate their board writes
/// here. A normal program is uploaded with the Connection file-transfer path
/// before it is run, so it is not constrained by PBLE/1's deliberately small
/// inline `runSource` ceiling. This class owns no document or UI state and
/// imports no transport implementation.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

import 'smart_punctuation.dart';

/// PBLE/1 file paths are capped at 128 UTF-8 bytes.
const int kMaxProgramBoardPathBytes = 128;

class ProgramBundlePathTooLong implements Exception {
  const ProgramBundlePathTooLong(this.path);

  final String path;

  @override
  String toString() => 'ProgramBundlePathTooLong($path)';
}

/// The source upload completed, but its sidecar commit record did not.
///
/// PBLE/1 has no multi-file transaction. Callers must therefore report that
/// [sourcePath] may have changed even though [companionPath] was not committed.
/// A previous companion is safe to leave in place because exact reopen rejects
/// its now-stale source binding.
class ProgramBundleIncomplete implements Exception {
  const ProgramBundleIncomplete({
    required this.sourcePath,
    required this.companionPath,
    required this.cause,
  });

  final String sourcePath;
  final String companionPath;
  final Object cause;

  @override
  String toString() =>
      'Program bundle incomplete: $sourcePath may have changed, but '
      '$companionPath was not committed ($cause)';
}

/// The next phase of a source/sidecar bundle action that was refused because
/// the stable Connection facade attached or detached a board.
enum ProgramBundleNextOperation { writeCompanion, runFile }

/// A bundle action stopped before its next verb because the board session
/// changed after the action began.
///
/// This prevents a source written to one board from gaining a sidecar on
/// another board, and prevents a committed pair on one board from causing Run
/// on another. The session stamp itself is intentionally opaque and is never
/// exposed by this error.
class ProgramBundleSessionChanged implements Exception {
  const ProgramBundleSessionChanged({
    required this.sourcePath,
    required this.companionPath,
    required this.nextOperation,
  });

  final String sourcePath;
  final String companionPath;
  final ProgramBundleNextOperation nextOperation;

  @override
  String toString() => switch (nextOperation) {
    ProgramBundleNextOperation.writeCompanion =>
      'Connection session changed after $sourcePath was uploaded; '
          '$companionPath was not written',
    ProgramBundleNextOperation.runFile =>
      'Connection session changed after $sourcePath + $companionPath were '
          'committed; Run was not dispatched',
  };
}

final class _PinnedBundleSession {
  const _PinnedBundleSession({
    required this.connection,
    required this.stamp,
    required this.sourcePath,
    required this.companionPath,
  });

  final Connection connection;
  final Object stamp;
  final String sourcePath;
  final String companionPath;
}

/// Connection-only actions shared by every source-producing app surface.
class ProgramActions {
  const ProgramActions(this._ref);

  final Ref _ref;

  /// Uploads [source] to the absolute board [path] and returns that path.
  ///
  /// The file transfer completes its size/CRC verification before this future
  /// succeeds. Typed Connection failures propagate unchanged.
  Future<String> saveSource({
    required String path,
    required String source,
    ProgressCb? onProgress,
  }) async {
    final String cleaned = normalizeSmartPunctuation(source);
    final Uint8List bytes = Uint8List.fromList(utf8.encode(cleaned));
    await _ref
        .read(connectionProvider)
        .putFile(path, bytes, onProgress: onProgress);
    return path;
  }

  /// Uploads [source], waits for its verified completion, then runs [path].
  ///
  /// `runFile` is never attempted when the upload fails.
  Future<void> runSourceFile({
    required String path,
    required String source,
    ProgressCb? onProgress,
  }) async {
    await saveSource(path: path, source: source, onProgress: onProgress);
    await _ref.read(connectionProvider).runFile(path);
  }

  /// Writes a Python file and then its raw JSON companion commit record.
  ///
  /// The source is deliberately first: if it fails, no companion is attempted;
  /// if the companion fails, any older companion no longer matches the changed
  /// source and exact recovery safely rejects it. [companionJson] bypasses smart
  /// punctuation normalization because Blockly string/comment data is opaque.
  Future<String> saveSourceBundle({
    required String path,
    required String source,
    required String companionPath,
    required String companionJson,
    ProgressCb? onProgress,
  }) async {
    final _PinnedBundleSession session = await _saveSourceBundlePinned(
      path: path,
      source: source,
      companionPath: companionPath,
      companionJson: companionJson,
      onProgress: onProgress,
    );
    return session.sourcePath;
  }

  Future<_PinnedBundleSession> _saveSourceBundlePinned({
    required String path,
    required String source,
    required String companionPath,
    required String companionJson,
    ProgressCb? onProgress,
  }) async {
    // The manager intentionally exposes one stable facade across boards. Pin
    // its current local session before even the synchronous preflight so every
    // later bundle phase can prove it still targets the same attachment.
    final Connection connection = _ref.read(connectionProvider);
    final Object sessionStamp = connectionSessionStampOf(connection);
    _preflightPath(path, requirePython: true);
    _preflightPath(companionPath);
    if (companionPath != '$path.pyble-blocks.json') {
      throw ProgramBundlePathTooLong(companionPath);
    }
    // Blocks generator output is an exact persistence artifact. Unlike the
    // text Editor path, do not rewrite punctuation inside user text/comments.
    await connection.putFile(
      path,
      Uint8List.fromList(utf8.encode(source)),
      onProgress: onProgress,
    );
    final _PinnedBundleSession pinned = _PinnedBundleSession(
      connection: connection,
      stamp: sessionStamp,
      sourcePath: path,
      companionPath: companionPath,
    );
    _requirePinnedSession(
      pinned,
      nextOperation: ProgramBundleNextOperation.writeCompanion,
    );
    try {
      await connection.putFile(
        companionPath,
        Uint8List.fromList(utf8.encode(companionJson)),
        onProgress: onProgress,
      );
    } catch (error, stackTrace) {
      Error.throwWithStackTrace(
        ProgramBundleIncomplete(
          sourcePath: path,
          companionPath: companionPath,
          cause: error,
        ),
        stackTrace,
      );
    }
    return pinned;
  }

  /// Writes a complete source+companion bundle, then runs only after both
  /// verified uploads succeed.
  Future<void> runSourceBundle({
    required String path,
    required String source,
    required String companionPath,
    required String companionJson,
    ProgressCb? onProgress,
  }) async {
    final _PinnedBundleSession session = await _saveSourceBundlePinned(
      path: path,
      source: source,
      companionPath: companionPath,
      companionJson: companionJson,
      onProgress: onProgress,
    );
    _requirePinnedSession(
      session,
      nextOperation: ProgramBundleNextOperation.runFile,
    );
    await session.connection.runFile(path);
  }

  void _requirePinnedSession(
    _PinnedBundleSession session, {
    required ProgramBundleNextOperation nextOperation,
  }) {
    final Connection current = _ref.read(connectionProvider);
    if (!identical(current, session.connection) ||
        !identical(connectionSessionStampOf(current), session.stamp)) {
      throw ProgramBundleSessionChanged(
        sourcePath: session.sourcePath,
        companionPath: session.companionPath,
        nextOperation: nextOperation,
      );
    }
  }

  static void _preflightPath(String path, {bool requirePython = false}) {
    final List<String> segments = path.split('/');
    final String topLevel = segments.length > 1 ? segments[1] : '';
    final bool hasControlCharacter = path.runes.any(
      (int value) => value < 0x20 || value == 0x7f,
    );
    final bool hasReservedSegment = segments.any(
      (String segment) => segment.toLowerCase().endsWith('.pbltmp'),
    );
    if (!path.startsWith('/') ||
        path.endsWith('/') ||
        path.contains(r'\') ||
        hasControlCharacter ||
        segments
            .skip(1)
            .any(
              (String segment) =>
                  segment.isEmpty || segment == '.' || segment == '..',
            ) ||
        topLevel.startsWith('pyble') ||
        topLevel.startsWith('pble') ||
        topLevel == '_boot.py' ||
        topLevel == 'boot.py' ||
        hasReservedSegment ||
        (requirePython && !path.endsWith('.py')) ||
        utf8.encode(path).length > kMaxProgramBoardPathBytes) {
      throw ProgramBundlePathTooLong(path);
    }
  }
}

/// The one file-backed board-action seam used by Editor and Blocks.
final Provider<ProgramActions> programActionsProvider =
    Provider<ProgramActions>((Ref ref) => ProgramActions(ref));
