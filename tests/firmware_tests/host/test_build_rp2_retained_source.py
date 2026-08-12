#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for an isolated, release-auditable RP2 build."""

from __future__ import annotations

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

        self._make_canonical_checkout()
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
                agent_version = "0.6.0"
                protocol_version = "PBLE/1"

                [targets_rp2]
                "rpi-pico2-w" = "RPI_PICO2_W"

                [arm_gnu_toolchain]
                release = "14.2.Rel1"
                gcc_version = "14.2.1 20241119"
                """
            ).format(
                origin=MICROPYTHON_ORIGIN,
                commit=self.micropython_commit,
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
            """
            #!/usr/bin/env bash
            [ "${1:-}" = version ]
            echo 'picotool v2.3.0 (PyBLE fixture)'
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
            } > "$output/CMakeCache.txt"

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
    ) -> subprocess.CompletedProcess[str]:
        hostile = str(self.base / "HOSTILE")
        env = {
            **os.environ,
            "PATH": "{}:{}".format(self.fake_bin, os.environ.get("PATH", "")),
            "PYBLE_BUILD_ROOT": str(self.build_root),
            "PYBLE_ARM_TOOLCHAIN_DIR": str(self.toolchain),
            "PYBLE_LOCK_FILE": str(self.firmware / "versions.lock"),
            "PYBLE_FAKE_ARTIFACTS": str(self.fake_artifacts),
            "PYBLE_MAKE_LOG": str(self.make_log),
            "PYBLE_PREPARE_LOG": str(self.prepare_log),
            "PYBLE_TEST_FAIL_PHASE": fail_phase,
            "PYBLE_TEST_MUTATION": mutation,
            "PYBLE_TEST_FORBIDDEN_PATH": str(self.repo.resolve()),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
