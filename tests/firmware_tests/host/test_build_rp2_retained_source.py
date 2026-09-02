#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for an isolated, release-auditable RP2 build."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import textwrap
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[3]
BUILD_RP2 = ROOT / "firmware" / "scripts" / "build_rp2.sh"
TARGET = "rpi-pico2-w"
BOARD = "PYBLE_RPI_PICO2_W"
MICROPYTHON_ORIGIN = "https://example.invalid/micropython.git"
NESTED_SUBMODULES = (
    "lib/btstack",
    "lib/cyw43-driver",
    "lib/lwip",
    "lib/mbedtls",
    "lib/micropython-lib",
    "lib/pico-sdk",
    "lib/tinyusb",
)
PICOTOOL_VERSION_LINE = (
    "picotool v2.3.0 (Darwin, AppleClang-15.0.0.15000309, Release)"
)
PICOTOOL_EXECUTABLE = (
    b"#!/bin/sh\n"
    b"[ \"${1:-}\" = version ] || exit 64\n"
    + f"printf '%s\\n' '{PICOTOOL_VERSION_LINE}'\n".encode("utf-8")
)
PICOTOOL_CONFIG = b'include("${CMAKE_CURRENT_LIST_DIR}/picotoolTargets.cmake")\n'
PICOTOOL_CONFIG_VERSION = b'set(PACKAGE_VERSION "2.3.0")\n'
PICOTOOL_TARGETS = b'include("${CMAKE_CURRENT_LIST_DIR}/picotoolTargets-release.cmake")\n'
PICOTOOL_TARGETS_RELEASE = (
    b'set_target_properties(picotool PROPERTIES IMPORTED_LOCATION_RELEASE '
    b'"${_IMPORT_PREFIX}/picotool/picotool")\n'
)
PICOTOOL_LIBUSB = b"synthetic pinned libusb bytes\n"


def _picotool_archive(
    executable: bytes = PICOTOOL_EXECUTABLE,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value, mode in (
            (".keep", b"", stat.S_IFREG | 0o644),
            ("picotool/", b"", stat.S_IFDIR | 0o755),
            ("picotool/picotool", executable, stat.S_IFREG | 0o755),
            (
                "picotool/picotoolConfig.cmake",
                PICOTOOL_CONFIG,
                stat.S_IFREG | 0o644,
            ),
            (
                "picotool/picotoolConfigVersion.cmake",
                PICOTOOL_CONFIG_VERSION,
                stat.S_IFREG | 0o644,
            ),
            (
                "picotool/picotoolTargets.cmake",
                PICOTOOL_TARGETS,
                stat.S_IFREG | 0o644,
            ),
            (
                "picotool/picotoolTargets-release.cmake",
                PICOTOOL_TARGETS_RELEASE,
                stat.S_IFREG | 0o644,
            ),
            (
                "picotool/libusb-1.0.0.dylib",
                PICOTOOL_LIBUSB,
                stat.S_IFREG | 0o444,
            ),
        ):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.external_attr = mode << 16
            archive.writestr(info, value)
    return output.getvalue()


PICOTOOL_ARCHIVE = _picotool_archive()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            "command failed ({}):\n{}".format(
                " ".join(arguments), completed.stdout
            )
        )
    return completed


