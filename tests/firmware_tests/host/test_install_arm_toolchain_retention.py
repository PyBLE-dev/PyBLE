#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for retaining and revalidating the pinned ARM distribution."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "firmware/scripts/install_arm_toolchain.sh"
ARCHIVE_NAME = "arm-gnu-toolchain-14.2.rel1-test-arm-none-eabi.tar.xz"
ARCHIVE_ROOT = "arm-gnu-toolchain-14.2.rel1-test-arm-none-eabi"
MANIFEST = "14.2.rel1-test-arm-none-eabi-manifest.txt"
GCC = b"#!/bin/sh\necho 'arm-none-eabi-gcc fixture 14.2.1 20241119'\n"
GXX = b"#!/bin/sh\necho 'arm-none-eabi-g++ fixture 14.2.1 20241119'\n"
MANIFEST_BYTES = b"Synthetic exact ARM binary release manifest.\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archive_bytes() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as archive:
        for relative, value, mode in (
            ("bin/arm-none-eabi-gcc", GCC, 0o755),
            ("bin/arm-none-eabi-g++", GXX, 0o755),
            (MANIFEST, MANIFEST_BYTES, 0o644),
        ):
            info = tarfile.TarInfo(f"{ARCHIVE_ROOT}/{relative}")
            info.size = len(value)
            info.mode = mode
            info.mtime = 0
            archive.addfile(info, io.BytesIO(value))
    return output.getvalue()


class ArmToolchainRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-arm-retention-red-"
        )
        self.root = Path(self.temporary.name)
        self.archive = self.root / ARCHIVE_NAME
        self.archive.write_bytes(archive_bytes())
        self.destination = self.root / "toolchain"
        self.lock = self.root / "versions.lock"
        self.write_lock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_lock(self, *, gcc_sha: str | None = None) -> None:
        self.lock.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "[arm_gnu_toolchain]\n"
            'release = "14.2.Rel1"\n'
            'gcc_version = "14.2.1 20241119"\n'
            f'sha256 = "{digest(self.archive.read_bytes())}"\n'
            f'url = "https://example.invalid/{ARCHIVE_NAME}"\n'
            f'archive_filename = "{ARCHIVE_NAME}"\n'
            f"archive_bytes = {self.archive.stat().st_size}\n"
            'archive_format = "tar.xz"\n'
            f'archive_root = "{ARCHIVE_ROOT}"\n'
            f'release_manifest_path = "{MANIFEST}"\n'
            f'release_manifest_sha256 = "{digest(MANIFEST_BYTES)}"\n'
            'c_asm_frontend_path = "bin/arm-none-eabi-gcc"\n'
            f'c_asm_frontend_sha256 = "{gcc_sha or digest(GCC)}"\n'
            'cxx_frontend_path = "bin/arm-none-eabi-g++"\n'
            f'cxx_frontend_sha256 = "{digest(GXX)}"\n',
            encoding="utf-8",
        )

    def run_installer(
        self, *, archive: Path | None = None, path_prefix: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYBLE_LOCK_FILE"] = str(self.lock)
        if archive is not None:
            environment["PYBLE_ARM_TARBALL"] = str(archive)
        else:
            environment.pop("PYBLE_ARM_TARBALL", None)
        if path_prefix is not None:
            environment["PATH"] = f"{path_prefix}:{environment['PATH']}"
        return subprocess.run(
            [str(INSTALLER), str(self.destination)],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_install_retains_and_revalidates_the_exact_distribution(self) -> None:
        first = self.run_installer(archive=self.archive)
        self.assertEqual(first.returncode, 0, first.stdout)
        retained = self.destination / ".pyble-dist" / ARCHIVE_NAME
        self.assertEqual(retained.read_bytes(), self.archive.read_bytes())
        self.assertEqual(
            (self.destination / MANIFEST).read_bytes(), MANIFEST_BYTES
        )
        self.assertEqual(
            (self.destination / "bin/arm-none-eabi-gcc").read_bytes(), GCC
        )
        self.assertEqual(
            (self.destination / "bin/arm-none-eabi-g++").read_bytes(), GXX
        )

        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_curl = fake_bin / "curl"
        fake_curl.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
        fake_curl.chmod(0o755)
        second = self.run_installer(path_prefix=fake_bin)
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(retained.read_bytes(), self.archive.read_bytes())

    def test_frontend_hash_mismatch_leaves_no_admitted_install(self) -> None:
        self.write_lock(gcc_sha="0" * 64)
        result = self.run_installer(archive=self.archive)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.destination.exists(), result.stdout)

    def test_missing_retained_archive_is_not_an_idempotent_success(self) -> None:
        first = self.run_installer(archive=self.archive)
        self.assertEqual(first.returncode, 0, first.stdout)
        retained = self.destination / ".pyble-dist" / ARCHIVE_NAME
        retained.unlink()

        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_curl = fake_bin / "curl"
        fake_curl.write_text("#!/bin/sh\nexit 92\n", encoding="utf-8")
        fake_curl.chmod(0o755)
        result = self.run_installer(path_prefix=fake_bin)
        self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
