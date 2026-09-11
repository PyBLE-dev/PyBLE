#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Install and retain the exact official picotool distribution pinned by the
# [picotool] section of firmware/versions.lock. Admission is atomic: the ZIP,
# every extracted member, required component hashes, executable mode, and the
# exact runtime version line are verified in a fresh sibling before rename.
# Existing installs are accepted only after complete byte-for-byte
# revalidation and are otherwise preserved for operator inspection.
#
#   install_picotool.sh [DEST]  (default: firmware/.picotool)
#
#   PYBLE_PICOTOOL_ARCHIVE=<path>  use a local ZIP without downloading it
#                                  (the same pin checks still apply)
#   PYBLE_LOCK_FILE=<path>          override versions.lock for test/provisioning

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
FW="$(cd "$HERE/.." && pwd -P)"
LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
DEST="${1:-${PYBLE_PICOTOOL_DIR:-$FW/.picotool}}"
ARCHIVE_OVERRIDE="${PYBLE_PICOTOOL_ARCHIVE:-}"

# The Python standard library supplies strict TOML and ZIP readers on every
# supported build host. Keeping extraction here avoids platform-specific
# `unzip` path/link behavior while the shell remains the public entry point.
python3 - "$LOCK" "$DEST" "$ARCHIVE_OVERRIDE" "$FW/.picotool" <<'PY'
from __future__ import annotations

import ctypes
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import tomllib
import urllib.parse
import urllib.request
import zipfile


lock_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
archive_override = sys.argv[3]
default_destination = sys.argv[4]


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"install_picotool: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: object, label: str, *, basename: bool = False) -> str:
    if not isinstance(value, str) or not value:
        fail(f"[picotool] {label} must be a nonempty string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value.endswith("/")
        or any(part in ("", ".", "..") for part in path.parts)
        or (basename and len(path.parts) != 1)
    ):
        fail(f"[picotool] {label} is unsafe: {value!r}")
    return value


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def reject_symlinked_existing_ancestors(path: Path, label: str) -> None:
    probe = path.absolute()
    while True:
        try:
            mode = probe.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            # Darwin exposes long-standing root aliases such as /var ->
            # /private/var and /tmp -> /private/tmp. Those privileged,
            # root-owned aliases are part of the platform path layout; a
            # symlink at any deeper caller-controlled component is not.
            if stat.S_ISLNK(mode) and probe.parent != Path(probe.anchor):
                fail(f"{label} has a symlinked ancestor: {probe}")
        if probe.parent == probe:
            break
        probe = probe.parent


def absolute_lexical_path(path: Path, label: str) -> Path:
    """Normalize a path without following caller-controlled symlinks."""

    if os.name != "posix" or not hasattr(os, "O_DIRECTORY") or not hasattr(
        os, "O_NOFOLLOW"
    ):
        fail(f"{label} requires reviewed POSIX dirfd support")
    try:
        raw = os.fspath(path)
        if not isinstance(raw, str) or not raw:
            fail(f"{label} path is invalid")
        if any(component == ".." for component in raw.split(os.sep)):
            fail(f"{label} contains lexical navigation")
        value = Path(os.path.abspath(raw))
        # Darwin's system-owned /var alias is part of the platform layout and
        # is commonly returned by tempfile. Normalize only that fixed alias;
        # every caller-controlled component remains subject to O_NOFOLLOW.
        if value.parts[:2] == (os.sep, "var"):
            try:
                if os.readlink("/var") == "private/var":
                    value = Path("/private/var").joinpath(*value.parts[2:])
            except OSError:
                pass
        return value
    except (OSError, TypeError, ValueError) as error:
        fail(f"{label} path is invalid: {error}")


def directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def close_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
) -> None:
    for descriptor, _path, _identity in reversed(chain):
        try:
            os.close(descriptor)
        except OSError:
            pass


def verify_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
    label: str,
) -> None:
    for descriptor, path, expected in chain:
        try:
            held = os.fstat(descriptor)
            visible = path.lstat()
        except OSError as error:
            fail(f"{label} identity changed: {error}")
        if not (
            stat.S_ISDIR(held.st_mode)
            and stat.S_ISDIR(visible.st_mode)
            and not stat.S_ISLNK(visible.st_mode)
            and directory_identity(held) == expected
            and directory_identity(visible) == expected
        ):
            fail(f"{label} identity changed")


