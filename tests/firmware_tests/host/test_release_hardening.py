#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-03/X-11 — Adversarial build and release hardening contract.
#
# Frozen sources:
#   docs/specifications/firmware/specs.md BLD-1…8, BLD-14, BLD-17…22
#   docs/specifications/firmware/browser-flashing.md §§1–6, 9
#
# Every fixture is created below a TemporaryDirectory. The tests neither use
# nor mutate local firmware outputs, upstream checkouts, tags, or hardware.

from __future__ import annotations

import copy
import csv
import hashlib
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

import test_release_bundle as bundle_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_ALL_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "build_all.sh"
BUILD_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "build.sh"
PREPARE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "prepare.sh"
OVERLAYS = REPO_ROOT / "firmware" / "board_overlays"
RELEASE = bundle_fixture.RELEASE
HAVE_RELEASE = RELEASE is not None
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
TARGETS = ("esp32", "esp32-s3", "esp32-c3")
MICROPYTHON_ORIGIN = "https://github.com/micropython/micropython"
BUILD_PROVENANCE_KEYS = {
    "schema_version",
    "target",
    "source_date_epoch",
    "pyble",
    "micropython",
    "esp_idf",
}


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            "git -C {} {} failed:\n{}\n{}".format(
                repo,
                " ".join(args),
                completed.stdout,
                completed.stderr,
            )
        )
    return completed.stdout.strip()


