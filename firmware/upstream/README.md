# Upstream MicroPython (submodule)

Part of [Pyble](https://pyble.dev) · MIT — see [`/LICENSE`](../../LICENSE).

This directory holds a Git submodule, `micropython/`, pinned at the SHA recorded
in [`firmware/versions.lock`](../versions.lock). It is **Layer 1** of the
firmware (see [`docs/specifications/firmware.md`](../../docs/specifications/firmware.md) §1).

## Do not edit upstream in place

**Never edit any file under `micropython/`.** Pyble is *not* a fork of the VM —
all Pyble-specific code lives outside this tree:

- **Agent (Layer 3):** `pyble_*` modules under `firmware/` — frozen Python first,
  native `USER_C_MODULE` later; the PBLE/1 wire contract is unchanged either way.
- **Board overlay (Layer 2):** per-chip config under
  `firmware/board_overlays/{esp32,esp32-s3,esp32-c3}/`, copied into the upstream
  `ports/esp32/boards/` tree at build prep — the submodule stays pristine.
- **Unavoidable patches:** isolated under `firmware/patches/micropython-<tag>/`
  with a written reason, re-reviewed for retirement at every upgrade. The default
  is **zero** patches.

## One MicroPython pin, three chips

The single pin in `versions.lock` builds all three ESP-IDF targets (`esp32`,
`esp32s3`, `esp32c3`); chip differences are confined to the board overlay. Two
related trees are **not** outer submodules:

- MicroPython's own `lib/` dependencies are fetched on demand by the port build
  (`make -C ports/esp32 … submodules`) — the standard MicroPython mechanism.
- **ESP-IDF is not a submodule** — it is installed separately from the pin in
  `versions.lock` into a gitignored directory by the firmware build scripts.

## Populate (one-time, firmware-base story)

From the repo root, once it is under Git:

```sh
git submodule add https://github.com/micropython/micropython firmware/upstream/micropython
git -C firmware/upstream/micropython checkout v1.28.0   # the ref in versions.lock
```

Then record the resulting SHA in [`firmware/versions.lock`](../versions.lock).
The build refuses to proceed unless the checked-out submodule SHA matches the
lock.