def open_directory_chain(
    path: Path,
    label: str,
) -> list[tuple[int, Path, tuple[int, int, int]]]:
    """Hold every existing directory component through no-follow dirfds."""

    directory = absolute_lexical_path(path, label)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    chain: list[tuple[int, Path, tuple[int, int, int]]] = []
    try:
        descriptor = os.open(os.sep, flags)
        opened = os.fstat(descriptor)
        chain.append((descriptor, Path(os.sep), directory_identity(opened)))
        current = Path(os.sep)
        for component in directory.parts[1:]:
            descriptor = os.open(component, flags, dir_fd=chain[-1][0])
            opened = os.fstat(descriptor)
            current = current / component
            if not stat.S_ISDIR(opened.st_mode):
                fail(f"{label} has a non-directory component: {current}")
            chain.append((descriptor, current, directory_identity(opened)))
        verify_directory_chain(chain, label)
        return chain
    except SystemExit:
        close_directory_chain(chain)
        raise
    except OSError as error:
        close_directory_chain(chain)
        fail(f"{label} is unsafe: {error}")


def new_sibling_name(
    parent_descriptor: int,
    prefix: str,
    suffix: str,
    *,
    directory: bool,
) -> tuple[str, tuple[int, int]]:
    """Create an unpredictable sibling through the held parent descriptor."""

    for _attempt in range(128):
        name = f"{prefix}{secrets.token_hex(8)}{suffix}"
        try:
            if directory:
                os.mkdir(name, 0o700, dir_fd=parent_descriptor)
            else:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                descriptor = os.open(
                    name,
                    flags,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                try:
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
        except FileExistsError:
            continue
        opened = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_kind(opened.st_mode):
            fail("new staging member has an unsafe type")
        return name, (opened.st_dev, opened.st_ino)
    fail("could not allocate a unique staging member")


def remove_owned_file(
    parent_descriptor: int,
    name: str | None,
    identity: tuple[int, int] | None,
) -> None:
    if name is None or identity is None:
        return
    try:
        visible = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(visible.st_mode)
            or (visible.st_dev, visible.st_ino) != identity
        ):
            return
        os.unlink(name, dir_fd=parent_descriptor)
    except OSError:
        pass


def remove_owned_tree(
    parent_descriptor: int,
    name: str | None,
    identity: tuple[int, int] | None,
) -> None:
    if name is None or identity is None:
        return
    try:
        visible = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISDIR(visible.st_mode)
            or stat.S_ISLNK(visible.st_mode)
            or (visible.st_dev, visible.st_ino) != identity
        ):
            return
        if not shutil.rmtree.avoids_symlink_attacks:
            return
        shutil.rmtree(name, dir_fd=parent_descriptor)
    except OSError:
        pass


