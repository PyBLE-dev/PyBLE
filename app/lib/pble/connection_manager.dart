// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart'
    show ValueListenable, ValueNotifier, VoidCallback;

// lib/pble is the SOLE sanctioned importer of lib/ble (CON-8, import-boundary
// gate): the production factory builds the fbp stack HERE so main.dart never
// names a transport type. scan_hit/scanner stay pure-neutral; only this file
// (and the wire client) reach the radio.
import '../ble/ble_adapter.dart';
import '../ble/ble_readiness.dart';
import '../ble/ble_scan_result.dart';
import '../ble/fbp_ble_adapter.dart';
import '../ble/fbp_ble_readiness.dart';
import 'conn_state.dart';
import 'connection.dart';
import 'pble_connection.dart';
import 'scan_hit.dart';
import 'scanner.dart';
import 'types.dart'; // re-exports pble_exception.dart (incl. NotConnectedException)

/// The runtime SESSION phase of the connect surface (ADR-0009, TDD §4.8/§5.2).
///
/// DISTINCT from [ConnState]: [ConnState] is the observable link/run state of a
/// single board (`disconnected`/`connecting`/`ready`/`running`), whereas
/// [ConnectPhase] tracks the manager's session lifecycle across scan → connect →
/// disconnect. Never conflate the two: `scanning`/`connected`/`failed` are
/// session phases, never link states.
enum ConnectPhase {
  /// No scan running and no board connected.
  idle,

  /// A scan is in progress.
  scanning,

  /// A board was chosen; GATT + HELLO are being established.
  connecting,

  /// A board is live (HELLO complete): `ready` or `running`.
  connected,

  /// The last `connect` attempt failed (the reason is in `lastError`).
  failed,
}

/// Builds a live [Connection] for a chosen device [deviceId]. In production this
/// opens a GATT link and runs HELLO (`PbleConnection.fromLink`); in tests it
/// returns a `FakeConnection`. A thrown error surfaces as `ConnectPhase.failed`.
typedef ConnectionFactory = Future<Connection> Function(String deviceId);

/// The runtime connection orchestration: it holds the ACTIVE board — which
/// changes across scan/connect/disconnect — behind ONE stable [connection]
/// facade whose identity NEVER changes (FR-CONN-6, ADR-0009). Widgets bind to
/// `connection` (via Riverpod) once and keep working as the underlying board
/// comes and goes.
abstract interface class ConnectionManager {
  /// The STABLE [Connection] facade. Its object identity is constant for the
  /// manager's whole life; its `state` walks `disconnected` → `connecting` →
  /// `ready`/`running` as boards attach, and its verbs delegate to the live
  /// board when connected — otherwise they throw [NotConnectedException].
  Connection get connection;

  /// Accumulating, deduped-by-id scan snapshots forwarded from the [Scanner].
  Stream<List<ScanHit>> get scanResults;

  /// The BLE readiness source (adapter on/off/unauthorized/unsupported),
  /// surfaced never swallowed, for the connect surface to render + localize.
  BleReadinessSource get readiness;

  /// The observable session [ConnectPhase].
  ValueListenable<ConnectPhase> get phase;

  /// The board chosen by the most recent [connect], or `null`.
  ScanHit? get selected;

  /// The most recent failure (e.g. a factory/link error), or `null`.
  Object? get lastError;

  /// Starts a scan; [phase] → [ConnectPhase.scanning].
  Future<void> startScan({Duration? timeout});

  /// Stops the scan; [phase] → [ConnectPhase.idle] when no board is connected.
  Future<void> stopScan();

  /// Builds and publishes a board for [id] via the [ConnectionFactory]; [phase]
  /// tracks its [ConnState] (`connecting` → `connected`). A factory failure sets
  /// [phase] to [ConnectPhase.failed] and records [lastError].
  Future<void> connect(String id);

  /// Tears the session back down to `idle`/`disconnected`.
  Future<void> disconnect();

  /// Releases all resources (the facade, the live board, the scan stream).
  Future<void> dispose();
}

