#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract tests for deterministic prepare.sh Python materialization.

The ESP manifests select four reviewed scaffolds.  The RP2 manifest selects an
exact literal eleven-file package.  Preparation must materialize those inputs,
not recursively trust whatever ignored files happen to be beside them in a
developer checkout.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "prepare.sh"

ESP_TARGETS = (
    "esp32",
    "esp32-s3",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3",
)

ESP_PYBLE_INVENTORY = (
    "__init__.py",
    "_version.py",
    "pyble_ble.py",
    "pyble_proto.py",
)

RP2_PYBLE_INVENTORY = (
    "__init__.py",
    "_version.py",
    "pyble_agent.py",
    "pyble_ble.py",
    "pyble_boot.py",
    "pyble_console.py",
    "pyble_device_config.py",
    "pyble_fs.py",
    "pyble_info.py",
    "pyble_proto.py",
    "pyble_runner.py",
)

UNREVIEWED_PATHS = (
    "unreviewed_future.py",
    "developer-notes.txt",
    "__pycache__",
    "__pycache__/pyble_agent.cpython-313.pyc",
)


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


class PreparePythonFixture:
    """Minimal repository that executes the production preparation script."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-prepare-python-materialization-"
        )
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

        for target in (*ESP_TARGETS, "rpi-pico2-w"):
            overlay = self.firmware / "board_overlays" / target
            overlay.mkdir(parents=True)
            (overlay / "manifest.py").write_text(
                "# synthetic literal manifest\n", encoding="utf-8"
            )
            (overlay / "_boot.py").write_text("# synthetic boot\n", encoding="utf-8")
            if target in ESP_TARGETS:
                (overlay / "partitions.csv").write_text(
                    "nvs,data,nvs,0x9000,0x6000,\n", encoding="utf-8"
                )

        python_modules = self.firmware / "python_modules"
        python_modules.mkdir()
        (python_modules / "pyble_st7789.py").write_text(
            "# synthetic display module\n", encoding="utf-8"
        )

        self.pyble = self.firmware / "pyble"
        self.pyble.mkdir()
        for relative in RP2_PYBLE_INVENTORY:
            (self.pyble / relative).write_text(
                "# canonical {}\n".format(relative), encoding="utf-8"
            )
        (self.pyble / "unreviewed_future.py").write_text(
            "# not selected by a reviewed manifest\n", encoding="utf-8"
        )
        (self.pyble / "developer-notes.txt").write_text(
            "local scratch material\n", encoding="utf-8"
        )
        cache = self.pyble / "__pycache__"
        cache.mkdir()
        (cache / "pyble_agent.cpython-313.pyc").write_bytes(b"ignored bytecode")

        (self.firmware / "patches").mkdir()
        (self.firmware / "versions.lock").write_text(
            textwrap.dedent(
                """
                [micropython]
                ref = "v1.28.0"

                [targets_rp2]
                "rpi-pico2-w" = "RPI_PICO2_W"
                """
            ).lstrip(),
            encoding="utf-8",
        )

        self.upstream.mkdir(parents=True)
        (self.upstream / "README.md").write_text("synthetic upstream\n", encoding="utf-8")
        _run(["git", "init", "-q"], cwd=self.upstream)
        _run(["git", "config", "user.name", "PyBLE Test"], cwd=self.upstream)
        _run(
            ["git", "config", "user.email", "test@pyble.invalid"], cwd=self.upstream
        )
        _run(["git", "add", "."], cwd=self.upstream)
        completed = _run(
            [
                "git",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                "synthetic upstream",
            ],
            cwd=self.upstream,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout)

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def prepare(self, target: str) -> subprocess.CompletedProcess[str]:
        return _run(
            [str(self.firmware / "scripts" / "prepare.sh"), target],
            cwd=self.repo,
            env={
                **os.environ,
                "PYBLE_UPSTREAM_DIR": str(self.upstream),
                "PYBLE_LOCK_FILE": str(self.firmware / "versions.lock"),
            },
        )

    def board_pyble(self, target: str) -> Path:
        if target == "rpi-pico2-w":
            return (
                self.upstream
                / "ports"
                / "rp2"
                / "boards"
                / "PYBLE_RPI_PICO2_W"
                / "pyble"
            )
        board = "PYBLE_{}".format(target.upper().replace("-", "_"))
        return self.upstream / "ports" / "esp32" / "boards" / board / "pyble"

    def expected_bytes(self, inventory: tuple[str, ...]) -> dict[str, bytes]:
        return {relative: (self.pyble / relative).read_bytes() for relative in inventory}

    @staticmethod
    def materialized_bytes(package: Path) -> dict[str, bytes]:
        return {
            path.relative_to(package).as_posix(): path.read_bytes()
            for path in package.rglob("*")
            if path.is_file()
        }


class PreparePythonMaterializationTests(unittest.TestCase):
    def test_every_esp_target_copies_exact_reviewed_four_file_inventory(self):
        fixture = PreparePythonFixture()
        try:
            expected = fixture.expected_bytes(ESP_PYBLE_INVENTORY)
            for target in ESP_TARGETS:
                with self.subTest(target=target):
                    completed = fixture.prepare(target)
                    self.assertEqual(completed.returncode, 0, completed.stdout)
                    self.assertEqual(
                        fixture.materialized_bytes(fixture.board_pyble(target)),
                        expected,
                        "ESP preparation must materialize only the four files "
                        "selected by the reviewed target manifest",
                    )
        finally:
            fixture.cleanup()

    def test_rp2_copies_exact_reviewed_literal_eleven_file_inventory(self):
        fixture = PreparePythonFixture()
        try:
            completed = fixture.prepare("rpi-pico2-w")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                fixture.materialized_bytes(fixture.board_pyble("rpi-pico2-w")),
                fixture.expected_bytes(RP2_PYBLE_INVENTORY),
                "RP2 preparation must materialize exactly the manifest's "
                "literal eleven-file frozen package",
            )
        finally:
            fixture.cleanup()

    def test_arbitrary_and_python_cache_content_never_crosses_boundary(self):
        fixture = PreparePythonFixture()
        try:
            for target in ("esp32", "rpi-pico2-w"):
                with self.subTest(target=target):
                    completed = fixture.prepare(target)
                    self.assertEqual(completed.returncode, 0, completed.stdout)
                    materialized = fixture.board_pyble(target)
                    copied = [
                        relative
                        for relative in UNREVIEWED_PATHS
                        if (materialized / relative).exists()
                    ]
                    self.assertEqual(
                        copied,
                        [],
                        "prepare copied arbitrary or Python-cache checkout content",
                    )
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
