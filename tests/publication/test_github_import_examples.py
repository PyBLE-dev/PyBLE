# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "examples" / "github-import"
README_PATH = FIXTURE_ROOT / "README.md"

MAX_FILE_BYTES = 256 * 1024
MAX_BATCH_BYTES = 1024 * 1024
SAFE_EXAMPLE_NAME = re.compile(r"^[a-z][a-z0-9_]*\.py$")

FORBIDDEN_BOARD_ASSUMPTIONS = {
    "fixed Pin construction": re.compile(r"\b(?:machine\s*\.\s*)?Pin\s*\("),
    "fixed pin/GPIO assignment": re.compile(
        r"\b(?:[a-z0-9]+_)*(?:pin|gpio)(?:_[a-z0-9]+)*\s*=\s*"
        r"(?:\d+|['\"][^'\"]+['\"])",
        re.IGNORECASE,
    ),
    "numbered GPIO": re.compile(r"\bgpio[\s_-]*\d+\b", re.IGNORECASE),
    "target or board name": re.compile(
        r"\b(?:esp8266|esp32(?:-s3|-c3)?|rp2|rp2040|rp2350|stm32|nrf52|"
        r"samd|pico(?:\s+2\s+w)?|waveshare)\b",
        re.IGNORECASE,
    ),
    "PyBLE board profile": re.compile(
        r"\b(?:esp32-4mb|esp32-s3-n16r8|waveshare-esp32-s3-lcd-147b|"
        r"esp32-c3-4mb|rpi-pico2-w)\b",
        re.IGNORECASE,
    ),
    "board-profile routing": re.compile(
        r"\b(?:board_profile|profile_id|pyble_st7789)\b",
        re.IGNORECASE,
    ),
}


class GithubImportExamplesPolicyTest(unittest.TestCase):
    def require_fixture_root(self) -> None:
        if not FIXTURE_ROOT.is_dir():
            self.skipTest(
                "examples/github-import is absent; the presence test owns "
                "the expected red failure"
            )

    def python_examples(self) -> list[Path]:
        return sorted(
            path
            for path in FIXTURE_ROOT.iterdir()
            if path.is_file() and path.suffix == ".py"
        )

    def strict_text(self, path: Path) -> tuple[bytes, str]:
        payload = path.read_bytes()
        self.assertNotIn(
            b"\x00",
            payload,
            f"NUL byte in {path.relative_to(REPO_ROOT)}",
        )
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            self.fail(
                f"non-UTF-8 fixture {path.relative_to(REPO_ROOT)}: {error}"
            )
        return payload, text

    def test_fixture_directory_readme_and_examples_exist(self) -> None:
        self.assertTrue(
            FIXTURE_ROOT.is_dir(),
            "root examples/github-import must contain the public import fixtures",
        )
        self.assertTrue(
            README_PATH.is_file(),
            "examples/github-import/README.md must document the public fixtures",
        )
        self.assertGreaterEqual(
            len(self.python_examples()),
            2,
            "the public fixture folder must contain multiple lowercase .py examples",
        )

    def test_fixture_folder_is_flat_source_only_and_safely_named(self) -> None:
        self.require_fixture_root()
        entries = sorted(FIXTURE_ROOT.rglob("*"))
        offenders = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in entries
            if path.is_symlink()
            or not path.is_file()
            or (
                path != README_PATH
                and not SAFE_EXAMPLE_NAME.fullmatch(path.name)
            )
        ]
        self.assertEqual(
            offenders,
            [],
            "fixtures must be one README plus flat, lowercase, safe .py files",
        )

        names = [path.name for path in self.python_examples()]
        self.assertEqual(
            len(names),
            len(set(names)),
            "GitHub-import fixture basenames must be unique",
        )
        self.assertEqual(
            len(names),
            len({name.casefold() for name in names}),
            "fixture basenames must remain unique on case-folding filesystems",
        )
        forbidden_compiled = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in entries
            if path.is_file() and path.suffix.casefold() in {".mpy", ".pyc"}
        ]
        self.assertEqual(
            forbidden_compiled,
            [],
            "public examples must never ship compiled .mpy or .pyc files",
        )

    def test_fixture_files_are_strict_utf8_nul_free_and_mit(self) -> None:
        self.require_fixture_root()
        for path in [README_PATH, *self.python_examples()]:
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO_ROOT)}")
            _, text = self.strict_text(path)
            header = "\n".join(text.splitlines()[:5])
            self.assertIn(
                "SPDX-License-Identifier: MIT",
                header,
                f"missing SPDX MIT header in {path.relative_to(REPO_ROOT)}",
            )

    def test_python_examples_fit_import_file_and_batch_limits(self) -> None:
        self.require_fixture_root()
        sizes: list[int] = []
        for path in self.python_examples():
            size = len(path.read_bytes())
            self.assertLessEqual(
                size,
                MAX_FILE_BYTES,
                f"{path.relative_to(REPO_ROOT)} exceeds the 256 KiB file limit",
            )
            sizes.append(size)
        self.assertLessEqual(
            sum(sizes),
            MAX_BATCH_BYTES,
            "the complete public .py fixture batch exceeds 1 MiB",
        )

    def test_python_examples_make_no_board_pin_or_profile_assumption(self) -> None:
        self.require_fixture_root()
        for path in self.python_examples():
            _, text = self.strict_text(path)
            for assumption, pattern in FORBIDDEN_BOARD_ASSUMPTIONS.items():
                self.assertIsNone(
                    pattern.search(text),
                    f"{path.relative_to(REPO_ROOT)} contains {assumption}",
                )


if __name__ == "__main__":
    unittest.main()