def _git(path: Path, *arguments: str) -> str:
    completed = _run(
        ["git", "-C", str(path), *arguments],
        cwd=path,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
        check=True,
    )
    return completed.stdout.strip()


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _commit_all(path: Path, message: str) -> str:
    _git(path, "add", ".")
    _git(path, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def _uf2_block(
    *,
    flags: int,
    address: int,
    payload: bytes,
    block_number: int,
    total_blocks: int,
    family: int,
    extension_word: int | None = None,
) -> bytes:
    block = bytearray(512)
    struct.pack_into(
        "<IIIIIIII",
        block,
        0,
        0x0A324655,
        0x9E5D5157,
        flags,
        address,
        len(payload),
        block_number,
        total_blocks,
        family,
    )
    block[32 : 32 + len(payload)] = payload
    if extension_word is not None:
        struct.pack_into("<I", block, 32 + len(payload), extension_word)
    struct.pack_into("<I", block, 508, 0x0AB16F30)
    return bytes(block)


def _realistic_rp2350_uf2(raw_image: bytes) -> bytes:
    chunks = [
        raw_image[offset : offset + 256].ljust(256, b"\0")
        for offset in range(0, len(raw_image), 256)
    ]
    extension = _uf2_block(
        flags=0x00002000 | 0x00008000,
        address=0x10FFFF00,
        payload=b"\xef" * 256,
        block_number=0,
        total_blocks=2,
        family=0xE48BFF57,
        extension_word=0x9957E304,
    )
    arm = b"".join(
        _uf2_block(
            flags=0x00002000,
            address=0x10000000 + index * 256,
            payload=chunk,
            block_number=index,
            total_blocks=len(chunks),
            family=0xE48BFF59,
        )
        for index, chunk in enumerate(chunks)
    )
    return extension + arm


class RP2BuildFixture:
    """A tiny real-Git source graph with fake build tools."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-rp2-retained-source-"
        )
        self.base = Path(self._temporary.name)
        self.repo = self.base / "repo"
        self.firmware = self.repo / "firmware"
        self.canonical = self.firmware / "upstream" / "micropython"
        self.build_root = self.base / "release-build"
        self.retained = (
            self.build_root / ".sources" / TARGET / "micropython"
        )
        self.output = self.build_root / TARGET
        self.fake_bin = self.base / "bin"
        self.fake_artifacts = self.base / "fake-artifacts"
        self.make_log = self.base / "make.jsonl"
        self.prepare_log = self.base / "prepare.log"
        self.toolchain = self.base / "arm-gnu"
        self.picotool = self.base / "pinned-picotool"
        self.picotool_executable = self.picotool / "picotool" / "picotool"
        self.ambient_picotool_marker = self.base / "ambient-picotool-ran"

        self._make_canonical_checkout()
        self._make_pinned_picotool()
        self._make_pyble_checkout()
        self._make_fake_tools()
        self._make_fake_artifacts()

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def _configure_git(self, path: Path) -> None:
        _git(path, "config", "user.name", "PyBLE Test")
        _git(path, "config", "user.email", "test@pyble.invalid")

    def _make_canonical_checkout(self) -> None:
        nested_source = self.base / "nested-source"
        nested_source.mkdir(parents=True)
        _git(nested_source, "init", "-q")
        self._configure_git(nested_source)
        (nested_source / "README.md").write_text(
            "retained nested source\n", encoding="utf-8"
        )
        self.nested_commit = _commit_all(nested_source, "nested source")

        (self.canonical / "ports" / "rp2").mkdir(parents=True)
        (self.canonical / "mpy-cross").mkdir(parents=True)
        _git(self.canonical, "init", "-q")
        self._configure_git(self.canonical)
        (self.canonical / "ports" / "rp2" / "source.c").write_text(
            "/* rp2 fixture */\n", encoding="utf-8"
        )
        (self.canonical / "ports" / "rp2" / "Makefile").write_text(
            "all:\n\t@:\n", encoding="utf-8"
        )
        (self.canonical / "mpy-cross" / "Makefile").write_text(
            "all:\n\t@:\n", encoding="utf-8"
        )
        _commit_all(self.canonical, "MicroPython fixture")

        self.nested_origins: dict[str, str] = {}
        for submodule_path in NESTED_SUBMODULES:
            origin = "https://example.invalid/{}.git".format(
                submodule_path.removeprefix("lib/")
            )
            self.nested_origins[submodule_path] = origin
            _git(
                self.canonical,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "-q",
                str(nested_source),
                submodule_path,
            )
            name = submodule_path
            _git(
                self.canonical,
                "config",
                "-f",
                ".gitmodules",
                "submodule.{}.url".format(name),
                origin,
            )
            _git(
                self.canonical / submodule_path,
                "remote",
                "set-url",
                "origin",
                origin,
            )

        self.micropython_commit = _commit_all(
            self.canonical, "pinned nested sources"
        )
        _git(self.canonical, "remote", "add", "origin", MICROPYTHON_ORIGIN)

    def _make_pyble_checkout(self) -> None:
        scripts = self.firmware / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(BUILD_RP2, scripts / "build_rp2.sh")
        (scripts / "build_rp2.sh").chmod(0o755)

        _write_executable(
            scripts / "prepare.sh",
            r"""
            #!/usr/bin/env bash
            set -eu
            printf '%s\n' "${PYBLE_UPSTREAM_DIR:?}" >> "$PYBLE_PREPARE_LOG"
            [ "${PYBLE_TEST_FAIL_PHASE:-}" != "prepare" ] || exit 89
            board="$PYBLE_UPSTREAM_DIR/ports/rp2/boards/PYBLE_RPI_PICO2_W"
            mkdir -p "$board/pyble"
            printf 'set(PICO_BOARD pico2_w)\n' > "$board/mpconfigboard.cmake"
            printf '# fixture\n' > "$board/manifest.py"
            """,
        )
        _write_executable(
            self.repo / "tools" / "ci" / "sha_drift.sh",
            r"""
            #!/usr/bin/env bash
            set -eu
            here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
            repo="$(cd "$here/../.." && pwd -P)"
            upstream="${PYBLE_UPSTREAM_DIR:-$repo/firmware/upstream/micropython}"
            [ -e "$upstream/.git" ]
            """,
        )
        (self.firmware / "board_overlays" / TARGET).mkdir(parents=True)
        (self.firmware / "board_overlays" / TARGET / "manifest.py").write_text(
            "# fixture\n", encoding="utf-8"
        )
        (self.firmware / "pyble").mkdir()
        (self.firmware / "pyble" / "pyble_agent.py").write_text(
            "# fixture\n", encoding="utf-8"
        )
        (self.firmware / "versions.lock").write_text(
            textwrap.dedent(
                """
                [micropython]
                repo = "{origin}"
                ref = "v1.28.0"
                commit = "{commit}"

                [pyble]
                agent_version = "0.6.1"
                protocol_version = "PBLE/1"

                [targets_rp2]
                "rpi-pico2-w" = "RPI_PICO2_W"

                [arm_gnu_toolchain]
                release = "14.2.Rel1"
                gcc_version = "14.2.1 20241119"

                [picotool]
                version = "2.3.0"
                version_line = "{picotool_version_line}"
                source_repo = "https://github.com/raspberrypi/picotool.git"
                source_ref = "2.3.0"
                source_commit = "6f6458d792b93685a11423b244a585eaa99eafcf"
                distribution_repo = "https://github.com/raspberrypi/pico-sdk-tools.git"
                distribution_ref = "v2.3.0-0"
                distribution_commit = "ad9e4a8375253cf4886bf168ea1a8d2746aadf24"
                url = "https://example.invalid/picotool-2.3.0-test-mac.zip"
                archive_filename = "picotool-2.3.0-test-mac.zip"
                archive_bytes = {picotool_archive_bytes}
                archive_format = "zip"
                sha256 = "{picotool_archive_sha256}"
                cmake_dir = "picotool"
                executable_path = "picotool/picotool"
                executable_sha256 = "{picotool_executable_sha256}"
                cmake_config_path = "picotool/picotoolConfig.cmake"
                cmake_config_sha256 = "{picotool_config_sha256}"
                bundled_libusb_path = "picotool/libusb-1.0.0.dylib"
                bundled_libusb_sha256 = "{picotool_libusb_sha256}"
                """
            ).format(
                origin=MICROPYTHON_ORIGIN,
                commit=self.micropython_commit,
                picotool_version_line=PICOTOOL_VERSION_LINE,
                picotool_archive_bytes=len(PICOTOOL_ARCHIVE),
                picotool_archive_sha256=_sha256(PICOTOOL_ARCHIVE),
                picotool_executable_sha256=_sha256(PICOTOOL_EXECUTABLE),
                picotool_config_sha256=_sha256(PICOTOOL_CONFIG),
                picotool_libusb_sha256=_sha256(PICOTOOL_LIBUSB),
            ).lstrip(),
            encoding="utf-8",
        )
        (self.repo / ".gitignore").write_text(
            "firmware/upstream/micropython/\n", encoding="utf-8"
        )
        (self.repo / "README.md").write_text("PyBLE fixture\n", encoding="utf-8")
        _git(self.repo, "init", "-q")
        self._configure_git(self.repo)
        self.pyble_commit = _commit_all(self.repo, "PyBLE fixture")

    def _make_pinned_picotool(self) -> None:
        _write_executable(
            self.picotool_executable,
            PICOTOOL_EXECUTABLE.decode("utf-8"),
        )
        (self.picotool / "picotool" / "picotoolConfig.cmake").write_bytes(
            PICOTOOL_CONFIG
        )
        (
            self.picotool / "picotool" / "picotoolConfigVersion.cmake"
        ).write_bytes(PICOTOOL_CONFIG_VERSION)
        (self.picotool / "picotool" / "picotoolTargets.cmake").write_bytes(
            PICOTOOL_TARGETS
        )
        (
            self.picotool / "picotool" / "picotoolTargets-release.cmake"
        ).write_bytes(PICOTOOL_TARGETS_RELEASE)
        (self.picotool / "picotool" / "libusb-1.0.0.dylib").write_bytes(
            PICOTOOL_LIBUSB
        )
        (self.picotool / "picotool" / "libusb-1.0.0.dylib").chmod(0o444)
        (self.picotool / ".keep").write_bytes(b"")
        retained = self.picotool / ".pyble-dist"
        retained.mkdir()
        (retained / "picotool-2.3.0-test-mac.zip").write_bytes(
            PICOTOOL_ARCHIVE
        )

    def _make_fake_tools(self) -> None:
        _write_executable(
            self.toolchain / "bin" / "arm-none-eabi-gcc",
            """
            #!/usr/bin/env bash
            echo 'arm-none-eabi-gcc (Arm GNU Toolchain 14.2.Rel1) 14.2.1 20241119'
            """,
        )
        _write_executable(
            self.toolchain / "bin" / "arm-none-eabi-g++",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        _write_executable(
            self.toolchain / "bin" / "arm-none-eabi-size",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        _write_executable(
            self.fake_bin / "picotool",
            r"""
            #!/usr/bin/env bash
            [ "${1:-}" = version ]
            : > "${PYBLE_AMBIENT_PICOTOOL_MARKER:?}"
            echo 'picotool v9.9.9 (ambient PATH fixture)'
            """,
        )
        _write_executable(
            self.fake_bin / "mv",
            r"""
            #!/usr/bin/env bash
            set -eu
            destination=""
            for argument in "$@"; do
              destination="$argument"
            done
            if [ "${PYBLE_TEST_MUTATION:-}" = "provenance-mv-fail" ]; then
              case "$destination" in
                */pyble-build-provenance.json) exit 97 ;;
              esac
            fi
            exec "$PYBLE_REAL_MV" "$@"
            """,
        )
        _write_executable(
            self.fake_bin / "make",
            r"""
            #!/usr/bin/env bash
            set -eu
            python3 - "$@" <<'PY'
            import json
            import os
            import sys
            keys = (
                "BUILD", "MICROPY_MPYCROSS", "CFLAGS_EXTRA", "CFLAGS",
                "CXXFLAGS", "ASMFLAGS", "CPPFLAGS", "EXTRA_CPPFLAGS",
                "EXTRA_CFLAGS", "EXTRA_CXXFLAGS", "MAKEFLAGS", "MFLAGS",
                "GNUMAKEFLAGS", "MAKEOVERRIDES", "PYTHONDONTWRITEBYTECODE",
                "CMAKE_ARGS", "picotool_DIR",
                "FETCHCONTENT_FULLY_DISCONNECTED",
                "FETCHCONTENT_SOURCE_DIR_PICOTOOL",
                "PICOTOOL_FETCH_FROM_GIT_PATH",
                "PICOTOOL_FORCE_FETCH_FROM_GIT",
                "CMAKE_FIND_USE_PACKAGE_REGISTRY",
                "CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY",
                "CMAKE_PREFIX_PATH",
            )
            record = {
                "cwd": os.getcwd(),
                "args": sys.argv[1:],
                "env": {key: os.environ.get(key, "") for key in keys},
            }
            with open(os.environ["PYBLE_MAKE_LOG"], "a", encoding="utf-8") as out:
                out.write(json.dumps(record, sort_keys=True) + "\n")
            PY

            command_directory=""
            output=""
            previous=""
            is_submodules=0
            for argument in "$@"; do
              if [ "$previous" = "-C" ]; then
                command_directory="$argument"
              fi
              case "$argument" in
                BUILD=*) output="${argument#BUILD=}" ;;
                submodules) is_submodules=1 ;;
              esac
              previous="$argument"
            done

            if [ "$(basename "$command_directory")" = "mpy-cross" ]; then
              [ "${PYBLE_TEST_FAIL_PHASE:-}" != "mpy-cross" ] || exit 90
              [ -n "$output" ] || output=build
              case "$output" in
                /*) compiler="$output/mpy-cross" ;;
                *) compiler="$command_directory/$output/mpy-cross" ;;
              esac
              mkdir -p "$(dirname "$compiler")"
              printf '#!/bin/sh\nexit 0\n' > "$compiler"
              chmod 755 "$compiler"
              if [ -n "${PYBLE_TEST_SIGNAL:-}" ]; then
                kill "-$PYBLE_TEST_SIGNAL" "$PPID"
              fi
              exit 0
            fi

            [ "$is_submodules" -eq 0 ] || exit 0
            [ "${PYBLE_TEST_FAIL_PHASE:-}" != "final" ] || exit 91
            [ -n "$output" ] || exit 92
            mkdir -p "$output/CMakeFiles/firmware.dir"
            cp "$PYBLE_FAKE_ARTIFACTS/firmware.uf2" "$output/firmware.uf2"
            cp "$PYBLE_FAKE_ARTIFACTS/firmware.bin" "$output/firmware.bin"
            cp "$PYBLE_FAKE_ARTIFACTS/firmware.elf" "$output/firmware.elf"
            if [ "${PYBLE_TEST_MUTATION:-}" = "host-path-elf" ]; then
              printf '%s' "$PYBLE_TEST_FORBIDDEN_PATH" >> "$output/firmware.elf"
            fi
            printf 'synthetic GNU linker map\n' > "$output/firmware.elf.map"
            if [ "${PYBLE_TEST_MUTATION:-}" = "symlink-link" ]; then
              ln -s "$output/firmware.elf.map" \
                "$output/CMakeFiles/firmware.dir/link.txt"
            else
              printf '%s/firmware-object.o\n' "$output" > \
                "$output/CMakeFiles/firmware.dir/link.txt"
            fi
            printf 'set(CMAKE_DEPENDS_LANGUAGES C)\n' > \
              "$output/CMakeFiles/firmware.dir/DependInfo.cmake"

            port="$command_directory"
            upstream="$(cd "$port/../.." && pwd -P)"
            {
              printf 'CMAKE_HOME_DIRECTORY:INTERNAL=%s\n' "$port"
              printf 'MICROPY_BOARD_DIR:UNINITIALIZED=%s/boards/%s\n' \
                "$port" "PYBLE_RPI_PICO2_W"
              printf 'PICO_SDK_PATH:PATH=%s/lib/pico-sdk\n' "$upstream"
              printf 'CMAKE_C_COMPILER:FILEPATH=%s/bin/arm-none-eabi-gcc\n' \
                "$PYBLE_ARM_TOOLCHAIN_DIR"
              printf 'CMAKE_CXX_COMPILER:FILEPATH=%s/bin/arm-none-eabi-g++\n' \
                "$PYBLE_ARM_TOOLCHAIN_DIR"
              printf 'CMAKE_ASM_COMPILER:FILEPATH=%s/bin/arm-none-eabi-gcc\n' \
                "$PYBLE_ARM_TOOLCHAIN_DIR"
              printf 'picotool_DIR:UNINITIALIZED=%s/picotool\n' \
                "$PYBLE_PICOTOOL_DIR"
              printf 'FETCHCONTENT_FULLY_DISCONNECTED:UNINITIALIZED=ON\n'
              printf 'PICOTOOL_FORCE_FETCH_FROM_GIT:UNINITIALIZED=OFF\n'
              printf 'CMAKE_FIND_USE_PACKAGE_REGISTRY:UNINITIALIZED=OFF\n'
              printf 'CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY:UNINITIALIZED=OFF\n'
            } > "$output/CMakeCache.txt"

            if [ "${PYBLE_TEST_MUTATION:-}" = "provenance-temp-write-fail" ]; then
              mkdir "$output/.pyble-build-provenance.json.$PPID"
            fi

            """,
        )

    def _make_fake_artifacts(self) -> None:
        self.fake_artifacts.mkdir()
        raw = bytes(range(251)) * 2
        (self.fake_artifacts / "firmware.bin").write_bytes(raw)
        (self.fake_artifacts / "firmware.uf2").write_bytes(
            _realistic_rp2350_uf2(raw)
        )
        (self.fake_artifacts / "firmware.elf").write_bytes(
            b"\x7fELF\0synthetic RP2350 image"
        )

    def execute(
        self,
        *,
        fail_phase: str = "",
        mutation: str = "",
        signal_name: str = "",
    ) -> subprocess.CompletedProcess[str]:
        hostile = str(self.base / "HOSTILE")
        env = {
            **os.environ,
            "PATH": "{}:{}".format(self.fake_bin, os.environ.get("PATH", "")),
            "PYBLE_BUILD_ROOT": str(self.build_root),
            "PYBLE_ARM_TOOLCHAIN_DIR": str(self.toolchain),
            "PYBLE_PICOTOOL_DIR": str(self.picotool),
            "PYBLE_AMBIENT_PICOTOOL_MARKER": str(
                self.ambient_picotool_marker
            ),
            "PYBLE_LOCK_FILE": str(self.firmware / "versions.lock"),
            "PYBLE_FAKE_ARTIFACTS": str(self.fake_artifacts),
            "PYBLE_MAKE_LOG": str(self.make_log),
            "PYBLE_PREPARE_LOG": str(self.prepare_log),
            "PYBLE_TEST_FAIL_PHASE": fail_phase,
            "PYBLE_TEST_MUTATION": mutation,
            "PYBLE_TEST_SIGNAL": signal_name,
            "PYBLE_TEST_FORBIDDEN_PATH": str(self.repo.resolve()),
            "PYBLE_REAL_MV": shutil.which("mv") or "/bin/mv",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "BUILD": hostile + "/build",
            "MICROPY_MPYCROSS": hostile + "/mpy-cross",
            "CFLAGS_EXTRA": "-DHOSTILE_CFLAGS_EXTRA=1",
            "CFLAGS": "-DHOSTILE_CFLAGS=1",
            "CXXFLAGS": "-DHOSTILE_CXXFLAGS=1",
            "ASMFLAGS": "-DHOSTILE_ASMFLAGS=1",
            "CPPFLAGS": "-DHOSTILE_CPPFLAGS=1",
            "EXTRA_CPPFLAGS": "-DHOSTILE_EXTRA_CPPFLAGS=1",
            "EXTRA_CFLAGS": "-DHOSTILE_EXTRA_CFLAGS=1",
            "EXTRA_CXXFLAGS": "-DHOSTILE_EXTRA_CXXFLAGS=1",
            "MAKEFLAGS": "CFLAGS_EXTRA=-DHOSTILE_MAKEFLAGS=1",
            "MFLAGS": "-DHOSTILE_MFLAGS=1",
            "GNUMAKEFLAGS": "CFLAGS=-DHOSTILE_GNUMAKEFLAGS=1",
            "MAKEOVERRIDES": "CFLAGS CFLAGS_EXTRA",
            "picotool_DIR": hostile + "/ambient-picotool-package",
            "FETCHCONTENT_FULLY_DISCONNECTED": "OFF",
            "FETCHCONTENT_SOURCE_DIR_PICOTOOL": hostile + "/fetched-picotool",
            "PICOTOOL_FETCH_FROM_GIT_PATH": hostile + "/git-picotool",
            "PICOTOOL_FORCE_FETCH_FROM_GIT": "ON",
            "CMAKE_FIND_USE_PACKAGE_REGISTRY": "ON",
            "CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY": "ON",
            "CMAKE_PREFIX_PATH": hostile + "/homebrew-prefix",
        }
        return _run(
            [str(self.firmware / "scripts" / "build_rp2.sh"), TARGET],
            cwd=self.repo,
            env=env,
        )

    def make_records(self) -> list[dict[str, object]]:
        if not self.make_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.make_log.read_text(encoding="utf-8").splitlines()
        ]

    def canonical_snapshot(self) -> dict[str, object]:
        nested = {}
        for submodule_path in NESTED_SUBMODULES:
            checkout = self.canonical / submodule_path
            nested[submodule_path] = {
                "head": _git(checkout, "rev-parse", "HEAD"),
                "origins": _git(
                    checkout, "remote", "get-url", "--all", "origin"
                ).splitlines(),
                "status": _git(
                    checkout, "status", "--porcelain", "--untracked-files=all"
                ),
            }
        return {
            "head": _git(self.canonical, "rev-parse", "HEAD"),
            "origins": _git(
                self.canonical, "remote", "get-url", "--all", "origin"
            ).splitlines(),
            "status": _git(
                self.canonical,
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ),
            "nested": nested,
        }

    def assert_retained_identity(self, testcase: unittest.TestCase) -> None:
        testcase.assertTrue(self.retained.is_dir())
        testcase.assertFalse(self.retained.is_symlink())
        testcase.assertEqual(
            _git(self.retained, "rev-parse", "HEAD"), self.micropython_commit
        )
        testcase.assertEqual(
            _git(self.retained, "remote", "get-url", "origin"),
            MICROPYTHON_ORIGIN,
        )
        for submodule_path in NESTED_SUBMODULES:
            with testcase.subTest(submodule=submodule_path):
                checkout = self.retained / submodule_path
                testcase.assertTrue(checkout.is_dir())
                testcase.assertFalse(checkout.is_symlink())
                testcase.assertEqual(
                    _git(checkout, "rev-parse", "HEAD"), self.nested_commit
                )
                testcase.assertEqual(
                    _git(checkout, "remote", "get-url", "origin"),
                    self.nested_origins[submodule_path],
                )
                testcase.assertEqual(
                    _git(
                        checkout,
                        "status",
                        "--porcelain",
                        "--untracked-files=all",
                    ),
                    "",
                )


class RP2RetainedSourceBuildContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BUILD_RP2.read_text(encoding="utf-8", errors="strict")
        cls.logical_source = re.sub(r"\\\n[ \t]*", " ", cls.source)

    def test_build_declares_the_exact_target_scoped_retained_checkout(self) -> None:
        self.assertTrue(
            re.search(r"\.sources[^\n]*(?:TARGET|rpi-pico2-w)", self.source)
            is not None,
            "build_rp2.sh must declare build/.sources/<target>/micropython",
        )

    def test_provisioning_is_local_offline_and_covers_selected_gitlinks(self) -> None:
        self.assertTrue(
            re.search(r"git\s+clone\b", self.logical_source) is not None,
            "the retained checkout must be materialized by a local Git clone",
        )
        self.assertTrue(
            "--no-hardlinks" in self.source,
            "the local clone must not share mutable object files",
        )
        for submodule in NESTED_SUBMODULES:
            with self.subTest(submodule=submodule):
                self.assertTrue(
                    submodule in self.source,
                    "selected nested gitlink is not explicitly retained",
                )
        self.assertTrue(
            re.search(
                r"(?m)^[ \t]*make\b[^\n]*\bsubmodules\b",
                self.logical_source,
            )
            is None,
            "reviewed gitlinks must be local inputs, not Make fetches",
        )

    def test_source_names_every_required_retained_audit_input(self) -> None:
        for required in (
            "firmware.uf2",
            "firmware.bin",
            "firmware.elf",
            "firmware.elf.map",
            "CMakeCache.txt",
            "CMakeFiles/firmware.dir/link.txt",
            "CMakeFiles/firmware.dir/DependInfo.cmake",
        ):
            with self.subTest(required=required):
                self.assertTrue(
                    required in self.source,
                    "required retained audit input is not admitted: " + required,
                )


class RP2RetainedSourceBehaviorTests(unittest.TestCase):
    def test_success_is_offline_isolated_deterministic_and_canonical_immutable(self) -> None:
        fixture = RP2BuildFixture()
        try:
            before = fixture.canonical_snapshot()
            completed = fixture.execute()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            fixture.assert_retained_identity(self)
            self.assertEqual(
                fixture.prepare_log.read_text(encoding="utf-8").splitlines(),
                [str(fixture.retained.resolve())],
            )
            port_records = [
                record
                for record in fixture.make_records()
                if any(
                    str(argument).endswith("/ports/rp2")
                    for argument in record["args"]
                )
            ]
            self.assertTrue(port_records)
            self.assertFalse(
                any("submodules" in record["args"] for record in port_records)
            )
            for record in port_records:
                self.assertIn(str(fixture.retained.resolve()), " ".join(record["args"]))
            self.assertEqual(fixture.canonical_snapshot(), before)
            self.assertFalse(
                fixture.ambient_picotool_marker.exists(),
                "the RP2 build invoked the ambient PATH picotool",
            )
            records = fixture.make_records()
            mpy_records = [
                record
                for record in records
                if any(
                    str(argument).endswith("/mpy-cross")
                    for argument in record["args"]
                )
            ]
            final_records = [
                record
                for record in records
                if any(
                    str(argument).endswith("/ports/rp2")
                    for argument in record["args"]
                )
                and "submodules" not in record["args"]
            ]
            self.assertEqual(len(mpy_records), 1, records)
            self.assertEqual(len(final_records), 1, records)
            compiler = Path(final_records[0]["env"]["MICROPY_MPYCROSS"])
            self.assertTrue(
                compiler.is_relative_to(fixture.retained.resolve() / "mpy-cross"),
                "the port must use mpy-cross built in the retained checkout",
            )
            self.assertTrue(compiler.is_file() and not compiler.is_symlink())

            serialized = json.dumps(records, sort_keys=True)
            self.assertNotIn("HOSTILE", serialized)
            final = final_records[0]
            self.assertFalse(
                any(
                    str(argument).startswith("CMAKE_ARGS=")
                    for argument in final["args"]
                ),
                "a command-line CMAKE_ARGS assignment prevents the upstream "
                "RP2 Makefile from appending its board and manifest settings",
            )
            self.assertIn("CMAKE_ARGS", final["env"])
            build_configuration = " ".join(
                [*final["args"], *final["env"].values()]
            )
            self.assertIn(
                "-Dpicotool_DIR={}".format(
                    fixture.picotool.resolve() / "picotool"
                ),
                build_configuration,
            )
            self.assertIn(
                "-DFETCHCONTENT_FULLY_DISCONNECTED=ON",
                build_configuration,
            )
            self.assertIn(
                "-DPICOTOOL_FORCE_FETCH_FROM_GIT=OFF",
                build_configuration,
            )
            self.assertIn(
                "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
                build_configuration,
            )
            self.assertIn(
                "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
                build_configuration,
            )
            compile_configuration = " ".join(
                [*final["args"], *final["env"].values()]
            )
            self.assertIn(
                "-ffile-prefix-map={}=/PYBLE".format(fixture.repo.resolve()),
                compile_configuration,
            )
            self.assertIn(
                "-ffile-prefix-map={}=/MICROPYTHON".format(
                    fixture.retained.resolve()
                ),
                compile_configuration,
            )
            for language in ("CXX", "ASM"):
                language_configuration = " ".join(
                    [
                        str(final["env"].get(language + "FLAGS", "")),
                        *[
                            str(argument)
                            for argument in final["args"]
                            if language in str(argument)
                        ],
                    ]
                )
                with self.subTest(language=language):
                    self.assertIn("-ffile-prefix-map=", language_configuration)

            provenance = json.loads(
                (fixture.output / "pyble-build-provenance.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(provenance["picotool"], PICOTOOL_VERSION_LINE)
        finally:
            fixture.cleanup()

    def test_mismatched_pinned_picotool_fails_without_ambient_fallback(self) -> None:
        fixture = RP2BuildFixture()
        try:
            fixture.picotool_executable.write_bytes(
                fixture.picotool_executable.read_bytes() + b"# changed\n"
            )
            fixture.picotool_executable.chmod(0o755)

            completed = fixture.execute()

            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertFalse(fixture.ambient_picotool_marker.exists())
            self.assertEqual([], fixture.make_records())
            self.assertFalse(fixture.output.exists())
            self.assertFalse(fixture.retained.exists())
        finally:
            fixture.cleanup()

    def test_every_retained_picotool_identity_is_checked_before_make(self) -> None:
        def nonzero_version(fixture: RP2BuildFixture) -> None:
            changed = PICOTOOL_EXECUTABLE + b"exit 1\n"
            archive = _picotool_archive(changed)
            fixture.picotool_executable.write_bytes(changed)
            fixture.picotool_executable.chmod(0o755)
            (
                fixture.picotool
                / ".pyble-dist"
                / "picotool-2.3.0-test-mac.zip"
            ).write_bytes(archive)
            lock = fixture.firmware / "versions.lock"
            text = lock.read_text(encoding="utf-8")
            text = text.replace(
                "archive_bytes = %d" % len(PICOTOOL_ARCHIVE),
                "archive_bytes = %d" % len(archive),
            )
            text = text.replace(
                _sha256(PICOTOOL_ARCHIVE),
                _sha256(archive),
            )
            text = text.replace(
                _sha256(PICOTOOL_EXECUTABLE),
                _sha256(changed),
            )
            lock.write_text(text, encoding="utf-8")
            _commit_all(fixture.repo, "nonzero picotool version fixture")

        def wrong_version(fixture: RP2BuildFixture) -> None:
            changed = PICOTOOL_EXECUTABLE.replace(b"v2.3.0", b"v2.3.1")
            fixture.picotool_executable.write_bytes(changed)
            fixture.picotool_executable.chmod(0o755)
            lock = fixture.firmware / "versions.lock"
            lock.write_text(
                lock.read_text(encoding="utf-8").replace(
                    _sha256(PICOTOOL_EXECUTABLE),
                    _sha256(changed),
                ),
                encoding="utf-8",
            )
            _commit_all(fixture.repo, "wrong runtime version fixture")

        cases = {
            "cmake-config": lambda fixture: (
                fixture.picotool / "picotool" / "picotoolConfig.cmake"
            ).write_bytes(b"changed package config\n"),
            "cmake-config-mode": lambda fixture: (
                fixture.picotool / "picotool" / "picotoolConfig.cmake"
            ).chmod(0o666),
            "bundled-libusb": lambda fixture: (
                (
                    fixture.picotool
                    / "picotool"
                    / "libusb-1.0.0.dylib"
                ).chmod(0o644),
                (
                    fixture.picotool
                    / "picotool"
                    / "libusb-1.0.0.dylib"
                ).write_bytes(b"changed bundled libusb\n"),
            ),
            "retained-archive": lambda fixture: (
                fixture.picotool
                / ".pyble-dist"
                / "picotool-2.3.0-test-mac.zip"
            ).write_bytes(b"changed retained archive\n"),
            "missing-package-target": lambda fixture: (
                fixture.picotool / "picotool" / "picotoolTargets.cmake"
            ).unlink(),
            "runtime-version-line": wrong_version,
            "runtime-version-nonzero": nonzero_version,
        }
        for label, mutate in cases.items():
            with self.subTest(identity=label):
                fixture = RP2BuildFixture()
                try:
                    mutate(fixture)
                    completed = fixture.execute()
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertFalse(fixture.ambient_picotool_marker.exists())
                    self.assertEqual([], fixture.make_records())
                    self.assertFalse(fixture.output.exists())
                    self.assertFalse(fixture.retained.exists())
                finally:
                    fixture.cleanup()

    def test_failed_build_atomically_removes_new_source_and_output(self) -> None:
        fixture = RP2BuildFixture()
        try:
            before = fixture.canonical_snapshot()
            completed = fixture.execute(fail_phase="final")
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertFalse(fixture.retained.exists())
            self.assertFalse(fixture.output.exists())
            source_owner = fixture.build_root / ".sources" / TARGET
            if source_owner.exists():
                self.assertEqual(list(source_owner.iterdir()), [])
            self.assertEqual(fixture.canonical_snapshot(), before)
        finally:
            fixture.cleanup()

    def test_unsafe_audit_inputs_are_rejected_before_provenance(self) -> None:
        for mutation in ("symlink-link", "host-path-elf"):
            with self.subTest(mutation=mutation):
                fixture = RP2BuildFixture()
                try:
                    completed = fixture.execute(mutation=mutation)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertFalse(
                        (fixture.output / "pyble-build-provenance.json").exists()
                    )
                finally:
                    fixture.cleanup()

    def test_provenance_admission_failures_remove_all_new_build_state(self) -> None:
        for mutation in ("provenance-temp-write-fail", "provenance-mv-fail"):
            with self.subTest(mutation=mutation):
                fixture = RP2BuildFixture()
                try:
                    completed = fixture.execute(mutation=mutation)
                    self.assertEqual(len(fixture.make_records()), 2)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertFalse(fixture.output.exists())
                    self.assertFalse(fixture.retained.exists())
                    self.assertFalse(
                        (
                            fixture.output
                            / "pyble-build-provenance.json"
                        ).exists()
                    )
                finally:
                    fixture.cleanup()

    def test_symlinked_source_ancestors_are_rejected_without_escape(self) -> None:
        for ancestor in (".sources", ".sources/rpi-pico2-w"):
            with self.subTest(ancestor=ancestor):
                fixture = RP2BuildFixture()
                try:
                    escaped = fixture.base / "escaped-source-root"
                    escaped.mkdir()
                    sentinel = escaped / "sentinel"
                    sentinel.write_bytes(b"outside build root\n")
                    link = fixture.build_root / ancestor
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(escaped, target_is_directory=True)

                    completed = fixture.execute()

                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertEqual(
                        sorted(path.name for path in escaped.iterdir()),
                        ["sentinel"],
                    )
                    self.assertEqual(sentinel.read_bytes(), b"outside build root\n")
                    self.assertFalse(fixture.make_log.exists())
                finally:
                    fixture.cleanup()

    def test_signals_after_successful_step_fail_and_clean_build_state(self) -> None:
        for signal_name in ("INT", "TERM"):
            with self.subTest(signal=signal_name):
                fixture = RP2BuildFixture()
                try:
                    completed = fixture.execute(signal_name=signal_name)
                    self.assertEqual(len(fixture.make_records()), 1)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertFalse(fixture.output.exists())
                    self.assertFalse(fixture.retained.exists())
                finally:
                    fixture.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
