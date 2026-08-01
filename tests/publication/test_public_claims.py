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
        cls.browser_attestation = (
            REPO_ROOT
            / "docs"
            / "validation"
            / "browser-flashing"
            / "v0.4.2-production.md"
        ).read_text(encoding="utf-8")
        cls.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
        cls.flash_page = (
            REPO_ROOT / "tools" / "web" / "src" / "app" / "flash" / "page.tsx"
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
        cls.firmware_requirements = (
            REPO_ROOT / "docs" / "specifications" / "firmware" / "specs.md"
        ).read_text(encoding="utf-8")
        cls.firmware_tdd = (
            REPO_ROOT / "docs" / "specifications" / "firmware" / "TDD.md"
        ).read_text(encoding="utf-8")
        cls.website_readme = (
            REPO_ROOT / "tools" / "web" / "README.md"
        ).read_text(encoding="utf-8")

    def test_readme_identifies_the_exact_hardware_tested_public_beta(self) -> None:
        firmware = markdown_section(self.readme, "What works")
        normalized = " ".join(firmware.split())

        self.assertIn(
            "public browser installer currently offers the exact v0.4.2 hardware-tested beta",
            normalized,
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
        normalized = " ".join(try_section.split())

        self.assertIn("v0.4.2 hardware-tested beta", normalized)
        self.assertIn(
            "Browser installation and interrupted-flash recovery passed",
            normalized,
        )
        self.assertIn("complete release qualification continues", normalized)
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
        self.assertEqual(
            [profile["firmware_sha256"] for profile in evidence["profiles"]],
            [
                "3bd148df6163d21dd6ee86eecdff47820f3b20323e7cc39a3253937c60af1245",
                "7cb73313b7108d9ee7bcd34780ecc25f6fef1590dfeee49bb08c424e58f741ff",
            ],
        )
        self.assertTrue(
            any(
                "not the formal" in limitation
                for limitation in evidence["limitations"]
            )
        )

    def test_post_release_attestation_bounds_the_completed_hil_scope(self) -> None:
        attestation = self.browser_attestation

        for identity in (
            "firmware-v0.4.2",
            "ce02b68ab73da903035aa9f992c1f7e8eb2a3691",
            "5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde",
            "3bd148df6163d21dd6ee86eecdff47820f3b20323e7cc39a3253937c60af1245",
            "7cb73313b7108d9ee7bcd34780ecc25f6fef1590dfeee49bb08c424e58f741ff",
        ):
            self.assertIn(identity, attestation)

        for wording in (
            "Supplemental production-browser result: **passed**",
            "`esp32-4mb`",
            "`esp32-s3-n16r8`",
            "7%",
            "immutable pre-public qualification ledger",
            "supersedes only its pending browser-installation and interrupted-recovery rows",
            "does not change its other pending qualification rows",
            "not a qualified release",
            "ESP32-C3 was not tested and remains unavailable",
        ):
            self.assertIn(wording, attestation)

    def test_public_surfaces_link_the_release_evidence_and_changelog(self) -> None:
        self.assertIn(
            "(docs/validation/browser-flashing/v0.4.2-production.md)",
            self.readme,
        )
        self.assertIn(
            "https://github.com/PyBLE-dev/PyBLE/releases/tag/firmware-v0.4.2",
            self.flash_page,
        )
        self.assertIn("Release evidence and exact hashes", self.flash_page)

        release = markdown_section(self.changelog, "Firmware 0.4.2 — 2026-07-31")
        self.assertIn("hardware-tested beta", release)
        self.assertIn("`esp32-4mb`", release)
        self.assertIn("`esp32-s3-n16r8`", release)
        self.assertIn("interrupted-flash recovery", release)
        self.assertIn("complete release qualification remains pending", release)
        self.assertNotIn("qualified release", release)

    def test_public_specifications_describe_the_exact_beta_without_overclaim(
        self,
    ) -> None:
        combined = "\n".join(
            (
                self.firmware_overview,
                self.hardware_overview,
                self.product_requirements,
                self.firmware_requirements,
                self.firmware_tdd,
                self.website_readme,
            )
        )

        for wording in (
            "v0.4.2 hardware-tested beta",
            "browser installation and interrupted-flash recovery passed",
            "complete release qualification remains pending",
            "`esp32-4mb`",
            "`esp32-s3-n16r8`",
            "ESP32-C3",
            "unavailable",
        ):
            self.assertIn(wording, combined)

        for stale_claim in (
            "current pre-v1 release qualifies",
            "| Current pre-v1 release |",
            "the two qualified profiles",
            "installer without claiming that release artifacts are ready",
            "stages the future browser firmware installer",
            "before the current public installer can be enabled",
            "the first validated firmware family",
        ):
            self.assertNotIn(stale_claim, combined)

        self.assertRegex(
            self.hardware_overview,
            r"(?s)`esp32-4mb`.{0,240}hardware-tested beta.{0,200}"
            r"`esp32-s3-n16r8`.{0,240}hardware-tested beta",
        )
        self.assertIn(
            "The exact v0.4.2 public-beta bundle covers exactly the two enabled, "
            "not-yet-qualified profiles",
            self.firmware_requirements,
        )
        self.assertIn(
            "two hardware-tested beta profiles in v0.4.2",
            self.firmware_tdd,
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
