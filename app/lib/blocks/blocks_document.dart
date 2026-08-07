// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-31 visual-workspace state and action controller (ADR-0013).
///
/// The WebView is an untrusted, replaceable renderer. It publishes versioned
/// JSON snapshots here; this pure Dart boundary validates and retains them.
/// Board actions never cross into JavaScript: Save and Run delegate to the same
/// file-backed [ProgramActions] used by the text editor.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/editor/editor.dart';

import 'blocks_companion.dart';
import 'blocks_examples.dart';

/// Version of the small WebView → Dart snapshot protocol.
const int kBlocksBridgeVersion = 1;

/// Maximum accepted UTF-8 bridge message (1 MiB).
const int kMaxBlocksBridgeMessageBytes = 1024 * 1024;

/// Maximum revision admitted on both sides of the JSON/JavaScript boundary.
///
/// Four billion workspace changes are ample for one in-process document while
/// staying far below JavaScript's 53-bit safe-integer ceiling.
const int kMaxBlocksRevision = 0xFFFFFFFF;

/// Maximum time a board action waits for the active WebView to acknowledge a
/// fresh generated-program snapshot.
const Duration kBlocksSnapshotTimeout = Duration(seconds: 5);

/// Overridable only so timeout behavior can be tested without a five-second
/// wall-clock delay.
final Provider<Duration> blocksSnapshotTimeoutProvider = Provider<Duration>(
  (Ref ref) => kBlocksSnapshotTimeout,
);

/// Feature-owned board target for generated visual programs.
const String kBlocksGeneratedPath = '/blocks.py';

/// Filename used by the explicit one-way editor hand-off.
const String kBlocksGeneratedName = 'blocks.py';

/// Platform workspace loading state.
enum BlocksStatus { loading, ready, error }

/// Result of admitting one untrusted JavaScript bridge message.
enum BlocksBridgeResult {
  ignored,
  staleSnapshot,
  snapshotAccepted,
  workspaceError,
  hostError,
  exampleCatalogRequested,
}

/// One immutable visual-workspace → Python result.
@immutable
class GeneratedProgram {
  const GeneratedProgram({
    required this.source,
    required this.workspaceJson,
    required this.revision,
  });

  /// Exact inspectable Python shown to and acted on for this revision.
  final String source;

  /// Canonical serialized Blockly JSON used to recreate the platform view.
  final String workspaceJson;

  /// Monotonic workspace revision emitted by the bridge.
  final int revision;
}

const Object _notProvided = Object();

/// Retained Blocks feature state.
@immutable
class BlocksDocument {
  const BlocksDocument({
    this.status = BlocksStatus.loading,
    this.targetPath = kBlocksGeneratedPath,
    this.program,
    this.retainedWorkspaceJson,
    this.retainedWorkspaceRevision,
    this.busy = false,
    this.error,
    this.workspaceError,
    this.workspaceReviewPending = false,
    this.loadAttempt = 0,
  }) : assert(
         (retainedWorkspaceJson == null) == (retainedWorkspaceRevision == null),
       );

  final BlocksStatus status;

  /// Board Python path owned by this visual document.
  final String targetPath;

  /// Last workspace that also produced valid, inspectable Python.
  final GeneratedProgram? program;

  /// Latest successfully serialized workspace, including an incomplete graph
  /// whose generator currently reports an error.
  ///
  /// This is intentionally separate from [program]: source is never presented
  /// as if it represented a newer invalid workspace.
  final String? retainedWorkspaceJson;
  final int? retainedWorkspaceRevision;

  final bool busy;

  /// A platform-host/bridge failure that requires recreating the WebView.
  final String? error;

  /// A generator/serialization failure inside a live workspace.
  ///
  /// This is deliberately separate from [error]: the workspace stays visible
  /// so the user can repair or remove the block that caused the failure.
  final String? workspaceError;

  /// A Python import is visible behind a native preview dialog but has not yet
  /// replaced the retained workspace. Save/Run remain disabled until commit.
  final bool workspaceReviewPending;

  /// Incremented on Retry so the lazy platform host is recreated.
  final int loadAttempt;

  bool get hasRunnableProgram =>
      status == BlocksStatus.ready &&
      !workspaceReviewPending &&
      workspaceError == null &&
      program != null &&
      retainedWorkspaceRevision == program!.revision &&
      program!.source.trim().isNotEmpty;

