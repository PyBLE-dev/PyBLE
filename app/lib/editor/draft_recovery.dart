// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// One local current-text recovery slot. Disk state and board dirty state are
/// independent; only a successful transaction acknowledges local protection.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pyble/data/draft_repository.dart';

import 'editor_document.dart';

/// Production supplies a factory; ordinary provider harnesses remain disk-free.
final draftRepositoryFactoryProvider =
    Provider<Future<DraftRepository> Function()?>((ref) => null);

/// Injectable already-open repository for focused storage/controller harnesses.
final draftRepositoryProvider = Provider<DraftRepository?>((ref) => null);

enum DraftRecoveryStatus {
  disabled,
  loading,
  decision,
  pending,
  saving,
  saved,
  failed,
  volatile,
}

class DraftRecoveryState {
  const DraftRecoveryState({
    required this.status,
    this.candidate,
    this.failure,
    this.timedOut = false,
    this.hasResolvedStartup = false,
    this.busy = false,
    this.checkpointTime,
  });

  final DraftRecoveryStatus status;
  final DraftSnapshot? candidate;
  final DraftStorageFailure? failure;
  final bool timedOut;
  final bool hasResolvedStartup;
  final bool busy;
  final DateTime? checkpointTime;

  bool get enabled => status != DraftRecoveryStatus.disabled;
  bool get blocksStartup =>
      enabled &&
      (status == DraftRecoveryStatus.loading ||
          status == DraftRecoveryStatus.decision ||
          (!hasResolvedStartup && status == DraftRecoveryStatus.failed));
}

final draftRecoveryProvider =
    NotifierProvider<DraftRecoveryController, DraftRecoveryState>(
      DraftRecoveryController.new,
    );

class _Checkpoint {
  _Checkpoint(this.document, this.epoch);
  final EditorDocument document;
  final int epoch;
  final Completer<bool> completion = Completer<bool>();
}

class DraftRecoveryController extends Notifier<DraftRecoveryState> {
  DraftRepository? _repository;
  Future<DraftRepository>? _opening;
  Future<DraftRead>? _loading;
  Future<void>? _startup;
  Future<void>? _active;
  Completer<void>? _replacementDone;
  _Checkpoint? _queued;
  Timer? _idle;
  Timer? _maximum;
  Timer? _startupTimer;
  DateTime? _lastCheckpointTime;
  int _operation = 0;
  int _generation = 0;
  int _decisionEpoch = 0;
  int _lastCommittedEpoch = -1;
  bool _started = false;
  bool _writable = false;
  bool _suppress = false;
  bool _replacement = false;
  bool _disposed = false;

  @override
  DraftRecoveryState build() {
    _repository = ref.read(draftRepositoryProvider);
    final bool ownsRepository = _repository == null;
    final bool enabled =
        _repository != null || ref.read(draftRepositoryFactoryProvider) != null;
    ref.listen<int>(editorDocumentEpochProvider, (previous, next) {
      if (previous != next) _changed();
    });
    ref.onDispose(() {
      _disposed = true;
      _cancelTimers();
      _startupTimer?.cancel();
      _queued?.completion.complete(false);
      _queued = null;
      // The application owns an injected repository. Only a factory-created
      // connection is ours, and it closes after already-running work settles.
      if (ownsRepository) {
        final Future<void> settled = Future.wait<void>([
          ?_active,
          ?_startup,
          ?_replacementDone?.future,
        ]).then((_) {});
        unawaited(
          settled
              .then((_) async {
                await _repository?.close();
              })
              .catchError((Object _) {}),
        );
      }
    });
    return DraftRecoveryState(
      status: enabled
          ? DraftRecoveryStatus.loading
          : DraftRecoveryStatus.disabled,
      hasResolvedStartup: !enabled,
    );
  }

  Future<DraftRepository> _open() async {
    if (_repository != null) return _repository!;
    final factory = ref.read(draftRepositoryFactoryProvider);
    if (factory == null) {
      throw const DraftStorageException(DraftStorageFailure.unavailable);
    }
    final Future<DraftRepository> opening = _opening ??= factory();
    try {
      return _repository = await opening;
    } catch (_) {
      if (identical(_opening, opening)) _opening = null;
      rethrow;
    }
  }

  Future<void> start() {
    if (!state.enabled) return Future<void>.value();
    if (_started) return _startup ?? Future<void>.value();
    _started = true;
    return _startup = _read();
  }

