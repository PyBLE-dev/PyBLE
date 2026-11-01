// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:collection';
import 'dart:typed_data';

import 'byte_transport.dart';
import 'fragment.dart';
import 'frame.dart';
import 'pble_constants.dart';
import 'pble_exception.dart';

/// The PBLE/1 request/response + event core (protocol.md §3.1/§3.2).
///
/// Runs over a [ByteTransport]: it fragments outbound frames to `mtu - 4`,
/// reassembles inbound packets, verifies each frame's CRC (a CRC-failed frame
/// is DROPPED, never surfaced — FR-PBLE-3), correlates each CMD only to the RSP
/// with its exact opcode and ID, and routes EVT frames (ID = 0) onto [events].
/// One bounded FIFO owns complete outbound frames; response waits remain
/// concurrent after their frame's writes finish.
class PbleEngine {
  PbleEngine(this._transport) {
    _inboundSub = _transport.inbound.listen(_onPacket);
    _transport.connected.addListener(_onConnectionChanged);
  }

  final ByteTransport _transport;
  late final StreamSubscription<Uint8List> _inboundSub;

  PbleReassembler _reassembler = PbleReassembler();
  final Map<int, _PendingRequest> _pending = <int, _PendingRequest>{};
  final StreamController<PbleFrame> _events =
      StreamController<PbleFrame>.broadcast(sync: true);
  final ListQueue<_ReceivedFrame> _received = ListQueue<_ReceivedFrame>();
  bool _dispatchingReceived = false;

  int _idCounter = 0;
  bool _disposed = false;
  int _linkGeneration = 0;
  static const int _maxOutgoingFrames = 255;
  final ListQueue<_OutgoingFrame> _outgoing = ListQueue<_OutgoingFrame>();
  _OutgoingFrame? _activeOutgoing;
  bool _writerRunning = false;

  /// Allocates the next request ID (1–255, never `0`), skipping any ID that is
  /// currently in flight (protocol.md §3.1). Rolls over after 255.
  int nextId() {
    for (int tries = 0; tries < 255; tries++) {
      _idCounter = _idCounter % 255 + 1; // 1..255, wrapping
      if (!_pending.containsKey(_idCounter)) return _idCounter;
    }
    throw StateError('no free PBLE/1 request id (all 255 in flight)');
  }

  /// EVT frames (ID = 0), routed as they arrive. Broadcast: listen per opcode.
  Stream<PbleFrame> get events => _events.stream;

  /// Sends [cmd] and completes with the RSP carrying its exact opcode and ID.
  ///
  /// Throws [PbleTimeoutException] if no RSP arrives within [timeout]. The
  /// caller owns [cmd].id (typically from [nextId]).
  /// [onResponseAccepted] runs once at the exact in-deadline response receive
  /// cut, before later EVT dispatch, even while the final write is pending.
  /// Validation errors fail this request without escaping the receive handler.
  Future<PbleFrame> request(
    PbleFrame cmd, {
    Duration timeout = const Duration(seconds: 5),
    void Function(PbleFrame)? onResponseAccepted,
  }) async {
    if (_disposed) {
      throw StateError('PbleEngine used after dispose()');
    }
    final _PendingRequest pending = _PendingRequest(
      cmd.opcode,
      timeout,
      onResponseAccepted,
    );
    _pending[cmd.id] = pending;
    // Disposal can reject this completion while an acknowledged write is
    // still pending. Observe errors now without replacing the original future
    // that the request later awaits (including its exact response/error).
    unawaited(
      pending.completer.future.then<void>(
        (_) {},
        onError: (Object _, StackTrace _) {},
      ),
    );
    try {
      await _queueFrame(cmd, acknowledged: true, request: pending);
      if (pending.completer.isCompleted) {
        return await pending.completer.future;
      }
      return await pending.completer.future.timeout(
        pending.remaining,
        onTimeout: () => throw const _RequestDeadlineExpired(),
      );
    } on _RequestDeadlineExpired {
      // An exact response can arrive while the final acknowledged write is
      // still pending. Its recorded on-time completion is authoritative even
      // if that write's residual deadline expires afterward.
      if (pending.completer.isCompleted) {
        return await pending.completer.future;
      }
      throw const PbleTimeoutException('no RSP within timeout');
    } on _FrameRetired catch (retired) {
      if (pending.completer.isCompleted) {
        return await pending.completer.future;
      }
      throw retired.reason;
    } finally {
      if (identical(_pending[cmd.id], pending)) {
        _pending.remove(cmd.id);
      }
    }
  }

