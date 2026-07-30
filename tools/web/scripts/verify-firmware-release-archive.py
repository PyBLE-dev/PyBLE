#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Safely verify and atomically extract an exact firmware release archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

MAX_EXPECTED_MEMBERS = 512
MAX_EXPECTED_BYTES = 128 * 1024 * 1024
TAR_MEMBER_OVERHEAD = 4 * 1024
TAR_FIXED_OVERHEAD = 64 * 1024


class ArchiveError(RuntimeError):
    """The archive is not the exact expected release bundle."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArchiveError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_inventory(
    root: Path,
) -> tuple[set[str], dict[str, tuple[int, str]]]:
    root_mode = root.lstat().st_mode
    _require(stat.S_ISDIR(root_mode), "expected bundle must be an ordinary directory")

    directories: set[str] = set()
    files: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        _require(not stat.S_ISLNK(mode), f"expected bundle contains a link: {relative}")
        if stat.S_ISDIR(mode):
            directories.add(relative)
        elif stat.S_ISREG(mode):
            files[relative] = (path.stat().st_size, _sha256(path))
        else:
            raise ArchiveError(
                f"expected bundle contains a special file: {relative}",
            )
    _require(bool(files), "expected bundle contains no files")
    _require(
        len(directories) + len(files) <= MAX_EXPECTED_MEMBERS,
        "expected bundle has too many entries",
    )
    _require(
        sum(size for size, _digest in files.values()) <= MAX_EXPECTED_BYTES,
        "expected bundle is too large",
    )
    return directories, files


def _canonical_member_name(member: tarfile.TarInfo) -> str:
    name = member.name
    _require(bool(name), "archive member name is empty")
    _require("\\" not in name, f"archive member path uses a backslash: {name}")
    path = PurePosixPath(name)
    _require(not path.is_absolute(), f"archive member path is absolute: {name}")
    _require(
        all(part not in ("", ".", "..") for part in path.parts),
        f"archive member path is not canonical: {name}",
    )
    canonical = path.as_posix()
    _require(
        name == canonical,
        f"archive member path is not canonical: {name}",
    )
    return canonical


def _validated_members(
    archive: tarfile.TarFile,
    expected_directories: set[str],
    expected_files: dict[str, tuple[int, str]],
) -> dict[str, tarfile.TarInfo]:
    seen: set[str] = set()
    regular_members: dict[str, tarfile.TarInfo] = {}
    archive_directories: set[str] = set()
    maximum_members = len(expected_directories) + len(expected_files)

    for member_index, member in enumerate(archive, start=1):
        _require(
            member_index <= maximum_members,
            "archive contains more members than the staged bundle",
        )
        name = _canonical_member_name(member)
        _require(name not in seen, f"duplicate archive member: {name}")
        seen.add(name)

        if member.type == tarfile.DIRTYPE:
            _require(member.size == 0, f"archive directory has data: {name}")
            archive_directories.add(name)
            continue
        _require(
            member.type in (tarfile.REGTYPE, tarfile.AREGTYPE),
            f"archive member type must be a regular file or directory: {name}",
        )
        _require(name in expected_files, f"unexpected archive file: {name}")
        expected_size, _expected_digest = expected_files[name]
        _require(
            member.size == expected_size,
            f"archive member size differs from staged bundle: {name}",
        )
        regular_members[name] = member

    _require(
        archive_directories == expected_directories,
        "archive directory inventory differs from staged bundle",
    )
    _require(
        set(regular_members) == set(expected_files),
        "archive file inventory differs from staged bundle",
    )
    return regular_members


def _archive_size_bounds(
    expected_directories: set[str],
    expected_files: dict[str, tuple[int, str]],
) -> tuple[int, int]:
    member_count = len(expected_directories) + len(expected_files)
    padded_payload = sum(
        ((size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE)
        * tarfile.BLOCKSIZE
        for size, _digest in expected_files.values()
    )
    normal_tar_bytes = (
        padded_payload
        + (member_count + 2) * tarfile.BLOCKSIZE
    )
    maximum_uncompressed = (
        normal_tar_bytes
        + member_count * TAR_MEMBER_OVERHEAD
        + TAR_FIXED_OVERHEAD
    )
    maximum_compressed = maximum_uncompressed + TAR_FIXED_OVERHEAD
    return maximum_compressed, maximum_uncompressed


def _decompress_bounded_archive(
    archive_path: Path,
    destination: Path,
    maximum_uncompressed: int,
) -> None:
    decompressed_bytes = 0
    with gzip.open(archive_path, "rb") as source, destination.open("wb") as target:
        while chunk := source.read(1024 * 1024):
            decompressed_bytes += len(chunk)
            _require(
                decompressed_bytes <= maximum_uncompressed,
                "archive exceeds the bounded uncompressed size",
            )
            target.write(chunk)


def verify_and_extract(
    archive_path: Path,
    expected_bundle: Path,
    output_directory: Path,
) -> None:
    """Validate the complete archive before publishing an extracted directory."""

    archive_path = Path(os.path.abspath(archive_path))
    expected_bundle = Path(os.path.abspath(expected_bundle))
    output_directory = Path(os.path.abspath(output_directory))
    archive_mode = archive_path.lstat().st_mode
    _require(stat.S_ISREG(archive_mode), "archive must be an ordinary file")
    _require(
        not os.path.lexists(output_directory),
        "archive output path already exists",
    )
    output_parent = output_directory.parent
    _require(
        stat.S_ISDIR(output_parent.lstat().st_mode),
        "archive output parent must be an ordinary directory",
    )

    expected_directories, expected_files = _expected_inventory(expected_bundle)
    maximum_compressed, maximum_uncompressed = _archive_size_bounds(
        expected_directories,
        expected_files,
    )
    archive_size = archive_path.stat().st_size
    _require(
        0 < archive_size <= maximum_compressed,
        "archive exceeds the bounded compressed size",
    )
    temporary_workspace = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.verification-",
            dir=output_parent,
        ),
    )
    temporary_workspace.chmod(0o700)
    decompressed_file = temporary_workspace / "archive.tar"
    temporary_root = temporary_workspace / "extracted"
    temporary_root.mkdir(mode=0o700)
    try:
        _decompress_bounded_archive(
            archive_path,
            decompressed_file,
            maximum_uncompressed,
        )
        with tarfile.open(decompressed_file, mode="r:") as archive:
            _validated_members(
                archive,
                expected_directories,
                expected_files,
            )
        with tarfile.open(decompressed_file, mode="r:") as archive:
            members = _validated_members(
                archive,
                expected_directories,
                expected_files,
            )

            for relative in sorted(expected_directories):
                target = temporary_root / relative
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
                target.chmod(0o755)

            for relative in sorted(expected_files):
                member = members[relative]
                source = archive.extractfile(member)
                _require(source is not None, f"cannot read archive member: {relative}")
                target = temporary_root / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                digest = hashlib.sha256()
                size = 0
                with source, target.open("xb") as destination:
                    while chunk := source.read(1024 * 1024):
                        destination.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                target.chmod(0o644)
                expected_size, expected_digest = expected_files[relative]
                _require(
                    size == expected_size and digest.hexdigest() == expected_digest,
                    f"archive bytes differ from staged bundle: {relative}",
                )

        temporary_root.chmod(0o755)
        os.rename(temporary_root, output_directory)
    finally:
        shutil.rmtree(temporary_workspace, ignore_errors=True)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--expected-bundle", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        verify_and_extract(
            args.archive,
            args.expected_bundle,
            args.output_dir,
        )
    except (ArchiveError, OSError, tarfile.TarError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
