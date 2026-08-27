# PyBLE app

The PyBLE app is a Flutter, tablet-first MicroPython IDE for iPadOS and
Android. It communicates with compatible boards through PBLE/1 over Bluetooth
Low Energy.

## Current capabilities

- BLE discovery, connection, reconnect, and capability negotiation
- Python editing with syntax highlighting, synchronized one-based line numbers,
  adjustable 10–24 point code sizing, save, run, stop, soft reboot, and live
  console
- Wireless filesystem browsing and integrity-checked transfer
- Optional public, unauthenticated GitHub browsing with immutable commit
  pinning, exact board-target review, and bounded `.py` import into the current
  connected Files folder
- Offline Blockly workspace with beginner examples, GPIO, and NeoPixel blocks
- Exact Blockly sidecars and bounded Python-to-block conversion
- Adaptive portrait and landscape layouts
- Offline About, notices, and privacy information

The public iPad beta is available through
[TestFlight](https://testflight.apple.com/join/yU4e8s6d).

GitHub import is the app's sole optional internet workflow. It sends no account
credential, board fact, or source file; it never auto-opens or runs imported
code. Editing, BLE, Files, Blocks, and Run remain account-free and independent
of GitHub availability.

## Requirements

- Flutter stable matching the version pinned in root CI
- Xcode for iPadOS builds
- Android SDK for Android builds and integration tests
- A supported BLE adapter or the test fakes for host-side tests

## Develop

```sh
flutter pub get --enforce-lockfile
flutter gen-l10n
dart format --output=none --set-exit-if-changed lib test integration_test
flutter analyze
flutter test --exclude-tags golden
```

Pixel goldens use reviewed macOS baselines. Run them separately on macOS:

```sh
flutter test --tags golden
```

Install a standalone development build on a connected device (the current
source build is `0.2.0+5`):

```sh
flutter run --release -d <device-id>
```

Platform WebView integration tests live under `integration_test/`. CI runs
unit, widget, and PBLE/1 conformance tests on Linux, exact pixel goldens on a
pinned macOS runner, and the real Blockly WebView integration on Android.

## Architecture and dependencies

- Public app contract: [`docs/specifications/app.md`](../docs/specifications/app.md)
- Detailed app specifications:
  [`docs/specifications/App/`](../docs/specifications/App/)
- PBLE/1 wire contract:
  [`docs/specifications/protocol.md`](../docs/specifications/protocol.md)
- Dependency and license ledger: [`DEPENDENCIES.md`](DEPENDENCIES.md)

Only `lib/pble/` may depend on the raw `lib/ble/` adapter. UI and features work
through the neutral connection interface, keeping tests hardware-independent.

Official distribution signing is maintainer-local. The repository contains no
certificate, provisioning profile, private key, or store credential.
