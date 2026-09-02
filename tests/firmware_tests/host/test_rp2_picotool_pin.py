#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED structural contract for deterministic RP2 picotool selection."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import re
import sys
import tomllib
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "firmware/versions.lock"
BUILD = ROOT / "firmware/scripts/build_rp2.sh"
INSTALLER = ROOT / "firmware/scripts/install_picotool.sh"
GITIGNORE = ROOT / ".gitignore"
RELEASE_SCRIPT = ROOT / "firmware/scripts/release_bundle.py"
VERSION_LINE = (
    "picotool v2.3.0 "
    "(Darwin, AppleClang-15.0.0.15000309, Release)"
)


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_v061_picotool_release_bundle",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load release_bundle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


def rp2_provenance(picotool: str) -> dict:
    return {
        "schema_version": 1,
        "target": "rpi-pico2-w",
        "port": "rp2",
        "board": "PYBLE_RPI_PICO2_W",
        "source_date_epoch": 1_786_506_287,
        "pyble": {"commit": "1" * 40, "clean": True},
        "micropython": {"commit": "2" * 40},
        "arm_gnu_toolchain": {
            "release": "14.2.Rel1",
            "gcc": (
                "arm-none-eabi-gcc (Arm GNU Toolchain 14.2.Rel1) "
                "14.2.1 20241119"
            ),
        },
        "picotool": picotool,
        "firmware_bin_bytes": 17,
    }


def source_lock(version: str) -> dict:
    value = {
        "pyble": {"agent_version": version},
        "micropython": {"commit": "2" * 40},
        "arm_gnu_toolchain": {
            "release": "14.2.Rel1",
            "gcc_version": "14.2.1 20241119",
        },
    }
    if version == "0.6.1":
        value["picotool"] = {"version_line": VERSION_LINE}
    return value


