# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# ADR-0023/0028 manifest contract for the exact-board PyBLE ST7789 runtime.
# Resolve source manifests directly: generated frozen_mpy/ files are
# intentionally not consulted because an incremental build can leave orphans.

import ast
import importlib.util
import pathlib
import re
import shutil
import tempfile
import unittest


HOST_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
OVERLAYS_DIR = FIRMWARE_DIR / "board_overlays"
UPSTREAM_DIR = FIRMWARE_DIR / "upstream" / "micropython"
MPY_LIB_DIR = UPSTREAM_DIR / "lib" / "micropython-lib"
CANONICAL_SOURCE = FIRMWARE_DIR / "python_modules" / "pyble_st7789.py"
TARGETS = {
    "esp32": "PYBLE_ESP32",
    "esp32-s3": "PYBLE_ESP32_S3",
    "waveshare-esp32-s3-lcd-147b": "PYBLE_WAVESHARE_ESP32_S3_LCD_147B",
    "esp32-c3": "PYBLE_ESP32_C3",
}


def _load_manifestfile():
    path = UPSTREAM_DIR / "tools" / "manifestfile.py"
    spec = importlib.util.spec_from_file_location("pyble_manifestfile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned MicroPython manifest resolver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _imports(source_path):
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"), filename=str(source_path)
    )
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


class ST7789ManifestContractTest(unittest.TestCase):
    def test_canonical_source_is_mit_and_has_no_board_wiring(self):
        self.assertTrue(
            CANONICAL_SOURCE.is_file(),
            "the canonical ST7789 source must exist at {}".format(
                CANONICAL_SOURCE.relative_to(REPO_ROOT)
            ),
        )
        source = CANONICAL_SOURCE.read_text(encoding="utf-8")
        self.assertTrue(
            any(
                "SPDX-License-Identifier: MIT" in line
                for line in source.splitlines()[:5]
            ),
            "the first-party ST7789 source must carry an SPDX MIT header",
        )
        self.assertNotRegex(
            source,
            re.compile(r"waveshare|esp32[-_]s3[-_]lcd", re.IGNORECASE),
            "the generic driver must not contain a Waveshare board identity",
        )
        self.assertNotRegex(
            source,
            re.compile(
                r"\b(?:GPIO_?(?:39|40|41|42|45|46)|"
                r"(?:machine\.)?Pin\s*\(\s*(?:39|40|41|42|45|46)\b)",
                re.IGNORECASE,
            ),
            "the generic driver must not embed the Waveshare GPIO wiring",
        )

    def test_only_exact_waveshare_variant_resolves_one_generated_st7789_source(self):
        self.assertTrue(
            CANONICAL_SOURCE.is_file(),
            "build prep needs the canonical ST7789 source",
        )
        manifestfile = _load_manifestfile()
        port_dir = UPSTREAM_DIR / "ports" / "esp32"

        for target, board_name in TARGETS.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="pyble-st7789-manifest-"
            ) as temporary_dir:
                board_dir = pathlib.Path(temporary_dir) / board_name
                shutil.copytree(OVERLAYS_DIR / target, board_dir)
                shutil.copytree(FIRMWARE_DIR / "pyble", board_dir / "pyble")

                generated_source = board_dir / "pyble_st7789.py"
                if target == "waveshare-esp32-s3-lcd-147b":
                    shutil.copy2(CANONICAL_SOURCE, generated_source)

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
                    if result.target_path == "pyble_st7789.py"
                ]
                expected_count = (
                    1 if target == "waveshare-esp32-s3-lcd-147b" else 0
                )
                self.assertEqual(
                    len(modules),
                    expected_count,
                    "{} must freeze {} pyble_st7789.py module(s)".format(
                        target, expected_count
                    ),
                )
                if target == "waveshare-esp32-s3-lcd-147b":
                    self.assertEqual(
                        pathlib.Path(modules[0].full_path).resolve(),
                        generated_source.resolve(),
                        "the exact Waveshare build must resolve the build-prep copy",
                    )
                    self.assertEqual(
                        generated_source.read_bytes(),
                        CANONICAL_SOURCE.read_bytes(),
                        "the generated board input must match canonical source",
                    )

    def test_boot_and_agent_do_not_import_optional_st7789_runtime(self):
        sources = [
            path
            for path in sorted(OVERLAYS_DIR.glob("*/_boot.py"))
            if path.parent.name != "waveshare-esp32-s3-lcd-147b"
        ]
        sources.extend(sorted((FIRMWARE_DIR / "pyble").glob("*.py")))
        self.assertTrue(sources, "boot and agent Python sources must be present")
        for source_path in sources:
            with self.subTest(path=source_path.relative_to(REPO_ROOT)):
                self.assertNotIn(
                    "pyble_st7789",
                    _imports(source_path),
                    "the optional Layer-4 driver must not enter boot/agent paths",
                )

    def test_generic_s3_overlay_contains_no_exact_board_display_source(self):
        generic = OVERLAYS_DIR / "esp32-s3"
        self.assertFalse((generic / "pyble_st7789.py").exists())
        self.assertFalse((generic / "pyble_waveshare_lcd147b.py").exists())
        manifest = (generic / "manifest.py").read_text(encoding="utf-8")
        self.assertNotIn("pyble_st7789.py", manifest)
        self.assertNotIn("pyble_waveshare_lcd147b.py", manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