def _validate_build_with_repo(target: str, build_dir: Path, repo_root: Path):
    try:
        return RELEASE.validate_build(target, build_dir, repo_root=repo_root)
    except TypeError as exc:
        raise AssertionError(
            "validate_build must accept repo_root so build identity can be "
            "bound to actual checkouts"
        ) from exc


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _init_git_repo(path: Path, filename: str = "tracked.txt") -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "PyBLE Test")
    _git(path, "config", "user.email", "test@pyble.invalid")
    (path / filename).parent.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text("fixture\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(
        path,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return _git(path, "rev-parse", "HEAD")


class BuildAllFixture:
    """A tiny Git checkout with the production all-target driver."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-build-all-hardening-"
        )
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build_root = self.root / "fresh-build"
        self.log = self.root / "invocations.log"
        self.source_log = self.root / "source-invocations.log"
        scripts = self.repo / "firmware" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(BUILD_ALL_SCRIPT, scripts / "build_all.sh")
        (scripts / "build_all.sh").chmod(
            (scripts / "build_all.sh").stat().st_mode | stat.S_IXUSR
        )
        _write_executable(
            scripts / "build.sh",
            r"""
            #!/usr/bin/env bash
            set -eu
            if [ "${1:-}" = "--plan" ]; then
              shift
            fi
            target="${1:?missing target}"
            printf '%s|%s|%s\n' \
              "$target" \
              "${PYBLE_UPSTREAM_DIR:-}" \
              "${PYBLE_BUILD_ROOT:-}" >> "$PYBLE_TEST_SOURCE_LOG"
            printf '%s|%s|%s\n' \
              "${PYBLE_SOURCE_COMMIT:-}" \
              "${SOURCE_DATE_EPOCH:-}" \
              "$target" >> "$PYBLE_TEST_LOG"
            if [ -n "${PYBLE_UPSTREAM_DIR:-}" ] &&
               [ -d "$PYBLE_UPSTREAM_DIR/.git" ]; then
              mkdir -p "$PYBLE_UPSTREAM_DIR/ports/esp32/managed_components"
              printf '%s\n' "$target" > \
                "$PYBLE_UPSTREAM_DIR/ports/esp32/managed_components/active-owner.txt"
            fi
            if [ "$target" = "esp32" ] && [ "${PYBLE_TEST_MUTATION:-}" = "dirty" ]; then
              printf 'changed during build\n' >> "$PYBLE_TEST_REPO/firmware/source.txt"
            fi
            if [ "$target" = "esp32" ] && [ "${PYBLE_TEST_MUTATION:-}" = "head" ]; then
              printf 'new committed source\n' >> "$PYBLE_TEST_REPO/firmware/source.txt"
              git -C "$PYBLE_TEST_REPO" add firmware/source.txt
              git -C "$PYBLE_TEST_REPO" \
                -c user.name='PyBLE Test' \
                -c user.email='test@pyble.invalid' \
                -c commit.gpgsign=false \
                commit -q -m 'mutate during build'
            fi
            if [ "$target" = "esp32-c3" ] && [ "${PYBLE_TEST_MUTATION:-}" = "final-dirty" ]; then
              printf 'changed during final build\n' >> "$PYBLE_TEST_REPO/firmware/source.txt"
            fi
            """,
        )
        self.canonical_upstream = (
            self.repo / "firmware" / "upstream" / "micropython"
        )
        canonical_owner = (
            self.canonical_upstream
            / "ports"
            / "esp32"
            / "managed_components"
            / "canonical-owner.txt"
        )
        canonical_owner.parent.mkdir(parents=True)
        canonical_owner.write_text("canonical\n", encoding="utf-8")
        self.micropython_commit = _init_git_repo(
            self.canonical_upstream,
            "ports/esp32/source.c",
        )
        _git(
            self.canonical_upstream,
            "remote",
            "add",
            "origin",
            MICROPYTHON_ORIGIN,
        )
        (self.repo / "firmware" / "versions.lock").write_text(
            textwrap.dedent(
                """
                [micropython]
                repo = "{origin}"
                ref = "v1.28.0"
                commit = "{commit}"
                """
            )
            .format(
                origin=MICROPYTHON_ORIGIN,
                commit=self.micropython_commit,
            )
            .lstrip(),
            encoding="utf-8",
        )
        (self.repo / "firmware" / "source.txt").write_text(
            "clean source\n", encoding="utf-8"
        )
        (self.repo / ".gitignore").write_text(
            "firmware/build/\n"
            "firmware/upstream/micropython/\n",
            encoding="utf-8",
        )
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "PyBLE Test")
        _git(self.repo, "config", "user.email", "test@pyble.invalid")
        _git(self.repo, "add", ".")
        _git(
            self.repo,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "source",
        )
        self.commit = _git(self.repo, "rev-parse", "HEAD")
        self.epoch = int(_git(self.repo, "show", "-s", "--format=%ct", "HEAD"))

    def cleanup(self):
        self._temporary.cleanup()

    def execute(self, mutation: str = "") -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PYBLE_TEST_LOG": str(self.log),
            "PYBLE_TEST_SOURCE_LOG": str(self.source_log),
            "PYBLE_TEST_REPO": str(self.repo),
            "PYBLE_TEST_MUTATION": mutation,
            "PYBLE_BUILD_ROOT": str(self.build_root),
            # A caller must not be able to split the three builds by injection.
            "PYBLE_SOURCE_COMMIT": "0" * 40,
            "SOURCE_DATE_EPOCH": "1",
        }
        return _run(
            [str(self.repo / "firmware" / "scripts" / "build_all.sh")],
            cwd=self.repo,
            env=env,
        )

    def invocations(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def source_invocations(self) -> list[str]:
        if not self.source_log.exists():
            return []
        return self.source_log.read_text(encoding="utf-8").splitlines()


class BuildAllSourceFreezeTests(unittest.TestCase):
    def test_each_target_gets_an_exact_retained_isolated_source_checkout(self):
        fixture = BuildAllFixture()
        try:
            self.assertFalse(
                fixture.build_root.exists(),
                "the fixture must exercise an explicitly selected fresh build root",
            )
            completed = fixture.execute()
            self.assertEqual(completed.returncode, 0, completed.stdout)

            sources = fixture.build_root / ".sources"
            self.assertTrue(
                sources.is_dir(),
                "build_all must provision the retained .sources tree",
            )
            self.assertEqual(
                {path.name for path in sources.iterdir()},
                set(TARGETS),
                "the source root must contain exactly one owner per target",
            )
            self.assertEqual(
                fixture.source_invocations(),
                [
                    "{}|{}|{}".format(
                        target,
                        fixture.build_root.resolve()
                        / ".sources"
                        / target
                        / "micropython",
                        fixture.build_root.resolve(),
                    )
                    for target in TARGETS
                ],
                "build_all must pass each exact retained checkout and the one "
                "explicit build root to build.sh",
            )

            for target in TARGETS:
                with self.subTest(target=target):
                    target_root = sources / target
                    self.assertEqual(
                        {path.name for path in target_root.iterdir()},
                        {"micropython"},
                    )
                    checkout = target_root / "micropython"
                    self.assertEqual(
                        _git(checkout, "rev-parse", "HEAD"),
                        fixture.micropython_commit,
                    )
                    self.assertEqual(
                        _git(checkout, "remote", "get-url", "origin"),
                        MICROPYTHON_ORIGIN,
                    )
                    managed = (
                        checkout / "ports" / "esp32" / "managed_components"
                    )
                    self.assertEqual(
                        (managed / "canonical-owner.txt").read_text(
                            encoding="utf-8"
                        ),
                        "canonical\n",
                    )
                    self.assertEqual(
                        (managed / "active-owner.txt").read_text(encoding="utf-8"),
                        target + "\n",
                        "one target's managed-component materialization must "
                        "remain owned by that target",
                    )

            canonical_managed = (
                fixture.canonical_upstream
                / "ports"
                / "esp32"
                / "managed_components"
            )
            self.assertEqual(
                {
                    path.name: path.read_text(encoding="utf-8")
                    for path in canonical_managed.iterdir()
                },
                {"canonical-owner.txt": "canonical\n"},
                "target builds must not mutate the canonical proof checkout",
            )
        finally:
            fixture.cleanup()

    def test_one_head_and_epoch_are_frozen_for_all_three_targets(self):
        fixture = BuildAllFixture()
        try:
            completed = fixture.execute()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                fixture.invocations(),
                [
                    "{}|{}|{}".format(fixture.commit, fixture.epoch, target)
                    for target in TARGETS
                ],
            )
        finally:
            fixture.cleanup()

    def test_relevant_dirty_source_is_rejected_before_the_first_target(self):
        fixture = BuildAllFixture()
        try:
            (fixture.repo / "firmware" / "source.txt").write_text(
                "dirty before build\n", encoding="utf-8"
            )
            completed = fixture.execute()
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                fixture.invocations(),
                [],
                "dirty source must be rejected before build.sh is invoked",
            )
        finally:
            fixture.cleanup()

    def test_source_or_head_change_during_a_target_stops_the_matrix(self):
        for mutation in ("dirty", "head"):
            with self.subTest(mutation=mutation):
                fixture = BuildAllFixture()
                try:
                    completed = fixture.execute(mutation)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertEqual(
                        [line.rsplit("|", 1)[-1] for line in fixture.invocations()],
                        ["esp32"],
                        "the matrix must re-check source identity immediately "
                        "after every target",
                    )
                finally:
                    fixture.cleanup()

    def test_source_change_during_the_final_target_is_still_rejected(self):
        fixture = BuildAllFixture()
        try:
            completed = fixture.execute("final-dirty")
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                [line.rsplit("|", 1)[-1] for line in fixture.invocations()],
                list(TARGETS),
                "the final target may run, but its source mutation must make "
                "the matrix fail before success is reported",
            )
        finally:
            fixture.cleanup()


class PrepareFixture:
    """Minimal upstream Git tree for exercising production prepare.sh."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-prepare-hardening-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.firmware = self.repo / "firmware"
        self.upstream = self.firmware / "upstream" / "micropython"
        scripts = self.firmware / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(PREPARE_SCRIPT, scripts / "prepare.sh")
        (scripts / "prepare.sh").chmod(
            (scripts / "prepare.sh").stat().st_mode | stat.S_IXUSR
        )
        _write_executable(
            self.repo / "tools" / "ci" / "sha_drift.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        _write_executable(
            self.repo / "tools" / "ci" / "patches_policy.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        overlay = self.firmware / "board_overlays" / "esp32"
        (overlay / "nested").mkdir(parents=True)
        (overlay / "_boot.py").write_text("BOOT = 1\n", encoding="utf-8")
        (overlay / "manifest.py").write_text("freeze('.')\n", encoding="utf-8")
        (overlay / "nested" / "config.txt").write_text("overlay-v1\n", encoding="utf-8")
        (overlay / "partitions.csv").write_text(
            "nvs,data,nvs,0x9000,0x6000,\n", encoding="utf-8"
        )
        pyble = self.firmware / "pyble"
        pyble.mkdir()
        (pyble / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (pyble / "agent.py").write_text("AGENT = 1\n", encoding="utf-8")
        (self.firmware / "patches").mkdir()
        (self.firmware / "versions.lock").write_text(
            textwrap.dedent(
                """
                [micropython]
                repo = "https://github.com/micropython/micropython"
                ref = "v1.28.0"
                commit = "1111111111111111111111111111111111111111"
                [esp_idf]
                repo = "https://github.com/espressif/esp-idf"
                ref = "v5.5.1"
                commit = "2222222222222222222222222222222222222222"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        tracked = (
            self.upstream
            / "ports"
            / "esp32"
            / "boards"
            / "ESP32_GENERIC"
            / "original.txt"
        )
        tracked.parent.mkdir(parents=True)
        tracked.write_text("upstream\n", encoding="utf-8")
        _git(self.upstream, "init", "-q")
        _git(self.upstream, "config", "user.name", "PyBLE Test")
        _git(self.upstream, "config", "user.email", "test@pyble.invalid")
        _git(self.upstream, "add", ".")
        _git(
            self.upstream,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "upstream",
        )
        upstream_commit = _git(self.upstream, "rev-parse", "HEAD")
        lock_path = self.firmware / "versions.lock"
        lock_path.write_text(
            lock_path.read_text(encoding="utf-8").replace(
                "1" * 40, upstream_commit
            ),
            encoding="utf-8",
        )
        self.tracked = tracked
        self.board = self.upstream / "ports" / "esp32" / "boards" / "PYBLE_ESP32"

    def cleanup(self):
        self._temporary.cleanup()

    def prepare(self) -> subprocess.CompletedProcess[str]:
        return _run(
            [str(self.firmware / "scripts" / "prepare.sh"), "esp32"],
            cwd=self.repo,
            env={
                **os.environ,
                "PYBLE_UPSTREAM_DIR": str(self.upstream),
                "PYBLE_LOCK_FILE": str(self.firmware / "versions.lock"),
            },
        )

    @staticmethod
    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def expected_board(self) -> dict[str, bytes]:
        expected = self.snapshot(self.firmware / "board_overlays" / "esp32")
        expected.update(
            {
                "pyble/{}".format(relative): value
                for relative, value in self.snapshot(self.firmware / "pyble").items()
            }
        )
        return expected


class PrepareConvergenceTests(unittest.TestCase):
    def test_target_board_is_an_exact_convergent_overlay_mirror(self):
        fixture = PrepareFixture()
        try:
            first = fixture.prepare()
            self.assertEqual(first.returncode, 0, first.stdout)
            (fixture.board / "stale.c").write_text("must disappear\n", encoding="utf-8")
            (fixture.board / "nested" / "old.txt").write_text(
                "must disappear\n", encoding="utf-8"
            )
            (
                fixture.firmware / "board_overlays" / "esp32" / "nested" / "config.txt"
            ).write_text("overlay-v2\n", encoding="utf-8")
            second = fixture.prepare()
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertEqual(
                fixture.snapshot(fixture.board),
                fixture.expected_board(),
                "prepare must remove stale prior overlay bytes before copying",
            )
        finally:
            fixture.cleanup()

    def test_tracked_upstream_drift_is_rejected_before_copy(self):
        fixture = PrepareFixture()
        try:
            fixture.tracked.write_text("locally edited upstream\n", encoding="utf-8")
            completed = fixture.prepare()
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertFalse(
                fixture.board.exists(),
                "tracked upstream drift must fail before creating build inputs",
            )
        finally:
            fixture.cleanup()

    def test_only_documented_generated_output_locations_are_permitted(self):
        fixture = PrepareFixture()
        try:
            first = fixture.prepare()
            self.assertEqual(first.returncode, 0, first.stdout)
            allowed = (
                fixture.upstream / "ports" / "esp32" / "build-PYBLE_ESP32",
                fixture.upstream / "mpy-cross" / "build",
            )
            for directory in allowed:
                directory.mkdir(parents=True)
                (directory / "generated.o").write_bytes(b"generated")
            accepted = fixture.prepare()
            self.assertEqual(
                accepted.returncode,
                0,
                "documented build outputs must not make preparation "
                "non-convergent:\n{}".format(accepted.stdout),
            )

            rogue = fixture.upstream / "py" / "unowned-generated.tmp"
            rogue.parent.mkdir()
            rogue.write_text("not an allowed generated path\n", encoding="utf-8")
            rejected = fixture.prepare()
            self.assertNotEqual(
                rejected.returncode,
                0,
                "unknown upstream debris must not be silently accepted",
            )
        finally:
            fixture.cleanup()


class BuildScriptFixture:
    """Runs production build.sh with a fake make and real tiny Git identities."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-build-provenance-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.firmware = self.repo / "firmware"
        self.upstream = self.firmware / "upstream" / "micropython"
        self.idf = self.firmware / ".esp-idf"
        self.output = self.root / "output"
        self.fake_artifacts = self.root / "fake-artifacts"
        self.make_log = self.root / "make-invocations.log"
        self.make_environment_log = self.root / "make-environment.log"
        self.mpy_cross_environment_log = self.root / "mpy-cross-environment.log"
        self.esptool_log = self.root / "esptool-invocations.log"
        scripts = self.firmware / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(BUILD_SCRIPT, scripts / "build.sh")
        (scripts / "build.sh").chmod(
            (scripts / "build.sh").stat().st_mode | stat.S_IXUSR
        )
        _write_executable(scripts / "prepare.sh", "#!/usr/bin/env bash\nexit 0\n")
        _write_executable(
            self.repo / "tools" / "ci" / "sha_drift.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        (self.firmware / "board_overlays" / "esp32").mkdir(parents=True)
        (self.firmware / "user_c_modules" / "pyble").mkdir(parents=True)
        (self.upstream / "mpy-cross").mkdir(parents=True)
        (self.upstream / "ports" / "esp32").mkdir(parents=True)
        _write_executable(self.idf / "export.sh", "#!/usr/bin/env bash\n:\n")
        self.micropython_commit = _init_git_repo(
            self.upstream, "source/micropython.c"
        )
        self.esp_idf_commit = _init_git_repo(self.idf, "source/esp-idf.c")
        (self.firmware / "versions.lock").write_text(
            textwrap.dedent(
                """
                [micropython]
                repo = "https://github.com/micropython/micropython"
                ref = "v1.28.0"
                commit = "{micropython}"
                [esp_idf]
                repo = "https://github.com/espressif/esp-idf"
                ref = "v5.5.1"
                commit = "{esp_idf}"
                [targets]
                "esp32" = "esp32"
                "esp32-s3" = "esp32s3"
                "esp32-c3" = "esp32c3"
                [pyble]
                agent_version = "0.4.0"
                protocol_version = "PBLE/1"
                """
            )
            .format(
                micropython=self.micropython_commit,
                esp_idf=self.esp_idf_commit,
            )
            .lstrip(),
            encoding="utf-8",
        )
        self.fake_bin = self.root / "bin"
        spec = bundle_fixture.PROFILE_SPECS["esp32-4mb"]
        (self.fake_artifacts / "bootloader").mkdir(parents=True)
        (self.fake_artifacts / "partition_table").mkdir()
        bootloader = bundle_fixture.make_esp_image(
            spec["chip_id"],
            spec["header_size_freq"],
            application=False,
            silicon_revision=spec["silicon_revision"],
        )
        elf = b"\x7fELF\0PyBLE build fixture"
        application = bundle_fixture.make_esp_image(
            spec["chip_id"],
            spec["header_size_freq"],
            application=True,
            silicon_revision=spec["silicon_revision"],
            app_elf_sha256=hashlib.sha256(elf).digest(),
        )
        partition_table = bundle_fixture.make_partition_table(
            spec["flash_size_bytes"]
        )
        merged = bundle_fixture.make_merged_image(
            spec["base_offset"],
            list(
                zip(
                    spec["component_offsets"],
                    (bootloader, partition_table, application),
                )
            ),
        )
        (self.fake_artifacts / "firmware.bin").write_bytes(merged)
        (self.fake_artifacts / "micropython.elf").write_bytes(elf)
        (self.fake_artifacts / "micropython.bin").write_bytes(application)
        (
            self.fake_artifacts / "bootloader" / "bootloader.bin"
        ).write_bytes(bootloader)
        (
            self.fake_artifacts
            / "partition_table"
            / "partition-table.bin"
        ).write_bytes(partition_table)
        bundle_fixture.write_json(
            self.fake_artifacts / "flasher_args.json",
            bundle_fixture.flasher_args_for(spec),
        )
        (self.fake_artifacts / "sdkconfig").write_text(
            "CONFIG_APP_REPRODUCIBLE_BUILD=y\n", encoding="utf-8"
        )
        bundle_fixture.write_json(
            self.fake_artifacts / "project_description.json",
            {
                "project_name": "micropython",
                "project_version": "v1.28.0",
                "target": "esp32",
                "build_dir": str(self.output / "esp32"),
                "idf_path": str(self.idf),
            },
        )
        _write_executable(
            self.fake_bin / "make",
            r"""
            #!/usr/bin/env bash
            set -eu
            {
              printf '%s' "$PWD"
              for argument in "$@"; do
                printf '|%s' "$argument"
              done
              printf '\n'
            } >> "$PYBLE_MAKE_LOG"
            printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
              "${CFLAGS_EXTRA-}" \
              "${EXTRA_CPPFLAGS-}" \
              "${CFLAGS-}" \
              "${CXXFLAGS-}" \
              "${CPPFLAGS-}" \
              "${EXTRA_CFLAGS-}" \
              "${EXTRA_CXXFLAGS-}" \
              "${MAKEFLAGS-}" \
              "${MFLAGS-}" \
              "${GNUMAKEFLAGS-}" \
              "${MAKEOVERRIDES-}" \
              "${PYTHONDONTWRITEBYTECODE-}" >> "$PYBLE_MAKE_ENV_LOG"
            printf '%s\n' "${MICROPY_MPYCROSS-}" \
              >> "$PYBLE_MPY_CROSS_ENV_LOG"
            output=""
            command_directory=""
            previous=""
            for argument in "$@"; do
              if [ "$previous" = "-C" ]; then
                command_directory="$argument"
              fi
              case "$argument" in
                BUILD=*) output="${argument#BUILD=}" ;;
              esac
              previous="$argument"
            done
            if [ "$(basename "$command_directory")" = "mpy-cross" ]; then
              case "$output" in
                /*) compiler="$output/mpy-cross" ;;
                *) compiler="$command_directory/$output/mpy-cross" ;;
              esac
              mkdir -p "$(dirname "$compiler")"
              printf '#!/bin/sh\nexit 0\n' > "$compiler"
              chmod 755 "$compiler"
            elif [ -n "$output" ]; then
              mkdir -p "$output"
              cp -R "$PYBLE_FAKE_ARTIFACTS"/. "$output"/
            fi
            """,
        )
        _write_executable(
            self.fake_bin / "python",
            r"""
            #!/usr/bin/env bash
            set -eu
            {
              first=1
              for argument in "$@"; do
                if [ "$first" -eq 0 ]; then
                  printf '|'
                fi
                printf '%s' "$argument"
                first=0
              done
              printf '\n'
            } >> "$PYBLE_ESPTOOL_LOG"
            [ "$#" -eq 6 ]
            [ "$1" = "-m" ]
            [ "$2" = "esptool" ]
            [ "$3" = "--chip" ]
            [ "$4" = "esp32" ]
            [ "$5" = "write_flash" ]
            [ "$6" = "--help" ]
            """,
        )
        (self.repo / ".gitignore").write_text(
            "firmware/upstream/micropython/\n"
            "firmware/.esp-idf/\n"
            "firmware/user_c_modules/pyble/pble_version.h\n",
            encoding="utf-8",
        )
        (self.repo / "source.txt").write_text("PyBLE source\n", encoding="utf-8")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "PyBLE Test")
        _git(self.repo, "config", "user.email", "test@pyble.invalid")
        _git(self.repo, "add", ".")
        _git(
            self.repo,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "PyBLE source",
        )
        self.pyble_commit = _git(self.repo, "rev-parse", "HEAD")
        self.source_date_epoch = int(
            _git(self.repo, "show", "-s", "--format=%ct", "HEAD")
        )

    def cleanup(self):
        self._temporary.cleanup()

    def build(self) -> subprocess.CompletedProcess[str]:
        return _run(
            [str(self.firmware / "scripts" / "build.sh"), "esp32"],
            cwd=self.repo,
            env={
                **os.environ,
                "PATH": "{}:{}".format(self.fake_bin, os.environ.get("PATH", "")),
                "PYBLE_BUILD_ROOT": str(self.output),
                "PYBLE_UPSTREAM_DIR": str(self.upstream),
                "PYBLE_IDF_DIR": str(self.idf),
                "PYBLE_LOCK_FILE": str(self.firmware / "versions.lock"),
                "PYBLE_FAKE_ARTIFACTS": str(self.fake_artifacts),
                "PYBLE_MAKE_LOG": str(self.make_log),
                "PYBLE_MAKE_ENV_LOG": str(self.make_environment_log),
                "PYBLE_MPY_CROSS_ENV_LOG": str(self.mpy_cross_environment_log),
                "PYBLE_ESPTOOL_LOG": str(self.esptool_log),
                "BUILD": str(self.root / "hostile-mpy-cross-build"),
                "MICROPY_MPYCROSS": str(self.root / "hostile-mpy-cross"),
                "CFLAGS_EXTRA": (
                    "-ffile-prefix-map=/ambient/source=/HOSTILE "
                    "-DHOSTILE_BUILD_FLAG=1"
                ),
                "EXTRA_CPPFLAGS": "-ffile-prefix-map=/ambient=/HOSTILE_CPP",
                "CFLAGS": "-DHOSTILE_CFLAGS=1",
                "CXXFLAGS": "-DHOSTILE_CXXFLAGS=1",
                "CPPFLAGS": "-DHOSTILE_CPPFLAGS=1",
                "EXTRA_CFLAGS": "-DHOSTILE_EXTRA_CFLAGS=1",
                "EXTRA_CXXFLAGS": "-DHOSTILE_EXTRA_CXXFLAGS=1",
                "MAKEFLAGS": (
                    "CFLAGS_EXTRA=-DHOSTILE_MAKE_CFLAGS "
                    "EXTRA_CPPFLAGS=-DHOSTILE_MAKE_CPPFLAGS"
                ),
                "MFLAGS": "-DHOSTILE_MFLAGS",
                "GNUMAKEFLAGS": "CFLAGS_EXTRA=-DHOSTILE_GNU_MAKE_CFLAGS",
                "MAKEOVERRIDES": "CFLAGS_EXTRA EXTRA_CPPFLAGS",
            },
        )

    def make_invocations(self) -> list[list[str]]:
        if not self.make_log.exists():
            return []
        return [
            line.split("|")
            for line in self.make_log.read_text(encoding="utf-8").splitlines()
        ]

    def make_environments(self) -> list[tuple[str, ...]]:
        if not self.make_environment_log.exists():
            return []
        return [
            tuple(line.split("|"))
            for line in self.make_environment_log.read_text(
                encoding="utf-8"
            ).splitlines()
        ]

    def esptool_invocations(self) -> list[list[str]]:
        if not self.esptool_log.exists():
            return []
        return [
            line.split("|")
            for line in self.esptool_log.read_text(encoding="utf-8").splitlines()
        ]

    def mpy_cross_environments(self) -> list[str]:
        if not self.mpy_cross_environment_log.exists():
            return []
        return self.mpy_cross_environment_log.read_text(
            encoding="utf-8"
        ).splitlines()


class BuildProvenanceEmissionTests(unittest.TestCase):
    def test_build_exercises_version_matched_recovery_subcommand(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                fixture.esptool_invocations(),
                [["-m", "esptool", "--chip", "esp32", "write_flash", "--help"]],
            )
        finally:
            fixture.cleanup()

    def test_port_submodules_and_final_build_share_the_exact_target_build_dir(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            port = str(fixture.upstream.resolve() / "ports" / "esp32")
            port_invocations = [
                arguments
                for arguments in fixture.make_invocations()
                if "-C" in arguments and port in arguments
            ]
            self.assertEqual(
                len(port_invocations),
                2,
                "the fixture expects one port submodules call and one final "
                "port build call",
            )
            expected = "BUILD={}".format(fixture.output.resolve() / "esp32")
            for arguments in port_invocations:
                with self.subTest(arguments=arguments):
                    self.assertEqual(
                        arguments.count(expected),
                        1,
                        "both mutable port phases must be scoped to the same "
                        "target build directory",
                    )
        finally:
            fixture.cleanup()

    def test_port_build_uses_only_stable_source_prefix_maps(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            upstream = fixture.upstream.resolve()
            repo = fixture.repo.resolve()
            port = str(upstream / "ports" / "esp32")
            expected = " ".join(
                (
                    "-ffile-prefix-map={}=/PYBLE".format(repo),
                    "-ffile-prefix-map={}=/IDF_BUILD".format(
                        fixture.output.resolve() / "esp32"
                    ),
                    "-ffile-prefix-map={}=/MICROPYTHON".format(upstream),
                    "-ffile-prefix-map={}=/IDF".format(fixture.idf.resolve()),
                )
            )
            environments = fixture.make_environments()
            self.assertEqual(
                environments[0][:-1],
                ("", "", "", "", "", "", "", "", "", "", ""),
                "ambient compiler flags must not influence the rebuilt compiler",
            )
            port_invocations = [
                arguments
                for arguments, environment in zip(
                    fixture.make_invocations(), environments, strict=True
                )
                if "-C" in arguments and port in arguments
            ]
            self.assertEqual(
                len(port_invocations),
                2,
                "the fixture expects submodule and final port make calls",
            )
            for arguments in port_invocations:
                with self.subTest(arguments=arguments):
                    self.assertEqual(
                        arguments.count("CFLAGS_EXTRA={}".format(expected)),
                        1,
                    )
                    self.assertEqual(
                        arguments.count("EXTRA_CPPFLAGS={}".format(expected)),
                        1,
                    )
            self.assertEqual(
                [environment[:-1] for environment in environments],
                [("", "", "", "", "", "", "", "", "", "", "")] * 3,
                "submodule configuration and the final application build must "
                "share exact runner-owned path maps; ambient flags may not be "
                "inherited or appended",
            )
        finally:
            fixture.cleanup()

    def test_build_disables_python_bytecode_cache_generation(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            environments = fixture.make_environments()
            self.assertTrue(environments)
            self.assertEqual(
                [environment[-1] for environment in environments],
                ["1"] * len(environments),
                "every build phase must prevent checkout-local Python caches",
            )
        finally:
            fixture.cleanup()

    def test_port_build_reuses_the_explicitly_built_host_mpy_cross(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                fixture.make_invocations()[0].count("BUILD=build"),
                1,
                "the host compiler build must ignore an ambient BUILD path",
            )
            expected = str(
                fixture.upstream.resolve() / "mpy-cross" / "build" / "mpy-cross"
            )
            self.assertEqual(
                fixture.mpy_cross_environments(),
                ["", expected, expected],
                "port phases must use the admitted host compiler instead of "
                "rebuilding it with the target BUILD inherited through make",
            )
        finally:
            fixture.cleanup()

    def test_build_rejects_host_source_paths_remaining_in_elf(self):
        for label in ("retained MicroPython", "PyBLE", "selected build root"):
            with self.subTest(source=label):
                fixture = BuildScriptFixture()
                try:
                    root = {
                        "retained MicroPython": fixture.upstream.resolve(),
                        "PyBLE": fixture.repo.resolve(),
                        "selected build root": fixture.output.resolve(),
                    }[label]
                    elf = fixture.fake_artifacts / "micropython.elf"
                    elf.write_bytes(elf.read_bytes() + b"\0" + str(root).encode())
                    completed = fixture.build()
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertRegex(
                        completed.stdout,
                        r"ELF.*(?:path|prefix)|(?:path|prefix).*ELF",
                    )
                finally:
                    fixture.cleanup()

    def test_successful_build_emits_exact_checkout_bound_provenance(self):
        fixture = BuildScriptFixture()
        try:
            completed = fixture.build()
            self.assertEqual(completed.returncode, 0, completed.stdout)
            path = fixture.output / "esp32" / "pyble-build-provenance.json"
            self.assertTrue(path.is_file(), completed.stdout)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "schema_version": 1,
                    "target": "esp32",
                    "source_date_epoch": fixture.source_date_epoch,
                    "pyble": {
                        "commit": fixture.pyble_commit,
                        "clean": True,
                    },
                    "micropython": {
                        "commit": fixture.micropython_commit,
                    },
                    "esp_idf": {"commit": fixture.esp_idf_commit},
                },
            )
        finally:
            fixture.cleanup()


class ActualCheckoutFixture:
    """ReleaseFixture with canonical proof inputs and three retained checkouts."""

    def __init__(self):
        self.release_fixture = bundle_fixture.ReleaseFixture()
        self.repo = self.release_fixture.repo
        self.upstream = self.repo / "firmware" / "upstream" / "micropython"
        self.idf = self.repo / "firmware" / ".esp-idf"
        port = self.upstream / "ports" / "esp32"
        port.mkdir(parents=True)
        (port / "source.c").write_text(
            "// SPDX-License-Identifier: MIT\n", encoding="utf-8"
        )
        self.micropython_commit = self._commit_existing(self.upstream, "MicroPython")
        self.esp_idf_commit = self._commit_existing(self.idf, "ESP-IDF")
        _git(self.upstream, "remote", "add", "origin", MICROPYTHON_ORIGIN)
        _git(
            self.idf,
            "remote",
            "add",
            "origin",
            "https://github.com/espressif/esp-idf",
        )
        lock_path = self.repo / "firmware" / "versions.lock"
        lock = lock_path.read_text(encoding="utf-8")
        lock = lock.replace("2" * 40, self.micropython_commit)
        lock = lock.replace("3" * 40, self.esp_idf_commit)
        lock_path.write_text(lock, encoding="utf-8")
        self.target_upstreams: dict[str, Path] = {}
        source_root = self.release_fixture.build_root / ".sources"
        for target in TARGETS:
            checkout = source_root / target / "micropython"
            checkout.parent.mkdir(parents=True)
            completed = _run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(self.upstream),
                    str(checkout),
                ]
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stdout)
            _git(
                checkout,
                "remote",
                "set-url",
                "origin",
                MICROPYTHON_ORIGIN,
            )
            self.target_upstreams[target] = checkout
            project_description = (
                self.release_fixture.build_root
                / target
                / "project_description.json"
            )
            description = json.loads(
                project_description.read_text(encoding="utf-8")
            )
            description["project_path"] = str(checkout / "ports" / "esp32")
            bundle_fixture.write_json(project_description, description)
        (self.repo / ".gitignore").write_text(
            "firmware/upstream/micropython/\nfirmware/.esp-idf/\n",
            encoding="utf-8",
        )
        (self.repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "PyBLE Test")
        _git(self.repo, "config", "user.email", "test@pyble.invalid")
        _git(self.repo, "add", ".")
        _git(
            self.repo,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "PyBLE fixture",
        )
        self.pyble_commit = _git(self.repo, "rev-parse", "HEAD")
        self.source_date_epoch = int(
            _git(self.repo, "show", "-s", "--format=%ct", "HEAD")
        )
        for target in TARGETS:
            bundle_fixture.write_json(
                self.release_fixture.build_root
                / target
                / "pyble-build-provenance.json",
                {
                    "schema_version": 1,
                    "target": target,
                    "source_date_epoch": self.source_date_epoch,
                    "pyble": {
                        "commit": self.pyble_commit,
                        "clean": True,
                    },
                    "micropython": {
                        "commit": self.micropython_commit,
                    },
                    "esp_idf": {"commit": self.esp_idf_commit},
                },
            )

    def project_description_path(self, target: str) -> Path:
        return (
            self.release_fixture.build_root
            / target
            / "project_description.json"
        )

    def set_project_path(self, target: str, path: Path) -> None:
        description_path = self.project_description_path(target)
        description = json.loads(description_path.read_text(encoding="utf-8"))
        description["project_path"] = str(path)
        bundle_fixture.write_json(description_path, description)

    @staticmethod
    def _commit_existing(path: Path, name: str) -> str:
        _git(path, "init", "-q")
        _git(path, "config", "user.name", "PyBLE Test")
        _git(path, "config", "user.email", "test@pyble.invalid")
        _git(path, "add", ".")
        _git(
            path,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            name,
        )
        return _git(path, "rev-parse", "HEAD")

    def cleanup(self):
        self.release_fixture.cleanup()


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class BuildProvenanceValidationTests(unittest.TestCase):
    def test_reproducibility_comparison_binds_both_retained_source_roots(self):
        fixture = ActualCheckoutFixture()
        try:
            primary = fixture.release_fixture.build_root
            second = fixture.release_fixture.root / "second-build"
            shutil.copytree(primary, second)
            for target in TARGETS:
                description_path = second / target / "project_description.json"
                description = json.loads(
                    description_path.read_text(encoding="utf-8")
                )
                description["build_dir"] = str(second / target)
                description["project_path"] = str(
                    second
                    / ".sources"
                    / target
                    / "micropython"
                    / "ports"
                    / "esp32"
                )
                bundle_fixture.write_json(description_path, description)

            self.assertIsNone(
                RELEASE.compare_build_roots(
                    primary,
                    second,
                    repo_root=fixture.repo,
                )
            )

            shutil.rmtree(second / ".sources" / "esp32" / "micropython")
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                r"(?i)(source|project|checkout|path|missing)",
            ):
                RELEASE.compare_build_roots(
                    primary,
                    second,
                    repo_root=fixture.repo,
                )
        finally:
            fixture.cleanup()

    def test_validate_build_binds_record_to_all_actual_checkout_heads(self):
        fixture = ActualCheckoutFixture()
        try:
            for target in TARGETS:
                with self.subTest(target=target):
                    result = _validate_build_with_repo(
                        target,
                        fixture.release_fixture.build_root / target,
                        fixture.repo,
                    )
                    self.assertEqual(
                        result["provenance"]["pyble"]["commit"],
                        fixture.pyble_commit,
                    )
                    self.assertEqual(
                        Path(result["project_description"]["project_path"]),
                        fixture.target_upstreams[target] / "ports" / "esp32",
                    )
                    self.assertEqual(
                        result["retained_source"],
                        {
                            "target": target,
                            "project_path": (
                                ".sources/%s/micropython/ports/esp32" % target
                            ),
                            "project_description_sha256": hashlib.sha256(
                                fixture.project_description_path(
                                    target
                                ).read_bytes()
                            ).hexdigest(),
                            "commit": fixture.micropython_commit,
                            "origin": MICROPYTHON_ORIGIN,
                        },
                        "release validation must expose a host-independent "
                        "retained-source record suitable for the semantic "
                        "license-audit receipt",
                    )
        finally:
            fixture.cleanup()

    def test_validate_build_rejects_source_checkout_paths_in_elf(self):
        for label in ("retained MicroPython", "PyBLE"):
            with self.subTest(prefix=label):
                fixture = ActualCheckoutFixture()
                try:
                    target = "esp32"
                    build = fixture.release_fixture.build_root / target
                    leaked_root = (
                        fixture.target_upstreams[target].resolve()
                        if label == "retained MicroPython"
                        else fixture.repo.resolve()
                    )
                    elf = build / "micropython.elf"
                    elf.write_bytes(
                        elf.read_bytes()
                        + b"\0"
                        + str(leaked_root).encode("utf-8")
                    )
                    bundle_fixture.rebind_fixture_application_to_elf(
                        build,
                        bundle_fixture.PROFILE_SPECS["esp32-4mb"],
                    )
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"ELF retains unmapped.*{}".format(label),
                    ):
                        _validate_build_with_repo(
                            target,
                            build,
                            fixture.repo,
                        )
                finally:
                    fixture.cleanup()

    def test_dirty_or_drifted_checkout_cannot_validate_old_build_identity(self):
        for mutation in (
            "pyble-dirty",
            "micropython-dirty",
            "micropython-head",
            "esp-idf-dirty",
            "esp-idf-head",
        ):
            with self.subTest(mutation=mutation):
                fixture = ActualCheckoutFixture()
                try:
                    if mutation == "pyble-dirty":
                        (fixture.repo / "tracked.txt").write_text(
                            "dirty\n", encoding="utf-8"
                        )
                    elif mutation.endswith("-dirty"):
                        checkout = (
                            fixture.target_upstreams["esp32"]
                            if mutation == "micropython-dirty"
                            else fixture.idf
                        )
                        tracked = (
                            checkout / "LICENSE"
                            if (checkout / "LICENSE").is_file()
                            else checkout / "tracked.txt"
                        )
                        tracked.write_text(
                            "dirty tracked checkout\n", encoding="utf-8"
                        )
                    else:
                        checkout = (
                            fixture.target_upstreams["esp32"]
                            if mutation == "micropython-head"
                            else fixture.idf
                        )
                        (checkout / "new-source.txt").write_text(
                            "new commit\n", encoding="utf-8"
                        )
                        _git(checkout, "add", "new-source.txt")
                        _git(
                            checkout,
                            "-c",
                            "user.name=PyBLE Test",
                            "-c",
                            "user.email=test@pyble.invalid",
                            "-c",
                            "commit.gpgsign=false",
                            "commit",
                            "-q",
                            "-m",
                            "drift",
                        )
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(clean|dirty|commit|checkout|provenance|drift)",
                    ):
                        _validate_build_with_repo(
                            "esp32",
                            fixture.release_fixture.build_root / "esp32",
                            fixture.repo,
                        )
                finally:
                    fixture.cleanup()

    def test_project_path_and_retained_checkout_fail_closed_matrix(self):
        mutations = (
            (
                "canonical-checkout",
                lambda fixture: fixture.set_project_path(
                    "esp32",
                    fixture.upstream / "ports" / "esp32",
                ),
            ),
            (
                "cross-target-checkout",
                lambda fixture: fixture.set_project_path(
                    "esp32",
                    fixture.target_upstreams["esp32-s3"] / "ports" / "esp32",
                ),
            ),
            (
                "missing-checkout",
                lambda fixture: fixture.set_project_path(
                    "esp32",
                    fixture.release_fixture.build_root
                    / ".sources"
                    / "esp32"
                    / "missing"
                    / "ports"
                    / "esp32",
                ),
            ),
            (
                "symlinked-checkout",
                self._replace_target_checkout_with_symlink,
            ),
            (
                "wrong-origin",
                lambda fixture: _git(
                    fixture.target_upstreams["esp32"],
                    "remote",
                    "set-url",
                    "origin",
                    "https://example.invalid/fork/micropython",
                ),
            ),
            (
                "wrong-head",
                self._commit_target_checkout_drift,
            ),
            (
                "dirty-tracked-checkout",
                lambda fixture: (
                    fixture.target_upstreams["esp32"] / "ports" / "esp32" / "source.c"
                ).write_text(
                    "// dirty retained checkout\n",
                    encoding="utf-8",
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(mutation=label):
                fixture = ActualCheckoutFixture()
                try:
                    mutate(fixture)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(source|project|checkout|path|origin|commit|clean|dirty|missing|symlink|target)",
                    ):
                        _validate_build_with_repo(
                            "esp32",
                            fixture.release_fixture.build_root / "esp32",
                            fixture.repo,
                        )
                finally:
                    fixture.cleanup()

    @staticmethod
    def _replace_target_checkout_with_symlink(
        fixture: ActualCheckoutFixture,
    ) -> None:
        checkout = fixture.target_upstreams["esp32"]
        backing = checkout.with_name("micropython-backing")
        checkout.rename(backing)
        checkout.symlink_to(backing.name, target_is_directory=True)

    @staticmethod
    def _commit_target_checkout_drift(fixture: ActualCheckoutFixture) -> None:
        checkout = fixture.target_upstreams["esp32"]
        drift = checkout / "ports" / "esp32" / "drift.c"
        drift.write_text("// new retained source\n", encoding="utf-8")
        _git(checkout, "add", "ports/esp32/drift.c")
        _git(
            checkout,
            "-c",
            "user.name=PyBLE Test",
            "-c",
            "user.email=test@pyble.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "retained checkout drift",
        )

    def test_retained_source_deletion_is_release_validation_blocking(self):
        fixture = ActualCheckoutFixture()
        try:
            shutil.rmtree(fixture.target_upstreams["esp32"])
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                r"(?i)(source|project|checkout|path|missing)",
            ):
                _validate_build_with_repo(
                    "esp32",
                    fixture.release_fixture.build_root / "esp32",
                    fixture.repo,
                )
        finally:
            fixture.cleanup()

    def test_provenance_record_shape_values_and_target_are_fail_closed(self):
        mutations = (
            lambda record: record.update(unexpected=True),
            lambda record: record.update(schema_version=2),
            lambda record: record.update(target="esp32-s3"),
            lambda record: record.update(source_date_epoch="1785326400"),
            lambda record: record.update(source_date_epoch=True),
            lambda record: record.update(source_date_epoch=-1),
            lambda record: record.update(source_date_epoch=1.5),
            lambda record: record["pyble"].update(clean=False),
            lambda record: record["pyble"].update(commit="abc123"),
            lambda record: record["micropython"].update(commit="A" * 40),
            lambda record: record["esp_idf"].update(commit="0" * 39),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    path = fixture.build_root / "esp32" / "pyble-build-provenance.json"
                    record = json.loads(path.read_text(encoding="utf-8"))
                    mutate(record)
                    bundle_fixture.write_json(path, record)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(provenance|source|epoch|target|commit|clean|field|schema)",
                    ):
                        RELEASE.validate_build("esp32", fixture.build_root / "esp32")
                finally:
                    fixture.cleanup()

    def test_all_targets_and_both_roots_require_one_commit_and_epoch(self):
        mutations = (
            lambda record: record.update(source_date_epoch=1785326401),
            lambda record: record["pyble"].update(commit="4" * 40),
            lambda record: record["micropython"].update(commit="5" * 40),
            lambda record: record["esp_idf"].update(commit="6" * 40),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    second = fixture.root / "second-build"
                    shutil.copytree(fixture.build_root, second)
                    path = second / "esp32-s3" / "pyble-build-provenance.json"
                    record = json.loads(path.read_text(encoding="utf-8"))
                    mutate(record)
                    bundle_fixture.write_json(path, record)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(provenance|source|epoch|commit|identity)",
                    ):
                        RELEASE.compare_build_roots(fixture.build_root, second)
                finally:
                    fixture.cleanup()


def _overlay_partition_entries(target: str) -> list[dict[str, int | str]]:
    type_values = {"app": 0, "data": 1}
    subtype_values = {
        ("data", "nvs"): 2,
        ("data", "phy"): 1,
        ("data", "fat"): 0x81,
        ("app", "factory"): 0,
    }
    entries: list[dict[str, int | str]] = []
    with (OVERLAYS / target / "partitions.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.reader(
            line for line in handle if not line.lstrip().startswith("#")
        ):
            if not row or not any(field.strip() for field in row):
                continue
            name, part_type, subtype, offset, size, flags = (
                field.strip() for field in row[:6]
            )
            entries.append(
                {
                    "name": name,
                    "type": type_values[part_type],
                    "subtype": subtype_values[(part_type, subtype)],
                    "offset": int(offset, 0),
                    "size": int(size, 0),
                    "flags": int(flags, 0) if flags else 0,
                }
            )
    return entries


def _encode_partition_table(entries: list[dict[str, int | str]]) -> bytes:
    raw = bytearray()
    for entry in entries:
        raw.extend(
            struct.pack(
                "<HBBII16sI",
                0x50AA,
                int(entry["type"]),
                int(entry["subtype"]),
                int(entry["offset"]),
                int(entry["size"]),
                str(entry["name"]).encode("ascii").ljust(16, b"\0"),
                int(entry["flags"]),
            )
        )
    digest = hashlib.md5(raw).digest()  # nosec: ESP partition format.
    raw.extend(b"\xeb\xeb" + b"\xff" * 14)
    raw.extend(digest)
    return bytes(raw).ljust(0xC00, b"\xff")


def _install_partition_table(
    fixture: bundle_fixture.ReleaseFixture,
    target: str,
    entries: list[dict[str, int | str]],
) -> None:
    profile_id = bundle_fixture.TARGET_TO_PROFILE[target]
    spec = bundle_fixture.PROFILE_SPECS[profile_id]
    build = fixture.build_root / target
    table = _encode_partition_table(entries)
    (build / "partition_table" / "partition-table.bin").write_bytes(table)
    (build / "firmware.bin").write_bytes(
        bundle_fixture.make_merged_image(
            spec["base_offset"],
            list(
                zip(
                    spec["component_offsets"],
                    (
                        (build / "bootloader" / "bootloader.bin").read_bytes(),
                        table,
                        (build / "micropython.bin").read_bytes(),
                    ),
                )
            ),
        )
    )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class ExactPartitionContractTests(unittest.TestCase):
    def test_every_binary_partition_record_must_equal_its_profile_csv(self):
        for target in TARGETS:
            mutations = (
                lambda entries: entries[0].update(offset=0x2000),
                lambda entries: entries[2].update(
                    size=int(entries[2]["size"]) - 0x1000
                ),
                lambda entries: entries[1].update(flags=1),
                lambda entries: entries.insert(
                    0,
                    {
                        "name": "extra",
                        "type": 1,
                        "subtype": 0x40,
                        "offset": 0x8000,
                        "size": 0x1000,
                        "flags": 0,
                    },
                ),
            )
            for mutate in mutations:
                with self.subTest(target=target, mutation=mutate):
                    fixture = bundle_fixture.ReleaseFixture()
                    try:
                        entries = copy.deepcopy(_overlay_partition_entries(target))
                        mutate(entries)
                        _install_partition_table(fixture, target, entries)
                        with self.assertRaisesRegex(
                            RELEASE.ReleaseError,
                            r"(?i)(partition|layout|csv|offset|size|flag|extra)",
                        ):
                            RELEASE.validate_build(target, fixture.build_root / target)
                    finally:
                        fixture.cleanup()

    def test_partition_overlap_remains_release_blocking(self):
        fixture = bundle_fixture.ReleaseFixture()
        try:
            entries = _overlay_partition_entries("esp32")
            entries[3]["offset"] = int(entries[2]["offset"]) + 0x1000
            _install_partition_table(fixture, "esp32", entries)
            with self.assertRaisesRegex(
                RELEASE.ReleaseError, r"(?i)partition.*overlap"
            ):
                RELEASE.validate_build("esp32", fixture.build_root / "esp32")
        finally:
            fixture.cleanup()


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class ImmutableBundleFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bundle_fixture.ReleaseFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def test_expected_release_file_must_not_be_a_symlink(self):
        bundle = self.fixture.make_bundle(public=False)
        notes = bundle / "RELEASE_NOTES.md"
        recovery = bundle / "RECOVERY.md"
        recovery.write_bytes(notes.read_bytes())
        notes.unlink()
        notes.symlink_to("RECOVERY.md")
        self.fixture.refresh_declared_hashes()
        with self.assertRaisesRegex(
            RELEASE.ReleaseError, r"(?i)(symlink|regular file|layout)"
        ):
            RELEASE.validate_bundle(
                bundle,
                public=False,
                qualification_repo_root=self.fixture.repo,
            )

    def test_extra_dangling_or_directory_symlink_is_not_ignored(self):
        for kind in ("dangling", "directory"):
            with self.subTest(kind=kind):
                bundle = self.fixture.make_bundle(public=False)
                extra = bundle / "unlisted-link"
                if kind == "dangling":
                    extra.symlink_to("missing-target")
                else:
                    extra.symlink_to("esp32-4mb", target_is_directory=True)
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError, r"(?i)(symlink|layout|unlisted|extra)"
                ):
                    RELEASE.validate_bundle(
                        bundle,
                        public=False,
                        qualification_repo_root=self.fixture.repo,
                    )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_extra_special_file_is_not_ignored(self):
        bundle = self.fixture.make_bundle(public=False)
        os.mkfifo(bundle / "unlisted.fifo", 0o600)
        with self.assertRaisesRegex(
            RELEASE.ReleaseError, r"(?i)(special|regular file|layout|unlisted)"
        ):
            RELEASE.validate_bundle(
                bundle,
                public=False,
                qualification_repo_root=self.fixture.repo,
            )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class CanonicalSchemaTests(unittest.TestCase):
    def test_release_schema_must_equal_the_canonical_generator_exactly(self):
        mutations = (
            lambda schema: schema.update(
                title="Locally modified but superficially valid schema"
            ),
            lambda schema: schema.update(description="unreviewed addition"),
            lambda schema: schema["properties"]["identity"]["properties"]["tag"].update(
                pattern=r"^.+$"
            ),
            lambda schema: schema["properties"]["profiles"].update(minItems=1),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    bundle = fixture.make_bundle(public=False)
                    path = bundle / "release.schema.json"
                    schema = json.loads(path.read_text(encoding="utf-8"))
                    mutate(schema)
                    bundle_fixture.write_json(path, schema)
                    fixture.refresh_sums()
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(canonical|schema.*exact|schema.*mismatch)",
                    ):
                        RELEASE.validate_bundle(
                            bundle,
                            public=False,
                            qualification_repo_root=fixture.repo,
                        )
                finally:
                    fixture.cleanup()


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class CandidateSourceStateTests(unittest.TestCase):
    @staticmethod
    def _provenance() -> dict:
        return {
            "pyble": {"commit": "1" * 40, "clean": True},
            "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
            "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
            "patch_count": 0,
            "runner": {"os": "FixtureOS 1", "architecture": "fixture64"},
            "tools": [{"name": "python", "version": "3.13.5"}],
        }

    def _create(self, fixture, output):
        return RELEASE.create_bundle(
            build_root=fixture.build_root,
            reproducibility_build_root=fixture.reproducibility_build_root,
            output_dir=output,
            repo_root=fixture.repo,
            installer_version="10.4.0",
            built_at="2026-07-29T12:00:00Z",
            provenance=self._provenance(),
            public=False,
        )

    def test_draft_or_proposed_pin_state_cannot_create_a_candidate(self):
        markers = (
            "# DRAFT — not yet frozen\n",
            "# pins are proposed defaults pending HIL\n",
        )
        for index, marker in enumerate(markers):
            with self.subTest(marker=marker):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    lock = fixture.repo / "firmware" / "versions.lock"
                    lock.write_text(
                        marker + lock.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    output = fixture.root / "candidate-{}".format(index)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(draft|proposed|frozen|pin.*state)",
                    ):
                        self._create(fixture, output)
                    self.assertFalse(output.exists())
                finally:
                    fixture.cleanup()

    def test_candidate_provenance_must_equal_every_build_record(self):
        mutations = (
            lambda record: record["pyble"].update(commit="4" * 40),
            lambda record: record["micropython"].update(commit="5" * 40),
            lambda record: record["esp_idf"].update(commit="6" * 40),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=mutate):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    path = (
                        fixture.build_root / "esp32-s3" / "pyble-build-provenance.json"
                    )
                    record = json.loads(path.read_text(encoding="utf-8"))
                    mutate(record)
                    bundle_fixture.write_json(path, record)
                    output = fixture.root / "candidate-{}".format(index)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(build.*provenance|source.*identity|commit)",
                    ):
                        self._create(fixture, output)
                    self.assertFalse(output.exists())
                finally:
                    fixture.cleanup()