/// The concrete [ConnectionManager] (ADR-0009). Wired from NEUTRAL abstractions
/// — a [Scanner], a [BleReadinessSource], and a [ConnectionFactory] — so tests
/// inject pure fakes (no radio, no `BleLink`), while [PbleConnectionManager.production]
/// builds the real fbp stack INTERNALLY so `main.dart` names no `lib/ble` type.
class PbleConnectionManager implements ConnectionManager {
  // Public named params (`scanner:`/`readiness:`/`connectionFactory:`) map onto
  // private final fields; an initializing formal would rename the params, so the
  // lint is deliberately suppressed here.
  // ignore_for_file: prefer_initializing_formals
  PbleConnectionManager({
    required Scanner scanner,
    required BleReadinessSource readiness,
    required ConnectionFactory connectionFactory,
  }) : _scanner = scanner,
       _readiness = readiness,
       _connectionFactory = connectionFactory {
    // Derive the session phase from the stable facade's live ConnState. The
    // facade mirrors whatever board is attached, so this one listener tracks
    // connecting → connected for every board across the session.
    _facade.state.addListener(_onFacadeState);
  }

  /// The PRODUCTION wiring: one [FbpBleAdapter] drives both discovery (wrapped
  /// as an accumulating [Scanner]) and connect (`fromLink` runs HELLO), plus the
  /// platform [FbpBleReadinessSource]. Keeps every `flutter_blue_plus`/`lib/ble`
  /// type inside `lib/pble` (CON-8): `main.dart` only names this factory.
  factory PbleConnectionManager.production({
    required String appName,
    required String appVersion,
  }) {
    final FbpBleAdapter adapter = FbpBleAdapter();
    return PbleConnectionManager(
      scanner: _AccumulatingScanner(adapter),
      readiness: FbpBleReadinessSource(),
      connectionFactory: (String id) async => PbleConnection.fromLink(
        link: await adapter.connect(id),
        appName: appName,
        appVersion: appVersion,
      ),
    );
  }

  final Scanner _scanner;
  final BleReadinessSource _readiness;
  final ConnectionFactory _connectionFactory;

  final _StableFacade _facade = _StableFacade();
  final ValueNotifier<ConnectPhase> _phase = ValueNotifier<ConnectPhase>(
    ConnectPhase.idle,
  );
  final StreamController<List<ScanHit>> _scanResults =
      StreamController<List<ScanHit>>.broadcast();

  // Boards seen this session (id → latest snapshot), so connect(id) can resolve
  // the chosen ScanHit even before a fresh scan.
  final Map<String, ScanHit> _hits = <String, ScanHit>{};

  StreamSubscription<List<ScanHit>>? _scanSub;
  Connection? _liveBoard;
  ScanHit? _selected;
  Object? _lastError;
  bool _disposed = false;

  @override
  Connection get connection => _facade;

  @override
  Stream<List<ScanHit>> get scanResults => _scanResults.stream;

  @override
  BleReadinessSource get readiness => _readiness;

  @override
  ValueListenable<ConnectPhase> get phase => _phase;

  @override
  ScanHit? get selected => _selected;

  @override
  Object? get lastError => _lastError;

  @override
  Future<void> startScan({Duration? timeout}) async {
    // Fire-and-forget: a broadcast-subscription cancel() future never completes
    // under `tester.pump()` (FakeAsync), which would stall connect/stopScan in
    // every widget test. The listener is removed synchronously either way; the
    // completion signal is not needed here (matches _StableFacade.detach below).
    unawaited(_scanSub?.cancel());
    _scanSub = null;
    _phase.value = ConnectPhase.scanning;
    final Stream<List<ScanHit>> stream = _scanner.scan(timeout: timeout);
    _scanSub = stream.listen((List<ScanHit> hits) {
      for (final ScanHit h in hits) {
        _hits[h.id] = h;
      }
      if (!_scanResults.isClosed) _scanResults.add(hits);
    });
  }

  @override
  Future<void> stopScan() async {
    // Fire-and-forget: a broadcast-subscription cancel() future never completes
    // under `tester.pump()` (FakeAsync), which would stall connect/stopScan in
    // every widget test. The listener is removed synchronously either way; the
    // completion signal is not needed here (matches _StableFacade.detach below).
    unawaited(_scanSub?.cancel());
    _scanSub = null;
    await _scanner.stopScan();
    // Only fall back to idle when no board is live (a connected session keeps
    // its connected/connecting phase).
    if (_liveBoard == null && _phase.value == ConnectPhase.scanning) {
      _phase.value = ConnectPhase.idle;
    }
  }

