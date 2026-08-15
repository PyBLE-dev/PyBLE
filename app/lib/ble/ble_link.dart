// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/foundation.dart' show ValueListenable;

/// The lifecycle state of a GATT link, retyped off the transport (no
/// `flutter_blue_plus` enum crosses the seam). Auto-reattempt on an unexpected
/// drop lives HERE in `lib/ble` (FR-BLE-4, TDD §7.3) via [ReconnectingBleLink];
/// `lib/pble` only maps these transitions onto its `ConnState` (FR-CONN-5).
///
///   • [disconnected] — down: never connected, backoff exhausted, or a
///     user-initiated `disconnect()`;
///   • [connecting] — first establishment in progress;
///   • [connected] — link up (TX subscribed, MTU negotiated);
///   • [reconnecting] — auto-reattempt in progress after an *unexpected* drop.
///
/// Order is additive to the S2 two-value enum; do not reorder (§7.3).
enum BleLinkState { disconnected, connecting, connected, reconnecting }

/// The byte pipe over a single GATT connection — the whole surface the protocol
/// layer runs on. It moves bytes and NOTHING else: no framing, no CRC, no
/// fragmentation, no opcode routing (that is all `lib/pble`, FR-BLE-3).
///
///   • [inbound] surfaces raw TX (…0003) notification payloads, uninterpreted;
///   • [write] pushes already-encoded bytes to RX (…0002) using the requested
///     acknowledged or Write-Without-Response GATT mode;
///   • [mtu] is the negotiated ATT MTU (247 requested, down to the BLE default)
///     so `lib/pble` can size fragments at `MTU − 4` (FR-BLE-2);
///   • [linkState] surfaces up/down transitions for the layer above.
abstract interface class BleLink {
  /// Raw TX notification payloads, byte-for-byte (never parsed).
  Stream<List<int>> get inbound;

  /// Writes already-encoded bytes to RX using the selected GATT write mode.
  Future<void> write(List<int> bytes, {required bool withoutResponse});

  /// The negotiated ATT MTU (BLE default 23 up to the requested 247).
  int get mtu;

  /// Lifecycle state of this link. A self-reconnecting link ([ReconnectingBleLink])
  /// drives the full four-state sequence; a single-connection link toggles
  /// [BleLinkState.connected]/[BleLinkState.disconnected].
  ValueListenable<BleLinkState> get linkState;

  /// Tears the GATT connection down.
  Future<void> disconnect();
}
