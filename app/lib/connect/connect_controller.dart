// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-22 — the connect controller: the read-model + intents the `ConnectScreen`
/// binds to (FR-CONNECT-1/2/5/6, ADR-0009).
///
/// It wraps the NEUTRAL runtime [ConnectionManager] — never `lib/ble`, never a
/// transport type (CON-8, FR-BLE-8) — and projects its scan / readiness / phase
/// / connection signals into ONE observable [ConnectState], plus the
/// scan/connect/disconnect intents. The live board's [DeviceInfo] is fetched on
/// connect as the round-trip PROOF the handshake gate (GATT → TX → MTU →
/// HELLO) completed (FR-CONNECT-2). Identity fields (deviceId/label) are
/// DISPLAY-ONLY and NEVER gate access (SEC-9).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

/// An immutable snapshot of everything the `ConnectScreen` renders, projected
/// from the [ConnectionManager] seam. Rebuilt on every controller notification.
@immutable
class ConnectState {
  const ConnectState({
    required this.readiness,
    required this.phase,
    required this.connState,
    required this.hits,
    required this.selected,
    required this.deviceInfo,
    required this.lastError,
  });

  /// The BLE adapter/permission readiness (adapter-off / unauthorized /
  /// unsupported / ready), surfaced never swallowed (FR-BLE-6/7).
  final BleReadiness readiness;

  /// The runtime session phase (idle / scanning / connecting / connected /
  /// failed) — distinct from [connState] (a single board's link state).
  final ConnectPhase phase;

  /// The stable facade's live link/run state.
  final ConnState connState;

  /// The boards seen so far this scan (deduped-by-id, latest-RSSI snapshot).
  final List<ScanHit> hits;

  /// The board chosen by the most recent connect attempt, or `null`.
  final ScanHit? selected;

  /// The connected board's live info (the round-trip PROOF), or `null` until it
  /// is fetched / while disconnected.
  final DeviceInfo? deviceInfo;

  /// The most recent connect failure, or `null`. Rendered verbatim under the
  /// failure state for on-hardware (HIL) debugging.
  final Object? lastError;

  /// Whether the adapter is powered on and authorized (scan/connect available).
  bool get isReady => readiness == BleReadiness.ready;

  /// Whether a scan is currently running.
  bool get isScanning => phase == ConnectPhase.scanning;

  /// How many distinct boards the current scan has seen.
  int get hitCount => hits.length;
}

/// The connect controller. A [ChangeNotifier] over the neutral
/// [ConnectionManager]: it listens to the manager's phase / connection-state
/// listenables and its readiness / scan-result streams, and exposes the merged
/// [state] plus the scan/connect/disconnect intents. It NEVER disposes the
/// manager (the root [connectionManagerProvider] owns that) — only its own
/// subscriptions and listeners (all removals are disposal-safe).
class ConnectController extends ChangeNotifier {
  ConnectController(this._manager)
    : _readiness = _manager.readiness.current,
      _hits = const <ScanHit>[] {
    _readinessSub = _manager.readiness.readiness.listen(_onReadiness);
    _scanSub = _manager.scanResults.listen(_onScanResults);
    _manager.phase.addListener(_onPhase);
    _manager.connection.state.addListener(_onConnState);
    // Cover a board that is already attached at construction (defensive).
    _maybeFetchInfo(_manager.connection.state.value);
  }

  final ConnectionManager _manager;

  BleReadiness _readiness;
  List<ScanHit> _hits;
  DeviceInfo? _deviceInfo;
  bool _fetchingInfo = false;
  bool _disposed = false;

  StreamSubscription<BleReadiness>? _readinessSub;
  StreamSubscription<List<ScanHit>>? _scanSub;

  /// The merged, immutable read-model the UI renders.
  ConnectState get state => ConnectState(
    readiness: _readiness,
    phase: _manager.phase.value,
    connState: _manager.connection.state.value,
    hits: _hits,
    selected: _manager.selected,
    deviceInfo: _deviceInfo,
    lastError: _manager.lastError,
  );

  // --- intents ---------------------------------------------------------------

  /// Starts a filtered scan for PyBLE boards. Clears the prior snapshot so the
  /// list rebuilds fresh (the accumulator re-emits from empty, FR-CONNECT-1).
  Future<void> startScan() async {
    _hits = const <ScanHit>[];
    _safeNotify();
    await _manager.startScan();
  }

  /// Stops an in-flight scan.
  Future<void> stopScan() => _manager.stopScan();

  /// Connects to [id] through the handshake gate. A failure is already reflected
  /// via `phase == failed` + `lastError`, so it is swallowed here (never an
  /// unhandled async error) and rendered by the UI (FR-CONNECT-6).
  Future<void> connect(String id) async {
    try {
      await _manager.connect(id);
    } on Object {
      // Intentionally swallowed: the failure is observable via [state].
    }
  }

  /// Drops the link and returns to the scan state.
  Future<void> disconnect() async {
    _deviceInfo = null;
    await _manager.disconnect();
  }

  // --- manager signal handlers ----------------------------------------------

  void _onReadiness(BleReadiness r) {
    _readiness = r;
    _safeNotify();
  }

  void _onScanResults(List<ScanHit> hits) {
    _hits = hits;
    _safeNotify();
  }

  void _onPhase() => _safeNotify();

  void _onConnState() {
    _maybeFetchInfo(_manager.connection.state.value);
    _safeNotify();
  }

  /// Fetches the live [DeviceInfo] once a board reaches `ready`/`running` — the
  /// proof the round-trip works — and clears it on `disconnected`.
  void _maybeFetchInfo(ConnState s) {
    if (s == ConnState.ready || s == ConnState.running) {
      if (_deviceInfo == null && !_fetchingInfo) {
        unawaited(_fetchInfo());
      }
    } else if (s == ConnState.disconnected) {
      _deviceInfo = null;
    }
  }

  Future<void> _fetchInfo() async {
    _fetchingInfo = true;
    try {
      _deviceInfo = await _manager.connection.deviceInfo();
    } on Object {
      // Leave null; any connect error surfaces via lastError/phase instead.
    } finally {
      _fetchingInfo = false;
      _safeNotify();
    }
  }

  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_readinessSub?.cancel());
    unawaited(_scanSub?.cancel());
    // removeListener is disposal-safe even if the manager was torn down first.
    _manager.phase.removeListener(_onPhase);
    _manager.connection.state.removeListener(_onConnState);
    super.dispose();
  }
}

/// The connect controller provider, wired to the root [connectionManagerProvider]
/// (ADR-0009). Auto-disposed with the surface; the manager it wraps outlives it.
final AutoDisposeChangeNotifierProvider<ConnectController>
connectControllerProvider =
    ChangeNotifierProvider.autoDispose<ConnectController>(
      (ref) => ConnectController(ref.watch(connectionManagerProvider)),
    );
