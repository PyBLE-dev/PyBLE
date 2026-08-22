# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0024/0028 exact-board manifest and source-audit contract."""

import ast
import importlib.util
import pathlib
import shutil
import tempfile
import unittest


HOST_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
OVERLAYS_DIR = FIRMWARE_DIR / "board_overlays"
UPSTREAM_DIR = FIRMWARE_DIR / "upstream" / "micropython"
MPY_LIB_DIR = UPSTREAM_DIR / "lib" / "micropython-lib"
CANONICAL_SOURCE = (
    OVERLAYS_DIR
    / "waveshare-esp32-s3-lcd-147b"
    / "pyble_waveshare_lcd147b.py"
)
RELEASE_BUNDLE = FIRMWARE_DIR / "scripts" / "release_bundle.py"
MODULE_NAME = "pyble_waveshare_lcd147b.py"
TARGETS = {
    "esp32": "PYBLE_ESP32",
    "esp32-s3": "PYBLE_ESP32_S3",
    "waveshare-esp32-s3-lcd-147b": "PYBLE_WAVESHARE_ESP32_S3_LCD_147B",
    "esp32-c3": "PYBLE_ESP32_C3",
}


def _load_manifestfile():
    path = UPSTREAM_DIR / "tools" / "manifestfile.py"
    spec = importlib.util.spec_from_file_location(
        "pyble_splash_manifestfile", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned MicroPython manifest resolver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else (node.target,)
        )
        if isinstance(target, ast.Name) and target.id == name
    ]
    if len(matches) != 1:
        raise AssertionError(
            "{} must assign {} exactly once".format(path, name)
        )
    return ast.literal_eval(matches[0])


class WaveshareBootSplashManifestContractTest(unittest.TestCase):
    def test_exact_board_overlay_is_the_one_canonical_mit_source(self):
        self.assertTrue(
            CANONICAL_SOURCE.is_file(),
            "missing canonical exact-board source: {}".format(
                CANONICAL_SOURCE.relative_to(REPO_ROOT)
            ),
        )
        source = CANONICAL_SOURCE.read_text(encoding="utf-8")
        self.assertTrue(
            any(
                "SPDX-License-Identifier: MIT" in line
                for line in source.splitlines()[:5]
            ),
            "the first-party companion must carry an SPDX MIT header",
        )
        authored_copies = sorted(OVERLAYS_DIR.glob("*/" + MODULE_NAME))
        authored_copies.extend(
            sorted((FIRMWARE_DIR / "python_modules").glob(MODULE_NAME))
        )
        self.assertEqual(authored_copies, [CANONICAL_SOURCE])

    def test_only_exact_board_manifest_declares_one_literal_companion(self):
        for target in TARGETS:
            with self.subTest(target=target):
                manifest_path = OVERLAYS_DIR / target / "manifest.py"
                tree = ast.parse(
                    manifest_path.read_text(encoding="utf-8"),
                    filename=str(manifest_path),
                )
                calls = []
                for node in ast.walk(tree):
                    if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "module"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == MODULE_NAME
                    ):
                        continue
                    calls.append(node)
                expected = (
                    1 if target == "waveshare-esp32-s3-lcd-147b" else 0
                )
                self.assertEqual(len(calls), expected)
                if calls:
                    keywords = {
                        keyword.arg: ast.literal_eval(keyword.value)
                        for keyword in calls[0].keywords
                    }
                    self.assertEqual(
                        keywords,
                        {"base_path": "$(BOARD_DIR)", "opt": 3},
                    )

    def test_effective_manifest_resolves_one_exact_board_copy_and_zero_elsewhere(self):
        self.assertTrue(CANONICAL_SOURCE.is_file())
        manifestfile = _load_manifestfile()
        port_dir = UPSTREAM_DIR / "ports" / "esp32"

        for target, board_name in TARGETS.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="pyble-splash-manifest-"
            ) as temporary_dir:
                board_dir = pathlib.Path(temporary_dir) / board_name
                shutil.copytree(OVERLAYS_DIR / target, board_dir)
                shutil.copytree(FIRMWARE_DIR / "pyble", board_dir / "pyble")
                if target == "waveshare-esp32-s3-lcd-147b":
                    # Build prep also supplies the canonical generic driver.
                    shutil.copy2(
                        FIRMWARE_DIR / "python_modules" / "pyble_st7789.py",
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
                selected = [
                    result
                    for result in resolver.files()
                    if result.target_path == MODULE_NAME
                ]
                expected = (
                    1 if target == "waveshare-esp32-s3-lcd-147b" else 0
                )
                self.assertEqual(len(selected), expected)
                if selected:
                    self.assertEqual(
                        pathlib.Path(selected[0].full_path).resolve(),
                        (board_dir / MODULE_NAME).resolve(),
                    )
                    self.assertEqual(
                        (board_dir / MODULE_NAME).read_bytes(),
                        CANONICAL_SOURCE.read_bytes(),
                    )

    def test_release_audit_maps_exact_destination_to_overlay_source_and_mit(self):
        mapping = _literal_assignment(
            RELEASE_BUNDLE, "_AUDIT_FIRST_PARTY_FROZEN_SOURCES"
        )
        self.assertIn(MODULE_NAME, mapping)
        self.assertEqual(
            mapping[MODULE_NAME],
            {
                "target": "waveshare-esp32-s3-lcd-147b",
                "introduced_version": "0.5.0",
                "canonical_path": (
                    "firmware/board_overlays/waveshare-esp32-s3-lcd-147b/"
                    "pyble_waveshare_lcd147b.py"
                ),
                "spdx_expression": "MIT",
            },
        )

    def test_generic_s3_has_no_companion_or_splash_boot_hook(self):
        generic = OVERLAYS_DIR / "esp32-s3"
        self.assertFalse((generic / MODULE_NAME).exists())
        manifest = (generic / "manifest.py").read_text(encoding="utf-8")
        boot = (generic / "_boot.py").read_text(encoding="utf-8")
        self.assertNotIn(MODULE_NAME, manifest)
        self.assertNotIn("pyble_waveshare_lcd147b", boot)
        self.assertNotIn("_maybe_show_boot_splash", boot)
        self.assertNotIn("wait_ready", boot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
