# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import json
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
        cls.roadmap = (REPO_ROOT / "docs" / "ROADMAP.md").read_text(
            encoding="utf-8"
        )
        cls.home_page = (
            REPO_ROOT / "tools" / "web" / "src" / "app" / "page.tsx"
        ).read_text(encoding="utf-8")
        cls.site_copy = (
            REPO_ROOT / "tools" / "web" / "src" / "lib" / "site.ts"
        ).read_text(encoding="utf-8")
        cls.support_page = (
            REPO_ROOT
            / "tools"
            / "web"
            / "src"
            / "app"
            / "support"
            / "page.tsx"
        ).read_text(encoding="utf-8")
        cls.browser_validation = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "validation"
                / "browser-flashing"
                / "v0.4.2-production.json"
            ).read_text(encoding="utf-8")
        )

    def test_readme_identifies_the_exact_hardware_tested_public_beta(self) -> None:
        firmware = markdown_section(self.readme, "What works")

        self.assertIn(
            "public browser installer currently offers the exact v0.4.2 hardware-tested beta",
            firmware,
        )
        self.assertIn("Production Chrome erase/install", firmware)
        self.assertIn("interrupted-flash recovery passed", firmware)
        self.assertIn("Complete release qualification continues", firmware)
        self.assertIn("`esp32-4mb`", firmware)
        self.assertIn("Classic ESP32, 4 MiB external SPI flash", firmware)
        self.assertIn("`esp32-s3-n16r8`", firmware)
        self.assertIn("16 MiB flash / 8 MiB Octal PSRAM", firmware)
        self.assertIn(
            "v0.4.2 hardware-tested beta; browser install/recovery passed",
            firmware,
        )
        self.assertIn("Planned; unavailable", firmware)
        self.assertNotIn("currently offers qualified images", firmware)
        self.assertNotIn("full HIL pending", firmware)

    def test_readme_caption_describes_only_the_visible_app(self) -> None:
        caption_start = self.readme.index("<em>Actual PyBLE app")
        caption_end = self.readme.index("</em>", caption_start)
        caption = self.readme[caption_start:caption_end]

        self.assertIn("in landscape", caption)
        self.assertIn("GPIO 48 NeoPixel Blocks", caption)
        self.assertIn("generated MicroPython", caption)
        self.assertNotRegex(caption, r"(?i)pictured|board|module")

    def test_readme_try_steps_use_the_hardware_tested_beta_safely(self) -> None:
        try_section = markdown_section(self.readme, "Try PyBLE")

        self.assertIn("v0.4.2 hardware-tested beta", try_section)
        self.assertIn("Browser installation and interrupted-flash recovery passed", try_section)
        self.assertIn("complete release qualification continues", try_section)
        self.assertNotIn("full HIL pending", try_section)
        self.assertNotIn("use it at your own risk", try_section)
        self.assertIn("exact profile", try_section)
        self.assertIn("back up", try_section)
        self.assertIn("enabled install action", try_section)
        self.assertIn("Flashing erases the board", try_section)
        self.assertNotIn("wait for that page", try_section.lower())

    def test_current_public_surfaces_agree_on_beta_and_c3_state(self) -> None:
        combined = "\n".join(
            (self.home_page, self.site_copy, self.support_page, self.roadmap)
        )

        for wording in (
            "v0.4.2",
            "hardware-tested beta",
            "browser install/recovery passed",
            "release qualification pending",
            "esp32-4mb",
            "esp32-s3-n16r8",
        ):
            self.assertIn(wording, combined)
        self.assertIn("Production Chrome install", combined)
        self.assertIn("interrupted-flash recovery passed", combined)
        self.assertNotIn("full HIL pending", combined)
        self.assertNotIn("use it at your own risk", combined.lower())
        self.assertIn("ESP32-C3", combined)
        self.assertRegex(combined, r"(?is)ESP32-C3.{0,180}unavailable")
        for stale in (
            "public browser installer stays unavailable",
            "public installer is unavailable while v0.4.2 HIL runs",
            "board provisioning will open only after v0.4.2",
            "Browser installation for qualified `esp32-4mb`",
        ):
            self.assertNotIn(stale, combined)

        near_term = markdown_section(self.roadmap, "Near term")
        self.assertIn(
            "Complete the app, PBLE/1, resource, and remaining firmware release",
            near_term,
        )

    def test_production_browser_claim_is_bound_to_public_evidence(self) -> None:
        evidence = self.browser_validation

        self.assertEqual(evidence["result"], "passed")
        self.assertEqual(evidence["release"]["version"], "0.4.2")
        self.assertEqual(
            evidence["release"]["release_json_sha256"],
            "5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde",
        )
        self.assertEqual(
            [profile["profile_id"] for profile in evidence["profiles"]],
            ["esp32-4mb", "esp32-s3-n16r8"],
        )
        for profile in evidence["profiles"]:
            self.assertGreater(profile["interruption_percentage"], 5)
            self.assertLess(profile["interruption_percentage"], 100)
            self.assertEqual(profile["recovery_write_percentage"], 100)
            self.assertTrue(profile["full_erase"])
            self.assertTrue(profile["hard_reset"])
            self.assertTrue(profile["visible_completion"])
            self.assertTrue(profile["serial_route_released"])
            self.assertEqual(profile["interruption_fetch_rounds"]["firmware"], 2)
            self.assertEqual(profile["recovery_fetch_rounds"]["firmware"], 2)
        self.assertTrue(
            any("not the formal" in limitation for limitation in evidence["limitations"])
        )

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
