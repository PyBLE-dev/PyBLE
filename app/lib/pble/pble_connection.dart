// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart'
    show ValueListenable, ValueNotifier, VoidCallback;

import '../ble/ble_link.dart';
import 'ble_byte_transport.dart';
import 'conn_state.dart';
import 'connection.dart';
import 'engine.dart';
import 'frame.dart';
import 'hello.dart';
import 'pble_constants.dart';
import 'types.dart'; // re-exports pble_exception.dart (the neutral type family)

/// The real, wire-backed [Connection] (FR-CONN-1, FR-PBLE-14).
///
/// Drives HELLO over a [PbleEngine], then speaks the FROZEN + HIL-verified
/// PBLE/1 run/console/file wire (protocol.md §5/§6/§8):
///
///   * run/console (A-11): `RUN 0x20` / `STOP 0x21` / `SOFT_REBOOT 0x22`, the
///     `RUN_STATE 0x40` → [runState] stream (with [ConnState.running] derived),
///     the `CONSOLE_DATA 0x30` → [console] stream, and fire-and-forget
///     `CONSOLE_INPUT 0x31`;
///   * files (A-12/A-13): `FILE_LIST`, CRC-verified `FILE_GET_*` streaming,
///     the windowed `FILE_PUT_*` uploader — up to `W` (`caps.window`, ref agent
///     8, fallback 4) `FILE_PUT_DATA` chunks outstanding past the cumulative
///     `FILE_PUT_ACK` watermark, Go-Back-N retransmit from the watermark on a
///     non-advancing (gap) ACK, `resume_offset` from `FILE_PUT_BEGIN` starting
///     the window mid-file — plus `FILE_DELETE`/`MKDIR`/`RENAME`.
///
/// Every non-OK RSP status maps through the single [pbleExceptionForStatus]
/// table to a distinct typed exception (FR-PBLE-13). `lib/pble` is the ONLY layer
/// that knows the wire; the UI binds to this via [Connection] and never sees a
/// frame or opcode.
class PbleConnection implements Connection {
  PbleConnection({
    required PbleEngine engine,
    required String appName,
    required String appVersion,
    this.dataTimeout = const Duration(seconds: 8),
  }) : _engine = engine,
       _negotiator = HelloNegotiator(
         engine: engine,
         appName: appName,
         appVersion: appVersion,
       ) {
    _eventsSub = _engine.events.listen(_onEvent);
  }

  /// The transfer DATA-phase inactivity ceiling. Commands already carry the
  /// engine's RSP timeout, but a download's GET_DATA/GET_END stream and an
  /// upload's PUT_ACKs are events with no RSP — if the board (or the link)
  /// stalls mid-stream, the transfer must fail with a typed
  /// [PbleTimeoutException] instead of hanging the caller forever.
  final Duration dataTimeout;

  /// Builds a connection OVER a [BleLink], observing its link state so the
  /// A-03 transitions drive [ConnState] automatically (frozen TDD §7.3):
  /// `connecting`/`reconnecting` → [ConnState.connecting]; `connected` → HELLO
  /// is (re-)negotiated on EVERY (re)connect → `ready`; `disconnected` →
  /// [ConnState.disconnected]. This is the production wiring `main.dart` uses
  /// once a board is selected; tests drive it with a fake link.
  factory PbleConnection.fromLink({
    required BleLink link,
    required String appName,
    required String appVersion,
    Duration dataTimeout = const Duration(seconds: 8),
  }) {
    final PbleConnection conn = PbleConnection(
      engine: PbleEngine(BleByteTransport(link)),
      appName: appName,
      appVersion: appVersion,
      dataTimeout: dataTimeout,
    );
    conn._observeLink(link);
    return conn;
  }

  final PbleEngine _engine;
  final HelloNegotiator _negotiator;
  final ValueNotifier<ConnState> _state = ValueNotifier<ConnState>(
    ConnState.disconnected,
  );
  final StreamController<RunState> _runStateController =
      StreamController<RunState>.broadcast();
  final StreamController<ConsoleEvent> _consoleController =
      StreamController<ConsoleEvent>.broadcast();

  late final StreamSubscription<PbleFrame> _eventsSub;
  HelloResult? _hello;

  // fromLink observation (null when constructed directly over a transport).
  BleLink? _observedLink;
  VoidCallback? _linkListener;