def atomic_publish_no_replace(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    """Rename siblings through one held parent while refusing replacement."""

    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination_value = os.fsencode(destination_name)
    if sys.platform == "darwin":
        operation = getattr(libc, "renameatx_np", None)
        if operation is None:
            fail("cannot prove atomic no-replace publication on Darwin")
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        arguments = (
            parent_descriptor,
            source,
            parent_descriptor,
            destination_value,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        operation = getattr(libc, "renameat2", None)
        if operation is None:
            fail("cannot prove atomic no-replace publication on Linux")
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        arguments = (
            parent_descriptor,
            source,
            parent_descriptor,
            destination_value,
            0x00000001,  # RENAME_NOREPLACE
        )
    else:
        fail(f"no reviewed atomic no-replace operation exists on {sys.platform}")

    ctypes.set_errno(0)
    if operation(*arguments) == 0:
        return
    error_number = ctypes.get_errno() or errno.EIO
    if error_number in (errno.EEXIST, errno.ENOTEMPTY, errno.EISDIR, errno.ENOTDIR):
        fail("destination appeared during atomic admission")
    fail(f"atomic no-replace publication failed: {os.strerror(error_number)}")


try:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
    fail(f"cannot read lock file {lock_path}: {error}")

raw_pin = lock.get("picotool")
if not isinstance(raw_pin, dict):
    fail(f"could not read [picotool] from {lock_path}")

required_keys = {
    "version",
    "version_line",
    "source_repo",
    "source_ref",
    "source_commit",
    "distribution_repo",
    "distribution_ref",
    "distribution_commit",
    "url",
    "archive_filename",
    "archive_bytes",
    "archive_format",
    "sha256",
    "cmake_dir",
    "executable_path",
    "executable_sha256",
    "cmake_config_path",
    "cmake_config_sha256",
    "bundled_libusb_path",
    "bundled_libusb_sha256",
}
if set(raw_pin) != required_keys:
    fail("[picotool] fields differ from the reviewed pin schema")

pin = raw_pin
for key in required_keys - {"archive_bytes"}:
    if not isinstance(pin[key], str) or not pin[key]:
        fail(f"[picotool] {key} must be a nonempty string")
if not isinstance(pin["archive_bytes"], int) or isinstance(
    pin["archive_bytes"], bool
) or pin["archive_bytes"] <= 0:
    fail("[picotool] archive_bytes must be a positive integer")
if pin["archive_format"] != "zip":
    fail("[picotool] archive_format must be zip")
for key in (
    "source_commit",
    "distribution_commit",
):
    if re.fullmatch(r"[0-9a-f]{40}", pin[key]) is None:
        fail(f"[picotool] {key} is not a full lowercase Git commit")
for key in (
    "sha256",
    "executable_sha256",
    "cmake_config_sha256",
    "bundled_libusb_sha256",
):
    if re.fullmatch(r"[0-9a-f]{64}", pin[key]) is None:
        fail(f"[picotool] {key} is not a lowercase SHA-256")

archive_filename = safe_relative(
    pin["archive_filename"], "archive_filename", basename=True
)
cmake_dir = safe_relative(pin["cmake_dir"], "cmake_dir")
executable_path = safe_relative(pin["executable_path"], "executable_path")
config_path = safe_relative(pin["cmake_config_path"], "cmake_config_path")
libusb_path = safe_relative(
    pin["bundled_libusb_path"], "bundled_libusb_path"
)
url_path = urllib.parse.unquote(urllib.parse.urlsplit(pin["url"]).path)
if PurePosixPath(url_path).name != archive_filename:
    fail("archive_filename disagrees with the pinned URL basename")
if cmake_dir != "picotool":
    fail("cmake_dir differs from the reviewed picotool package root")
for value, label in (
    (executable_path, "executable_path"),
    (config_path, "cmake_config_path"),
    (libusb_path, "bundled_libusb_path"),
):
    if PurePosixPath(value).parts[0] != cmake_dir:
        fail(f"[picotool] {label} escapes cmake_dir")

required_members = {
    ".keep",
    "picotool/",
    executable_path,
    config_path,
    "picotool/picotoolConfigVersion.cmake",
    "picotool/picotoolTargets.cmake",
    "picotool/picotoolTargets-release.cmake",
    libusb_path,
}


def checked_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, int]]:
    members: list[tuple[zipfile.ZipInfo, int]] = []
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if name in seen:
            fail(f"duplicate ZIP member: {name}")
        seen.add(name)
        if info.flag_bits & 0x1:
            fail(f"encrypted ZIP member is not supported: {name}")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in ("", ".", "..") for part in path.parts)
        ):
            fail(f"unsafe ZIP member path: {name}")
        if not (name == ".keep" or path.parts[0] == "picotool"):
            fail(f"unexpected top-level ZIP member: {name}")
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if info.is_dir():
            if kind not in (0, stat.S_IFDIR) or not name.endswith("/"):
                fail(f"invalid ZIP directory type: {name}")
            mode = stat.S_IFDIR | (stat.S_IMODE(mode) or 0o755)
        else:
            if name.endswith("/") or kind not in (0, stat.S_IFREG):
                fail(f"unsupported ZIP member type: {name}")
            mode = stat.S_IFREG | (stat.S_IMODE(mode) or 0o644)
        members.append((info, mode))
    missing = required_members - seen
    if missing:
        fail("required ZIP members are missing: " + ", ".join(sorted(missing)))
    executable = next(mode for info, mode in members if info.filename == executable_path)
    if not executable & stat.S_IXUSR:
        fail("pinned picotool member is not executable")
    return members


