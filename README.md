# PyBLE

**Python over Bluetooth Low Energy** — an open-source, tablet-first
MicroPython IDE.

[![CI](https://github.com/PyBLE-dev/PyBLE/actions/workflows/ci.yml/badge.svg)](https://github.com/PyBLE-dev/PyBLE/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Platforms](https://img.shields.io/badge/app-iPadOS%20%7C%20Android-2D5BFF.svg)](#app)
[![Protocol](https://img.shields.io/badge/protocol-PBLE%2F1-0E7490.svg)](docs/specifications/protocol.md)

PyBLE lets you edit, transfer, run, and stop MicroPython programs on a
compatible microcontroller board over Bluetooth Low Energy. Its normal
workflow needs no USB serial connection, Wi-Fi onboarding, cloud account, or
telemetry.

- Website and browser installer: [pyble.dev](https://pyble.dev)
- iPad external beta:
  [join with TestFlight](https://testflight.apple.com/join/yU4e8s6d)
- License: [MIT](LICENSE)

## What works

### App

The Flutter app currently provides:

- filtered BLE discovery and PBLE/1 connection;
- a MicroPython editor with save, run, stop, soft reboot, and live console;
- wireless file browsing and transfer with integrity checks;
- an offline Blockly workspace with GPIO and standard MicroPython NeoPixel
  blocks;
- editable beginner examples;
- exact Blockly sidecar reopening and a bounded Python-to-blocks importer;
- an adaptive tablet interface for portrait and landscape use; and
- local operation without an account, analytics, or cloud dependency.

The iPad build is available through public TestFlight. Android source and CI
support are present; a public store channel has not been announced.

### Firmware

The board-side agent is built with upstream MicroPython and exposes PBLE/1 as a
BLE GATT peripheral. It supports:

- capability and device-information negotiation;
- run, stop, console, and soft-reboot control;
- filesystem operations with CRC validation and atomic uploads;
- resumable transfer behavior and bounded transport recovery;
- optional `main.py` auto-run protection;
- board naming and identify support; and
- upstream MicroPython’s standard `neopixel` module.

The public browser installer currently offers qualified images for:

| Installer profile | Typical target | Availability |
|---|---|---|
| `esp32-4mb` | Classic ESP32, 4 MB flash | Available |
| `esp32-s3-n16r8` | ESP32-S3, 16 MB flash / 8 MB PSRAM | Available |
| `esp32-c3-4mb` | ESP32-C3, 4 MB flash | Source target; public installer pending HIL |

These are the initial validated ports, not a chip-family allowlist. A future
board is compatible when it has a maintained PyBLE agent port, BLE GATT
peripheral support, adequate resources, PBLE/1 conformance, recovery testing,
and hardware-validation evidence. Stock MicroPython plus generic Bluetooth
hardware is not sufficient by itself.

## How it fits together

```text
┌─────────────────────────┐       PBLE/1 over BLE       ┌─────────────────────────┐
│ PyBLE Flutter app       │ ◀─────────────────────────▶ │ Compatible board        │
│ iPadOS / Android        │  run · files · console      │ MicroPython + agent     │
└─────────────────────────┘                             └─────────────────────────┘
```

This repository is intentionally a monorepo:

- [`app/`](app/) — the Flutter tablet application;
- [`firmware/`](firmware/) — the portable agent, board overlays, and release
  tooling;
- [`docs/specifications/protocol.md`](docs/specifications/protocol.md) — the
  open PBLE/1 wire contract;
- [`tests/`](tests/) — host, conformance, release, and HIL test runners;
- [`tools/`](tools/) — repository gates and the `pyble.dev` website; and
- [`docs/`](docs/) — public specifications, decisions, roadmap, and validation
  evidence.

Keeping these parts together lets a protocol change update the app, firmware,
shared conformance corpus, documentation, and CI atomically.

## Try PyBLE

1. Open [pyble.dev/flash](https://pyble.dev/flash) in desktop Chrome or Edge.
2. Select the exact supported profile for your board and flash the qualified
   agent firmware. Flashing erases the board; review the installer warning and
   back up files first.
3. Install the iPad beta from
   [TestFlight](https://testflight.apple.com/join/yU4e8s6d), or build the
   Flutter app locally.
4. Open PyBLE, scan for the board, connect, and run an example.

See [support and troubleshooting](https://pyble.dev/support) for browser,
Bluetooth, and recovery requirements.

## Build and test

Clone with both pinned upstream dependencies:

```sh
git clone --recurse-submodules https://github.com/PyBLE-dev/PyBLE.git
cd PyBLE
```

App:

```sh
cd app
flutter pub get --enforce-lockfile
flutter gen-l10n
dart format --output=none --set-exit-if-changed lib test integration_test
flutter analyze
flutter test
```

Firmware host tests:

```sh
tests/firmware_tests/run_tests.sh
```

Firmware build preparation and target builds:

```sh
firmware/scripts/install_esp_idf.sh
firmware/scripts/build.sh esp32
firmware/scripts/build.sh esp32-s3
firmware/scripts/build.sh esp32-c3
```

Website:

```sh
cd tools/web
npm ci
npm run check
```

The complete build requires the pinned toolchains documented in the relevant
component README and specifications.

## Documentation

- [Documentation index](docs/README.md)
- [Product specification](docs/specifications/product.md)
- [Architecture](docs/specifications/architecture.md)
- [PBLE/1 protocol](docs/specifications/protocol.md)
- [Firmware contract](docs/specifications/firmware.md)
- [App contract](docs/specifications/app.md)
- [Hardware and compatibility](docs/specifications/hardware.md)
- [Public roadmap](docs/ROADMAP.md)
- [Architecture decisions](docs/decisions/README.md)
- [Security policy](SECURITY.md)

## Contributing

Contributions are welcome, especially new validated board ports, protocol and
transport tests, accessibility improvements, translations, and beginner
examples. Read [CONTRIBUTING.md](CONTRIBUTING.md) and
[AGENTS.md](AGENTS.md) before opening a pull request.

Every commit must carry a DCO sign-off. PyBLE uses a clean-room boundary and CI
gates for prohibited identifiers, SPDX headers, dependency boundaries,
localization parity, submodule pins, app tests, website checks, and firmware
builds.

PyBLE is an independent [MIT-licensed](LICENSE) SciLabPro open-source project.
