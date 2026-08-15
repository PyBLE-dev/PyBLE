// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
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
/// The only mutable state is the ID counter and the pending-request table.
class PbleEngine {
  PbleEngine(this._transport) {
    _inboundSub = _transport.inbound.listen(_onPacket);
  }

  final ByteTransport _transport;
  late final StreamSubscription<Uint8List> _inboundSub;

  final PbleReassembler _reassembler = PbleReassembler();
  final Map<int, _PendingRequest> _pending = <int, _PendingRequest>{};
  final StreamController<PbleFrame> _events =
      StreamController<PbleFrame>.broadcast();

  int _idCounter = 0;
  bool _disposed = false;

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
  Future<PbleFrame> request(
    PbleFrame cmd, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    if (_disposed) {
      throw StateError('PbleEngine used after dispose()');
    }
    final _PendingRequest pending = _PendingRequest(cmd.opcode, timeout);
    _pending[cmd.id] = pending;
    try {
      final List<Uint8List> packets = PbleFragmenter(
        mtu: _transport.mtu,
      ).fragment(encodeFrame(cmd));
      for (final Uint8List packet in packets) {
        final Duration remaining = pending.remaining;
        await _transport
            .send(packet, acknowledged: true)
            .timeout(
              remaining,
              onTimeout: () => throw const _RequestDeadlineExpired(),
            );
      }
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
    final List<Uint8List> packets = PbleFragmenter(
      mtu: _transport.mtu,
    ).fragment(encodeFrame(cmd));
    for (final Uint8List packet in packets) {
      await _transport.send(packet, acknowledged: false);
    }
  }

  void _onPacket(Uint8List packet) {
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

    // EVT (ID = 0) routes onto the event stream, keyed by opcode downstream.
    if (frame.type == Pble.typeEvt || frame.id == Pble.evtId) {
      if (!_events.isClosed) _events.add(frame);
      return;
    }

    // Otherwise complete only the exact {TYPE=RSP, OPCODE, ID} request.
    final _PendingRequest? pending = _pending[frame.id];
    if (pending != null &&
        frame.type == Pble.typeRsp &&
        frame.opcode == pending.opcode &&
        !pending.completer.isCompleted &&
        !pending.expired) {
      pending.completer.complete(frame);
    }
  }

  /// Cancels the inbound subscription, fails any in-flight requests, and closes
  /// the event stream. The engine must not be reused after this.
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await _inboundSub.cancel();
    for (final _PendingRequest pending in _pending.values) {
      if (!pending.completer.isCompleted) {
        pending.completer.completeError(
          const PbleTimeoutException('engine disposed'),
        );
      }
    }
    _pending.clear();
    await _events.close();
  }
}

/// One monotonic deadline shared by every acknowledged write and the RSP wait.
final class _PendingRequest {
  _PendingRequest(this.opcode, this.timeout) : elapsed = (Stopwatch()..start());

  final int opcode;
  final Duration timeout;
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