  BlocksDocument copyWith({
    BlocksStatus? status,
    String? targetPath,
    Object? program = _notProvided,
    Object? retainedWorkspaceJson = _notProvided,
    Object? retainedWorkspaceRevision = _notProvided,
    bool? busy,
    Object? error = _notProvided,
    Object? workspaceError = _notProvided,
    bool? workspaceReviewPending,
    int? loadAttempt,
  }) {
    return BlocksDocument(
      status: status ?? this.status,
      targetPath: targetPath ?? this.targetPath,
      program: identical(program, _notProvided)
          ? this.program
          : program as GeneratedProgram?,
      retainedWorkspaceJson: identical(retainedWorkspaceJson, _notProvided)
          ? this.retainedWorkspaceJson
          : retainedWorkspaceJson as String?,
      retainedWorkspaceRevision:
          identical(retainedWorkspaceRevision, _notProvided)
          ? this.retainedWorkspaceRevision
          : retainedWorkspaceRevision as int?,
      busy: busy ?? this.busy,
      error: identical(error, _notProvided) ? this.error : error as String?,
      workspaceError: identical(workspaceError, _notProvided)
          ? this.workspaceError
          : workspaceError as String?,
      workspaceReviewPending:
          workspaceReviewPending ?? this.workspaceReviewPending,
      loadAttempt: loadAttempt ?? this.loadAttempt,
    );
  }
}

/// An action was requested before non-empty generated source was available.
class BlocksNotReady implements Exception {
  const BlocksNotReady();

  @override
  String toString() => 'BlocksNotReady';
}

/// A second board mutation was requested while the first is in progress.
class BlocksBusy implements Exception {
  const BlocksBusy();

  @override
  String toString() => 'BlocksBusy';
}

/// No live Blockly host is available to acknowledge the current workspace.
class BlocksHostUnavailable implements Exception {
  const BlocksHostUnavailable([this.message = 'Blockly host is unavailable']);

  final String message;

  @override
  String toString() => 'BlocksHostUnavailable($message)';
}

/// The live workspace failed to generate a fresh program snapshot.
class BlocksGenerationFailed implements Exception {
  const BlocksGenerationFailed(this.message);

  final String message;

  @override
  String toString() => 'BlocksGenerationFailed($message)';
}

/// The live host did not acknowledge a requested snapshot in time.
class BlocksSnapshotTimeout implements Exception {
  const BlocksSnapshotTimeout();

  @override
  String toString() => 'BlocksSnapshotTimeout';
}

/// Opening generated source would replace a different dirty editor document.
class BlocksEditorConflict implements Exception {
  const BlocksEditorConflict(this.documentName);

  final String documentName;

  @override
  String toString() => 'BlocksEditorConflict($documentName)';
}

/// Create Copy was requested while the active workspace was not empty.
class BlocksWorkspaceNotEmpty implements Exception {
  const BlocksWorkspaceNotEmpty();

  @override
  String toString() => 'BlocksWorkspaceNotEmpty';
}

class _FreshSnapshotWaiter {
  const _FreshSnapshotWaiter({
    required this.hostId,
    required this.requestId,
    required this.afterRevision,
    required this.completer,
  });

  final int hostId;
  final int requestId;
  final int afterRevision;
  final Completer<GeneratedProgram> completer;
}

class _PendingWorkspaceLoad {
  _PendingWorkspaceLoad({
    required this.rollback,
    required this.expectedSource,
    required this.expectedWorkspace,
    required this.reviewBeforeCommit,
    required this.completer,
  });

  final BlocksDocument rollback;
  final String? expectedSource;
  final Map<String, dynamic> expectedWorkspace;
  final bool reviewBeforeCommit;
  final Completer<GeneratedProgram> completer;
  GeneratedProgram? acknowledged;
}

/// Owns validated snapshots and all native Blocks actions.
class BlocksDocumentController extends Notifier<BlocksDocument> {
  int _nextHostId = 0;
  int _nextRequestId = 0;
  int? _activeHostId;
  bool _activeHostReady = false;
  Future<void> Function(int requestId)? _requestSnapshot;
  Future<BlocksExamplePreview> Function(String workspaceJson)? _previewExample;
  _FreshSnapshotWaiter? _freshSnapshotWaiter;
  _PendingWorkspaceLoad? _pendingWorkspaceLoad;
  final Set<Completer<void>> _previewHostWaiters = <Completer<void>>{};

