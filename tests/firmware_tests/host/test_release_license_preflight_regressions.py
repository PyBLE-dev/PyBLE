#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Release-license preflight regressions found against the v0.6.0
# five-profile baseline build.

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_license_preflight_regressions",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        return None, "cannot load release_bundle.py"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced as a skip reason.
        return None, "cannot import release_bundle.py: %s" % exc
    return module, ""


RELEASE, RELEASE_LOAD_ERROR = load_release_module()

EXPECTED_PYBLE_C_SOURCES = (
    "pble_proto.c",
    "pble_ble.c",
    "pble_info.c",
    "pble_device_config.c",
    "pble_runner.c",
    "pble_console.c",
    "pble_fs.c",
    "pble_lock.c",
    "pble_boot.c",
    "pble_vm_lifecycle.c",
    "pble_termination.c",
)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class ReleaseLicensePreflightRegressionTests(unittest.TestCase):
    def test_canonical_platform_root_alias_preserves_fail_closed_walk(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-root-alias-red-"
        ) as temporary:
            fixture = Path(temporary)
            physical_parent = fixture / "private"
            physical_root = physical_parent / "build"
            physical_root.mkdir(parents=True)
            logical_parent = fixture / "logical"
            logical_parent.symlink_to(physical_parent, target_is_directory=True)
            logical_root = logical_parent / "build"

            retained = physical_root / ".sources/rpi-pico2-w/micropython"
            retained.mkdir(parents=True)
            self.assertTrue(logical_root.samefile(physical_root))
            try:
                RELEASE._audit_no_symlink_components(
                    logical_root,
                    retained.resolve(),
                    "canonical platform-root alias",
                )
            except RELEASE.ReleaseError as exc:
                self.fail(
                    "same-inode platform root aliases must be accepted: %s"
                    % exc
                )

            real_child = physical_root / "real-child"
            real_child.mkdir()
            nested_alias = physical_root / "nested-alias"
            nested_alias.symlink_to(real_child, target_is_directory=True)
            with self.assertRaisesRegex(RELEASE.ReleaseError, "symlink"):
                RELEASE._audit_no_symlink_components(
                    logical_root,
                    physical_root.resolve() / "nested-alias/input.c",
                    "nested symlink",
                )

            root_alias = physical_parent / "build-alias"
            root_alias.symlink_to(physical_root, target_is_directory=True)
            with self.assertRaisesRegex(RELEASE.ReleaseError, "symlink"):
                RELEASE._audit_no_symlink_components(
                    root_alias,
                    retained.resolve(),
                    "symlinked selected root",
                )

            escaped = physical_parent / "build-near-match/input.c"
            escaped.parent.mkdir()
            escaped.write_bytes(b"/* outside the admitted root */\n")
            with self.assertRaisesRegex(RELEASE.ReleaseError, "escapes"):
                RELEASE._audit_no_symlink_components(
                    logical_root,
                    escaped.resolve(),
                    "escaped near-match path",
                )

    def test_exact_compiled_pyble_source_inventory_includes_lifecycle_files(
        self,
    ) -> None:
        self.assertEqual(
            RELEASE._AUDIT_PYBLE_C_SOURCES,
            EXPECTED_PYBLE_C_SOURCES,
            "the audit must freeze the same eleven first-party C sources as "
            "micropython.cmake",
        )
        source_root = REPO_ROOT / "firmware/user_c_modules/pyble"
        cmake_sources = tuple(
            re.findall(
                r"\$\{CMAKE_CURRENT_LIST_DIR\}/(pble_[a-z_]+\.c)",
                (source_root / "micropython.cmake").read_text(encoding="utf-8"),
            )
        )
        self.assertEqual(cmake_sources, EXPECTED_PYBLE_C_SOURCES)
        compiled_sources = {
            (source_root / name).resolve() for name in EXPECTED_PYBLE_C_SOURCES
        }
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-source-inventory-red-"
        ) as temporary:
            pyble_sources, _berkeley_sources = (
                RELEASE._audit_exact_compile_source_sets(
                    repo_root=REPO_ROOT,
                    build_root=Path(temporary),
                    target="esp32",
                    compiled_sources=compiled_sources,
                )
            )
        self.assertEqual(pyble_sources, compiled_sources)


if __name__ == "__main__":
    unittest.main()
