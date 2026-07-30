// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;

import 'conn_state.dart';
import 'connection.dart';
import 'types.dart'; // re-exports pble_exception.dart (the neutral type family)

/// A shipped, no-BLE [Connection] double (FR-CONN-7, D5).
///
/// First-class production artifact — not a mock in `test/` — so every UI FR is
/// testable without a board. It holds NO wire/transport code: state, run, and
/// console are scripted in memory, and file ops back onto an in-memory tree.
///
/// S3 scripting surface (A-11/A-12):
///   * [emitRunState] drives [runState], with [ConnState.running] DERIVED while
///     `RunState.running` (so widget tests see the collapse);
///   * [emitConsole] pushes [console] events, incl. the client-synthesized
///     [ConsoleStream.system] tag;
///   * an in-memory file tree backs [listDir]/[getFile]/[putFile]/[mkdir]/
///     [rename]/[delete], with monotonic synthetic [TransferProgress];
///   * [injectError] arms a ONE-SHOT [PbleException] on the next verb;
///   * [runFile]/[runSource] complete OK even when a scripted program then fails
///     async; [softReboot] scripts a disconnect → reconnect.
///
/// The identity verbs + the full error-injection/progress POLISH are the
/// A-14/S4 shipped-FakeConnection freeze; S3 adds only what A-11/A-12 need.
class FakeConnection implements Connection {
  FakeConnection({
    ConnState initial = ConnState.disconnected,
    DeviceInfo? deviceInfo,
  }) : _state = ValueNotifier<ConnState>(initial),
       _info = deviceInfo ?? _defaultInfo;

  static const DeviceInfo _defaultInfo = DeviceInfo(
    chip: 'esp32-s3',
    mpyVersion: '1.28.0',
    freeMem: 0,
    fsRoot: '/',
    deviceId: '0000',
    label: '',
    // A representative negotiated board, so UI suites see realistic caps without
    // a radio. All display-only / non-gating (SEC-9/CON-7).
    protoVersion: 1,
    agentVersion: '0.4.0',
    mtu: 247,
    window: 4,
    chunk: 243,
    hasSd: false,
    hasIdentify: false,
    autoRun: false,
  );

  final ValueNotifier<ConnState> _state;
  DeviceInfo _info;

  final StreamController<RunState> _runState =
      StreamController<RunState>.broadcast();
  final StreamController<ConsoleEvent> _console =
      StreamController<ConsoleEvent>.broadcast();

  // In-memory file tree: files (path → bytes) + directories (normalized path).
  final Map<String, Uint8List> _files = <String, Uint8List>{};
  final Set<String> _dirs = <String>{};

  // One-shot error injection: the next verb throws this, then it clears.
  PbleException? _injected;

  @override
  ValueListenable<ConnState> get state => _state;

  @override
  Stream<RunState> get runState => _runState.stream;

  @override
  Stream<ConsoleEvent> get console => _console.stream;

  @override
  Future<DeviceInfo> deviceInfo() async => _info;

  // --- scripting hooks (test-facing) -----------------------------------------

  /// Scripts an observable [ConnState] transition. Notifies listeners.
  void emit(ConnState next) => _state.value = next;

  /// Re-scripts the [DeviceInfo] returned by later [deviceInfo] reads.
  set scriptedDeviceInfo(DeviceInfo info) => _info = info;

  /// Drives [runState] and DERIVES [ConnState.running] while the session is up.
  void emitRunState(RunState rs) {
    if (!_runState.isClosed) _runState.add(rs);
    final ConnState cur = _state.value;
    if (cur == ConnState.ready || cur == ConnState.running) {
      _state.value = rs == RunState.running
          ? ConnState.running
          : ConnState.ready;
    }
  }

  /// Pushes a [ConsoleEvent] onto [console] (any stream, incl. `system`).
  void emitConsole(ConsoleStream stream, List<int> bytes) {
    if (!_console.isClosed) {
      _console.add(
        ConsoleEvent(stream: stream, bytes: Uint8List.fromList(bytes)),
      );
    }
  }

