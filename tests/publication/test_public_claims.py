# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def markdown_section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = document.index(marker) + len(marker)
    end = document.find("\n## ", start)
    return document[start:] if end < 0 else document[start:end]


class PublicClaimsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        cls.bug_template = (
            REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml"
        ).read_text(encoding="utf-8")

    def test_readme_is_truthful_before_v042_hil_completes(self) -> None:
        firmware = markdown_section(self.readme, "What works")

        self.assertIn(
            "public browser installer is currently unavailable pending v0.4.2 HIL",
            firmware,
        )
        self.assertIn("`esp32-4mb`", firmware)
        self.assertIn("Classic ESP32, 4 MiB external SPI flash", firmware)
        self.assertIn("`esp32-s3-n16r8`", firmware)
        self.assertIn("16 MiB flash / 8 MiB Octal PSRAM", firmware)
        self.assertNotIn("currently offers qualified images", firmware)
        self.assertNotIn("| Available", firmware)

    def test_readme_caption_describes_only_the_visible_app(self) -> None:
        caption_start = self.readme.index("<em>Actual PyBLE app")
        caption_end = self.readme.index("</em>", caption_start)
        caption = self.readme[caption_start:caption_end]

        self.assertIn("in landscape", caption)
        self.assertIn("GPIO 48 NeoPixel Blocks", caption)
        self.assertIn("generated MicroPython", caption)
        self.assertNotRegex(caption, r"(?i)pictured|board|module")

    def test_readme_try_steps_are_gated_on_an_active_installer(self) -> None:
        try_section = markdown_section(self.readme, "Try PyBLE")

        self.assertIn("currently unavailable pending v0.4.2 HIL", try_section)
        self.assertIn("active release version", try_section)
        self.assertIn("enabled install action", try_section)
        self.assertNotRegex(try_section, r"(?is)select .*qualified\s+agent firmware")

    def test_bug_template_collects_the_exact_installer_diagnostics(self) -> None:
        for field_id in (
            "profile",
            "module",
            "memory",
            "browser",
            "operating_system",
            "installer_stage",
            "tablet",
            "tablet_os",
        ):
            self.assertIn(f"    id: {field_id}\n", self.bug_template)

        for wording in (
            "Exact installer profile ID",
            "Exact board model and module marking",
            "Flash capacity, PSRAM capacity, and PSRAM type",
            "Browser name and exact version",
            "Desktop operating system and exact version",
            "Failed installer stage",
            "Exact tablet or device model",
            "Tablet operating system and exact version",
        ):
            self.assertIn(wording, self.bug_template)

        self.assertRegex(self.bug_template, r"(?i)remove.*(?:secret|credential)")


if __name__ == "__main__":
    unittest.main()
