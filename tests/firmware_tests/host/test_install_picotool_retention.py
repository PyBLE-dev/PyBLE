#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the pinned, retained picotool macOS distribution."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "firmware/scripts/install_picotool.sh"
ARCHIVE_NAME = "picotool-2.3.0-test-mac.zip"
VERSION_LINE = (
    "picotool v2.3.0 "
    "(Darwin, AppleClang-15.0.0.15000309, Release)"
)
EXECUTABLE_PATH = "picotool/picotool"
CONFIG_PATH = "picotool/picotoolConfig.cmake"
CONFIG_VERSION_PATH = "picotool/picotoolConfigVersion.cmake"
TARGETS_PATH = "picotool/picotoolTargets.cmake"
TARGETS_RELEASE_PATH = "picotool/picotoolTargets-release.cmake"
LIBUSB_PATH = "picotool/libusb-1.0.0.dylib"
EXECUTABLE = (
    b"#!/bin/sh\n"
    b"[ \"${1:-}\" = version ] || exit 64\n"
    + f"printf '%s\\n' '{VERSION_LINE}'\n".encode("utf-8")
)
CONFIG = b'include("${CMAKE_CURRENT_LIST_DIR}/picotoolTargets.cmake")\n'
CONFIG_VERSION = b"""set(PACKAGE_VERSION \"2.3.0\")
if(PACKAGE_FIND_VERSION VERSION_GREATER PACKAGE_VERSION)
  set(PACKAGE_VERSION_COMPATIBLE FALSE)
else()
  set(PACKAGE_VERSION_COMPATIBLE TRUE)
  if(PACKAGE_FIND_VERSION STREQUAL PACKAGE_VERSION)
    set(PACKAGE_VERSION_EXACT TRUE)
  endif()
endif()
"""
TARGETS = b"""if(NOT TARGET picotool)
  add_executable(picotool IMPORTED)
  get_filename_component(_IMPORT_PREFIX \"${CMAKE_CURRENT_LIST_DIR}/..\" ABSOLUTE)
  include(\"${CMAKE_CURRENT_LIST_DIR}/picotoolTargets-release.cmake\")
  unset(_IMPORT_PREFIX)
endif()
"""
TARGETS_RELEASE = b"""set_property(TARGET picotool APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(picotool PROPERTIES
  IMPORTED_LOCATION_RELEASE \"${_IMPORT_PREFIX}/picotool/picotool\"
)
"""
LIBUSB = b"synthetic pinned libusb bytes\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_member(
    archive: zipfile.ZipFile,
    name: str,
    value: bytes,
    mode: int,
) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.date_time = (2020, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    archive.writestr(info, value)


def write_archive(
    path: Path,
    *,
    executable: bytes = EXECUTABLE,
    executable_mode: int = stat.S_IFREG | 0o755,
    include_executable: bool = True,
    include_config: bool = True,
    include_libusb: bool = True,
    config: bytes = CONFIG,
    libusb: bytes = LIBUSB,
    extra_members: tuple[tuple[str, bytes, int], ...] = (),
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        _zip_member(archive, ".keep", b"", stat.S_IFREG | 0o644)
        _zip_member(archive, "picotool/", b"", stat.S_IFDIR | 0o755)
        if include_executable:
            _zip_member(
                archive,
                EXECUTABLE_PATH,
                executable,
                executable_mode,
            )
        if include_config:
            for name, value in (
                (CONFIG_PATH, config),
                (CONFIG_VERSION_PATH, CONFIG_VERSION),
                (TARGETS_PATH, TARGETS),
                (TARGETS_RELEASE_PATH, TARGETS_RELEASE),
            ):
                _zip_member(
                    archive,
                    name,
                    value,
                    stat.S_IFREG | 0o644,
                )
        if include_libusb:
            _zip_member(
                archive,
                LIBUSB_PATH,
                libusb,
                stat.S_IFREG | 0o644,
            )
        for name, value, mode in extra_members:
            _zip_member(archive, name, value, mode)


def mark_first_member_encrypted(path: Path) -> None:
    """Set ZIP encryption flags without changing the synthetic member bytes."""
    value = bytearray(path.read_bytes())
    local = value.find(b"PK\x03\x04")
    central = value.find(b"PK\x01\x02")
    if local < 0 or central < 0:
        raise AssertionError("synthetic ZIP headers are missing")
    value[local + 6] |= 0x01
    value[central + 8] |= 0x01
    path.write_bytes(value)


@unittest.skipUnless(
    INSTALLER.is_file(),
    "[red] the pinned picotool installer is not implemented",
)
class PicotoolRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-picotool-retention-red-"
        )
        self.root = Path(self.temporary.name)
        self.archive = self.root / ARCHIVE_NAME
        write_archive(self.archive)
        self.destination = self.root / "installed-picotool"
        self.lock = self.root / "versions.lock"
        self.write_lock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_lock(
        self,
        *,
        archive: Path | None = None,
        executable: bytes = EXECUTABLE,
        executable_sha256: str | None = None,
        version_line: str = VERSION_LINE,
        archive_filename: str = ARCHIVE_NAME,
        url_filename: str = ARCHIVE_NAME,
        archive_bytes: int | None = None,
        archive_sha256: str | None = None,
        cmake_dir: str = "picotool",
        executable_path: str = EXECUTABLE_PATH,
        config_path: str = CONFIG_PATH,
        config_sha256: str | None = None,
        libusb_path: str = LIBUSB_PATH,
        libusb_sha256: str | None = None,
    ) -> None:
        selected_archive = archive or self.archive
        self.lock.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "[picotool]\n"
            'version = "2.3.0"\n'
            f'version_line = "{version_line}"\n'
            'source_repo = "https://github.com/raspberrypi/picotool.git"\n'
            'source_ref = "2.3.0"\n'
            'source_commit = "6f6458d792b93685a11423b244a585eaa99eafcf"\n'
            'distribution_repo = '
            '"https://github.com/raspberrypi/pico-sdk-tools.git"\n'
            'distribution_ref = "v2.3.0-0"\n'
            'distribution_commit = '
            '"ad9e4a8375253cf4886bf168ea1a8d2746aadf24"\n'
            f'url = "https://example.invalid/{url_filename}"\n'
            f'archive_filename = "{archive_filename}"\n'
            f"archive_bytes = "
            f"{selected_archive.stat().st_size if archive_bytes is None else archive_bytes}\n"
            'archive_format = "zip"\n'
            f'sha256 = "{archive_sha256 or digest(selected_archive.read_bytes())}"\n'
            f'cmake_dir = "{cmake_dir}"\n'
            f'executable_path = "{executable_path}"\n'
            f'executable_sha256 = '
            f'"{executable_sha256 or digest(executable)}"\n'
            f'cmake_config_path = "{config_path}"\n'
            f'cmake_config_sha256 = "{config_sha256 or digest(CONFIG)}"\n'
            f'bundled_libusb_path = "{libusb_path}"\n'
            f'bundled_libusb_sha256 = "{libusb_sha256 or digest(LIBUSB)}"\n',
            encoding="utf-8",
        )

    def run_installer(
        self,
        *,
        archive: Path | None = None,
        path_prefix: Path | None = None,
        destination: Path | None = None,
        process_umask: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not INSTALLER.is_file():
            return subprocess.CompletedProcess(
                [str(INSTALLER)],
                127,
                stdout="install_picotool.sh is missing",
            )
        environment = dict(os.environ)
        environment["PYBLE_LOCK_FILE"] = str(self.lock)
        if archive is not None:
            environment["PYBLE_PICOTOOL_ARCHIVE"] = str(archive)
        else:
            environment.pop("PYBLE_PICOTOOL_ARCHIVE", None)
        if path_prefix is not None:
            environment["PATH"] = f"{path_prefix}:{environment['PATH']}"
        return subprocess.run(
            [str(INSTALLER), str(destination or self.destination)],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            preexec_fn=(
                (lambda: os.umask(process_umask))
                if process_umask is not None
                else None
            ),
        )

    def assert_no_staging_tree(self) -> None:
        self.assertEqual(
            [],
            sorted(
                path
                for path in self.root.iterdir()
                if ".incoming." in path.name
            ),
            "a failed installer left a sibling staging tree",
        )

    def test_install_retains_and_revalidates_the_exact_distribution(self) -> None:
        first = self.run_installer(archive=self.archive)
        self.assertEqual(first.returncode, 0, first.stdout)
        retained = self.destination / ".pyble-dist" / ARCHIVE_NAME
        self.assertEqual(retained.read_bytes(), self.archive.read_bytes())
        self.assertEqual(
            (self.destination / EXECUTABLE_PATH).read_bytes(), EXECUTABLE
        )
        self.assertEqual((self.destination / CONFIG_PATH).read_bytes(), CONFIG)
        self.assertEqual(
            (self.destination / CONFIG_VERSION_PATH).read_bytes(),
            CONFIG_VERSION,
        )
        self.assertEqual((self.destination / TARGETS_PATH).read_bytes(), TARGETS)
        self.assertEqual(
            (self.destination / TARGETS_RELEASE_PATH).read_bytes(),
            TARGETS_RELEASE,
        )
        self.assertEqual((self.destination / LIBUSB_PATH).read_bytes(), LIBUSB)
        self.assertTrue(os.access(self.destination / EXECUTABLE_PATH, os.X_OK))

        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_curl = fake_bin / "curl"
        fake_curl.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
        fake_curl.chmod(0o755)
        second = self.run_installer(path_prefix=fake_bin)
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(retained.read_bytes(), self.archive.read_bytes())

    def test_restrictive_umask_cannot_change_retained_tree_modes(self) -> None:
        result = self.run_installer(
            archive=self.archive,
            process_umask=0o077,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            stat.S_IMODE((self.destination / ".pyble-dist").stat().st_mode),
            0o755,
        )
        self.assertEqual(
            stat.S_IMODE(
                (
                    self.destination / ".pyble-dist" / ARCHIVE_NAME
                ).stat().st_mode
            ),
            0o644,
        )

    @unittest.skipUnless(shutil.which("cmake"), "cmake is required for package smoke")
    def test_installed_distribution_is_a_real_find_package_config(self) -> None:
        installed = self.run_installer(archive=self.archive)
        self.assertEqual(installed.returncode, 0, installed.stdout)
        project = self.root / "cmake-smoke"
        project.mkdir()
        (project / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(pyble_picotool_smoke NONE)\n"
            "find_package(picotool 2.3.0 EXACT REQUIRED CONFIG "
            "NO_DEFAULT_PATH PATHS \"${PICOTOOL_PACKAGE_DIR}\")\n"
            "if(NOT TARGET picotool)\n"
            "  message(FATAL_ERROR \"picotool imported target is missing\")\n"
            "endif()\n"
            "get_target_property(_location picotool IMPORTED_LOCATION_RELEASE)\n"
            "if(NOT _location STREQUAL \"${EXPECTED_PICOTOOL}\")\n"
            "  message(FATAL_ERROR \"unexpected picotool location: ${_location}\")\n"
            "endif()\n",
            encoding="utf-8",
        )
        configured = subprocess.run(
            [
                shutil.which("cmake"),
                "-S",
                str(project),
                "-B",
                str(project / "build"),
                "-DPICOTOOL_PACKAGE_DIR=%s"
                % (self.destination / "picotool"),
                "-DEXPECTED_PICOTOOL=%s"
                % (self.destination / EXECUTABLE_PATH),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            configured.returncode,
            0,
            configured.stdout + configured.stderr,
        )

    def test_hash_mismatch_fails_without_admitting_any_install(self) -> None:
        cases = {
            "archive-size": {"archive_bytes": self.archive.stat().st_size + 1},
            "archive-sha": {"archive_sha256": "0" * 64},
            "executable-sha": {"executable_sha256": "0" * 64},
            "config-sha": {"config_sha256": "0" * 64},
            "libusb-sha": {"libusb_sha256": "0" * 64},
        }
        for label, overrides in cases.items():
            with self.subTest(digest=label):
                self.write_lock(**overrides)
                destination = self.root / ("installed-" + label)
                result = self.run_installer(
                    archive=self.archive,
                    destination=destination,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists(), result.stdout)
                self.assert_no_staging_tree()

    def test_same_length_archive_mutation_fails_the_archive_digest(self) -> None:
        original = self.archive.read_bytes()
        mutated = bytearray(original)
        mutated[-1] ^= 1
        self.archive.write_bytes(mutated)
        self.write_lock(
            archive_bytes=len(original),
            archive_sha256=digest(original),
        )

        result = self.run_installer(archive=self.archive)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.destination.exists(), result.stdout)
        self.assert_no_staging_tree()

    def test_component_digests_are_checked_after_archive_digest(self) -> None:
        cases = {
            "changed-config": {"config": b"# changed package config\n"},
            "changed-libusb": {"libusb": b"changed bundled libusb\n"},
        }
        for label, archive_overrides in cases.items():
            with self.subTest(component=label):
                archive = self.root / (label + ".zip")
                write_archive(archive, **archive_overrides)
                self.write_lock(archive=archive)
                destination = self.root / ("installed-" + label)
                result = self.run_installer(
                    archive=archive,
                    destination=destination,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists(), result.stdout)
                self.assert_no_staging_tree()

    def test_exact_version_line_is_required_before_admission(self) -> None:
        wrong = self.root / "wrong-version.zip"
        wrong_executable = EXECUTABLE.replace(b"v2.3.0", b"v2.3.1")
        write_archive(wrong, executable=wrong_executable)
        self.write_lock(archive=wrong, executable=wrong_executable)

        result = self.run_installer(archive=wrong)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.destination.exists(), result.stdout)
        self.assert_no_staging_tree()

    def test_unsafe_zip_topologies_fail_before_destination_admission(self) -> None:
        cases = {
            "escaping-member": (("../escape", b"escape", stat.S_IFREG | 0o644),),
            "nested-escape": (
                ("picotool/../escape", b"escape", stat.S_IFREG | 0o644),
            ),
            "absolute-member": (("/absolute", b"escape", stat.S_IFREG | 0o644),),
            "unexpected-root": (("other/tool", b"tool", stat.S_IFREG | 0o755),),
            "duplicate-member": (
                (EXECUTABLE_PATH, EXECUTABLE, stat.S_IFREG | 0o755),
            ),
            "symlink": (("picotool/link", b"picotool", stat.S_IFLNK | 0o777),),
            "special-file": (("picotool/fifo", b"", stat.S_IFIFO | 0o644),),
        }
        for label, members in cases.items():
            with self.subTest(topology=label):
                archive = self.root / f"{label}.zip"
                write_archive(archive, extra_members=members)
                self.write_lock(archive=archive)
                destination = self.root / f"installed-{label}"
                result = self.run_installer(
                    archive=archive,
                    destination=destination,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists(), result.stdout)
                self.assert_no_staging_tree()

    def test_missing_nonexecutable_or_encrypted_required_members_are_rejected(self):
        cases = {}
        missing_executable = self.root / "missing-executable.zip"
        write_archive(missing_executable, include_executable=False)
        cases["missing-executable"] = missing_executable
        missing_config = self.root / "missing-config.zip"
        write_archive(missing_config, include_config=False)
        cases["missing-config"] = missing_config
        missing_libusb = self.root / "missing-libusb.zip"
        write_archive(missing_libusb, include_libusb=False)
        cases["missing-libusb"] = missing_libusb
        nonexecutable = self.root / "nonexecutable.zip"
        write_archive(
            nonexecutable,
            executable_mode=stat.S_IFREG | 0o644,
        )
        cases["nonexecutable"] = nonexecutable
        encrypted = self.root / "encrypted.zip"
        write_archive(encrypted)
        mark_first_member_encrypted(encrypted)
        cases["encrypted"] = encrypted

        for label, archive in cases.items():
            with self.subTest(member=label):
                self.write_lock(archive=archive)
                destination = self.root / f"installed-{label}"
                result = self.run_installer(
                    archive=archive,
                    destination=destination,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists(), result.stdout)
                self.assert_no_staging_tree()

    def test_preexisting_mismatched_destination_is_preserved_and_rejected(self) -> None:
        self.destination.mkdir()
        sentinel = self.destination / "operator-owned-sentinel"
        sentinel.write_bytes(b"do not replace\n")

        result = self.run_installer(archive=self.archive)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(sentinel.read_bytes(), b"do not replace\n")
        self.assertEqual([sentinel], list(self.destination.iterdir()))
        self.assert_no_staging_tree()

    def test_retained_tree_is_revalidated_byte_for_byte_without_extras(self) -> None:
        cases = {
            "mutated-targets": lambda root: (
                root / TARGETS_PATH
            ).write_bytes(b"tampered targets\n"),
            "mutated-libusb": lambda root: (
                root / LIBUSB_PATH
            ).write_bytes(b"tampered libusb\n"),
            "mutated-retained-archive": lambda root: (
                root / ".pyble-dist" / ARCHIVE_NAME
            ).write_bytes(b"tampered retained archive\n"),
            "changed-mode": lambda root: (
                root / CONFIG_VERSION_PATH
            ).chmod(0o600),
            "injected-extra": lambda root: (
                root / "picotool" / "unreviewed-extra"
            ).write_bytes(b"not in the distribution\n"),
        }
        for label, mutate in cases.items():
            with self.subTest(tree=label):
                destination = self.root / ("installed-tree-" + label)
                first = self.run_installer(
                    archive=self.archive,
                    destination=destination,
                )
                self.assertEqual(first.returncode, 0, first.stdout)
                mutate(destination)
                before = {
                    path.relative_to(destination).as_posix(): (
                        path.read_bytes(), path.stat().st_mode & 0o777
                    )
                    for path in destination.rglob("*")
                    if path.is_file()
                }
                fake_bin = self.root / ("fake-bin-" + label)
                fake_bin.mkdir()
                fake_curl = fake_bin / "curl"
                fake_curl.write_text("#!/bin/sh\nexit 93\n", encoding="utf-8")
                fake_curl.chmod(0o755)
                second = self.run_installer(
                    path_prefix=fake_bin,
                    destination=destination,
                )
                self.assertNotEqual(second.returncode, 0, second.stdout)
                after = {
                    path.relative_to(destination).as_posix(): (
                        path.read_bytes(), path.stat().st_mode & 0o777
                    )
                    for path in destination.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before, "revalidation rewrote owner bytes")
                self.assert_no_staging_tree()

    def test_lock_controlled_paths_and_url_basename_cannot_escape(self) -> None:
        cases = {
            "archive-parent": {"archive_filename": "../escape.zip"},
            "archive-absolute": {"archive_filename": "/tmp/escape.zip"},
            "url-mismatch": {"url_filename": "different.zip"},
            "cmake-parent": {"cmake_dir": "../picotool"},
            "executable-parent": {"executable_path": "picotool/../tool"},
            "config-absolute": {"config_path": "/tmp/config.cmake"},
            "libusb-parent": {"libusb_path": "../libusb.dylib"},
        }
        for label, overrides in cases.items():
            with self.subTest(lock_path=label):
                self.write_lock(**overrides)
                destination = self.root / ("installed-lock-" + label)
                result = self.run_installer(
                    archive=self.archive,
                    destination=destination,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists(), result.stdout)
                self.assert_no_staging_tree()

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
        self.assertFalse(retained.exists())

    def test_symlinked_input_archive_and_destination_are_rejected(self) -> None:
        archive_link = self.root / "archive-link.zip"
        archive_link.symlink_to(self.archive)
        input_result = self.run_installer(archive=archive_link)
        self.assertNotEqual(input_result.returncode, 0, input_result.stdout)
        self.assertFalse(self.destination.exists())

        external = self.root / "external-destination"
        external.mkdir()
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"outside\n")
        destination_link = self.root / "destination-link"
        destination_link.symlink_to(external, target_is_directory=True)
        destination_result = self.run_installer(
            archive=self.archive,
            destination=destination_link,
        )
        self.assertNotEqual(destination_result.returncode, 0, destination_result.stdout)
        self.assertEqual(sentinel.read_bytes(), b"outside\n")
        self.assertEqual([sentinel], list(external.iterdir()))

        external_parent = self.root / "external-parent"
        external_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(external_parent, target_is_directory=True)
        ancestor_result = self.run_installer(
            archive=self.archive,
            destination=linked_parent / "installed",
        )
        self.assertNotEqual(ancestor_result.returncode, 0, ancestor_result.stdout)
        self.assertFalse((external_parent / "installed").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