  Future<void> retry() {
    if (!state.enabled) return Future<void>.value();
    // A failed checkpoint retries the current text. Startup/volatile retry
    // reads and previews the preserved slot before any replacement decision.
    if (state.hasResolvedStartup &&
        state.status != DraftRecoveryStatus.volatile &&
        state.candidate == null &&
        _writable) {
      return saveRecoveryCopy().then((_) {});
    }
    _started = true;
    return _startup = _read();
  }

  Future<void> _read() async {
    final int operation = ++_operation;
    final int epoch = ref.read(editorDocumentEpochProvider);
    _cancelTimers();
    _cancelQueued();
    _writable = false;
    state = DraftRecoveryState(
      checkpointTime: _lastCheckpointTime,
      status: DraftRecoveryStatus.loading,
    );
    _startupTimer?.cancel();
    _startupTimer = Timer(const Duration(seconds: 10), () {
      if (_valid(operation)) {
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: DraftRecoveryStatus.failed,
          timedOut: true,
          failure: DraftStorageFailure.unavailable,
        );
      }
    });
    // Reuse a pending open/read rather than opening the database underneath it.
    final Future<DraftRead> loading = _loading ??= _loadAfterWriter();
    try {
      final DraftRead result = await loading;
      if (!_valid(operation)) return;
      _generation = result.generation;
      _lastCheckpointTime = result.snapshot?.checkpointTime;
      _decisionEpoch = ref.read(editorDocumentEpochProvider);
      if (result.snapshot != null) {
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: DraftRecoveryStatus.decision,
          candidate: result.snapshot,
        );
      } else {
        _writable = true;
        final bool changed =
            epoch != _decisionEpoch ||
            ref.read(editorDocumentProvider) != const EditorDocument.untitled();
        _lastCommittedEpoch = changed ? -1 : _decisionEpoch;
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: changed
              ? DraftRecoveryStatus.pending
              : DraftRecoveryStatus.saved,
          hasResolvedStartup: true,
        );
        if (changed) _changed();
      }
    } catch (error) {
      if (_valid(operation)) {
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: DraftRecoveryStatus.failed,
          failure: _failure(error),
        );
      }
    } finally {
      if (identical(_loading, loading)) _loading = null;
      if (_valid(operation)) _startupTimer?.cancel();
    }
  }

  Future<DraftRead> _loadAfterWriter() async {
    await _replacementDone?.future;
    await _active;
    return (await _open()).load();
  }

  bool _valid(int operation) => !_disposed && operation == _operation;

  void continueWithoutRecovery() {
    if (!state.enabled) return;
    ++_operation;
    _startupTimer?.cancel();
    _cancelTimers();
    _cancelQueued();
    _writable = false;
    state = DraftRecoveryState(
      checkpointTime: _lastCheckpointTime,
      status: DraftRecoveryStatus.volatile,
      candidate: state.candidate,
      failure: state.failure,
      hasResolvedStartup: true,
    );
  }

  bool restore() {
    final DraftSnapshot? snapshot = state.candidate;
    if (snapshot == null ||
        state.status != DraftRecoveryStatus.decision ||
        state.busy ||
        ref.read(editorDocumentEpochProvider) != _decisionEpoch) {
      return false;
    }
    _suppress = true;
    try {
      ref
          .read(editorDocumentProvider.notifier)
          .restoreDraft(name: snapshot.name, content: snapshot.content);
    } finally {
      _suppress = false;
    }
    _writable = true;
    _lastCommittedEpoch = ref.read(editorDocumentEpochProvider);
    state = DraftRecoveryState(
      checkpointTime: _lastCheckpointTime,
      status: DraftRecoveryStatus.saved,
      hasResolvedStartup: true,
    );
    return true;
  }

  Future<bool> discard() async {
    if (state.candidate == null ||
        state.busy ||
        state.status != DraftRecoveryStatus.decision ||
        ref.read(editorDocumentEpochProvider) != _decisionEpoch) {
      return false;
    }
    final DraftSnapshot candidate = state.candidate!;
    final int operation = _operation;
    final int epoch = _decisionEpoch;
    bool cleared = false;
    _replacement = true;
    _replacementDone = Completer<void>();
    _cancelTimers();
    _cancelQueued();
    state = DraftRecoveryState(
      checkpointTime: _lastCheckpointTime,
      status: DraftRecoveryStatus.decision,
      candidate: candidate,
      busy: true,
    );
    try {
      await _active;
      if (!_valid(operation) ||
          ref.read(editorDocumentEpochProvider) != epoch) {
        return false;
      }
      _generation = await (await _open()).clear(
        expectedGeneration: _generation,
      );
      cleared = true;
      _lastCheckpointTime = null;
      if (!_valid(operation) ||
          ref.read(editorDocumentEpochProvider) != epoch) {
        return false;
      }
      _adopt(const EditorDocument.untitled());
      _writable = true;
      _lastCommittedEpoch = ref.read(editorDocumentEpochProvider);
      state = DraftRecoveryState(
        checkpointTime: _lastCheckpointTime,
        status: DraftRecoveryStatus.saved,
        hasResolvedStartup: true,
      );
      return true;
    } catch (error) {
      if (_valid(operation)) {
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: DraftRecoveryStatus.decision,
          candidate: candidate,
          failure: _failure(error),
        );
      }
      _stopOnUnsafeFailure(error);
      return false;
    } finally {
      _replacement = false;
      _replacementDone?.complete();
      _replacementDone = null;
      if (_valid(operation) &&
          state.status == DraftRecoveryStatus.decision &&
          state.busy) {
        if (cleared) {
          // Deletion was confirmed for the old copy; preserve any newer live
          // edits and checkpoint them instead of installing a fresh buffer.
          _writable = true;
          state = DraftRecoveryState(
            checkpointTime: _lastCheckpointTime,
            status: DraftRecoveryStatus.pending,
            hasResolvedStartup: true,
          );
          _changed();
        } else {
          _decisionEpoch = ref.read(editorDocumentEpochProvider);
          state = DraftRecoveryState(
            checkpointTime: _lastCheckpointTime,
            status: DraftRecoveryStatus.decision,
            candidate: candidate,
          );
        }
      }
    }
  }

  void _changed() {
    if (_disposed ||
        _suppress ||
        !state.enabled ||
        !_writable ||
        state.blocksStartup ||
        _replacement) {
      return;
    }
    state = DraftRecoveryState(
      checkpointTime: _lastCheckpointTime,
      status: DraftRecoveryStatus.pending,
      hasResolvedStartup: true,
    );
    _idle?.cancel();
    _idle = Timer(const Duration(milliseconds: 500), _checkpointCurrent);
    _maximum ??= Timer(const Duration(seconds: 2), _checkpointCurrent);
  }

  void _checkpointCurrent() {
    _cancelTimers();
    if (!_disposed && _writable && !state.blocksStartup && !_replacement) {
      unawaited(
        _enqueue(
          ref.read(editorDocumentProvider),
          ref.read(editorDocumentEpochProvider),
        ),
      );
    }
  }

  /// Wait for this captured revision, independently of later edits.
  Future<bool> saveRecoveryCopy() {
    if (!state.enabled || !_writable || state.blocksStartup || _replacement) {
      return Future<bool>.value(false);
    }
    _cancelTimers();
    final int epoch = ref.read(editorDocumentEpochProvider);
    if (epoch == _lastCommittedEpoch) return Future<bool>.value(true);
    return _enqueue(ref.read(editorDocumentProvider), epoch);
  }

  /// Lifecycle pause/inactive requests the same checkpoint as the explicit UI.
  Future<bool> flush() => saveRecoveryCopy();

  Future<bool> _enqueue(EditorDocument document, int epoch) {
    if (_queued?.epoch == epoch) return _queued!.completion.future;
    _cancelQueued();
    final checkpoint = _Checkpoint(document, epoch);
    _queued = checkpoint;
    _active ??= Future<void>.microtask(_drain);
    return checkpoint.completion.future;
  }

  Future<void> _drain() async {
    try {
      while (!_disposed && _queued != null && !_replacement) {
        final _Checkpoint checkpoint = _queued!;
        _queued = null;
        if (checkpoint.epoch == ref.read(editorDocumentEpochProvider)) {
          state = DraftRecoveryState(
            checkpointTime: _lastCheckpointTime,
            status: DraftRecoveryStatus.saving,
            hasResolvedStartup: true,
          );
        }
        try {
          await _commit(checkpoint.document);
          _lastCommittedEpoch = checkpoint.epoch;
          if (!_disposed &&
              _writable &&
              !state.blocksStartup &&
              !_replacement) {
            final bool current =
                ref.read(editorDocumentEpochProvider) == checkpoint.epoch;
            state = DraftRecoveryState(
              checkpointTime: _lastCheckpointTime,
              status: current
                  ? DraftRecoveryStatus.saved
                  : DraftRecoveryStatus.pending,
              hasResolvedStartup: true,
            );
          }
          checkpoint.completion.complete(true);
        } catch (error) {
          if (!_disposed &&
              _writable &&
              !state.blocksStartup &&
              !_replacement) {
            state = DraftRecoveryState(
              checkpointTime: _lastCheckpointTime,
              status: DraftRecoveryStatus.failed,
              failure: _failure(error),
              hasResolvedStartup: true,
            );
          }
          _stopOnUnsafeFailure(error);
          checkpoint.completion.complete(false);
        }
      }
    } finally {
      _active = null;
    }
  }

  Future<void> _commit(EditorDocument document) async {
    final DraftRepository repository = await _open();
    if (document == const EditorDocument.untitled()) {
      _generation = await repository.clear(expectedGeneration: _generation);
      _lastCheckpointTime = null;
    } else {
      final int next = _generation + 1;
      final DateTime checkpointTime = DateTime.now().toUtc();
      await repository.write(
        DraftSnapshot(
          name: document.name,
          content: document.content,
          originPath: document.boardPath,
          generation: next,
          checkpointTime: checkpointTime,
        ),
        expectedGeneration: _generation,
      );
      _generation = next;
      _lastCheckpointTime = checkpointTime;
    }
  }

  /// Adopt a user-confirmed replacement only after its local checkpoint. The
  /// caller owns confirmation and supplies the epoch captured before any await.
  Future<bool> replaceDocument(
    EditorDocument replacement, {
    required int expectedEpoch,
    bool allowVolatile = false,
    bool Function()? isStillValid,
  }) async {
    final int operation = _operation;
    bool valid() =>
        _valid(operation) &&
        ref.read(editorDocumentEpochProvider) == expectedEpoch &&
        (isStillValid?.call() ?? true);
    if (!valid() || _replacement || state.blocksStartup) return false;
    if (!state.enabled || (!_writable && allowVolatile)) {
      _adopt(replacement);
      return true;
    }
    if (!_writable) return false;
    _replacement = true;
    _replacementDone = Completer<void>();
    _cancelTimers();
    _cancelQueued();
    try {
      await _active;
      if (!valid()) return false;
      await _commit(replacement);
      if (!valid()) {
        // The live newer revision remains authoritative and must not be
        // replaced by an old completion, even if a checkpoint reached disk.
        return false;
      }
      _adopt(replacement);
      _lastCommittedEpoch = ref.read(editorDocumentEpochProvider);
      state = DraftRecoveryState(
        checkpointTime: _lastCheckpointTime,
        status: DraftRecoveryStatus.saved,
        hasResolvedStartup: true,
      );
      return true;
    } catch (error) {
      if (!_disposed) {
        state = DraftRecoveryState(
          checkpointTime: _lastCheckpointTime,
          status: DraftRecoveryStatus.failed,
          failure: _failure(error),
          hasResolvedStartup: true,
        );
      }
      _stopOnUnsafeFailure(error);
      return false;
    } finally {
      _replacement = false;
      _replacementDone?.complete();
      _replacementDone = null;
      if (!_disposed &&
          _writable &&
          ref.read(editorDocumentEpochProvider) != _lastCommittedEpoch &&
          state.status != DraftRecoveryStatus.failed) {
        _changed();
      }
    }
  }

  void _adopt(EditorDocument document) {
    _suppress = true;
    try {
      ref.read(editorDocumentProvider.notifier).adoptDocument(document);
    } finally {
      _suppress = false;
    }
  }

  void _cancelQueued() {
    _queued?.completion.complete(false);
    _queued = null;
  }

  void _cancelTimers() {
    _idle?.cancel();
    _maximum?.cancel();
    _idle = null;
    _maximum = null;
  }

  void _stopOnUnsafeFailure(Object error) {
    final reason = _failure(error);
    if (reason == DraftStorageFailure.conflict ||
        reason == DraftStorageFailure.corrupt ||
        reason == DraftStorageFailure.unsupportedVersion) {
      // The high-water mark/content can no longer be trusted. Retry must read
      // and offer an explicit choice rather than reusing a stale generation.
      _writable = false;
      _cancelTimers();
      _cancelQueued();
    }
  }

  DraftStorageFailure _failure(Object error) => error is DraftStorageException
      ? error.reason
      : DraftStorageFailure.unavailable;
}
