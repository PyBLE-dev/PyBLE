// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/pble/` — the PBLE/1 client and the single [Connection] seam every
/// widget binds to (docs/specifications/app.md §2 and §3).
///
/// This is the ONLY layer that knows the wire. It will grow the frame codec +
/// CRC, fragmentation/reassembly, request/response correlation, the file-
/// transfer state machine (window + resume), the console stream, and the
/// status-byte → `PbleException` mapping — authored fresh against the FROZEN
/// docs/specifications/protocol.md (PBLE/1), with no proprietary wire, opcodes,
/// or UUIDs (clean-room, CON-6 / FR-PBLE-15).
///
/// The seam the UI binds to — `ConnState`, `DeviceInfo`, `Connection`,
/// `FakeConnection`, and the typed `PbleException` hierarchy — is exported here.
/// The wire internals (frame codec, fragmentation, engine, HELLO, transport,
/// the constants mirror) stay usable within `lib/pble` but are NOT part of the
/// UI-facing surface, so a widget can never reach a frame/opcode/status byte.
///
/// A-10/S2 adds the PBLE/1 client (codec + CRC, fragmentation, ID correlation,
/// HELLO/caps negotiation) and the wire-backed `PbleConnection`; the run/console
/// /file verbs land at A-11/A-12/A-13/A-14 (S3–S4).
library;

// The neutral BLE readiness type + source are DEFINED in lib/ble (retyped off
// the platform there) and re-exported through this barrel so widgets reach them
// via lib/pble only — the single sanctioned import path (FR-BLE-8, CON-8). The
// runtime ConnectionManager takes a BleReadinessSource, so both cross the seam.
export '../ble/ble_readiness.dart' show BleReadiness, BleReadinessSource;
export 'conn_state.dart';
export 'connection.dart';
export 'connection_manager.dart'
    show
        ConnectionManager,
        PbleConnectionManager,
        ConnectPhase,
        ConnectionFactory;
export 'fake_connection.dart';
export 'pble_connection.dart' show PbleConnection;
export 'pble_exception.dart';
export 'scan_hit.dart';
export 'scanner.dart' show Scanner, FakeScanner;
export 'types.dart';