def validate_archive(path: Path) -> list[tuple[zipfile.ZipInfo, int]]:
    if not regular_file(path):
        fail(f"archive is not a regular non-symlink file: {path}")
    size = path.stat().st_size
    if size != pin["archive_bytes"]:
        fail(f"archive size mismatch: wanted {pin['archive_bytes']}, got {size}")
    actual = sha256(path)
    if actual != pin["sha256"]:
        fail(f"archive SHA-256 mismatch: wanted {pin['sha256']}, got {actual}")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = checked_members(archive)
            bad = archive.testzip()
            if bad is not None:
                fail(f"ZIP member failed CRC verification: {bad}")
            return members
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        fail(f"invalid ZIP archive: {error}")


def copy_download_bounded(response: object, output: object) -> None:
    """Copy at most the pinned archive size plus one detection byte."""

    total = 0
    while True:
        allowance = pin["archive_bytes"] + 1 - total
        if allowance <= 0:
            fail("download exceeded the pinned archive_bytes bound")
        chunk = response.read(min(1024 * 1024, allowance))
        if not chunk:
            return
        if not isinstance(chunk, bytes):
            fail("download returned non-byte content")
        output.write(chunk)
        total += len(chunk)
        if total > pin["archive_bytes"]:
            fail("download exceeded the pinned archive_bytes bound")


def expected_tree_from_archive(path: Path) -> dict[str, tuple[str, int, bytes | None]]:
    expected: dict[str, tuple[str, int, bytes | None]] = {
        ".pyble-dist": ("dir", 0o755, None),
        f".pyble-dist/{archive_filename}": ("file", 0o644, path.read_bytes()),
    }
    with zipfile.ZipFile(path, "r") as archive:
        for info, mode in checked_members(archive):
            relative = info.filename.rstrip("/")
            if info.is_dir():
                expected[relative] = ("dir", stat.S_IMODE(mode), None)
            else:
                expected[relative] = (
                    "file",
                    stat.S_IMODE(mode),
                    archive.read(info),
                )
    return expected


def validate_component(path: Path, wanted: str, label: str) -> None:
    if not regular_file(path):
        fail(f"{label} is missing, non-regular, or symlinked: {path}")
    actual = sha256(path)
    if actual != wanted:
        fail(f"{label} SHA-256 mismatch: wanted {wanted}, got {actual}")