  void _observeLink(BleLink link) {
    _observedLink = link;
    _linkListener = () {
      switch (link.linkState.value) {
        case BleLinkState.connecting:
        case BleLinkState.reconnecting:
          _state.value = ConnState.connecting;
        case BleLinkState.connected:
          // Re-negotiate HELLO on every (re)connect (TDD §7.3). A failed
          // handshake surfaces as ConnState.disconnected; the typed error is
          // deliberately not rethrown here — nothing awaits a link callback.
          unawaited(handshake().catchError((_) {}));
        case BleLinkState.disconnected:
          _state.value = ConnState.disconnected;
          // Abort any in-flight transfer NOW: a reconnect re-HELLOs and the
          // board clears its transfer context on disconnect, so an orphaned
          // download/ACK completer would otherwise await forever (the app
          // "hangs" while the pill quietly recovers).
          _abortTransfers(
            const NotConnectedException('link dropped mid-transfer'),
          );
      }
    };
    link.linkState.addListener(_linkListener!);
    _linkListener!(); // sync with the link's current state at attach time
  }

  // --- single-active-transfer context (SEC-2 / FR-CONN-9) --------------------
  bool _transferActive = false;
  _Download? _download;
  _Upload? _upload;
  Timer? _downloadStallTimer;
  Timer? _putStallTimer;

  /// Fails the in-flight download and/or windowed upload with [e]. Idempotent;
  /// safe to call with nothing in flight.
  void _abortTransfers(PbleException e) {
    _downloadStallTimer?.cancel();
    _putStallTimer?.cancel();
    final _Download? d = _download;
    if (d != null && !d.completer.isCompleted) d.completer.completeError(e);
    final _Upload? u = _upload;
    if (u != null && !u.done.isCompleted) u.done.completeError(e);
  }

  /// (Re-)arms the download inactivity watchdog: every GET_DATA pushes the
  /// deadline out by [dataTimeout]; silence past it fails the download with a
  /// typed timeout instead of hanging (FR-PBLE-9 honesty — never a silent stall).
  void _armDownloadStall(_Download d) {
    _downloadStallTimer?.cancel();
    _downloadStallTimer = Timer(dataTimeout, () {
      if (!d.completer.isCompleted) {
        d.completer.completeError(
          const PbleTimeoutException(
            'download stalled: no data from the board',
          ),
        );
      }
    });
  }

  @override
  ValueListenable<ConnState> get state => _state;

  @override
  Stream<RunState> get runState => _runStateController.stream;

  @override
  Stream<ConsoleEvent> get console => _consoleController.stream;

  /// Runs HELLO and caches the negotiated result. On success the state moves to
  /// `ready`; on any failure it returns to `disconnected` and the typed error
  /// (e.g. [UnsupportedProtocolException], a §8 subtype) is rethrown.
  Future<void> handshake() async {
    _state.value = ConnState.connecting;
    try {
      _hello = await _negotiator.negotiate();
      _state.value = ConnState.ready;
    } catch (_) {
      _state.value = ConnState.disconnected;
      rethrow;
    }
  }

  @override
  Future<DeviceInfo> deviceInfo() async {
    final HelloResult? hello = _hello;
    if (hello == null) {
      throw StateError('handshake() must complete before deviceInfo()');
    }
    return hello.caps;
  }

  // --- A-11 run / console ----------------------------------------------------

  @override
  Future<void> runFile(String path) => _run(0, utf8.encode(path));

  @override
  Future<void> runSource(String snippet) => _run(1, utf8.encode(snippet));