  /// Fragments and sends [cmd] WITHOUT registering a pending request.
  ///
  /// For the fire-and-forget CMDs that carry no RSP — `CONSOLE_INPUT 0x31` and
  /// `FILE_PUT_DATA 0x16` — and for `SOFT_REBOOT 0x22`, which is fire-then-
  /// expect-disconnect (the board reset may preempt any RSP). The caller MUST
  /// NOT await a reply; correlation-by-ID does not apply.
  Future<void> fire(PbleFrame cmd) async {
    if (_disposed) {
      throw StateError('PbleEngine used after dispose()');
    }
    try {
      await _queueFrame(cmd, acknowledged: false);
    } on _FrameRetired catch (retired) {
      throw retired.reason;
    }
  }

  Future<void> _queueFrame(
    PbleFrame command, {
    required bool acknowledged,
    _PendingRequest? request,
  }) {
    if (!_transport.connected.value) {
      throw const BleLinkException('link disconnected');
    }
    if (_outgoing.length + (_activeOutgoing == null ? 0 : 1) >=
        _maxOutgoingFrames) {
      throw const PbleTransportBusyException('outbound frame queue full');
    }
    final _OutgoingFrame frame = _OutgoingFrame(
      encodeFrame(command),
      acknowledged,
      _linkGeneration,
      request,
    );
    if (request != null) {
      frame.deadline = Timer(request.remaining, () {
        // Remove expired waiting frames immediately. An active physical write
        // retains ownership until it settles, even though its caller can finish.
        _outgoing.remove(frame);
        frame.fail(const _RequestDeadlineExpired());
      });
    }
    _outgoing.add(frame);
    if (!_writerRunning) {
      _writerRunning = true;
      unawaited(_drainOutgoing());
    }
    return frame.done.future;
  }

  Future<void> _drainOutgoing() async {
    try {
      while (_outgoing.isNotEmpty) {
        final _OutgoingFrame frame = _outgoing.removeFirst();
        _activeOutgoing = frame;
        try {
          final List<Uint8List> packets = PbleFragmenter(
            mtu: _transport.mtu,
          ).fragment(frame.message);
          for (final Uint8List packet in packets) {
            if (frame.done.isCompleted) break;
            if (frame.request?.expired ?? false) {
              throw const _RequestDeadlineExpired();
            }
            if (_disposed || frame.generation != _linkGeneration) {
              frame.fail(
                const _FrameRetired(PbleTimeoutException('engine retired')),
              );
              break;
            }
            // Do not race this Future against the caller deadline: an SDK
            // write can still be in flight after timeout/disconnect/dispose.
            // The same physical owner waits for it, then checks cancellation
            // before any continuation or successor frame is submitted.
            await _transport.send(packet, acknowledged: frame.acknowledged);
          }
          frame.succeed();
        } catch (error, stack) {
          frame.fail(error, stack);
        } finally {
          frame.deadline?.cancel();
          _activeOutgoing = null;
        }
      }
    } finally {
      _writerRunning = false;
    }
  }

  void _onConnectionChanged() {
    if (!_disposed && !_transport.connected.value) {
      _retireFrames(const BleLinkException('link disconnected'));
    }
  }

  void _retireFrames(PbleException reason) {
    _linkGeneration++;
    _reassembler = PbleReassembler();
    _received.clear();
    final _FrameRetired retired = _FrameRetired(reason);
    _activeOutgoing?.deadline?.cancel();
    _activeOutgoing?.fail(retired);
    for (final _OutgoingFrame frame in _outgoing) {
      frame.deadline?.cancel();
      frame.fail(retired);
    }
    _outgoing.clear();
    for (final _PendingRequest pending in _pending.values) {
      if (!pending.completer.isCompleted) {
        pending.completer.completeError(reason);
      }
    }
    _pending.clear();
  }

