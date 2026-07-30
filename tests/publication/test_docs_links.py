# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ci"))

from docs_links import find_broken_links  # noqa: E402


class DocsLinksTest(unittest.TestCase):
    def test_accepts_files_directories_anchors_and_external_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text(
                "[root](../README.md)\n"
                "[section](../README.md#section)\n"
                "[directory](../docs/)\n"
                "[web](https://pyble.dev)\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("# Section\n", encoding="utf-8")

            self.assertEqual(find_broken_links(root), [])

    def test_rejects_missing_and_escaping_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "[missing](docs/missing.md)\n"
                "[escape](../private.md)\n",
                encoding="utf-8",
            )

            errors = find_broken_links(root)

            self.assertEqual(len(errors), 2)
            self.assertIn("missing target", errors[0])
            self.assertIn("escapes repository", errors[1])

    def test_rejects_a_missing_markdown_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Existing heading\n\n[bad](#missing-heading)\n",
                encoding="utf-8",
            )

            self.assertEqual(
                find_broken_links(root),
                ["README.md: missing anchor: #missing-heading"],
            )

    def test_rejects_a_case_mismatched_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "Guide.md").write_text("# Guide\n", encoding="utf-8")
            (root / "README.md").write_text(
                "[guide](docs/guide.md)\n",
                encoding="utf-8",
            )

            self.assertEqual(
                find_broken_links(root),
                ["README.md: target case mismatch: docs/guide.md"],
            )

    def test_public_repository_links_are_valid(self) -> None:
        self.assertEqual(find_broken_links(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
