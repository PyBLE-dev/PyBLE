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
/// is DROPPED, never surfaced — FR-PBLE-3), correlates RSP frames to their CMD
/// by ID, and routes EVT frames (ID = 0) onto [events]. The only mutable state
/// is the ID counter and the pending-request table.
class PbleEngine {
  PbleEngine(this._transport) {
    _inboundSub = _transport.inbound.listen(_onPacket);
  }

  final ByteTransport _transport;
  late final StreamSubscription<Uint8List> _inboundSub;

  final PbleReassembler _reassembler = PbleReassembler();
  final Map<int, Completer<PbleFrame>> _pending = <int, Completer<PbleFrame>>{};
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

  /// Sends [cmd] and completes with the RSP carrying the matching ID.
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
    final Completer<PbleFrame> completer = Completer<PbleFrame>();
    _pending[cmd.id] = completer;
    try {
      final List<Uint8List> packets = PbleFragmenter(
        mtu: _transport.mtu,
      ).fragment(encodeFrame(cmd));
      for (final Uint8List packet in packets) {
        await _transport.send(packet);
      }
      return await completer.future.timeout(timeout);
    } on TimeoutException {
      throw const PbleTimeoutException('no RSP within timeout');
    } finally {
      _pending.remove(cmd.id);
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
      await _transport.send(packet);
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

    // Otherwise correlate to the pending CMD by ID.
    final Completer<PbleFrame>? completer = _pending.remove(frame.id);
    if (completer != null && !completer.isCompleted) {
      completer.complete(frame);
    }
  }

  /// Cancels the inbound subscription, fails any in-flight requests, and closes
  /// the event stream. The engine must not be reused after this.
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await _inboundSub.cancel();
    for (final Completer<PbleFrame> completer in _pending.values) {
      if (!completer.isCompleted) {
        completer.completeError(const PbleTimeoutException('engine disposed'));
      }
    }
    _pending.clear();
    await _events.close();
  }
}