def validate_version(root: Path) -> None:
    executable = root / executable_path
    if not os.access(executable, os.X_OK):
        fail(f"pinned picotool is not executable: {executable}")
    try:
        completed = subprocess.run(
            [str(executable), "version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        fail(f"could not execute pinned picotool: {error}")
    if completed.returncode != 0 or completed.stdout != pin["version_line"] + "\n":
        fail(
            "picotool version mismatch: wanted {!r}, got {!r}".format(
                pin["version_line"], completed.stdout.rstrip("\n")
            )
        )


def validate_installed_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        fail(f"install root is missing, symlinked, or not a directory: {root}")
    retained = root / ".pyble-dist" / archive_filename
    validate_archive(retained)
    expected = expected_tree_from_archive(retained)
    observed: set[str] = set()
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            child = current_path / name
            relative = child.relative_to(root).as_posix()
            observed.add(relative)
            try:
                mode = child.lstat().st_mode
            except OSError as error:
                fail(f"cannot inspect installed member {relative}: {error}")
            wanted = expected.get(relative)
            if wanted is None:
                fail(f"installed tree has an unexpected member: {relative}")
            wanted_kind, wanted_mode, wanted_bytes = wanted
            if wanted_kind == "dir":
                if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                    fail(f"installed directory type changed: {relative}")
            else:
                if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                    fail(f"installed file type changed: {relative}")
                if child.read_bytes() != wanted_bytes:
                    fail(f"installed member bytes changed: {relative}")
            if stat.S_IMODE(mode) != wanted_mode:
                fail(f"installed member mode changed: {relative}")
    if observed != set(expected):
        missing = sorted(set(expected) - observed)
        fail("installed tree is incomplete: " + ", ".join(missing))
    validate_component(root / executable_path, pin["executable_sha256"], "picotool")
    validate_component(root / config_path, pin["cmake_config_sha256"], "CMake config")
    validate_component(root / libusb_path, pin["bundled_libusb_sha256"], "bundled libusb")


def validate_installed(root: Path) -> None:
    # The executable probe is an intentionally bounded external callback. A
    # complete second tree pass after it prevents a concurrent mutation during
    # that callback from being admitted as an exact retained distribution.
    validate_installed_tree(root)
    validate_version(root)
    validate_installed_tree(root)


def validate_installed_descriptor(
    descriptor: int,
    expected_identity: tuple[int, int, int],
    label: str,
) -> None:
    """Revalidate one held directory inode, independent of path replacement."""

    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or directory_identity(opened) != expected_identity
    ):
        fail(f"{label} identity changed before revalidation")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    original_working_directory = os.open(".", flags)
    try:
        os.fchdir(descriptor)
        validate_installed(Path("."))
    finally:
        try:
            os.fchdir(original_working_directory)
        finally:
            os.close(original_working_directory)
    reopened = os.fstat(descriptor)
    if directory_identity(reopened) != expected_identity:
        fail(f"{label} identity changed during revalidation")


destination = absolute_lexical_path(destination, "destination")
if destination.name in ("", ".", ".."):
    fail("destination name is unsafe")
reject_symlinked_existing_ancestors(destination, "destination")
parent = destination.parent
reject_symlinked_existing_ancestors(parent, "destination parent")
parent.mkdir(parents=True, exist_ok=True)
reject_symlinked_existing_ancestors(parent, "destination parent")
if not parent.is_dir():
    fail(f"destination parent is not a directory: {parent}")

parent_chain = open_directory_chain(parent, "destination parent")
parent_descriptor = parent_chain[-1][0]
temporary_download: Path | None = None
temporary_download_name: str | None = None
temporary_download_identity: tuple[int, int] | None = None
incoming: Path | None = None
incoming_name: str | None = None
incoming_identity: tuple[int, int] | None = None
incoming_descriptor: int | None = None
published = False
try:
    verify_directory_chain(parent_chain, "destination parent")
    if os.path.lexists(destination):
        existing = os.stat(
            destination.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(existing.st_mode) or stat.S_ISLNK(existing.st_mode):
            fail(f"existing destination is unsafe and was preserved: {destination}")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        existing_descriptor = os.open(
            destination.name,
            directory_flags,
            dir_fd=parent_descriptor,
        )
        try:
            try:
                validate_installed_descriptor(
                    existing_descriptor,
                    directory_identity(existing),
                    "existing destination",
                )
            except SystemExit as error:
                fail(
                    "existing destination does not match the complete pin; "
                    f"preserved ({error})"
                )
        finally:
            os.close(existing_descriptor)
        verify_directory_chain(parent_chain, "destination parent")
        reopened = os.stat(
            destination.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        visible = destination.lstat()
        if not (
            directory_identity(existing) == directory_identity(reopened)
            and directory_identity(reopened) == directory_identity(visible)
        ):
            fail("existing destination identity changed during revalidation")
        verify_directory_chain(parent_chain, "destination parent")
        print(
            "install_picotool: already installed and matching the complete pin at "
            f"{destination}"
        )
        raise SystemExit(0)

    if archive_override:
        archive_path = absolute_lexical_path(
            Path(archive_override),
            "input archive",
        )
        reject_symlinked_existing_ancestors(archive_path, "input archive")
    else:
        temporary_download_name, temporary_download_identity = new_sibling_name(
            parent_descriptor,
            ".picotool-download.",
            ".zip",
            directory=False,
        )
        temporary_download = parent / temporary_download_name
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                flags = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                output_descriptor = os.open(
                    temporary_download_name,
                    flags,
                    dir_fd=parent_descriptor,
                )
                opened = os.fstat(output_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != temporary_download_identity
                ):
                    os.close(output_descriptor)
                    fail("download staging file identity changed")
                with os.fdopen(output_descriptor, "wb") as output:
                    with urllib.request.urlopen(pin["url"], timeout=60) as response:
                        copy_download_bounded(response, output)
                last_error = None
                break
            except Exception as error:  # network errors vary by Python/platform
                last_error = error
                if attempt != 2:
                    time.sleep(1 << attempt)
        if last_error is not None:
            fail(f"download failed after three attempts: {last_error}")
        archive_path = temporary_download

    verify_directory_chain(parent_chain, "destination parent")
    members = validate_archive(archive_path)
    verify_directory_chain(parent_chain, "destination parent")
    incoming_name, incoming_identity = new_sibling_name(
        parent_descriptor,
        f".{destination.name}.incoming.",
        "",
        directory=True,
    )
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    incoming_descriptor = os.open(
        incoming_name,
        directory_flags,
        dir_fd=parent_descriptor,
    )
    original_working_directory = os.open(".", directory_flags)
    try:
        opened_incoming = os.fstat(incoming_descriptor)
        if (
            not stat.S_ISDIR(opened_incoming.st_mode)
            or (opened_incoming.st_dev, opened_incoming.st_ino)
            != incoming_identity
        ):
            fail("staging directory identity changed")
        verify_directory_chain(parent_chain, "destination parent")
        os.fchdir(incoming_descriptor)
        incoming = Path(".")
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info, mode in members:
                target = incoming.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=False)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as source, target.open(
                        "xb"
                    ) as output:
                        shutil.copyfileobj(source, output)
                target.chmod(stat.S_IMODE(mode))

        retained_dir = incoming / ".pyble-dist"
        retained_dir.mkdir(mode=0o755)
        retained_dir.chmod(0o755)
        retained_archive = retained_dir / archive_filename
        with archive_path.open("rb") as source, retained_archive.open(
            "xb"
        ) as output:
            shutil.copyfileobj(source, output)
        retained_archive.chmod(0o644)

        validate_installed(incoming)
    finally:
        os.fchdir(original_working_directory)
        os.close(original_working_directory)
    verify_directory_chain(parent_chain, "destination parent")
    if os.path.lexists(destination):
        fail(f"destination appeared during admission: {destination}")
    verify_directory_chain(parent_chain, "destination parent")
    atomic_publish_no_replace(
        parent_descriptor,
        incoming_name,
        destination.name,
    )
    published = True
    admitted = os.stat(
        destination.name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISDIR(admitted.st_mode)
        or stat.S_ISLNK(admitted.st_mode)
        or (admitted.st_dev, admitted.st_ino) != incoming_identity
    ):
        fail("published destination identity changed")
    verify_directory_chain(parent_chain, "destination parent")
    visible = destination.lstat()
    if directory_identity(visible) != directory_identity(admitted):
        fail("published destination is not visible through the held parent")
    verify_directory_chain(parent_chain, "destination parent")
    validate_installed_descriptor(
        incoming_descriptor,
        directory_identity(admitted),
        "published destination",
    )
    admitted = os.stat(
        destination.name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISDIR(admitted.st_mode)
        or stat.S_ISLNK(admitted.st_mode)
        or (admitted.st_dev, admitted.st_ino) != incoming_identity
    ):
        fail("published destination identity changed during revalidation")
    verify_directory_chain(parent_chain, "destination parent")
    visible = destination.lstat()
    if directory_identity(visible) != directory_identity(admitted):
        fail("revalidated destination is not visible through the held parent")
    verify_directory_chain(parent_chain, "destination parent")
    os.close(incoming_descriptor)
    incoming_descriptor = None
    incoming = None
    incoming_name = None
    incoming_identity = None
finally:
    if incoming_descriptor is not None:
        try:
            os.close(incoming_descriptor)
        except OSError:
            pass
    if published:
        # A post-publication parent/identity failure removes only the inode we
        # admitted through the held parent. A contender in a replacement
        # visible parent is never addressed by path and is therefore kept.
        remove_owned_tree(
            parent_descriptor,
            destination.name,
            incoming_identity,
        )
    else:
        remove_owned_tree(
            parent_descriptor,
            incoming_name,
            incoming_identity,
        )
    remove_owned_file(
        parent_descriptor,
        temporary_download_name,
        temporary_download_identity,
    )
    close_directory_chain(parent_chain)

print(f"install_picotool: picotool {pin['version']} ready at {destination}")
PY
