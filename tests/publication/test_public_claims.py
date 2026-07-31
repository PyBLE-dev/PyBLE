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
        cls.firmware_overview = (
            REPO_ROOT / "docs" / "specifications" / "firmware.md"
        ).read_text(encoding="utf-8")
        cls.hardware_overview = (
            REPO_ROOT / "docs" / "specifications" / "hardware.md"
        ).read_text(encoding="utf-8")
        cls.product_requirements = (
            REPO_ROOT / "docs" / "specifications" / "prd.md"
        ).read_text(encoding="utf-8")
        cls.website_readme = (
            REPO_ROOT / "tools" / "web" / "README.md"
        ).read_text(encoding="utf-8")
        cls.website_specification = (
            REPO_ROOT / "docs" / "specifications" / "website.md"
        ).read_text(encoding="utf-8")
        cls.firmware_requirements = (
            REPO_ROOT / "docs" / "specifications" / "firmware" / "specs.md"
        ).read_text(encoding="utf-8")
        cls.browser_flashing = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "firmware"
            / "browser-flashing.md"
        ).read_text(encoding="utf-8")
        cls.flash_page = (
            REPO_ROOT / "tools" / "web" / "src" / "app" / "flash" / "page.tsx"
        ).read_text(encoding="utf-8")
        cls.flash_status = (
            REPO_ROOT
            / "tools"
            / "web"
            / "src"
            / "components"
            / "flash-status.tsx"
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

    def test_firmware_and_hardware_overviews_are_preactivation_truthful(self) -> None:
        self.assertIn(
            "v0.4.2 candidate set is `esp32-4mb`",
            self.firmware_overview,
        )
        self.assertIn(
            "public browser installer remains unavailable pending final HIL",
            self.firmware_overview,
        )
        self.assertNotIn(
            "current pre-v1 release qualifies",
            self.firmware_overview,
        )
        self.assertIn(
            "| `esp32-4mb` | Classic ESP32; 4 MiB external SPI flash; "
            "no PSRAM assumed | `ESP32` | v0.4.2 HIL pending; installer "
            "unavailable |",
            self.hardware_overview,
        )
        self.assertIn(
            "| `esp32-s3-n16r8` | ESP32-S3; 16 MiB flash; 8 MiB Octal PSRAM "
            "| `ESP32-S3` | v0.4.2 HIL pending; installer unavailable |",
            self.hardware_overview,
        )
        self.assertNotIn(
            "| Current pre-v1 release |",
            self.hardware_overview,
        )

    def test_public_summaries_distinguish_build_targets_from_release_support(
        self,
    ) -> None:
        self.assertIn(
            "initial ESP-IDF build/reference targets",
            self.website_readme,
        )
        self.assertIn(
            "public installer remains unavailable pending v0.4.2 HIL",
            self.website_readme,
        )
        self.assertNotIn(
            "initial validated ESP32 / ESP32-S3 / ESP32-C3 firmware targets",
            self.website_readme,
        )
        board_scope_start = self.product_requirements.index(
            "- **Board scope**",
        )
        board_scope_end = self.product_requirements.index(
            "\n\n**Pending",
            board_scope_start,
        )
        board_scope = self.product_requirements[
            board_scope_start:board_scope_end
        ]
        self.assertIn("initial build/reference targets", board_scope)
        self.assertIn(
            "release compatibility remains exact-profile and HIL-gated",
            board_scope,
        )
        self.assertNotIn("initial validated firmware targets", board_scope)

    def test_preactivation_profiles_are_candidates_not_current_releases(
        self,
    ) -> None:
        self.assertIn(
            "v0.4.2 candidate qualification scope is profile-scoped",
            self.firmware_overview,
        )
        self.assertIn(
            "current v0.4.2 candidate set is the exact `esp32-4mb`",
            self.website_specification,
        )
        self.assertIn(
            "v0.4.2 release candidate targets exactly these two",
            self.browser_flashing,
        )
        self.assertIn(
            "current pre-v1 candidate set is exactly `esp32-4mb`",
            self.product_requirements,
        )
        self.assertIn(
            "current pre-v1 candidate qualification set is exactly",
            self.firmware_requirements,
        )

        prohibited_claims = (
            "current pre-v1 qualification is profile-scoped",
            "current pre-v1 release list is",
            "current pre-v1 public set is",
            "current pre-v1 release set is",
            "current pre-v1 public bundle contains exactly these two qualified",
            "current pre-v1 qualification set is exactly",
        )
        for claim in prohibited_claims:
            for document in (
                self.firmware_overview,
                self.website_specification,
                self.browser_flashing,
                self.product_requirements,
                self.firmware_requirements,
            ):
                self.assertNotIn(claim, document)

    def test_preactivation_installer_ui_does_not_call_candidates_qualified(
        self,
    ) -> None:
        self.assertIn(
            "candidate ESP32 and ESP32-S3 profiles",
            self.flash_page,
        )
        self.assertIn(
            "both exact current candidate profiles",
            self.flash_page,
        )
        self.assertIn(
            "both exact current candidate profiles",
            self.flash_status,
        )
        self.assertNotIn(
            "qualified ESP32 and ESP32-S3 profiles",
            self.flash_page,
        )
        self.assertNotIn(
            "both exact current release profiles",
            self.flash_page,
        )
        self.assertNotIn(
            "both exact current release profiles",
            self.flash_status,
        )


if __name__ == "__main__":
    unittest.main()