  Future<void> _run(int mode, List<int> data) async {
    // RUN 0x20 [mode:u8][data]. The RSP status is OK even for a program that
    // will fail; the failure arrives async (stderr + RUN_STATE(error)).
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.run, <int>[mode & 0xff, ...data]),
    );
    _checkStatus(rsp);
  }

  @override
  Future<void> stop() async {
    // STOP 0x21 no-payload; the RSP is ALWAYS OK (idempotent).
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.stop, const <int>[]),
    );
    _checkStatus(rsp);
  }

  @override
  Future<void> softReboot() async {
    // SOFT_REBOOT 0x22 is fire-then-expect-disconnect: the reset may preempt the
    // RSP, so send WITHOUT awaiting a reply. The ensuing link drop drives state.
    await _engine.fire(_cmd(PbleOpcode.softReboot, const <int>[]));
  }

  @override
  Future<void> sendInput(String text) async {
    // CONSOLE_INPUT 0x31 is fire-and-forget: the firmware sends no RSP.
    await _engine.fire(_cmd(PbleOpcode.consoleInput, utf8.encode(text)));
  }

  // --- A-12 file operations --------------------------------------------------

  @override
  Future<List<RemoteEntry>> listDir(String path) async {
    // FILE_LIST 0x10 [plen][path] → RSP [status][more:u8][count:u16] + entries.
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.fileList, _pathField(path)),
    );
    _checkStatus(rsp);

    final Uint8List p = rsp.payload;
    int off = 1; // skip [status]
    off += 1; // [more]: truncation-only — never re-issued (A-30/S7 surfaces it)
    final int count = _readU16(p, off);
    off += 2;

    final List<RemoteEntry> entries = <RemoteEntry>[];
    for (int i = 0; i < count; i++) {
      final int etype = p[off];
      off += 1;
      final int esize = _readU32(p, off);
      off += 4;
      final int nlen = _readU16(p, off);
      off += 2;
      final String name = utf8.decode(p.sublist(off, off + nlen));
      off += nlen;
      entries.add(RemoteEntry(name: name, isDir: etype == 1, size: esize));
    }
    return entries;
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async {
    _beginTransfer();
    try {
      // FILE_GET_BEGIN 0x12 [offset:u32][plen][path] → RSP [status][total:u32].
      final PbleFrame begin = await _engine.request(
        _cmd(PbleOpcode.fileGetBegin, <int>[..._u32(0), ..._pathField(path)]),
      );
      _checkStatus(begin);
      final int total = _readU32(begin.payload, 1);

      final _Download download = _Download(
        total: total,
        onProgress: onProgress,
      );
      _download = download;
      _armDownloadStall(download);
      onProgress?.call(TransferProgress(sent: 0, total: total));

      // GET_DATA events accumulate; GET_END verifies size + whole-file CRC
      // BEFORE completing (FR-PBLE-9) — a mismatch completes with [ECrc]. The
      // inactivity watchdog (re-armed per chunk) and the link-drop abort bound
      // this await: it can never hang past [dataTimeout] of silence.
      return await download.completer.future;
    } finally {
      _downloadStallTimer?.cancel();
      _downloadStallTimer = null;
      _download = null;
      _endTransfer();
    }
  }

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    _beginTransfer();
    try {
      final int total = bytes.length;
      final int crc = pbleCrc32(bytes);

      // FILE_PUT_BEGIN 0x15 [total:u32][crc:u32][plen][path]
      //   → RSP [status][resume_offset:u32].
      final PbleFrame begin = await _engine.request(
        _cmd(PbleOpcode.filePutBegin, <int>[
          ..._u32(total),
          ..._u32(crc),
          ..._pathField(path),
        ]),
      );
      _checkStatus(begin);
      // resume_offset (FR-PBLE-10): a board holding a verified prefix returns it
      // so the window starts mid-file — never re-send the verified bytes.
      final int resumeOffset = _readU32(begin.payload, 1);

      // Sliding window (FR-PBLE-8, A-13): keep up to W FILE_PUT_DATA chunks
      // outstanding past the cumulative FILE_PUT_ACK watermark. W is NOT a wire
      // field — it is the pacing credit advertised in HELLO caps.window. The
      // window fill + ACK-driven advance + Go-Back-N resend all run through the
      // FILE_PUT_ACK event route (_onEvent) against [upload]; this method drives
      // the initial fill, then awaits [upload.done] (whole file acked, or a
      // typed stall / link-drop failure).
      final _Upload upload = _Upload(
        bytes: bytes,
        total: total,
        chunk: _chunkSize(),
        window: _window(),
        watermark: resumeOffset,
        onProgress: onProgress,
      );
      _upload = upload;
      onProgress?.call(TransferProgress(sent: resumeOffset, total: total));

      if (upload.watermark >= total) {
        // Empty file, or a resume whose verified prefix is already the whole
        // file: nothing to send, no ACK will come — go straight to END.
        if (!upload.done.isCompleted) upload.done.complete();
      } else {
        _pumpWindow(upload); // fire the first ≤ W chunks
        _armPutStall(upload); // no ACK progress within dataTimeout → typed fail
      }
      try {
        await upload
            .done
            .future; // watermark == total, or a typed transfer error
      } catch (_) {
        // The transfer failed mid-flight (stall watchdog, write error). The
        // BOARD still holds the transfer slot: protocol.md §5 allows exactly one
        // active transfer and answers every later *_BEGIN with EBUSY until this
        // one is closed. Without an END the next save — and every "open in
        // editor" — fails EBUSY for the rest of the BLE session (verified on
        // hardware). FILE_PUT_END is the sanctioned close: it answers
        // ERANGE/ECRC for the incomplete temp, deletes the temp, KEEPS the old
        // file (§5), and releases the slot. Best-effort, and it must never mask
        // the original failure.
        await _releaseBoardTransfer(crc);
        rethrow;
      }
      _putStallTimer?.cancel();

      // FILE_PUT_END 0x17 [crc:u32] → RSP [status]; success ONLY on OK
      // (ERANGE incomplete / ECRC mismatch — the old file is kept).
      final PbleFrame endRsp = await _engine.request(
        _cmd(PbleOpcode.filePutEnd, _u32(crc)),
      );
      _checkStatus(endRsp);
      onProgress?.call(TransferProgress(sent: total, total: total));
    } finally {
      _putStallTimer?.cancel();
      _putStallTimer = null;
      _upload = null;
      _endTransfer();
    }
  }

  /// Fills the upload window: fires every not-yet-sent FILE_PUT_DATA chunk from
  /// [_Upload.nextOffset] up to `watermark + W*chunk` (capped at total), so at
  /// most `W` chunks are ever outstanding past the acked watermark (AC-1). A
  /// Go-Back-N resend first rewinds `nextOffset` to the watermark, so this same
  /// loop retransmits the window (AC-3). Sends are recorded in order (the frame
  /// is enqueued synchronously before the transport's first await); a send
  /// failure aborts the transfer with a typed error.
  void _pumpWindow(_Upload u) {
    final int ceiling = u.watermark + u.window * u.chunk;
    while (u.nextOffset < u.total && u.nextOffset < ceiling) {
      final int start = u.nextOffset;
      final int end = (start + u.chunk) < u.total ? start + u.chunk : u.total;
      final Uint8List piece = Uint8List.sublistView(u.bytes, start, end);
      // FILE_PUT_DATA 0x16 [offset:u32][bytes] — CMD, NO RSP.
      unawaited(
        _engine
            .fire(_cmd(PbleOpcode.filePutData, <int>[..._u32(start), ...piece]))
            .catchError((Object e) {
              if (!u.done.isCompleted) {
                u.done.completeError(
                  e is PbleException
                      ? e
                      : const NotConnectedException('upload write failed'),
                );
              }
            }),
      );
      u.nextOffset = end;
    }
  }

  /// Closes an aborted upload on the BOARD so its single transfer slot is freed
  /// (protocol.md §5). Sends `FILE_PUT_END`, which for an incomplete temp answers
  /// `ERANGE`/`ECRC`, deletes the temp and keeps the old file — exactly the
  /// abort semantics we want. Every failure here is swallowed on purpose: this
  /// runs while a REAL error is propagating, and a dead link (the common cause)
  /// would otherwise replace the caller's honest error with a timeout.
  Future<void> _releaseBoardTransfer(int crc) async {
    try {
      await _engine
          .request(
            _cmd(PbleOpcode.filePutEnd, _u32(crc)),
            timeout: const Duration(seconds: 2),
          )
          .catchError((Object _) => _cmd(PbleOpcode.filePutEnd, const <int>[]));
    } catch (_) {
      // Link already gone: the board resets its own transfer state on
      // disconnect, so the slot is freed anyway.
    }
  }

  /// (Re-)arms the upload inactivity watchdog. Re-armed on every ACK that makes
  /// progress (advances the watermark); a filled window that then goes silent —
  /// no further ACK progress within [dataTimeout] — fails typed instead of
  /// hanging (FR-PBLE-9 honesty). A non-advancing (dup/gap) ACK does NOT re-arm:
  /// a board that only re-acks its stale watermark is still stalled.
  void _armPutStall(_Upload u) {
    _putStallTimer?.cancel();
    _putStallTimer = Timer(dataTimeout, () {
      if (!u.done.isCompleted) {
        u.done.completeError(
          const PbleTimeoutException(
            'upload stalled: no ACK progress from the board',
          ),
        );
      }
    });
  }

  @override
  Future<void> delete(String path) async {
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.fileDelete, _pathField(path)),
    );
    _checkStatus(rsp);
  }

  @override
  Future<void> mkdir(String path) async {
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.mkdir, _pathField(path)),
    );
    _checkStatus(rsp);
  }

  @override
  Future<void> rename(String from, String to) async {
    // FILE_RENAME 0x1A [slen][src][dlen][dst].
    final PbleFrame rsp = await _engine.request(
      _cmd(PbleOpcode.fileRename, <int>[
        ..._pathField(from),
        ..._pathField(to),
      ]),
    );
    _checkStatus(rsp);
  }

  @override
  Future<void> dispose() async {
    _downloadStallTimer?.cancel();
    _putStallTimer?.cancel();
    if (_linkListener != null) {
      _observedLink?.linkState.removeListener(_linkListener!);
    }
    await _eventsSub.cancel();
    await _engine.dispose();
    await _runStateController.close();
    await _consoleController.close();
    _state.dispose();
  }

  // --- inbound EVT routing (protocol.md §6 / §5) -----------------------------

  void _onEvent(PbleFrame frame) {
    final int op = frame.opcode;
    final Uint8List p = frame.payload;

    if (op == PbleOpcode.runState.code) {
      final RunState rs = _runStateFromByte(p.isEmpty ? 0 : p[0]);
      if (!_runStateController.isClosed) _runStateController.add(rs);
      _applyRunStateToConn(rs);
    } else if (op == PbleOpcode.consoleData.code) {
      final int stream = p.isEmpty ? 0 : p[0];
      final Uint8List bytes = p.length > 1
          ? Uint8List.sublistView(p, 1)
          : Uint8List(0);
      final ConsoleStream cs = stream == 1
          ? ConsoleStream.stderr
          : ConsoleStream.stdout;
      if (!_consoleController.isClosed) {
        _consoleController.add(ConsoleEvent(stream: cs, bytes: bytes));
      }
    } else if (op == PbleOpcode.fileGetData.code) {
      final _Download? d = _download;
      if (d == null) return;
      // [offset:u32][bytes] — bytes arrive in order for a single transfer.
      final Uint8List bytes = p.length > 4
          ? Uint8List.sublistView(p, 4)
          : Uint8List(0);
      d.builder.add(bytes);
      d.received += bytes.length;
      _armDownloadStall(d); // data flowed: push the stall deadline out
      d.onProgress?.call(TransferProgress(sent: d.received, total: d.total));
    } else if (op == PbleOpcode.fileGetEnd.code) {
      final _Download? d = _download;
      if (d == null || d.completer.isCompleted) return;
      final int crc = _readU32(p, 0);
      final Uint8List assembled = d.builder.toBytes();
      if (assembled.length != d.total || pbleCrc32(assembled) != crc) {
        // Never report a bad whole-file transfer as success (FR-PBLE-9).
        d.completer.completeError(
          const ECrc('download whole-file size/CRC mismatch'),
        );
      } else {
        d.completer.complete(assembled);
      }
    } else if (op == PbleOpcode.filePutAck.code) {
      // FILE_PUT_ACK 0x41 [ack_offset:u32] — the cumulative watermark. Drives
      // the sliding window (A-13): a HIGHER offset advances the base + releases
      // credit (one ACK may retire several chunks); a non-advancing offset is a
      // GAP signal → Go-Back-N retransmit from the watermark.
      final _Upload? u = _upload;
      if (u == null || u.done.isCompleted) return;
      final int ack = _readU32(p, 0);
      if (ack > u.watermark) {
        // Advance the base (clamp: never past total). Progress is watermark-
        // driven, so it is monotonic and a resend never moves the bar back.
        u.watermark = ack < u.total ? ack : u.total;
        u.onProgress?.call(TransferProgress(sent: u.watermark, total: u.total));
        _armPutStall(u); // progress: push the stall deadline out
        if (u.watermark >= u.total) {
          if (!u.done.isCompleted) u.done.complete();
          return;
        }
        if (u.nextOffset < u.watermark) u.nextOffset = u.watermark;
        _pumpWindow(u); // release credit: fire up to W again
      } else {
        // Non-advancing cumulative ACK = the board's watermark did not move: a
        // chunk was dropped/out-of-order. Go-Back-N — rewind to the watermark
        // and retransmit the window (never before it, never past the file end).
        u.nextOffset = u.watermark;
        _pumpWindow(u);
      }
    }
  }

  void _applyRunStateToConn(RunState rs) {
    // ConnState.running is DERIVED and only meaningful once the session is up:
    // never override disconnected/connecting. done/idle/error collapse to ready.
    final ConnState cur = _state.value;
    if (cur == ConnState.ready || cur == ConnState.running) {
      _state.value = rs == RunState.running
          ? ConnState.running
          : ConnState.ready;
    }
  }

  RunState _runStateFromByte(int b) => switch (b) {
    1 => RunState.running,
    2 => RunState.done,
    3 => RunState.error,
    _ => RunState.idle,
  };

  // --- helpers ---------------------------------------------------------------

  /// Builds a CMD frame on [op] with a fresh correlation ID.
  PbleFrame _cmd(PbleOpcode op, List<int> payload) => PbleFrame(
    type: Pble.typeCmd,
    opcode: op.code,
    id: _engine.nextId(),
    payload: Uint8List.fromList(payload),
  );

  /// Throws the typed §8 exception for a non-OK RSP `[status]` byte; OK returns.
  void _checkStatus(PbleFrame rsp) {
    final int code = rsp.payload.isEmpty
        ? PbleStatus.eInternal.code
        : rsp.payload[0];
    final PbleStatus status = PbleStatus.fromCode(code) ?? PbleStatus.eInternal;
    final PbleException? err = pbleExceptionForStatus(status);
    if (err != null) throw err;
  }

  /// The negotiated `PUT` chunk size, falling back if caps did not report one.
  int _chunkSize() {
    final int c = _hello?.caps.chunk ?? 0;
    return c > 0 ? c : 128;
  }

  /// Claims the single active-transfer slot (SEC-2 / FR-CONN-9); a concurrent
  /// transfer is refused with [EBusy] BEFORE any BEGIN frame is sent.
  void _beginTransfer() {
    if (_transferActive) {
      throw const EBusy('another file transfer is already active');
    }
    _transferActive = true;
  }

  void _endTransfer() => _transferActive = false;

  /// The negotiated sliding-window depth `W` (HELLO caps.window; ref agent 8),
  /// falling back to 4 if caps did not advertise a positive window (FR-PBLE-8).
  int _window() {
    final int w = _hello?.caps.window ?? 0;
    return w > 0 ? w : 4;
  }

  // little-endian scalar codecs (protocol.md §5 "all multi-byte LE").
  List<int> _u16(int v) => <int>[v & 0xff, (v >> 8) & 0xff];

  List<int> _u32(int v) => <int>[
    v & 0xff,
    (v >> 8) & 0xff,
    (v >> 16) & 0xff,
    (v >> 24) & 0xff,
  ];

  /// A `[plen:u16][path UTF-8]` field (protocol.md §5).
  List<int> _pathField(String path) {
    final List<int> bytes = utf8.encode(path);
    return <int>[..._u16(bytes.length), ...bytes];
  }

  int _readU16(Uint8List b, int off) => b[off] | (b[off + 1] << 8);

  int _readU32(Uint8List b, int off) =>
      b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24);
}

