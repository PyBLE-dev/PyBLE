// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'types.dart';

/// Strict PBLE/1 §6.1 snapshot decoder. An advertised malformed snapshot must
/// never be interpreted as idle or as an unsupported capability.
RunSnapshot decodeRunSnapshot(Uint8List bytes) {
  Never invalid() => throw const PbleFormatException('invalid run snapshot');
  if (bytes.length != 25 || bytes[0] != 1) invalid();
  final Uint8List boot = Uint8List.sublistView(bytes, 1, 9);
  if (boot.every((int b) => b == 0)) invalid();
  final ByteData data = ByteData.sublistView(bytes);
  final int runId = data.getUint32(9, Endian.little);
  final int revision = data.getUint64(13, Endian.little);
  final int state = bytes[21];
  final int origin = bytes[22];
  final int reason = bytes[23];
  final int flags = bytes[24];
  if (revision > 9007199254740991 ||
      state > 3 ||
      origin > 3 ||
      reason > 3 ||
      (flags & ~3) != 0) {
    invalid();
  }
  if (runId == 0) {
    if (revision != 0 ||
        state != 0 ||
        origin != 0 ||
        reason != 0 ||
        flags != 0) {
      invalid();
    }
  } else {
    if (origin == 0 || revision < runId) invalid();
    if (state == 1) {
      if (reason != 0) invalid();
    } else {
      if (flags != 0 ||
          reason !=
              switch (state) {
                0 => 3,
                2 => 1,
                _ => 2,
              }) {
        invalid();
      }
    }
  }
  return RunSnapshot(
    bootId: boot.map((int b) => b.toRadixString(16).padLeft(2, '0')).join(),
    runId: runId,
    revision: revision,
    state: RunState.values[state],
    origin: RunOrigin.values[origin],
    terminalReason: RunTerminalReason.values[reason],
    queued: (flags & 1) != 0,
    stopping: (flags & 2) != 0,
  );
}
