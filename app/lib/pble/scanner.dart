// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'scan_hit.dart';

/// The neutral scan seam (FR-CONNECT-1, ADR-0009). `lib/pble` is the sole layer
/// that knows the transport; it presents discovery EXCLUSIVELY through this
/// interface and [ScanHit], so a widget lists boards without ever touching
/// `lib/ble` (CON-8, FR-BLE-8).
///
/// [scan] yields an ACCUMULATING, deduped-by-id, latest-RSSI snapshot LIST: each
/// event is the full set of boards seen so far this scan (one entry per id, its
/// RSSI refreshed), so the UI binds a stable list that updates in place. The
/// production accumulator wraps the radio adapter; [FakeScanner] scripts the
/// snapshots with no radio.
abstract interface class Scanner {
  /// Starts a scan and streams accumulating [ScanHit] snapshots. An optional
  /// [timeout] auto-stops the scan (the accumulator cancels the radio scan and
  /// closes the stream).
  Stream<List<ScanHit>> scan({Duration? timeout});

  /// Stops an in-flight scan.
  Future<void> stopScan();
}

/// A shipped, no-radio [Scanner] double (FR-CONN-7): script the accumulated
/// snapshot lists with [emit], observe [scanning]/[scanStartCount]/
/// [stopScanCount]/[lastTimeout]. Each [scan] returns a fresh stream so a
/// re-scan after a [stopScan] works, exactly like the production accumulator.
class FakeScanner implements Scanner {
  StreamController<List<ScanHit>>? _controller;
  bool _scanning = false;
  int _scanStartCount = 0;
  int _stopScanCount = 0;
  Duration? _lastTimeout;

  /// Whether a scan is currently running (`scan` called, no `stopScan` since).
  bool get scanning => _scanning;

  /// How many times [scan] has been called.
  int get scanStartCount => _scanStartCount;

  /// How many times [stopScan] has been called.
  int get stopScanCount => _stopScanCount;

  /// The [Duration] passed to the most recent [scan] (`null` if none / omitted).
  Duration? get lastTimeout => _lastTimeout;

  @override
  Stream<List<ScanHit>> scan({Duration? timeout}) {
    // Discard any prior scan's stream; each scan() is a fresh accumulation.
    unawaited(_controller?.close());
    _scanning = true;
    _scanStartCount++;
    _lastTimeout = timeout;
    _controller = StreamController<List<ScanHit>>.broadcast();
    return _controller!.stream;
  }

  /// Scripts one accumulated snapshot onto the current scan stream.
  void emit(List<ScanHit> hits) {
    final StreamController<List<ScanHit>>? c = _controller;
    if (c != null && !c.isClosed) c.add(List<ScanHit>.unmodifiable(hits));
  }

  @override
  Future<void> stopScan() async {
    _scanning = false;
    _stopScanCount++;
  }

  /// Releases the current scan stream (test-lifecycle hook; optional).
  Future<void> dispose() async {
    await _controller?.close();
    _controller = null;
  }
}