  @override
  Future<void> connect(String id) async {
    // Scanning and GATT do not run together — stop the scan first (FR-BLE-5).
    // Fire-and-forget: a broadcast-subscription cancel() future never completes
    // under `tester.pump()` (FakeAsync), which would stall connect/stopScan in
    // every widget test. The listener is removed synchronously either way; the
    // completion signal is not needed here (matches _StableFacade.detach below).
    unawaited(_scanSub?.cancel());
    _scanSub = null;
    await _scanner.stopScan();

    _selected = _hits[id] ?? ScanHit(id: id, name: '', rssi: 0);
    _lastError = null;
    _phase.value = ConnectPhase.connecting;
    try {
      final Connection board = await _connectionFactory(id);
      _liveBoard = board;
      _facade.attach(board);
      // Derive the phase from the freshly attached board's live state (the
      // listener also fires on the sync-up, but re-derive to cover a board that
      // attaches already-ready with no state change).
      _phase.value = _phaseForConn(_facade.state.value);
    } catch (error) {
      _lastError = error;
      _phase.value = ConnectPhase.failed;
      rethrow;
    }
  }

  @override
  Future<void> disconnect() async {
    final Connection? board = _liveBoard;
    // Null the live board BEFORE detaching so the facade's reset to
    // disconnected does not drive the phase (we set it to idle explicitly).
    _liveBoard = null;
    _facade.detach();
    await board?.dispose();
    _selected = null;
    _phase.value = ConnectPhase.idle;
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    // Fire-and-forget: a broadcast-subscription cancel() future never completes
    // under `tester.pump()` (FakeAsync), which would stall connect/stopScan in
    // every widget test. The listener is removed synchronously either way; the
    // completion signal is not needed here (matches _StableFacade.detach below).
    unawaited(_scanSub?.cancel());
    _scanSub = null;
    _facade.state.removeListener(_onFacadeState);
    final Connection? board = _liveBoard;
    _liveBoard = null;
    await board?.dispose();
    await _scanResults.close();
    await _facade.dispose();
    _phase.dispose();
  }

  // Track the session phase off the stable facade's live ConnState. Only
  // meaningful while a board is attached; scan/failure phases own the idle path.
  void _onFacadeState() {
    if (_liveBoard == null) return;
    _phase.value = _phaseForConn(_facade.state.value);
  }

  static ConnectPhase _phaseForConn(ConnState s) => switch (s) {
    ConnState.connecting => ConnectPhase.connecting,
    ConnState.ready || ConnState.running => ConnectPhase.connected,
    ConnState.disconnected => ConnectPhase.idle,
  };
}