/// In-progress download context (the only per-transfer state on [PbleConnection]
/// beyond the active-writer flag).
class _Download {
  _Download({required this.total, required this.onProgress});

  final int total;
  final ProgressCb? onProgress;
  final BytesBuilder builder = BytesBuilder(copy: false);
  final Completer<Uint8List> completer = Completer<Uint8List>();
  int received = 0;
}

/// In-progress windowed upload context (A-13). The wire is window-agnostic
/// (protocol.md §5 is FROZEN): [window] is the client-side pacing credit from
/// HELLO caps.window, never a wire field.
class _Upload {
  _Upload({
    required this.bytes,
    required this.total,
    required this.chunk,
    required this.window,
    required this.watermark,
    required this.onProgress,
  }) : nextOffset = watermark;

  final Uint8List bytes;
  final int total;
  final int chunk;
  final int window;
  final ProgressCb? onProgress;

  /// Cumulative acked offset — the window base and the resume floor. Advances
  /// only on a higher FILE_PUT_ACK; a Go-Back-N resend never rewinds below it.
  int watermark;

  /// High-water of chunks put on the wire. Advances as chunks are fired; a
  /// Go-Back-N resend rewinds it to [watermark] to retransmit the window.
  int nextOffset;

  /// Completes when the whole file is acked (watermark == total); completes with
  /// a typed error on stall / link-drop / write failure.
  final Completer<void> done = Completer<void>();
}
