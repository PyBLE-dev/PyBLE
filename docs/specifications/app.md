# PyBLE — App Architecture

Status: **DRAFT** · Last updated: 2026-08-15

The PyBLE app is a Flutter, tablet-first IDE for iPad and Android. It connects
to a compatible MicroPython board over BLE, speaks PBLE/1, and presents an
editor, console, file explorer, block editor, and plots. Discovery and feature
availability are service- and capability-driven, never gated by a silicon
vendor or a fixed chip allowlist. ESP32, ESP32-S3, and ESP32-C3 are the initial
firmware targets.

> **Detailed app docs:** this page is the overview. The full requirements live in [`App/specs.md`](App/specs.md) and the technical design in [`App/TDD.md`](App/TDD.md) (Technical Design Document), both derived from [PRD §9](prd.md).

## 1. Layering

```
UI widgets (editor · console · files · blocks · plots · connect)
        │   (callbacks only — no transport imports)
        ▼
PBLE/1 client     lib/pble/      ── Connection API
        │
        ▼
BLE adapter       lib/ble/       ── byte stream in/out
        │
        ▼
flutter_blue_plus
```

Strict rule: **UI widgets never import `lib/ble/`**, and only the `lib/pble/` client knows the wire format. This keeps the editor/console/files transport-agnostic and testable against a fake `Connection`.

## 2. Packages / directories

| Path | Responsibility |
|---|---|
| `lib/ble/` | `flutter_blue_plus` wrapper: scan filtered to the PyBLE service UUID, connect, MTU 247, `Stream<List<int>>` in / mode-explicit `write(bytes)` out, connection-state + reconnect. |
| `lib/pble/` | PBLE/1 client: frame codec + CRC, fragmentation/reassembly, acknowledged response-bearing writes, fire-and-forget WWR, request/response correlation under one absolute deadline, file-transfer state machine (window + resume), console stream, error→exception mapping. Exposes `Connection`. |
| `lib/editor/` | Code editor (`flutter_code_editor`), Run/Save actions, file tabs. |
| `lib/console/` | Live console view + stdin input; traceback rendering. |
| `lib/files/` | Board file explorer: list/open/upload/download/rename/delete/mkdir, multi-select. |
| `lib/blocks/` | Blockly (WebView) → inspectable MicroPython generation (numeric `machine.Pin`, `time.sleep_ms`, standard `neopixel.NeoPixel`, and explicit `pyble_st7789` TFT subset) → eight offline editable beginner examples with explicit GPIO choice → shared Run/Save path. The TFT UI is bundled independently of the connected target; its generated import requires the exact `waveshare-esp32-s3-lcd-147b` firmware or a user-installed API-compatible module. |
| `lib/plots/` | `fl_chart` views over CSV/streamed values. |
| `lib/connect/` | Scan/connect UI, saved boards. |
| `lib/github_import/` | Pull a folder of `.py` from a public GitHub repo → `Connection.putFile`. |
| `lib/localization/` | `intl`/ARB strings (`en` first; parity enforced for added languages). |
| `lib/data/` | Local persistence: projects, settings, saved boards (offline-first). |

## 3. The `Connection` API (the seam every widget binds to)

```dart
abstract interface class Connection {
  ValueListenable<ConnState> get state;       // disconnected/connecting/ready/running
  Future<DeviceInfo> deviceInfo();

  // run / console
  Future<void> runFile(String path);
  Future<void> runSource(String source);
  Future<void> stop();
  Future<void> softReboot();
  Stream<ConsoleEvent> get console;           // {stream: stdout|stderr|system, bytes}
  Future<void> sendInput(String text);

  // files
  Future<List<RemoteEntry>> listDir(String path);
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress});
  Future<void> putFile(String path, Uint8List bytes, {ProgressCb? onProgress});
  Future<void> delete(String path);
  Future<void> mkdir(String path);
  Future<void> rename(String from, String to);
}
```

Widgets receive a `Connection` (or narrow callbacks derived from it). Tests inject a `FakeConnection`. There is no QR pairing, no lease/heartbeat, and no board-specific gating — just scan, connect, use.

## 4. Connect flow