  @override
  BlocksDocument build() {
    ref.onDispose(() {
      _failPreviewHostWaiters(
        const BlocksHostUnavailable('Blocks document was disposed'),
      );
    });
    return const BlocksDocument();
  }

  /// Whether the current platform-host epoch has published a valid snapshot.
  bool get hasActiveReadyHost => _activeHostId != null && _activeHostReady;

  /// Waits until the production host can run a disposable scratch preview.
  ///
  /// Editor/File conversion may need to focus Blocks first so its lazily-built
  /// platform view exists. Waiting changes no workspace and performs no board
  /// I/O; host failure and timeout are typed.
  Future<void> waitForPreviewHost() async {
    if (_activeHostId != null && _activeHostReady && _previewExample != null) {
      return;
    }
    final Completer<void> completer = Completer<void>();
    _previewHostWaiters.add(completer);
    try {
      await completer.future.timeout(
        const Duration(seconds: 15),
        onTimeout: () => throw const BlocksSnapshotTimeout(),
      );
    } finally {
      _previewHostWaiters.remove(completer);
    }
  }

  /// Invalidates a host mounted only to serve a disposable conversion preview
  /// and restores the exact document captured before that mount.
  ///
  /// The host's initial snapshot is legitimate renderer state, but it must not
  /// become a user-visible document mutation when Preview is cancelled or
  /// fails. Invalidating the epoch first also makes late platform messages and
  /// the widget's eventual [endHost] harmless.
  void restoreAfterTransientPreviewHost(BlocksDocument snapshot) {
    if (_pendingWorkspaceLoad != null) throw const BlocksBusy();
    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failPreviewHostWaiters(
      const BlocksHostUnavailable('Transient Blockly preview was dismissed'),
    );
    _failFreshSnapshot(
      const BlocksHostUnavailable('Transient Blockly preview was dismissed'),
    );
    state = snapshot;
  }

