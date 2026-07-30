// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: lower-hex <-> bytes helpers for the PBLE/1 codec + conformance
// suites. Pure Dart; imports no `lib/**`. Owner: app-test-author.

import 'dart:typed_data';

/// Decodes a lower/upper-hex string (even length, no separators) to bytes.
Uint8List hexToBytes(String hex) {
  if (hex.length.isOdd) {
    throw ArgumentError.value(hex, 'hex', 'odd-length hex string');
  }
  final out = Uint8List(hex.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(hex.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}

/// Encodes bytes as a contiguous lower-hex string (matching the corpus form).
String bytesToHex(List<int> bytes) =>
    bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
