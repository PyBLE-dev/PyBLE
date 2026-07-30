// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:typed_data';

import 'engine.dart';
import 'frame.dart';
import 'pble_constants.dart';
import 'types.dart'; // re-exports pble_exception.dart (the neutral type family)

/// The result of a successful HELLO exchange (protocol.md §7).
class HelloResult {
  const HelloResult(this.protoVersion, this.caps);

  /// The `proto_version` the board selected (guaranteed to be in the offer).
  final int protoVersion;

  /// The negotiated capabilities, mapped to a neutral [DeviceInfo].
  final DeviceInfo caps;
}

/// Drives the PBLE/1 HELLO version + capability negotiation (protocol.md §7/§9).
///
/// HELLO is the FIRST exchange after connect (FR-PBLE-5): the client offers
/// `proto_versions[]` and its app name/version, the board replies
/// `[status:u8][caps]`. A non-OK status surfaces as its typed §8 exception (via
/// [pbleExceptionForStatus], the same table the run/file verbs use); a
/// `proto_version` the client did not offer is refused with a typed
/// [UnsupportedProtocolException] (FR-PBLE-6) — the app never speaks an
/// unsupported version, and never silently proceeds.
class HelloNegotiator {
  HelloNegotiator({
    required this.engine,
    required this.appName,
    required this.appVersion,
  });

  final PbleEngine engine;
  final String appName;
  final String appVersion;

  /// Performs the HELLO exchange and returns the negotiated result.
  Future<HelloResult> negotiate({List<int> offer = Pble.protoOffer}) async {
    final PbleFrame cmd = PbleFrame(
      type: Pble.typeCmd,
      opcode: PbleOpcode.hello.code,
      id: engine.nextId(),
      payload: _encodeHelloRequest(offer),
    );
    final PbleFrame rsp = await engine.request(cmd);

    final Uint8List payload = rsp.payload;
    if (payload.isEmpty) {
      throw const PbleFormatException('empty HELLO response payload');
    }

    // RSP payload = [status:u8][caps]  (§7).
    final int statusByte = payload[0];
    if (statusByte != PbleStatus.ok.code) {
      // Non-OK → its distinct typed §8 subtype (never a catch-all).
      throw pbleExceptionForStatus(
        PbleStatus.fromCode(statusByte) ?? PbleStatus.eInternal,
      )!;
    }

    final DeviceInfo caps = parseCaps(
      utf8.decode(payload.sublist(1), allowMalformed: true),
    );

    // §9: refuse a chosen proto_version the client did not offer.
    final int chosen = caps.protoVersion;
    if (!offer.contains(chosen)) {
      throw UnsupportedProtocolException(List<int>.unmodifiable(offer), chosen);
    }

    return HelloResult(chosen, caps);
  }

  /// Serializes the HELLO CMD request body.
  ///
  /// NOTE: the §7 HELLO *request* byte-serialization is NOT frozen (no
  /// conformance vector asserts it — the shared corpus treats HELLO payloads as
  /// opaque). This mirrors the observed newline `key=value` caps form for
  /// symmetry; it is provisional and will be reconciled when protocol.md §7
  /// freezes the payload encoding.
  Uint8List _encodeHelloRequest(List<int> offer) {
    final String text = <String>[
      'proto_versions=${offer.join(',')}',
      'app_name=$appName',
      'app_version=$appVersion',
    ].join('\n');
    return Uint8List.fromList(utf8.encode(text));
  }
}

/// Parses PBLE/1 caps text into a neutral [DeviceInfo] (protocol.md §7).
///
/// `caps` is newline-separated ASCII `key=value` text. The parser is TOLERANT
/// (§9 additive): unknown keys are ignored, missing keys fall back to defaults,
/// and malformed lines are skipped — so a newer board never breaks an older
/// client.
///
/// `identify_led = 255` maps to "none" (`null`); `identify_led` is a display
/// GPIO int, never a profile/gate (CON-7). `device_id`/`label` are DISPLAY-ONLY
/// (SEC-9) and never used to authorize or build a registry.
DeviceInfo parseCaps(String capsText) {
  final Map<String, String> caps = <String, String>{};
  for (final String rawLine in capsText.split('\n')) {
    final String line = rawLine.trim();
    if (line.isEmpty) continue;
    final int eq = line.indexOf('=');
    if (eq < 0) continue; // tolerate malformed lines
    caps[line.substring(0, eq).trim()] = line.substring(eq + 1);
  }

  int? intOf(String key) {
    final String? v = caps[key];
    return v == null ? null : int.tryParse(v.trim());
  }

  bool boolOf(String key) => (caps[key]?.trim() ?? '0') == '1';

  final int? ledRaw = intOf('identify_led');

  return DeviceInfo(
    // S1 identity/base fields.
    chip: caps['chip'] ?? '',
    mpyVersion: caps['mpy'] ?? caps['mpy_version'] ?? '',
    freeMem: intOf('free_mem') ?? 0,
    fsRoot: caps['fs_root'] ?? '/',
    deviceId: caps['device_id'] ?? '',
    label: caps['label'] ?? '',
    // S2 negotiated caps.
    protoVersion: intOf('proto') ?? Pble.protoVersion,
    agentVersion: caps['agent'] ?? caps['agent_version'] ?? '',
    mtu: intOf('mtu') ?? 23,
    window: intOf('window') ?? 4,
    chunk: intOf('chunk') ?? 0,
    hasSd: boolOf('has_sd'),
    hasIdentify: boolOf('has_identify'),
    identifyLed: (ledRaw == null || ledRaw == 255) ? null : ledRaw,
    autoRun: boolOf('auto_run'),
  );
}