/// The ONE stable [Connection] the manager hands out (FR-CONN-6). Its identity
/// never changes; it mirrors the currently-attached live board's `state`,
/// forwards its `console`/`runState`, and delegates every verb to it — or throws
/// [NotConnectedException] (never a silent success) when none is attached.
class _StableFacade
    implements
        Connection,
        ConnectionSessionStampSource,
        ConnectionDirectoryListingSource {
  final ValueNotifier<ConnState> _state = ValueNotifier<ConnState>(
    ConnState.disconnected,
  );
  final StreamController<RunState> _runState =
      StreamController<RunState>.broadcast();
  final StreamController<ConsoleEvent> _console =
      StreamController<ConsoleEvent>.broadcast();

  Connection? _live;
  Object _connectionSessionStamp = Object();
  bool _liveSessionEstablished = false;
  VoidCallback? _liveStateListener;
  StreamSubscription<RunState>? _liveRunStateSub;
  StreamSubscription<ConsoleEvent>? _liveConsoleSub;

  /// Attaches [live] as the active board: mirror its state now and on change,
  /// and forward its console/run-state streams.
  void attach(Connection live) {
    detach();
    _live = live;
    _connectionSessionStamp = Object();
    _liveSessionEstablished = false;
    _liveStateListener = () {
      final ConnState next = live.state.value;
      final bool nextEstablished =
          next == ConnState.ready || next == ConnState.running;
      if (_liveSessionEstablished && !nextEstablished) {
        // An in-place reconnect creates a successor link session without a
        // facade detach/attach. Rotate before mirroring the non-ready state so
        // a multi-step action captured by the old link cannot resume later.
        _connectionSessionStamp = Object();
      }
      _liveSessionEstablished = nextEstablished;
      _state.value = next;
    };
    live.state.addListener(_liveStateListener!);
    _liveStateListener!(); // sync the facade to the board's current state
    _liveRunStateSub = live.runState.listen((RunState rs) {
      if (!_runState.isClosed) _runState.add(rs);
    });
    _liveConsoleSub = live.console.listen((ConsoleEvent e) {
      if (!_console.isClosed) _console.add(e);
    });
  }

  /// Detaches the active board and resets the facade to `disconnected`. Does NOT
  /// dispose the board — the manager owns that lifecycle.
  void detach() {
    final Connection? live = _live;
    final VoidCallback? listener = _liveStateListener;
    if (live != null && listener != null) {
      live.state.removeListener(listener);
    }
    _liveStateListener = null;
    unawaited(_liveRunStateSub?.cancel());
    _liveRunStateSub = null;
    unawaited(_liveConsoleSub?.cancel());
    _liveConsoleSub = null;
    _live = null;
    _connectionSessionStamp = Object();
    _liveSessionEstablished = false;
    _state.value = ConnState.disconnected;
  }

  Connection get _required {
    final Connection? live = _live;
    if (live == null) {
      throw const NotConnectedException('no board is connected');
    }
    return live;
  }

  @override
  ValueListenable<ConnState> get state => _state;

  @override
  Object get connectionSessionStamp => _connectionSessionStamp;

  @override
  Stream<RunState> get runState => _runState.stream;

  @override
  Stream<ConsoleEvent> get console => _console.stream;

  // Every verb is `async` so a `_required` throw while disconnected surfaces as
  // a REJECTED future (typed NotConnectedException), never a synchronous throw.

  @override
  Future<DeviceInfo> deviceInfo() async => _required.deviceInfo();

  @override
  Future<void> runFile(String path) async => _required.runFile(path);

  @override
  Future<void> runSource(String snippet) async => _required.runSource(snippet);

  @override
  Future<void> stop() async => _required.stop();

  @override
  Future<void> softReboot() async => _required.softReboot();

  @override
  Future<void> sendInput(String text) async => _required.sendInput(text);

  @override
  Future<List<RemoteEntry>> listDir(String path) async =>
      _required.listDir(path);

  @override
  Future<DirectoryListing> listDirWithMetadata(String path) async {
    final Connection live = _required;
    if (live case final ConnectionDirectoryListingSource source) {
      return source.listDirWithMetadata(path);
    }
    return DirectoryListing(entries: await live.listDir(path), truncated: true);
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async =>
      _required.getFile(path, onProgress: onProgress);

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async => _required.putFile(path, bytes, onProgress: onProgress);

  @override
  Future<void> delete(String path) async => _required.delete(path);

  @override
  Future<void> mkdir(String path) async => _required.mkdir(path);

  @override
  Future<void> rename(String from, String to) async =>
      _required.rename(from, to);

  @override
  Future<void> dispose() async {
    detach();
    await _runState.close();
    await _console.close();
    _state.dispose();
  }
}

/// The production [Scanner] accumulator: subscribes to the radio adapter's
/// per-hit stream and emits a deduped-by-id, latest-RSSI snapshot LIST on each
/// hit (retyping each [BleScanResult] to a neutral [ScanHit]). Private to
/// `lib/pble` — the only `Scanner` that touches the transport.
class _AccumulatingScanner implements Scanner {
  _AccumulatingScanner(this._adapter);

  final BleAdapter _adapter;

  final Map<String, ScanHit> _hits = <String, ScanHit>{};
  StreamController<List<ScanHit>>? _controller;
  StreamSubscription<BleScanResult>? _sub;
  Timer? _timeoutTimer;

  @override
  Stream<List<ScanHit>> scan({Duration? timeout}) {
    // A fresh scan starts a fresh accumulation.
    _hits.clear();
    unawaited(_controller?.close());
    final StreamController<List<ScanHit>> controller =
        StreamController<List<ScanHit>>.broadcast();
    _controller = controller;

    _sub = _adapter.scan().listen((BleScanResult r) {
      _hits[r.id] = ScanHit(id: r.id, name: r.name, rssi: r.rssi);
      if (!controller.isClosed) {
        controller.add(List<ScanHit>.unmodifiable(_hits.values));
      }
    });

    _timeoutTimer?.cancel();
    if (timeout != null) {
      _timeoutTimer = Timer(timeout, () => unawaited(stopScan()));
    }
    return controller.stream;
  }

  @override
  Future<void> stopScan() async {
    _timeoutTimer?.cancel();
    _timeoutTimer = null;
    await _sub?.cancel();
    _sub = null;
    await _adapter.stopScan();
    await _controller?.close();
    _controller = null;
  }
}