  /// Arms a ONE-SHOT [PbleException]: the next in-scope verb throws it, then the
  /// injection clears so a subsequent call succeeds again.
  void injectError(PbleException error) => _injected = error;

  // --- A-11 run / console ----------------------------------------------------

  @override
  Future<void> runFile(String path) async => _maybeThrow();

  @override
  Future<void> runSource(String snippet) async => _maybeThrow();

  @override
  Future<void> stop() async => _maybeThrow();

  @override
  Future<void> softReboot() async {
    _maybeThrow();
    // Fire-then-expect-disconnect: script the board reset's link drop → the
    // A-03 reconnect path bringing the session back up.
    scheduleMicrotask(() {
      _state.value = ConnState.disconnected;
      scheduleMicrotask(() {
        _state.value = ConnState.connecting;
        scheduleMicrotask(() => _state.value = ConnState.ready);
      });
    });
  }

  @override
  Future<void> sendInput(String text) async {
    // Fire-and-forget: never throws, even with an armed injection.
  }

  // --- A-12 file operations (in-memory tree) ---------------------------------

  @override
  Future<List<RemoteEntry>> listDir(String path) async {
    _maybeThrow();
    final String dir = _normalize(path);
    final List<RemoteEntry> entries = <RemoteEntry>[];
    for (final MapEntry<String, Uint8List> f in _files.entries) {
      if (_parent(f.key) == dir) {
        entries.add(
          RemoteEntry(name: _leaf(f.key), isDir: false, size: f.value.length),
        );
      }
    }
    for (final String d in _dirs) {
      if (_parent(d) == dir) {
        entries.add(RemoteEntry(name: _leaf(d), isDir: true, size: 0));
      }
    }
    return entries;
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async {
    _maybeThrow();
    final Uint8List? bytes = _files[_normalize(path)];
    if (bytes == null) {
      throw ENoEnt('no such file: $path');
    }
    _emitProgress(bytes.length, onProgress);
    return Uint8List.fromList(bytes);
  }

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    _maybeThrow();
    _files[_normalize(path)] = Uint8List.fromList(bytes);
    _emitProgress(bytes.length, onProgress);
  }

  @override
  Future<void> delete(String path) async {
    _maybeThrow();
    final String p = _normalize(path);
    _files.remove(p);
    _dirs.remove(p);
  }

  @override
  Future<void> mkdir(String path) async {
    _maybeThrow();
    _dirs.add(_normalize(path));
  }

  @override
  Future<void> rename(String from, String to) async {
    _maybeThrow();
    final String src = _normalize(from);
    final String dst = _normalize(to);
    final Uint8List? bytes = _files.remove(src);
    if (bytes != null) {
      _files[dst] = bytes;
    } else if (_dirs.remove(src)) {
      _dirs.add(dst);
    }
  }

  @override
  Future<void> dispose() async {
    await _runState.close();
    await _console.close();
    _state.dispose();
  }

  // --- helpers ---------------------------------------------------------------

  /// Throws (and clears) an armed one-shot injection, if any.
  void _maybeThrow() {
    final PbleException? e = _injected;
    if (e != null) {
      _injected = null;
      throw e;
    }
  }

  /// Emits monotonic synthetic progress from `0` to `total`.
  void _emitProgress(int total, ProgressCb? onProgress) {
    if (onProgress == null) return;
    onProgress(TransferProgress(sent: 0, total: total));
    const int steps = 4;
    for (int i = 1; i <= steps; i++) {
      onProgress(
        TransferProgress(sent: (total * i / steps).floor(), total: total),
      );
    }
    onProgress(TransferProgress(sent: total, total: total));
  }

  String _normalize(String path) {
    if (path.length > 1 && path.endsWith('/')) {
      return path.substring(0, path.length - 1);
    }
    return path;
  }

  String _parent(String path) {
    final int i = path.lastIndexOf('/');
    return i <= 0 ? '/' : path.substring(0, i);
  }

  String _leaf(String path) => path.substring(path.lastIndexOf('/') + 1);
}