  /// Registers a new renderer generation and returns its opaque host epoch.
  ///
  /// This invalidates older messages synchronously. The widget calls
  /// [markHostLoading] after its current build frame, because Riverpod forbids a
  /// provider mutation from a descendant's `initState`.
  int beginHost({
    required Future<void> Function(int requestId) requestSnapshot,
    Future<BlocksExamplePreview> Function(String workspaceJson)? previewExample,
  }) {
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly host was recreated'),
    );
    final int hostId = ++_nextHostId;
    _nextRequestId = 0;
    _activeHostId = hostId;
    _activeHostReady = false;
    _requestSnapshot = requestSnapshot;
    _previewExample = previewExample;
    return hostId;
  }

  /// Makes retained source non-actionable until [hostId] publishes a snapshot.
  void markHostLoading(int hostId) {
    if (_activeHostId != hostId) return;
    _activeHostReady = false;
    state = state.copyWith(
      status: BlocksStatus.loading,
      error: null,
      workspaceError: null,
    );
  }

  /// Ends [hostId] if it is still current and invalidates delayed callbacks.
  void endHost(int hostId) {
    if (_activeHostId != hostId) return;
    if (_pendingWorkspaceLoad != null) {
      _rollbackWorkspaceLoad(
        const BlocksHostUnavailable(
          'Blockly candidate host was disposed before loading completed',
        ),
      );
      return;
    }
    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failPreviewHostWaiters(
      const BlocksHostUnavailable('Blockly host was disposed'),
    );
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly host was disposed'),
    );
  }

  /// Validates and applies one message from the JavaScript channel.
  ///
  /// Nothing malformed escapes as an uncaught exception; it becomes a
  /// contained feature error and the last valid snapshot remains available.
  BlocksBridgeResult receiveBridgeMessage(String message, {int? hostId}) {
    if (!_isCurrentHost(hostId)) return BlocksBridgeResult.ignored;
    try {
      if (utf8.encode(message).length > kMaxBlocksBridgeMessageBytes) {
        throw const FormatException('bridge message exceeds 1 MiB');
      }
      final Object? decoded = jsonDecode(message);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('bridge message must be a JSON object');
      }
      if (decoded['version'] != kBlocksBridgeVersion) {
        throw const FormatException('unsupported bridge version');
      }

      switch (decoded['type']) {
        case 'snapshot':
          return _acceptSnapshot(decoded, hostId: hostId);
        case 'openExamples':
          final Object? exampleId = decoded['exampleId'];
          if (exampleId != null &&
              (exampleId is! String ||
                  !kBlocksExampleIds.contains(exampleId))) {
            return BlocksBridgeResult.ignored;
          }
          final BlocksExampleCatalogRequest current = ref.read(
            blocksExampleCatalogRequestProvider,
          );
          ref
              .read(blocksExampleCatalogRequestProvider.notifier)
              .state = BlocksExampleCatalogRequest(
            serial: current.serial + 1,
            initialExampleId: exampleId as String?,
          );
          return BlocksBridgeResult.exampleCatalogRequested;
        case 'error':
          final Object? value = decoded['message'];
          if (value is! String || value.trim().isEmpty) {
            throw const FormatException('bridge error has no message');
          }
          if (_pendingWorkspaceLoad != null) {
            _rollbackWorkspaceLoad(BlocksGenerationFailed(value));
            return BlocksBridgeResult.hostError;
          }
          final int? requestId = _optionalRequestId(decoded);
          final ({String json, int revision})? retainedWorkspace =
              _optionalRetainedWorkspace(decoded);
          if (retainedWorkspace != null) {
            final int? currentRevision = state.retainedWorkspaceRevision;
            final bool stale =
                currentRevision != null &&
                retainedWorkspace.revision <= currentRevision;
            if (!stale) {
              if (hostId != null) _activeHostReady = true;
              state = state.copyWith(
                status: BlocksStatus.ready,
                retainedWorkspaceJson: retainedWorkspace.json,
                retainedWorkspaceRevision: retainedWorkspace.revision,
                error: null,
                workspaceError: value,
              );
            }
            _failMatchingFreshSnapshot(
              requestId,
              BlocksGenerationFailed(value),
            );
            return stale
                ? BlocksBridgeResult.staleSnapshot
                : BlocksBridgeResult.workspaceError;
          }
          final bool rendererReady = hostId == null
              ? state.status == BlocksStatus.ready
              : _activeHostReady;
          if (!rendererReady) {
            if (hostId != null) _activeHostReady = false;
            state = state.copyWith(
              status: BlocksStatus.error,
              error: value,
              workspaceError: null,
            );
            _failFreshSnapshot(BlocksHostUnavailable(value));
            _failPreviewHostWaiters(BlocksHostUnavailable(value));
            return BlocksBridgeResult.hostError;
          }
          state = state.copyWith(
            status: BlocksStatus.ready,
            error: null,
            workspaceError: value,
          );
          _failMatchingFreshSnapshot(requestId, BlocksGenerationFailed(value));
          return BlocksBridgeResult.workspaceError;
        default:
          throw const FormatException('unknown bridge message type');
      }
    } catch (error) {
      if (_pendingWorkspaceLoad != null) {
        _rollbackWorkspaceLoad(BlocksHostUnavailable(error.toString()));
        return BlocksBridgeResult.hostError;
      }
      if (hostId != null) _activeHostReady = false;
      state = state.copyWith(
        status: BlocksStatus.error,
        error: error.toString(),
        workspaceError: null,
      );
      _failFreshSnapshot(BlocksHostUnavailable(error.toString()));
      _failPreviewHostWaiters(BlocksHostUnavailable(error.toString()));
      return BlocksBridgeResult.hostError;
    }
  }

  bool _isCurrentHost(int? hostId) => hostId == null || hostId == _activeHostId;

  int? _optionalRequestId(Map<String, dynamic> message) {
    if (!message.containsKey('requestId')) return null;
    final Object? value = message['requestId'];
    if (value is! int || value < 1 || value > kMaxBlocksRevision) {
      throw const FormatException(
        'bridge request ID is outside the safe range',
      );
    }
    return value;
  }

  ({String json, int revision})? _optionalRetainedWorkspace(
    Map<String, dynamic> message,
  ) {
    final bool hasWorkspace = message.containsKey('workspace');
    final bool hasRevision = message.containsKey('revision');
    if (!hasWorkspace && !hasRevision) return null;
    if (!hasWorkspace || !hasRevision) {
      throw const FormatException(
        'bridge workspace error must include workspace and revision',
      );
    }

    final Object? workspace = message['workspace'];
    final Object? revision = message['revision'];
    if (workspace is! Map<String, dynamic>) {
      throw const FormatException('bridge error workspace must be an object');
    }
    if (revision is! int || revision < 0 || revision > kMaxBlocksRevision) {
      throw const FormatException(
        'bridge error revision is outside the safe range',
      );
    }
    return (json: jsonEncode(workspace), revision: revision);
  }

  int _allocateRequestId() {
    if (_nextRequestId >= kMaxBlocksRevision) _nextRequestId = 0;
    return ++_nextRequestId;
  }

  BlocksBridgeResult _acceptSnapshot(
    Map<String, dynamic> message, {
    required int? hostId,
  }) {
    final Object? revisionValue = message['revision'];
    final Object? sourceValue = message['source'];
    final Object? workspaceValue = message['workspace'];
    final int? requestId = _optionalRequestId(message);
    if (revisionValue is! int ||
        revisionValue < 0 ||
        revisionValue > kMaxBlocksRevision) {
      throw const FormatException(
        'snapshot revision is outside the safe range',
      );
    }
    if (sourceValue is! String) {
      throw const FormatException('snapshot source must be a string');
    }
    if (workspaceValue is! Map<String, dynamic>) {
      throw const FormatException('snapshot workspace must be an object');
    }

    // Blockly generator output is already syntactically controlled. Preserve
    // it byte-for-byte: punctuation inside a text/comment field is user data,
    // and exact sidecar reopen depends on raw production-source equality.
    final String source = sourceValue;
    final GeneratedProgram candidate = GeneratedProgram(
      source: source,
      workspaceJson: jsonEncode(workspaceValue),
      revision: revisionValue,
    );
    final int? retainedRevision = state.retainedWorkspaceRevision;
    final bool stale =
        retainedRevision != null && revisionValue <= retainedRevision;
    if (!stale) {
      final _PendingWorkspaceLoad? pending = _pendingWorkspaceLoad;
      if (pending != null &&
          ((pending.expectedSource != null &&
                  source != pending.expectedSource) ||
              !_jsonValuesEqual(workspaceValue, pending.expectedWorkspace))) {
        _rollbackWorkspaceLoad(
          const BlocksGenerationFailed(
            'Loaded workspace did not match its validated preview',
          ),
        );
        return BlocksBridgeResult.hostError;
      }
      if (hostId != null) _activeHostReady = true;
      _completePreviewHostWaitersIfReady();
      state = state.copyWith(
        status: BlocksStatus.ready,
        program: candidate,
        retainedWorkspaceJson: candidate.workspaceJson,
        retainedWorkspaceRevision: candidate.revision,
        error: null,
        workspaceError: null,
      );
      _acknowledgeWorkspaceLoad(candidate);
    }

    final _FreshSnapshotWaiter? waiter = _freshSnapshotWaiter;
    if (waiter != null &&
        waiter.hostId == _activeHostId &&
        waiter.requestId == requestId &&
        revisionValue > waiter.afterRevision &&
        !waiter.completer.isCompleted) {
      waiter.completer.complete(candidate);
    }
    return stale
        ? BlocksBridgeResult.staleSnapshot
        : BlocksBridgeResult.snapshotAccepted;
  }

  /// Contains a main-frame platform-view failure inside the Blocks surface.
  void reportHostError(String message, {int? hostId}) {
    if (!_isCurrentHost(hostId)) return;
    if (_pendingWorkspaceLoad != null) {
      _rollbackWorkspaceLoad(BlocksHostUnavailable(message));
      return;
    }
    if (hostId != null) _activeHostReady = false;
    state = state.copyWith(
      status: BlocksStatus.error,
      error: message,
      workspaceError: null,
    );
    _failFreshSnapshot(BlocksHostUnavailable(message));
    _failPreviewHostWaiters(BlocksHostUnavailable(message));
  }

  /// Recreates the lazy WebView while retaining its last workspace snapshot.
  void retry() {
    if (_pendingWorkspaceLoad != null) {
      _rollbackWorkspaceLoad(
        const BlocksHostUnavailable('Blockly candidate retry requested'),
      );
      return;
    }
    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failPreviewHostWaiters(
      const BlocksHostUnavailable('Blockly host retry requested'),
    );
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly host retry requested'),
    );
    state = state.copyWith(
      status: BlocksStatus.loading,
      error: null,
      workspaceError: null,
      loadAttempt: state.loadAttempt + 1,
    );
  }

  /// Discards an unrecoverable retained workspace and creates an empty host.
  void startFresh() {
    if (state.busy || _pendingWorkspaceLoad != null) throw const BlocksBusy();
    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failPreviewHostWaiters(
      const BlocksHostUnavailable('Blockly workspace was discarded'),
    );
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly workspace was discarded'),
    );
    state = state.copyWith(
      status: BlocksStatus.loading,
      program: null,
      retainedWorkspaceJson: null,
      retainedWorkspaceRevision: null,
      error: null,
      workspaceError: null,
      workspaceReviewPending: false,
      loadAttempt: state.loadAttempt + 1,
    );
  }

  GeneratedProgram _programForAction() {
    final GeneratedProgram? program = state.program;
    if (state.status != BlocksStatus.ready ||
        state.workspaceError != null ||
        (_activeHostId != null && !_activeHostReady) ||
        program == null ||
        state.retainedWorkspaceRevision != program.revision ||
        program.source.trim().isEmpty) {
      throw const BlocksNotReady();
    }
    return program;
  }

  /// Generates and canonicalizes an example in a scratch Blockly workspace.
  ///
  /// The live workspace, its revision, and board state are untouched.
  Future<BlocksExamplePreview> previewExample(String workspaceJson) async {
    final Future<BlocksExamplePreview> Function(String workspaceJson)? preview =
        _previewExample;
    if (_activeHostId == null || !_activeHostReady || preview == null) {
      throw const BlocksHostUnavailable(
        'Blockly example preview is unavailable',
      );
    }
    final BlocksExamplePreview result = await preview(workspaceJson);
    if (result.source.trim().isEmpty) {
      throw const BlocksGenerationFailed('The example generated no Python');
    }
    return result;
  }

  /// Loads a canonical, already-generated example as an editable workspace.
  ///
  /// [replace] is deliberately required for every non-empty workspace.
  Future<void> loadExampleWorkspace(
    BlocksExamplePreview example, {
    required bool replace,
  }) async {
    await _stageWorkspace(
      workspaceJson: example.workspaceJson,
      expectedSource: example.source,
      targetPath: state.targetPath,
      replace: replace,
      reviewBeforeCommit: false,
    );
  }

  /// Stages an imported Python workspace in the real Blockly host for review.
  ///
  /// The candidate is visible but non-actionable until [commitWorkspaceReview].
  /// Cancel, host failure, source mismatch, or workspace mismatch recreates the
  /// exact prior document. This method itself performs no board I/O.
  Future<GeneratedProgram> stageWorkspaceReview({
    required String workspaceJson,
    required String targetPath,
    required bool replace,
    String? expectedSource,
  }) => _stageWorkspace(
    workspaceJson: workspaceJson,
    expectedSource: expectedSource,
    targetPath: targetPath,
    replace: replace,
    reviewBeforeCommit: true,
  );

  Future<GeneratedProgram> _stageWorkspace({
    required String workspaceJson,
    required String? expectedSource,
    required String targetPath,
    required bool replace,
    required bool reviewBeforeCommit,
  }) {
    if (state.busy || _pendingWorkspaceLoad != null) throw const BlocksBusy();
    final bool empty = isSemanticallyEmptyBlocksWorkspace(
      state.retainedWorkspaceJson,
    );
    if (!empty && !replace) throw const BlocksWorkspaceNotEmpty();
    if (expectedSource != null && expectedSource.trim().isEmpty) {
      throw const BlocksGenerationFailed('The candidate generated no Python');
    }
    try {
      blocksCompanionPathFor(targetPath);
    } on ArgumentError {
      throw const BlocksGenerationFailed(
        'The candidate board path is not absolute',
      );
    }

    final Object? decoded;
    try {
      decoded = jsonDecode(workspaceJson);
    } on FormatException catch (error) {
      throw BlocksExampleFormatException(error.message);
    }
    if (decoded is! Map<String, dynamic> ||
        decoded['blocks'] is! Map<String, dynamic>) {
      throw const BlocksExampleFormatException(
        'generated example workspace is malformed',
      );
    }
    final String canonicalWorkspace = jsonEncode(decoded);
    final int baseRevision = state.retainedWorkspaceRevision ?? 0;
    final Completer<GeneratedProgram> completer = Completer<GeneratedProgram>();
    _pendingWorkspaceLoad = _PendingWorkspaceLoad(
      rollback: state,
      expectedSource: expectedSource,
      expectedWorkspace: decoded,
      reviewBeforeCommit: reviewBeforeCommit,
      completer: completer,
    );

    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly candidate workspace is loading'),
    );
    state = state.copyWith(
      status: BlocksStatus.loading,
      targetPath: targetPath,
      program: null,
      retainedWorkspaceJson: canonicalWorkspace,
      retainedWorkspaceRevision: baseRevision,
      error: null,
      workspaceError: null,
      workspaceReviewPending: reviewBeforeCommit,
      loadAttempt: state.loadAttempt + 1,
    );
    return completer.future;
  }

  void _acknowledgeWorkspaceLoad(GeneratedProgram program) {
    final _PendingWorkspaceLoad? pending = _pendingWorkspaceLoad;
    if (pending == null) return;
    pending.acknowledged = program;
    if (!pending.completer.isCompleted) pending.completer.complete(program);
    if (!pending.reviewBeforeCommit) {
      _pendingWorkspaceLoad = null;
      state = state.copyWith(workspaceReviewPending: false);
    }
  }

  /// Commits the exact candidate acknowledged by the active production host.
  void commitWorkspaceReview() {
    final _PendingWorkspaceLoad? pending = _pendingWorkspaceLoad;
    if (pending == null ||
        !pending.reviewBeforeCommit ||
        pending.acknowledged == null) {
      throw const BlocksNotReady();
    }
    _pendingWorkspaceLoad = null;
    state = state.copyWith(workspaceReviewPending: false);
  }

  /// Cancels a provisional import and restores the exact prior workspace.
  void cancelWorkspaceReview() {
    final _PendingWorkspaceLoad? pending = _pendingWorkspaceLoad;
    if (pending == null || !pending.reviewBeforeCommit) return;
    _rollbackWorkspaceLoad(
      const BlocksHostUnavailable('Blockly candidate review was cancelled'),
    );
  }

  void _rollbackWorkspaceLoad(Object error) {
    final _PendingWorkspaceLoad? pending = _pendingWorkspaceLoad;
    if (pending == null) return;
    _pendingWorkspaceLoad = null;
    _activeHostId = null;
    _activeHostReady = false;
    _requestSnapshot = null;
    _previewExample = null;
    _failFreshSnapshot(
      const BlocksHostUnavailable('Blockly candidate load rolled back'),
    );
    state = pending.rollback.copyWith(
      status: BlocksStatus.loading,
      error: null,
      workspaceReviewPending: false,
      loadAttempt: state.loadAttempt + 1,
    );
    if (!pending.completer.isCompleted) {
      pending.completer.completeError(error, StackTrace.current);
    }
  }

  void _beginAction() {
    if (state.busy || _pendingWorkspaceLoad != null) throw const BlocksBusy();
    _programForAction();
    state = state.copyWith(busy: true);
  }

  void _endAction() {
    state = state.copyWith(busy: false);
  }

  Future<GeneratedProgram> _freshProgramForAction() async {
    final GeneratedProgram current = _programForAction();
    final int? hostId = _activeHostId;
    final Future<void> Function(int requestId)? requestSnapshot =
        _requestSnapshot;
    if (hostId == null || requestSnapshot == null) {
      throw const BlocksHostUnavailable();
    }

    final int requestId = _allocateRequestId();
    final Completer<GeneratedProgram> completer = Completer<GeneratedProgram>();
    final _FreshSnapshotWaiter waiter = _FreshSnapshotWaiter(
      hostId: hostId,
      requestId: requestId,
      afterRevision: current.revision,
      completer: completer,
    );
    _freshSnapshotWaiter = waiter;
    final Completer<void> requestCompletion = Completer<void>();
    final Future<List<Object?>> exchange = Future.wait<Object?>(
      <Future<Object?>>[requestCompletion.future, completer.future],
      eagerError: true,
    );
    try {
      unawaited(
        Future<void>.sync(() => requestSnapshot(requestId)).then<void>(
          (_) {
            if (!requestCompletion.isCompleted) requestCompletion.complete();
          },
          onError: (Object error, StackTrace stackTrace) {
            if (!requestCompletion.isCompleted) {
              requestCompletion.completeError(error, stackTrace);
            }
          },
        ),
      );
      final List<Object?> values = await exchange.timeout(
        ref.read(blocksSnapshotTimeoutProvider),
        onTimeout: () => throw const BlocksSnapshotTimeout(),
      );
      final GeneratedProgram fresh = values[1]! as GeneratedProgram;
      if (fresh.source.trim().isEmpty) {
        throw const BlocksNotReady();
      }
      return fresh;
    } finally {
      if (identical(_freshSnapshotWaiter, waiter)) {
        _freshSnapshotWaiter = null;
      }
    }
  }

  void _failFreshSnapshot(Object error) {
    final _FreshSnapshotWaiter? waiter = _freshSnapshotWaiter;
    if (waiter == null || waiter.completer.isCompleted) return;
    waiter.completer.completeError(error);
  }

  void _failMatchingFreshSnapshot(int? requestId, Object error) {
    final _FreshSnapshotWaiter? waiter = _freshSnapshotWaiter;
    if (requestId == null ||
        waiter == null ||
        waiter.requestId != requestId ||
        waiter.completer.isCompleted) {
      return;
    }
    waiter.completer.completeError(error);
  }

  void _completePreviewHostWaitersIfReady() {
    if (_activeHostId == null || !_activeHostReady || _previewExample == null) {
      return;
    }
    for (final Completer<void> waiter in List<Completer<void>>.of(
      _previewHostWaiters,
    )) {
      if (!waiter.isCompleted) waiter.complete();
    }
  }

  void _failPreviewHostWaiters(Object error) {
    for (final Completer<void> waiter in List<Completer<void>>.of(
      _previewHostWaiters,
    )) {
      if (!waiter.isCompleted) waiter.completeError(error);
    }
  }

  /// Requests and uploads the exact current workspace revision.
  Future<String> save() async {
    _beginAction();
    try {
      final GeneratedProgram program = await _freshProgramForAction();
      final String targetPath = state.targetPath;
      final BlocksCompanion companion = BlocksCompanion.create(
        pythonPath: targetPath,
        pythonSource: program.source,
        workspaceJson: program.workspaceJson,
      );
      return await ref
          .read(programActionsProvider)
          .saveSourceBundle(
            path: targetPath,
            source: program.source,
            companionPath: blocksCompanionPathFor(targetPath),
            companionJson: companion.encode(),
          );
    } finally {
      _endAction();
    }
  }

  /// Requests and uploads the current revision, then runs its verified file.
  Future<void> run() async {
    _beginAction();
    try {
      final GeneratedProgram program = await _freshProgramForAction();
      final String targetPath = state.targetPath;
      final BlocksCompanion companion = BlocksCompanion.create(
        pythonPath: targetPath,
        pythonSource: program.source,
        workspaceJson: program.workspaceJson,
      );
      await ref
          .read(programActionsProvider)
          .runSourceBundle(
            path: targetPath,
            source: program.source,
            companionPath: blocksCompanionPathFor(targetPath),
            companionJson: companion.encode(),
          );
    } finally {
      _endAction();
    }
  }

  /// Requests and returns the exact current source for native inspection.
  Future<String> previewSource() async {
    _beginAction();
    try {
      return (await _freshProgramForAction()).source;
    } finally {
      _endAction();
    }
  }

  /// Copies a freshly acknowledged revision into an independent editor document.
  ///
  /// Callers must explicitly resolve a dirty-buffer conflict.
  Future<void> openInEditor({bool replaceDirty = false}) async {
    _beginAction();
    try {
      final GeneratedProgram program = await _freshProgramForAction();
      final EditorDocument editor = ref.read(editorDocumentProvider);
      final String generatedName = state.targetPath.substring(
        state.targetPath.lastIndexOf('/') + 1,
      );
      final bool sameGeneratedDocument =
          editor.name == generatedName && editor.content == program.source;
      if (editor.dirty && !sameGeneratedDocument && !replaceDirty) {
        throw BlocksEditorConflict(editor.name);
      }
      ref
          .read(editorDocumentProvider.notifier)
          .openGenerated(name: generatedName, content: program.source);
    } finally {
      _endAction();
    }
  }
}

bool _jsonValuesEqual(Object? left, Object? right) {
  if (identical(left, right)) return true;
  if (left is num && right is num) return left == right;
  if (left is List<dynamic> && right is List<dynamic>) {
    if (left.length != right.length) return false;
    for (int index = 0; index < left.length; index += 1) {
      if (!_jsonValuesEqual(left[index], right[index])) return false;
    }
    return true;
  }
  if (left is Map<String, dynamic> && right is Map<String, dynamic>) {
    if (left.length != right.length) return false;
    for (final MapEntry<String, dynamic> entry in left.entries) {
      if (!right.containsKey(entry.key) ||
          !_jsonValuesEqual(entry.value, right[entry.key])) {
        return false;
      }
    }
    return true;
  }
  return left == right;
}

/// In-process source of truth for the visual workspace and generated source.
final NotifierProvider<BlocksDocumentController, BlocksDocument>
blocksDocumentProvider =
    NotifierProvider<BlocksDocumentController, BlocksDocument>(
      BlocksDocumentController.new,
    );