1. **Scan** — `flutter_blue_plus` scan filtered to the PyBLE service UUID; show advertised `PyBLE-XXXX` names + RSSI.
2. **Connect** — open GATT, subscribe to TX notify, request MTU 247, read INFO / send HELLO, show `DeviceInfo`, including its display-only board ID and PyBLE agent firmware version.
3. **Use** — editor/console/files bind to the `Connection`.
4. **Reconnect** — on link loss, auto-reattempt; in-flight file transfers resume via PBLE/1 §5. Saved boards reconnect by remembered identifier.

The `DeviceInfo.chip` value is a port-defined technical identifier. The app
renders unknown future values verbatim and continues from advertised PBLE/1
capabilities; a missing in-app pin reference is informational and MUST NOT
block the connection.

The connected Board-info card renders `DeviceInfo.deviceId` as **Board ID** and
`DeviceInfo.agentVersion` as **PyBLE firmware**, verbatim. It MUST NOT substitute
the platform scan identifier, derive either value, or use either value as an
authorization/profile gate. When a legacy or nonconforming agent reports an
empty value, the card shows a localized **Not reported** fallback and keeps the
connection usable.

`DeviceInfo.chip == "esp32-s3"` does not identify which provisioning image is
installed and cannot distinguish the lean `esp32-s3-n16r8` image from the
separate `waveshare-esp32-s3-lcd-147b` image. The app therefore MUST NOT infer
either release profile, hide or enable TFT tools, auto-select the exact-board
example, or gate a connection from that value. TFT module availability remains
an ordinary MicroPython import/runtime result on the connected board.

## 5. Platform notes

- **iPadOS + Android** at parity. BLE permissions: iOS `NSBluetoothAlwaysUsageDescription`; Android `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` (Android 12+) and location handling on older versions.
- **No USB serial, no Wi-Fi onboarding** — BLE only (this is what makes iPad first-class).
- Tablet-first responsive layout (split editor/console/files); must not break on a phone.

## 6. Reuse provenance (clean-room note)

Several board-agnostic widgets (editor, console, file explorer, plots, Blockly bridge, GitHub import, tablet scaffold, localization) are **re-implemented or relicensed-MIT by the author** from their own prior art, retyped onto PyBLE's neutral types (`Connection`, `ConsoleEvent`, `RemoteEntry`). They carry **no** closed-source protocol client, board profiles, UUIDs, catalog, curriculum, or pedagogy — the PBLE/1 client, BLE adapter, and eight small starter workspaces are written fresh for PyBLE. The eighth is an explicitly named hardware example with disconnected pin roles and truthful module-availability guidance, not a board registry, connection gate, or lesson flow. See the [clean-room boundary](architecture.md#5-clean-room--ip-boundary), [ADR-0002](../decisions/0002-fresh-protocol.md), [ADR-0016](../decisions/0016-offline-beginner-blockly-examples.md), [ADR-0023](../decisions/0023-explicit-st7789-user-runtime.md), and [ADR-0028](../decisions/0028-separate-waveshare-lcd147b-firmware-profile.md).

## 7. Testing

- **`lib/pble/`** — conformance tests against PBLE/1 (frame round-trips, CRC, fragmentation, file-transfer window/resume, error mapping) using an in-memory fake transport.
- **`lib/ble/`** — mocked-transport tests for scan filter, connect, reconnect.
- **UI** — widget + golden tests against a `FakeConnection`; locale parity check
  for ARB; Blocks tests restore/generate every catalog workspace, require
  explicit GPIO roles, and prove Preview/cancel/failure never mutate work or
  perform an implicit board action; TFT tests additionally prove exact runtime
  imports, explicit geometry/pins, Python round-trip, and that toolbox/example
  visibility never depends on `DeviceInfo` or a provisioning profile. Example
  copy MUST state that the exact Waveshare firmware (or a separately installed
  compatible module) supplies the TFT runtime and that lean generic S3 firmware
  does not.
- **integration** — end-to-end against a fake board, plus on-device smoke tests
  for every target claimed by a release (initially ESP32, ESP32-S3, and
  ESP32-C3); an example copy must survive WebView recreation/rotation as
  ordinary workspace JSON.