  void _onPacket(Uint8List packet) {
    if (_disposed || !_transport.connected.value) return;
    final Uint8List? message = _reassembler.offer(packet);
    if (message == null) return;

    final PbleFrame frame;
    try {
      frame = decodeFrame(message);
    } on PbleException {
      // CRC-failed / malformed reassembled frame is DROPPED (FR-PBLE-3):
      // never delivered upward as a response or event payload.
      return;
    }

    final _PendingRequest? candidate = _pending[frame.id];
    // Capture response eligibility when the decoded frame arrives, before a
    // reentrant listener can delay dispatch beyond this same absolute budget.
    final _PendingRequest? response =
        candidate != null &&
            frame.type == Pble.typeRsp &&
            frame.opcode == candidate.opcode &&
            !candidate.completer.isCompleted &&
            !candidate.expired
        ? candidate
        : null;
    _received.add(_ReceivedFrame(frame, response));
    if (_dispatchingReceived) return;
    _dispatchingReceived = true;
    try {
      // An EVT listener may submit a command to a synchronous loopback pipe.
      // Queue that nested receive until this dispatch returns, preserving wire
      // order without reentering a synchronous broadcast controller's add().
      while (!_disposed && _received.isNotEmpty) {
        _dispatchFrame(_received.removeFirst());
      }
    } finally {
      _dispatchingReceived = false;
    }
  }

  void _dispatchFrame(_ReceivedFrame received) {
    final PbleFrame frame = received.frame;
    // EVT (ID = 0) routes onto the event stream, keyed by opcode downstream.
    if (frame.type == Pble.typeEvt || frame.id == Pble.evtId) {
      if (!_events.isClosed) _events.add(frame);
      return;
    }

    // Otherwise complete only the exact {TYPE=RSP, OPCODE, ID} request.
    final _PendingRequest? pending = received.response;
    if (pending != null &&
        identical(_pending[frame.id], pending) &&
        !pending.completer.isCompleted) {
      try {
        pending.onResponseAccepted?.call(frame);
        // A callback can synchronously retire the engine/link. Its retirement
        // already completed this request, so never complete it a second time.
        if (!pending.completer.isCompleted) pending.completer.complete(frame);
      } catch (error, stack) {
        if (!pending.completer.isCompleted) {
          pending.completer.completeError(error, stack);
        }
      }
    }
  }

  /// Cancels the inbound subscription, fails any in-flight requests, and closes
  /// the event stream. The engine must not be reused after this.
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _transport.connected.removeListener(_onConnectionChanged);
    _retireFrames(const PbleTimeoutException('engine disposed'));
    Object? cancelError;
    StackTrace? cancelStack;
    try {
      await _inboundSub.cancel();
    } catch (error, stack) {
      cancelError = error;
      cancelStack = stack;
    }
    await _events.close();
    if (cancelError != null) {
      Error.throwWithStackTrace(cancelError, cancelStack!);
    }
  }
}

final class _ReceivedFrame {
  _ReceivedFrame(this.frame, this.response);
  final PbleFrame frame;
  final _PendingRequest? response;
}

final class _OutgoingFrame {
  _OutgoingFrame(
    this.message,
    this.acknowledged,
    this.generation,
    this.request,
  );
  final Uint8List message;
  final bool acknowledged;
  final int generation;
  final _PendingRequest? request;
  final Completer<void> done = Completer<void>();
  Timer? deadline;

  void succeed() {
    if (!done.isCompleted) done.complete();
  }

  void fail(Object error, [StackTrace? stack]) {
    if (!done.isCompleted) done.completeError(error, stack);
  }
}

final class _FrameRetired implements Exception {
  const _FrameRetired(this.reason);
  final PbleException reason;
}

/// One monotonic deadline shared by every acknowledged write and the RSP wait.
final class _PendingRequest {
  _PendingRequest(this.opcode, this.timeout, this.onResponseAccepted)
    : elapsed = (Stopwatch()..start());

  final int opcode;
  final Duration timeout;
  final void Function(PbleFrame)? onResponseAccepted;
  final Stopwatch elapsed;
  final Completer<PbleFrame> completer = Completer<PbleFrame>();

  bool get expired => elapsed.elapsed > timeout;

  Duration get remaining {
    final int microseconds =
        timeout.inMicroseconds - elapsed.elapsedMicroseconds;
    if (microseconds <= 0) throw const _RequestDeadlineExpired();
    return Duration(microseconds: microseconds);
  }
}

/// Identifies only expiry of this engine's own absolute request deadline.
final class _RequestDeadlineExpired implements Exception {
  const _RequestDeadlineExpired();
}