class CrystalConfigurationGateTests(unittest.TestCase):
    def test_s3_and_c3_select_exact_crystal_without_auto_detection(self):
        for target in ("esp32-s3", "esp32-c3"):
            with self.subTest(target=target):
                text = (OVERLAYS / target / "sdkconfig.board").read_text(
                    encoding="utf-8"
                )
                self.assertRegex(text, r"(?m)^# CONFIG_XTAL_FREQ_AUTO is not set$")
                self.assertRegex(text, r"(?m)^CONFIG_XTAL_FREQ_40=y$")

    @unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
    def test_resolved_auto_xtal_configuration_is_release_blocking(self):
        for target in ("esp32-s3", "esp32-c3"):
            with self.subTest(target=target):
                fixture = bundle_fixture.ReleaseFixture()
                try:
                    (fixture.build_root / target / "sdkconfig").write_text(
                        "CONFIG_APP_REPRODUCIBLE_BUILD=y\n"
                        "CONFIG_XTAL_FREQ_AUTO=y\n"
                        "CONFIG_XTAL_FREQ_40=y\n"
                        "CONFIG_XTAL_FREQ=40\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(xtal|crystal|auto)",
                    ):
                        RELEASE.validate_build(target, fixture.build_root / target)
                finally:
                    fixture.cleanup()

    @unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
    def test_resolved_s3_and_c3_crystal_is_exactly_40_mhz(self):
        wrong_configs = (
            "CONFIG_XTAL_FREQ_40=y\nCONFIG_XTAL_FREQ=26\n",
            "CONFIG_XTAL_FREQ_26=y\nCONFIG_XTAL_FREQ=26\n",
            "",
        )
        for target in ("esp32-s3", "esp32-c3"):
            for config in wrong_configs:
                with self.subTest(target=target, config=config):
                    fixture = bundle_fixture.ReleaseFixture()
                    try:
                        (fixture.build_root / target / "sdkconfig").write_text(
                            "CONFIG_APP_REPRODUCIBLE_BUILD=y\n" + config,
                            encoding="utf-8",
                        )
                        with self.assertRaisesRegex(
                            RELEASE.ReleaseError,
                            r"(?i)(xtal|crystal|40)",
                        ):
                            RELEASE.validate_build(target, fixture.build_root / target)
                    finally:
                        fixture.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