class PicotoolPinContractTests(unittest.TestCase):
    def test_versions_lock_binds_the_reviewed_official_distribution(self) -> None:
        lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
        self.assertIn("picotool", lock)
        self.assertEqual(
            lock["picotool"],
            {
                "version": "2.3.0",
                "version_line": VERSION_LINE,
                "source_repo": "https://github.com/raspberrypi/picotool.git",
                "source_ref": "2.3.0",
                "source_commit": "6f6458d792b93685a11423b244a585eaa99eafcf",
                "distribution_repo": (
                    "https://github.com/raspberrypi/pico-sdk-tools.git"
                ),
                "distribution_ref": "v2.3.0-0",
                "distribution_commit": (
                    "ad9e4a8375253cf4886bf168ea1a8d2746aadf24"
                ),
                "url": (
                    "https://github.com/raspberrypi/pico-sdk-tools/releases/"
                    "download/v2.3.0-0/picotool-2.3.0-mac.zip"
                ),
                "archive_filename": "picotool-2.3.0-mac.zip",
                "archive_bytes": 1_980_457,
                "archive_format": "zip",
                "sha256": (
                    "085ea99ccc2d64309e967a72e307fb113838713a46ba45bf7e156e519cca7d8e"
                ),
                "cmake_dir": "picotool",
                "executable_path": "picotool/picotool",
                "executable_sha256": (
                    "a4b3c4e64dea7b99e810c5c777bf13fb2722b8d0355e0b64a28244ddc1b0f8b5"
                ),
                "cmake_config_path": "picotool/picotoolConfig.cmake",
                "cmake_config_sha256": (
                    "ca12b6fee18e6583713cfdcb2e81886aaee741d40304ea2cc88c4f5b2df2b6c3"
                ),
                "bundled_libusb_path": "picotool/libusb-1.0.0.dylib",
                "bundled_libusb_sha256": (
                    "b3d0c88bcb04fe61e4f56bc304a31fef56e19ee5ec2edaebd0fce44afb2b9237"
                ),
            },
        )

    def test_installer_and_default_install_root_are_declared(self) -> None:
        self.assertTrue(INSTALLER.is_file(), "install_picotool.sh is required")
        self.assertTrue(INSTALLER.stat().st_mode & 0o100)
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("PYBLE_PICOTOOL_ARCHIVE", source)
        self.assertIn("PYBLE_LOCK_FILE", source)
        self.assertIn("$FW/.picotool", source)
        self.assertIn("[picotool]", source)

    def test_build_selects_only_the_verified_explicit_package(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        logical = re.sub(r"\\\n[ \t]*", " ", source)

        self.assertIn("PYBLE_PICOTOOL_DIR", source)
        self.assertIn("$FW/.picotool", source)
        self.assertIn("executable_path", source)
        self.assertRegex(
            logical,
            r'"\$PICOTOOL(?:_EXECUTABLE)?"\s+version',
        )
        self.assertNotRegex(logical, r"(?<![/$\w])picotool\s+version")
        self.assertNotRegex(logical, r"\b(?:brew|which)\s+picotool\b")
        self.assertNotRegex(logical, r"command\s+-v\s+picotool\b")

        self.assertIn("-Dpicotool_DIR=", source)
        self.assertIn("-DFETCHCONTENT_FULLY_DISCONNECTED=ON", source)
        self.assertIn("-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", source)
        self.assertIn("-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF", source)
        self.assertIn("FETCHCONTENT_SOURCE_DIR_PICOTOOL", source)
        self.assertIn("PICOTOOL_FETCH_FROM_GIT_PATH", source)
        self.assertIn("PICOTOOL_FORCE_FETCH_FROM_GIT", source)
        self.assertIn("-DPICOTOOL_FORCE_FETCH_FROM_GIT=OFF", source)

        self.assertIn("version_line", source)

    def test_only_the_exact_default_tree_is_gitignored(self) -> None:
        lines = {
            line.strip()
            for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("firmware/.picotool/", lines)
        self.assertNotIn(".picotool/", lines)
        self.assertNotIn("**/.picotool/", lines)
        self.assertNotIn("firmware/.picotool*", lines)
        self.assertNotIn("firmware/.picotool-cache/", lines)

    def test_release_provenance_requires_the_exact_line_only_for_v061(self) -> None:
        self.assertIn(
            "firmware_version",
            inspect.signature(RELEASE._validate_rp2_build_provenance).parameters,
            "picotool strictness must be routed from the selected candidate version",
        )

        def git_output(_root, _label, *arguments):
            if arguments == ("rev-parse", "HEAD"):
                return "1" * 40
            if arguments == (
                "show",
                "-s",
                "--format=%ct",
                "1" * 40,
            ):
                return "1786506287"
            raise AssertionError("unexpected git query: %r" % (arguments,))

        def validate(version: str, picotool: str, *, lock_value=None):
            with (
                mock.patch.object(
                    RELEASE,
                    "_read_lock",
                    return_value=(
                        source_lock(version)
                        if lock_value is None
                        else lock_value
                    ),
                ),
                mock.patch.object(
                    RELEASE,
                    "_git_output",
                    side_effect=git_output,
                ),
                mock.patch.object(RELEASE, "_require_checkout_clean"),
            ):
                return RELEASE._validate_rp2_build_provenance(
                    rp2_provenance(picotool),
                    "rpi-pico2-w",
                    firmware_bin_bytes=17,
                    repo_root=ROOT,
                    firmware_version=version,
                )

        self.assertEqual(validate("0.6.1", VERSION_LINE)["picotool"], VERSION_LINE)
        for merely_version_shaped in (
            "picotool v2.3.0 (Fixture, Release)",
            "picotool v2.3.1 (Darwin, Release)",
            VERSION_LINE + " ",
            " " + VERSION_LINE,
            VERSION_LINE + "\n",
            VERSION_LINE.replace("picotool", "Picotool"),
            VERSION_LINE.replace("Release", "release"),
            "",
        ):
            with self.subTest(value=merely_version_shaped), self.assertRaises(
                RELEASE.ReleaseError
            ):
                validate("0.6.1", merely_version_shaped)

        for malformed_lock in (
            {
                key: value
                for key, value in source_lock("0.6.1").items()
                if key != "picotool"
            },
            {
                **source_lock("0.6.1"),
                "picotool": {},
            },
        ):
            with self.subTest(lock=malformed_lock), self.assertRaises(
                RELEASE.ReleaseError
            ):
                validate("0.6.1", VERSION_LINE, lock_value=malformed_lock)

        historical = "picotool v2.3.0 (Fixture, Release)"
        self.assertEqual(
            validate(
                "0.6.0",
                historical,
                lock_value=source_lock("0.6.1"),
            )["picotool"],
            historical,
            "the validator checkout's v0.6.1 lock must not reinterpret "
            "historical v0.6.0 evidence",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
