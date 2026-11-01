# PyBLE agent firmware

PyBLE firmware combines pinned upstream MicroPython with a portable PBLE/1 BLE
agent and board overlays. Upstream source remains a Git submodule and is not
edited in place.

Current source selects development `0.7.0-dev.1` for the first capability-gated
run/session-status increment. This is separate from published firmware and
complete release admission; see the
[execution record](../docs/developments/2026-q4-reliable-workflow/firmware-v070/00_Execution_Record.md).

## Reference build variants

| PyBLE target | Upstream IDF target | Public browser profile |
|---|---|---|
| `esp32` | `esp32` | `esp32-4mb` |
| `esp32-s3` | `esp32s3` | `esp32-s3-n16r8` |
| `waveshare-esp32-s3-lcd-147b` | `esp32s3` | `waveshare-esp32-s3-lcd-147b` |
| `esp32-c3` | `esp32c3` | `esp32-c3-4mb` |
| `rpi-pico2-w` | RP2 / `RPI_PICO2_W` (ARM build plane) | `rpi-pico2-w` (UF2/manual BOOTSEL) |

These targets are reference ports, not the permanent scope of the platform.

## Initialize

From the repository root:

```sh
git submodule update --init --recursive
firmware/scripts/install_esp_idf.sh
```

Pins for MicroPython, ESP-IDF, toolchains, and target mappings live in
[`versions.lock`](versions.lock).

## Build

Inspect a build plan without installing ESP-IDF:

```sh
firmware/scripts/build.sh --plan esp32
```

Build one target:

```sh
firmware/scripts/build.sh esp32
firmware/scripts/build.sh esp32-s3
firmware/scripts/build.sh waveshare-esp32-s3-lcd-147b
firmware/scripts/build.sh esp32-c3
firmware/scripts/build_rp2.sh --plan rpi-pico2-w
```

Or build the complete matrix:

```sh
firmware/scripts/build_all.sh
```

Build outputs are local and ignored. Release artifacts are published through
GitHub Releases rather than committed to this repository.

## Test

Fast repository and firmware gates:

```sh
firmware/scripts/check.sh
tests/firmware_tests/run_tests.sh
```

Hardware validation and release qualification have additional prerequisites;
see:

- [`docs/specifications/firmware.md`](../docs/specifications/firmware.md)
- [`docs/specifications/firmware/specs.md`](../docs/specifications/firmware/specs.md)
- [`docs/specifications/firmware/browser-flashing.md`](../docs/specifications/firmware/browser-flashing.md)
- [`tests/firmware_tests/hil/README.md`](../tests/firmware_tests/hil/README.md)

## Upstream and patches

Do not edit `firmware/upstream/micropython` in place. Target-specific files live
under `board_overlays/` and are copied into the build tree by the preparation
step.

The default patch set is empty. Any unavoidable upstream patch belongs under
`patches/`, must document why an overlay or upstream fix is insufficient, and
must pass the patch-policy gate.

## License

PyBLE-authored firmware source is MIT. Upstream MicroPython, ESP-IDF, compiler
runtimes, and bundled components retain their own licenses. The release license
policy, notices, and reviewed evidence live under [`licenses/`](licenses/).
