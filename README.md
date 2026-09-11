# PyBLE

**Python over Bluetooth Low Energy** — an open-source, tablet-first
MicroPython IDE.

[![CI](https://github.com/PyBLE-dev/PyBLE/actions/workflows/ci.yml/badge.svg)](https://github.com/PyBLE-dev/PyBLE/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22064467.svg)](https://doi.org/10.5281/zenodo.22064467)
[![Platforms](https://img.shields.io/badge/app-iPadOS%20%7C%20Android-2D5BFF.svg)](#app)
[![Protocol](https://img.shields.io/badge/protocol-PBLE%2F1-0E7490.svg)](docs/specifications/protocol.md)
[![Firmware](https://img.shields.io/badge/firmware-v0.6.1%20published-15803D.svg)](https://pyble.dev/flash)

PyBLE lets you edit, transfer, run, and stop MicroPython programs on a
compatible microcontroller board over Bluetooth Low Energy. Its normal
workflow needs no USB serial connection, Wi-Fi onboarding, cloud account, or
telemetry.

- Published firmware v0.6.1: [installer and download](https://pyble.dev/flash)
- Tutorials: [learn PyBLE](https://pyble.dev/learn)
- Firmware features and functional block diagram: [architecture reference](https://pyble.dev/features)
- Official example collection: [PyBLE-dev/examples](https://github.com/PyBLE-dev/examples)
- iPad external beta:
  [join with TestFlight](https://testflight.apple.com/join/yU4e8s6d)
- Android invited testing: [see the app page](https://pyble.dev/app)
- License: [MIT](LICENSE)

<p align="center">
  <img
    src="tools/web/public/app/pyble-neopixel-gpio48-ipad-landscape.png"
    alt="Actual PyBLE iPad app showing GPIO 48 NeoPixel Blocks beside generated MicroPython code"
    width="960"
  >
</p>

<p align="center">
  <em>Actual PyBLE app in landscape: GPIO 48 NeoPixel Blocks beside the generated MicroPython.</em>
</p>

## What works

### App

The Flutter app currently provides:

- filtered BLE discovery and PBLE/1 connection;
- connected-board details with the PBLE/1 board ID and PyBLE agent firmware
  version retained in the always-visible connection status;
- a Python-highlighted MicroPython editor with always-visible, one-based line
  numbers, an adjustable 10–24 point code font, save, run, stop, soft reboot,
  and live console;
- wireless file browsing and transfer with integrity checks, reviewed
  multi-file deletion, and a compact Files action menu;
- an optional public GitHub example browser that resolves a repository/ref to
  an immutable commit, previews exact `.py` source-to-board paths, and imports
  selected files into the connected Files folder only after explicit review;
  the official repository URL is prefilled and editable, with a branch chooser
  and an optional manual tag/commit input;
- an offline Blockly workspace with GPIO and standard MicroPython NeoPixel
  blocks, including explicit numeric GPIOs and bounded named `machine.Pin`
  identities;
- editable beginner examples;
- exact Blockly sidecar reopening and a bounded Python-to-blocks importer;
- an adaptive tablet interface for portrait and landscape use;
- an offline privacy policy accessible from About; and
- core editing, BLE, Files, Blocks, and Run operation without an account,
  analytics, or cloud dependency. GitHub is the sole optional network surface;
  its public, unauthenticated requests start only when the user opens the
  importer.

GitHub import is deliberately bounded and non-executing. It accepts a canonical
public repository URL, lazily browses one SHA-pinned snapshot, and selects only
ordinary lowercase `.py` files from one folder. Before any board write, PyBLE
fetches and validates the complete batch, shows the exact destination paths,
and asks separately before overwriting existing files. Import never creates a
remote folder hierarchy, opens an editor document, or runs downloaded code.

The current App source version is `0.2.0+8`; App and firmware versions are
independent. iPad testing uses TestFlight, and Android distribution follows
the testing access shown on the [App page](https://pyble.dev/app). The
[Google Play build-8 handoff](docs/testing/google-play/0.2.0-build-8.md)
records prepared artifacts and their exact source; preparation does not
establish a live store release or mean those earlier artifacts contain later
connection-lifecycle fixes. Both platforms share the same Flutter source and
app test gates. The iOS/iPadOS project minimum is 15.

### Firmware

The board-side agent is built with upstream MicroPython and exposes PBLE/1 as a
BLE GATT peripheral. It supports:

- capability and device-information negotiation with session-scoped HELLO;
- run, stop, console, and soft-reboot control, with fresh globals per file RUN
  and stdin isolated to its owning run;
- LFS2 workspaces across all five profiles, CRC-checked resumable uploads,
  atomic publication, storage-reserve checks, and serialized file mutations;
- bounded fragment reassembly and transport/session recovery;
- optional `main.py` auto-run protection and checked configuration persistence;
- board naming and identify support;
- an exact-board ST7789 display and boot splash on Waveshare's B-version; and
- upstream MicroPython’s standard `neopixel` module.

The installer offers the owner-confirmed public v0.6.1 release across all five
exact release profiles. The owner confirmed completed qualification and
authorized publication on 2026-09-11. Existing automated qualification records
remain incomplete and are preserved unchanged; owner confirmation does not
mark missing automated measurements passed. The four ESP profiles use Web Serial
from a supported desktop Chromium browser; Pico 2 W uses a browser-verified UF2
download followed by a manual BOOTSEL copy.

| Profile | Exact hardware constraint | Provisioning | Public status |
| --- | --- | --- | --- |
| `esp32-4mb` | Classic ESP32; exactly 4 MiB external flash; no PSRAM required | ESP Web Serial | Owner-confirmed v0.6.1 |
| `esp32-s3-n16r8` | Lean ESP32-S3; exactly 16 MiB flash and 8 MiB Octal PSRAM | ESP Web Serial | Owner-confirmed v0.6.1 |
| `waveshare-esp32-s3-lcd-147b` | Exact ESP32-S3-LCD-1.47B B-version; 16 MiB flash and 8 MiB Octal PSRAM | ESP Web Serial | Owner-confirmed v0.6.1 |
| `esp32-c3-4mb` | ESP32-C3 revision v0.3 or newer; exactly 4 MiB flash; no PSRAM required | ESP Web Serial | Owner-confirmed v0.6.1 |
| `rpi-pico2-w` | Raspberry Pi Pico 2 W; RP2350 with CYW43439 | Verified UF2 + manual BOOTSEL copy | Owner-confirmed v0.6.1 |

The immutable
[release descriptor](https://pyble.dev/firmware/v0.6.1/release.json), with
SHA-256
`71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd`,
binds the five artifacts to exact source
[`c8f549eeabe6d2b8c2766eab022517944bb09c8c`](https://github.com/PyBLE-dev/PyBLE/tree/c8f549eeabe6d2b8c2766eab022517944bb09c8c).
See the [owner confirmation](https://pyble.dev/firmware-v0.6.1-owner-confirmation.md),
[release notes](https://pyble.dev/firmware/v0.6.1/RELEASE_NOTES.md),
[artifact checksums](https://pyble.dev/firmware/v0.6.1/SHA256SUMS), and
[recovery guide](https://pyble.dev/firmware/v0.6.1/RECOVERY.md) before installing.

Back up before moving from older workspace formats. v0.6.1 refuses nonblank or
uncertain media that it cannot mount safely; it does not silently reformat an
old workspace. That refusal requires USB recovery rather than a BLE session.
The prior [qualified v0.6.0 release](https://pyble.dev/firmware/v0.6.0/RELEASE_NOTES.md)
and its [source tag](https://github.com/PyBLE-dev/PyBLE/tree/firmware-v0.6.0)
remain historical references, not the current installer selection.

These maintained release profiles are not an app-side chip or board allowlist.
A future board is compatible when it has a maintained PyBLE agent port, BLE
GATT peripheral support, adequate resources, PBLE/1 conformance, recovery
testing, and hardware-validation evidence. Stock MicroPython plus generic
Bluetooth hardware is not sufficient by itself.

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
- [`examples/`](examples/) — small source/conformance examples and GitHub-import
  fixtures; the separately maintained [official example collection](https://github.com/PyBLE-dev/examples)
  contains the user-facing examples for all five profiles;
- [`docs/specifications/protocol.md`](docs/specifications/protocol.md) — the
  open PBLE/1 wire contract;
- [`tests/`](tests/) — host, conformance, release, and HIL test runners;
- [`tools/`](tools/) — repository gates and the `pyble.dev` website; and
- [`docs/`](docs/) — public specifications, decisions, roadmap, and validation
  evidence.

Keeping these parts together lets a protocol change update the app, firmware,
shared conformance corpus, documentation, and CI atomically.

## Try PyBLE

1. Install the iPad beta from
   [TestFlight](https://testflight.apple.com/join/yU4e8s6d), or build the
   Flutter app locally.
2. Open [pyble.dev/flash](https://pyble.dev/flash) in a supported desktop
   Chromium browser. Confirm that the published v0.6.1 release is selected,
   then choose only the exact profile matching the board and memory topology.
3. Before provisioning, back up the board and accept every safety
   acknowledgement. Flashing erases the board and its existing workspace.
4. For the four ESP profiles, connect the board and install with Web Serial.
   For Pico 2 W, download the verified UF2 and copy it manually to the BOOTSEL
   mass-storage volume. iPadOS cannot perform either wired provisioning step.
5. Open PyBLE, scan for the provisioned board, and connect over BLE.
6. In **Files**, create or open a writable subfolder such as `/examples` within
   the board's advertised filesystem root. Do not assume `/` is writable on
   every board; read the destination warning before importing there.
7. Choose **Import examples from GitHub**. The prefilled URL
   `https://github.com/PyBLE-dev/examples` is editable. Let the branch chooser
   load, select `main` (or another available branch), and browse to
   `examples/portable/basics/hello_console`. If GitHub reports its public
   request limit, wait for the displayed retry time rather than repeatedly
   reloading. Advanced users can enter a tag or commit manually.
8. Select `pyble_hello_console.py`, review the displayed immutable commit SHA
   and exact board destination, and confirm any overwrite separately. The
   official URL does not bypass source review or imply validation of every
   example. Import does not open or run the file; open it from Files and
   choose Run only when you are ready.

Follow the [guided tutorials](https://pyble.dev/learn), including real Lenovo
workflow screenshots, for the complete learning path. See
[support and troubleshooting](https://pyble.dev/support) for browser,
Bluetooth, network, and recovery requirements. A GitHub account or token is not
needed for the optional import; every other workflow remains available without
it.

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
flutter test --exclude-tags golden
# Run the pixel-golden lane on its pinned macOS host:
flutter test --tags golden
```

Firmware host tests:

```sh
tests/firmware_tests/run_tests.sh
python3 -m unittest discover -s tests/firmware_tests/host -p 'test_*.py' -v
```

Firmware build preparation and target builds:

```sh
firmware/scripts/install_esp_idf.sh
firmware/scripts/build.sh esp32
firmware/scripts/build.sh esp32-s3
firmware/scripts/build.sh waveshare-esp32-s3-lcd-147b
firmware/scripts/build.sh esp32-c3
firmware/scripts/install_arm_toolchain.sh
firmware/scripts/install_picotool.sh
firmware/scripts/build_rp2.sh rpi-pico2-w
```

These are the five target builds in the published v0.6.1 release. The four ESP
targets produce Web Serial artifacts; `rpi-pico2-w` produces the UF2 used by
the verified-download and BOOTSEL flow.

The commands above build the current checkout. To start from the exact source
used for the public v0.6.1 artifacts, detach at the exact source commit and
restore its pinned submodules:

```sh
git switch --detach c8f549eeabe6d2b8c2766eab022517944bb09c8c
git submodule update --init --recursive
```

Website:

```sh
cd tools/web
npm ci
npm run check
```

The website gate includes a high/critical npm advisory audit, deterministic
third-party notices, and timeout-bounded regression coverage for the image
parser bundled inside the pinned preview adapter. Production remains a checked
static export with no Node.js website process.

The complete build requires the pinned toolchains documented in the relevant
component README and specifications.

Firmware binaries are external release artifacts, not committed source.
The public v0.6.1 installation uses its exact owner-confirmed release descriptor
and artifact hashes; the standard automated qualification gate remains
unchanged. A source-only website build remains fail-closed unless an explicit
validated release input is supplied. See the
[publication record](docs/testing/firmware-v0.6.1-publication-2026-09-11.md)
and [website deployment record](docs/testing/website/site-v061-consistency-2026-09-11.md)
for the release-specific deployment path; building this checkout does not
publish new firmware or replace the live site.

## Documentation

- [Documentation index](docs/README.md)
- [Changelog](CHANGELOG.md)
- [Tutorials with reviewed App screenshots](https://pyble.dev/learn)
- [Firmware features and functional block diagram](https://pyble.dev/features)
- [Official examples repository](https://github.com/PyBLE-dev/examples)
- [Published firmware v0.6.1 source](https://github.com/PyBLE-dev/PyBLE/tree/c8f549eeabe6d2b8c2766eab022517944bb09c8c)
- [Firmware v0.6.1 release notes](https://pyble.dev/firmware/v0.6.1/RELEASE_NOTES.md)
- [Firmware v0.6.1 publication record](docs/testing/firmware-v0.6.1-publication-2026-09-11.md)
- [Product specification](docs/specifications/product.md)
- [Architecture](docs/specifications/architecture.md)
- [PBLE/1 protocol](docs/specifications/protocol.md)
- [Firmware contract](docs/specifications/firmware.md)
- [App contract](docs/specifications/app.md)
- [Hardware and compatibility](docs/specifications/hardware.md)
- [Public roadmap](docs/ROADMAP.md)
- [Architecture decisions](docs/decisions/README.md)
- [Validation evidence index](docs/validation/README.md)
- [Security policy](SECURITY.md)

## Citation

If you use PyBLE in research, teaching, or another published work, use the
metadata in [CITATION.cff](CITATION.cff). The app and firmware are versioned
independently, so cite the exact archived project snapshot or component
release you used; published firmware v0.6.1 is not the app version.

The first whole-project citation snapshot is
[`source-2026.08.23`](https://github.com/PyBLE-dev/PyBLE/releases/tag/source-2026.08.23).
Cite that exact snapshot with DOI
[`10.5281/zenodo.22064468`](https://doi.org/10.5281/zenodo.22064468); use the
project concept DOI
[`10.5281/zenodo.22064467`](https://doi.org/10.5281/zenodo.22064467) to link
all archived PyBLE versions. The snapshot contains app source `0.1.0+4` and
records qualified firmware `0.6.0` as a separate component release.

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
