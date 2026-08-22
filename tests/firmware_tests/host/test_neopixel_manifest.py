# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-24 manifest contract for the standard upstream MicroPython NeoPixel driver.
# Resolve the source manifests directly: generated frozen_mpy/ files are
# intentionally not consulted because an incremental build can leave orphans.

import importlib.util
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


HOST_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
UPSTREAM_DIR = FIRMWARE_DIR / "upstream" / "micropython"
MPY_LIB_DIR = UPSTREAM_DIR / "lib" / "micropython-lib"
NEOPIXEL_PACKAGE_DIR = (
    MPY_LIB_DIR / "micropython" / "drivers" / "led" / "neopixel"
)
PINNED_NEOPIXEL_SOURCE = (NEOPIXEL_PACKAGE_DIR / "neopixel.py").resolve()
PINNED_NEOPIXEL_MANIFEST = (NEOPIXEL_PACKAGE_DIR / "manifest.py").resolve()
CANONICAL_ST7789_SOURCE = FIRMWARE_DIR / "python_modules" / "pyble_st7789.py"
UPSTREAM_ESP32_MANIFEST = (
    UPSTREAM_DIR / "ports" / "esp32" / "boards" / "manifest.py"
)
TARGETS = {
    "esp32": "PYBLE_ESP32",
    "esp32-s3": "PYBLE_ESP32_S3",
    "waveshare-esp32-s3-lcd-147b": "PYBLE_WAVESHARE_ESP32_S3_LCD_147B",
    "esp32-c3": "PYBLE_ESP32_C3",
}


def _git(cwd, *args):
    return subprocess.run(
        ("git", "-C", str(cwd), *args),
        check=True,
        capture_output=True,
        text=False,
    ).stdout


def _tracked_bytes(repo, relative_path):
    return _git(repo, "show", "HEAD:{}".format(relative_path.as_posix()))


def _load_manifestfile():
    path = UPSTREAM_DIR / "tools" / "manifestfile.py"
    spec = importlib.util.spec_from_file_location("pyble_manifestfile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned MicroPython manifest resolver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NeoPixelManifestContractTest(unittest.TestCase):
    def test_pinned_upstream_neopixel_inputs_are_pristine(self):
        lock_text = (FIRMWARE_DIR / "versions.lock").read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^\[micropython\].*?^commit\s*=\s*\"([0-9a-f]{40})\"",
            lock_text,
        )
        self.assertIsNotNone(match, "versions.lock must pin MicroPython by commit")
        self.assertEqual(
            _git(UPSTREAM_DIR, "rev-parse", "HEAD").decode().strip(),
            match.group(1),
            "the effective manifests must resolve from the pinned MicroPython checkout",
        )

        gitlink = _git(
            UPSTREAM_DIR, "ls-tree", "HEAD", "lib/micropython-lib"
        ).decode()
        gitlink_match = re.match(
            r"160000 commit ([0-9a-f]{40})\tlib/micropython-lib\n", gitlink
        )
        self.assertIsNotNone(
            gitlink_match, "pinned MicroPython must pin its micropython-lib submodule"
        )
        self.assertEqual(
            _git(MPY_LIB_DIR, "rev-parse", "HEAD").decode().strip(),
            gitlink_match.group(1),
            "NeoPixel must come from the pinned micropython-lib checkout",
        )

        pristine_inputs = (
            (
                UPSTREAM_DIR,
                pathlib.Path("ports/esp32/boards/manifest.py"),
                UPSTREAM_ESP32_MANIFEST,
            ),
            (
                MPY_LIB_DIR,
                pathlib.Path(
                    "micropython/drivers/led/neopixel/manifest.py"
                ),
                PINNED_NEOPIXEL_MANIFEST,
            ),
            (
                MPY_LIB_DIR,
                pathlib.Path(
                    "micropython/drivers/led/neopixel/neopixel.py"
                ),
                PINNED_NEOPIXEL_SOURCE,
            ),
        )
        for repo, relative_path, worktree_path in pristine_inputs:
            with self.subTest(path=relative_path):
                self.assertEqual(
                    worktree_path.read_bytes(),
                    _tracked_bytes(repo, relative_path),
                    "do not edit pinned upstream NeoPixel inputs in place",
                )

    def test_pyble_does_not_copy_or_implement_a_neopixel_driver(self):
        # Release source is the Git-tracked tree.  Retained build checkouts are
        # intentionally ignored and may contain their own pristine upstream
        # neopixel.py; scanning the ambient filesystem would misclassify those
        # generated inputs as PyBLE-authored/shipped copies.
        tracked_paths = _git(
            REPO_ROOT,
            "ls-files",
            "-z",
            "--",
            "firmware",
        ).decode("utf-8").split("\0")
        copied_drivers = sorted(
            path for path in tracked_paths if path.endswith("/neopixel.py")
        )
        self.assertEqual(
            copied_drivers,
            [],
            "PyBLE must freeze the standard pinned driver, not ship a copied/custom one",
        )

    def test_every_target_resolves_exactly_one_pinned_neopixel_module(self):
        manifestfile = _load_manifestfile()
        port_dir = UPSTREAM_DIR / "ports" / "esp32"

        for target, board_name in TARGETS.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="pyble-neopixel-manifest-"
            ) as temporary_dir:
                board_dir = pathlib.Path(temporary_dir) / board_name
                shutil.copytree(
                    FIRMWARE_DIR / "board_overlays" / target,
                    board_dir,
                )
                shutil.copytree(FIRMWARE_DIR / "pyble", board_dir / "pyble")
                if target == "waveshare-esp32-s3-lcd-147b":
                    shutil.copy2(
                        CANONICAL_ST7789_SOURCE,
                        board_dir / "pyble_st7789.py",
                    )

                resolver = manifestfile.ManifestFile(
                    manifestfile.MODE_FREEZE,
                    {
                        "MPY_DIR": str(UPSTREAM_DIR),
                        "PORT_DIR": str(port_dir),
                        "BOARD_DIR": str(board_dir),
                        "MPY_LIB_DIR": str(MPY_LIB_DIR),
                    },
                )
                resolver.execute(str(board_dir / "manifest.py"))

                modules = [
                    result
                    for result in resolver.files()
                    if result.target_path == "neopixel.py"
                ]
                self.assertEqual(
                    len(modules),
                    1,
                    "{} must freeze exactly one standard neopixel.py".format(target),
                )
                self.assertEqual(
                    pathlib.Path(modules[0].full_path).resolve(),
                    PINNED_NEOPIXEL_SOURCE,
                    "{} must resolve NeoPixel from pinned upstream".format(target),
                )
                self.assertNotIn(
                    FIRMWARE_DIR / "build",
                    pathlib.Path(modules[0].full_path).resolve().parents,
                    "generated frozen_mpy intermediates are not authoritative",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
