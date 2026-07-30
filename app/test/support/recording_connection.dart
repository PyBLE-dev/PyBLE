// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: a RECORDING Connection double for the working-loop [red] suites
// (ADR-0010, TDD §11.6). It EXTENDS the shipped `FakeConnection` (owner:
// app-protocol-engineer, lib/pble) so every scripting hook — emit / emitRunState
// / emitConsole / injectError + the in-memory file tree — is inherited
// unchanged, and adds the observability the loop tests need: which board verb
// was invoked, and with what arguments (Run → putFile + runFile, stdin →
// sendInput, upload → putFile, …).
//
// This is scaffold the test-author OWNS (test/support); it adds NO lib/** code
// and needs no new FakeConnection hook — the recording is a thin decorator over
// the existing verbs. If a future suite needs the SHIPPED FakeConnection itself
// to record calls, that is a hand-off to app-protocol-engineer; for the loop, a
// test-side recorder is sufficient and keeps lib/pble untouched.

import 'dart:typed_data';

import 'package:pyble/pble/pble.dart';

/// One recorded `putFile` invocation (target path + the bytes written).
class PutFileCall {
  const PutFileCall(this.path, this.bytes);
  final String path;
  final Uint8List bytes;
}

/// A [FakeConnection] that records the run / console / file verbs it receives,
/// while delegating behaviour (and every scripting hook) to `super`.
///
/// [steppedProgress] makes transfers emit their [TransferProgress] across
/// separate microtasks (not the shipped fake's single synchronous burst) so a
/// controller/widget observer can actually SEE intermediate progress — Riverpod
/// coalesces rapid synchronous state updates, hiding a burst. (A recommended,
/// non-blocking enhancement to the SHIPPED `FakeConnection` for
/// app-protocol-engineer: a stepped/async progress mode usable by every suite.)
class RecordingConnection extends FakeConnection {
  RecordingConnection({
    super.initial = ConnState.disconnected,
    super.deviceInfo,
    this.steppedProgress = false,
  });

  /// When true, transfers report progress across microtasks (observable).
  final bool steppedProgress;

  Future<void> _stepProgress(int total, ProgressCb cb) async {
    const int steps = 4;
    for (int i = 0; i <= steps; i++) {
      await Future<void>.delayed(Duration.zero);
      cb(TransferProgress(sent: (total * i / steps).floor(), total: total));
    }
  }

  /// Snippets passed to [runSource], in call order.
  final List<String> runSourceCalls = <String>[];

  /// Paths passed to [runFile], in call order.
  final List<String> runFileCalls = <String>[];

  /// Cross-verb order for workflows whose safety depends on sequencing.
  final List<String> operationLog = <String>[];

  /// Number of [stop] invocations.
  int stopCalls = 0;

  /// Number of [softReboot] invocations.
  int softRebootCalls = 0;

  /// Text lines passed to [sendInput], in call order.
  final List<String> sendInputCalls = <String>[];

  /// Recorded [putFile] invocations, in call order.
  final List<PutFileCall> putFileCalls = <PutFileCall>[];

  /// Paths passed to [getFile], in call order.
  final List<String> getFileCalls = <String>[];

  /// Paths passed to [delete], in call order.
  final List<String> deleteCalls = <String>[];

  /// Paths passed to [mkdir], in call order.
  final List<String> mkdirCalls = <String>[];

  /// `(from, to)` pairs passed to [rename], in call order.
  final List<(String, String)> renameCalls = <(String, String)>[];

  @override
  Future<void> runSource(String snippet) {
    runSourceCalls.add(snippet);
    return super.runSource(snippet);
  }

  @override
  Future<void> runFile(String path) {
    operationLog.add('runFile:$path');
    runFileCalls.add(path);
    return super.runFile(path);
  }

  @override
  Future<void> stop() {
    stopCalls++;
    return super.stop();
  }

  @override
  Future<void> softReboot() {
    softRebootCalls++;
    return super.softReboot();
  }

  @override
  Future<void> sendInput(String text) {
    sendInputCalls.add(text);
    return super.sendInput(text);
  }

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    operationLog.add('putFile:$path');
    putFileCalls.add(PutFileCall(path, Uint8List.fromList(bytes)));
    if (steppedProgress && onProgress != null) {
      await super.putFile(path, bytes); // write the tree, no synchronous burst
      await _stepProgress(bytes.length, onProgress);
      return;
    }
    return super.putFile(path, bytes, onProgress: onProgress);
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async {
    getFileCalls.add(path);
    if (steppedProgress && onProgress != null) {
      final Uint8List bytes = await super.getFile(path);
      await _stepProgress(bytes.length, onProgress);
      return bytes;
    }
    return super.getFile(path, onProgress: onProgress);
  }

  @override
  Future<void> delete(String path) {
    deleteCalls.add(path);
    return super.delete(path);
  }

  @override
  Future<void> mkdir(String path) {
    mkdirCalls.add(path);
    return super.mkdir(path);
  }

  @override
  Future<void> rename(String from, String to) {
    renameCalls.add((from, to));
    return super.rename(from, to);
  }
}
