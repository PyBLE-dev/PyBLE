// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:math' show pow;

import 'package:flutter/foundation.dart'
    show ValueListenable, ValueNotifier, VoidCallback;

import 'ble_link.dart';

/// Opens a fresh GATT link to the given identifier. `BleAdapter.connect`
/// satisfies this shape, so [ReconnectingBleLink] reattempts by the *remembered*
/// id — no re-scan (FR-BLE-4).
typedef BleConnect = Future<BleLink> Function(String id);

/// The bounded exponential backoff governing auto-reattempts (frozen policy,
/// TDD §7.3): default intervals `0.5, 1, 2, 4, 8, 8 s` over 6 attempts, **no
/// jitter** (deterministic tests). Every field is injectable so a mocked
/// transport can shrink the schedule.
class BleBackoff {
  const BleBackoff({
    this.initial = const Duration(milliseconds: 500),
    this.factor = 2.0,
    this.maxInterval = const Duration(seconds: 8),
    this.maxAttempts = 6,
  });

  /// The first reattempt delay.
  final Duration initial;

  /// Multiplier applied per successive attempt.
  final double factor;

  /// Ceiling each interval is capped at.
  final Duration maxInterval;

  /// Number of reattempts before giving up and settling on `disconnected`.
  final int maxAttempts;

  /// Delay before reattempt [n] (1-based): `initial * factor^(n-1)`, capped at
  /// [maxInterval].
  Duration delayFor(int n) {
    final num scaled = initial.inMicroseconds * pow(factor, n - 1);
    final Duration raw = Duration(microseconds: scaled.round());
    return raw > maxInterval ? maxInterval : raw;
  }
}

/// A [BleLink] that transparently re-establishes its byte pipe after an
/// *unexpected* drop, following the bounded [BleBackoff] policy (FR-BLE-4).
///
/// It wraps a [BleConnect] factory (the flutter_blue_plus adapter in production,
/// a fake in tests) rather than a single connection, so reconnect is testable
/// with no radio. It only restores the raw pipe — HELLO/caps re-negotiation and
/// in-flight transfer resume are `lib/pble`'s (TDD §7.3/§8.4).
class ReconnectingBleLink implements BleLink {
  ReconnectingBleLink({
    required this.id,
    required this.connect,
    this.backoff = const BleBackoff(),
  });

  /// The remembered identifier every reattempt targets (FR-BLE-4).
  final String id;

  /// Opens a fresh link to [id]; re-invoked on every reattempt.
  final BleConnect connect;

  /// The bounded reattempt policy.
  final BleBackoff backoff;

  final StreamController<List<int>> _inbound =
      StreamController<List<int>>.broadcast();
  final ValueNotifier<BleLinkState> _state = ValueNotifier<BleLinkState>(
    BleLinkState.disconnected,
  );

  BleLink? _inner;
  StreamSubscription<List<int>>? _innerInbound;
  VoidCallback? _innerStateListener;

  /// Set by a user-initiated [disconnect]; disables all auto-reattempt.
  bool _userClosed = false;

  @override
  Stream<List<int>> get inbound => _inbound.stream;

  @override
  Future<void> write(List<int> bytes) =>
      _inner?.write(bytes) ?? Future<void>.value();

  @override
  int get mtu => _inner?.mtu ?? 0;

  @override
  ValueListenable<BleLinkState> get linkState => _state;

  /// Establishes the link for the first time; on an unexpected drop it then
  /// auto-reattempts to [id] per [backoff].
  Future<void> start() async {
    _userClosed = false;
    _state.value = BleLinkState.connecting;
    if (await _establish()) return;
    await _reattempt();
  }

  @override
  Future<void> disconnect() async {
    // Intentional teardown: disable reattempt BEFORE tearing the inner link
    // down, so its resulting drop is not mistaken for an unexpected loss.
    _userClosed = true;
    _detachInner();
    final BleLink? inner = _inner;
    _inner = null;
    await inner?.disconnect();
    _state.value = BleLinkState.disconnected;
  }

  /// One connect attempt. Returns whether the link is now up.
  Future<bool> _establish() async {
    try {
      final BleLink link = await connect(id);
      if (_userClosed) {
        await link.disconnect();
        return false;
      }
      _attachInner(link);
      _state.value = BleLinkState.connected;
      return true;
    } catch (_) {
      return false;
    }
  }

  /// The bounded reattempt loop; settles `disconnected` when exhausted.
  Future<void> _reattempt() async {
    _state.value = BleLinkState.reconnecting;
    for (int attempt = 1; attempt <= backoff.maxAttempts; attempt++) {
      if (_userClosed) return;
      await Future<void>.delayed(backoff.delayFor(attempt));
      if (_userClosed) return;
      if (await _establish()) return;
    }
    if (!_userClosed) _state.value = BleLinkState.disconnected;
  }

  void _onInnerDrop() {
    if (_userClosed) return;
    if (_state.value == BleLinkState.reconnecting) {
      return; // already reattempting
    }
    unawaited(_reattempt());
  }

  void _attachInner(BleLink link) {
    _detachInner();
    _inner = link;
    _innerInbound = link.inbound.listen(
      _inbound.add,
      onError: _inbound.addError,
    );
    void listener() {
      if (link.linkState.value == BleLinkState.disconnected) _onInnerDrop();
    }

    _innerStateListener = listener;
    link.linkState.addListener(listener);
  }

  void _detachInner() {
    final VoidCallback? listener = _innerStateListener;
    if (listener != null) {
      _inner?.linkState.removeListener(listener);
      _innerStateListener = null;
    }
    _innerInbound?.cancel();
    _innerInbound = null;
  }
}
