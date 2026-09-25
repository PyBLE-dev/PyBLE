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

    def test_readme_identifies_the_owner_confirmed_v061_release(self) -> None:
        firmware = markdown_section(self.readme, "What works")
        normalized = " ".join(firmware.split())

        self.assertIn(
            "owner-confirmed public v0.6.1 release",
            normalized,
        )
        self.assertIn("all five exact release profiles", normalized)
        self.assertIn("four ESP profiles use Web Serial", normalized)
        self.assertIn("verified UF2", firmware)
        self.assertIn("BOOTSEL", firmware)
        self.assertIn("`esp32-4mb`", firmware)
        self.assertIn("`esp32-s3-n16r8`", firmware)
        self.assertIn("`waveshare-esp32-s3-lcd-147b`", firmware)
        self.assertIn("`esp32-c3-4mb`", firmware)
        self.assertIn("`rpi-pico2-w`", firmware)
        self.assertEqual(firmware.count("Owner-confirmed v0.6.1"), 5)
        self.assertIn("automated qualification records remain incomplete", normalized)
        self.assertIn("LFS2", firmware)
        self.assertIn("fresh globals", normalized)
        self.assertNotIn("All five exact-byte HIL rows passed", firmware)
        self.assertNotIn("v0.4.2 hardware-tested beta", firmware)
        self.assertNotIn("Planned; unavailable", firmware)
        self.assertNotIn("in-progress `0.6.0`", firmware)

    def test_readme_caption_describes_only_the_visible_app(self) -> None:
        caption_start = self.readme.index("<em>Actual PyBLE app")
        caption_end = self.readme.index("</em>", caption_start)
        caption = self.readme[caption_start:caption_end]

        self.assertIn("in landscape", caption)
        self.assertIn("GPIO 48 NeoPixel Blocks", caption)
        self.assertIn("generated MicroPython", caption)
        self.assertNotRegex(caption, r"(?i)pictured|board|module")

    def test_readme_try_steps_use_the_published_v061_release_safely(self) -> None:
        try_section = markdown_section(self.readme, "Try PyBLE")
        normalized = " ".join(try_section.split())

        self.assertIn("published v0.6.1 release", normalized)
        self.assertIn("four ESP profiles", normalized)
        self.assertIn("Web Serial", try_section)
        self.assertIn("Pico 2 W", try_section)
        self.assertIn("verified UF2", try_section)
        self.assertIn("BOOTSEL", try_section)
        self.assertIn("iPadOS cannot perform", normalized)
        self.assertNotIn("use it at your own risk", try_section)
        self.assertIn("exact profile", try_section)
        self.assertIn("back up", try_section)
        self.assertIn("Flashing erases the board", try_section)
        self.assertNotIn("v0.4.2 hardware-tested beta", try_section)
        self.assertIn("https://github.com/PyBLE-dev/examples", try_section)
        self.assertIn("branch chooser", normalized)
        self.assertIn("editable", normalized)
        self.assertIn("/examples", try_section)
        self.assertIn("pyble_hello_console.py", try_section)
        self.assertIn("https://pyble.dev/learn", self.readme)
        self.assertIn("https://pyble.dev/features", self.readme)
        self.assertNotIn("examples/github-import", try_section)

    def test_current_public_surfaces_agree_on_v061_publication(self) -> None:
        combined = "\n".join(
            (self.home_page, self.site_copy, self.support_page, self.roadmap)
        )

        for wording in (
            "v0.6.1",
            "owner-confirmed",
            "esp32-4mb",
            "esp32-s3-n16r8",
            "esp32-c3-4mb",
            "rpi-pico2-w",
        ):
            self.assertIn(wording, combined)
        self.assertNotIn("full HIL pending", combined)
        self.assertNotIn("use it at your own risk", combined.lower())
        for stale in (
            "public browser installer stays unavailable",
            "public installer is unavailable while v0.4.2 HIL runs",
            "board provisioning will open only after v0.4.2",
            "Browser installation for qualified `esp32-4mb`",
        ):
            self.assertNotIn(stale, combined)

        available = " ".join(
            markdown_section(self.roadmap, "Available now").split()
        )
        self.assertIn("published firmware v0.6.1", available)
        self.assertIn("owner confirmation", available)
        self.assertIn("five exact profiles", available)
        self.assertIn("Pico 2 W", available)
        self.assertNotIn("v0.4.2", self.roadmap)

        near_term = markdown_section(self.roadmap, "Near term")
        self.assertIn(
            "v0.7.0",
            near_term,
        )
        self.assertIn("automated qualification", near_term)

    def test_readme_distinguishes_app_source_from_store_availability(self) -> None:
        firmware = markdown_section(self.readme, "What works")
        normalized = " ".join(firmware.split())
        self.assertIn("0.2.0+8", firmware)
        self.assertIn("Google Play open testing", normalized)
        self.assertIn("published Android version is `0.2.0`", normalized)
        self.assertIn("exact source", normalized)
        self.assertIn("later connection-lifecycle fixes", normalized)
        self.assertIn(
            "https://play.google.com/store/apps/details?id=dev.pyble.pyble",
            self.readme,
        )
        self.assertNotRegex(self.readme, r"(?i)Android (?:invited|internal) test")
        self.assertIn("offline privacy policy", normalized)
        self.assertIn("multi-file deletion", normalized)

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
            "https://pyble.dev/firmware/v0.6.1/release.json",
            self.readme,
        )
        self.assertIn(
            "https://pyble.dev/firmware/v0.6.1/RELEASE_NOTES.md",
            self.readme,
        )
        self.assertIn(
            "https://pyble.dev/firmware/v0.6.1/SHA256SUMS",
            self.readme,
        )
        self.assertIn(
            "https://pyble.dev/firmware/v0.6.1/RECOVERY.md",
            self.readme,
        )
        self.assertIn(
            "https://github.com/PyBLE-dev/PyBLE/tree/c8f549eeabe6d2b8c2766eab022517944bb09c8c",
            self.readme,
        )
        self.assertIn(
            "71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd",
            self.readme,
        )
        self.assertIn(
            "https://pyble.dev/firmware-v0.6.1-owner-confirmation.md",
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

        v060 = markdown_section(
            self.changelog, "Firmware 0.6.0 — 2026-08-21"
        )
        for wording in (
            "qualified five-profile release",
            "`esp32-4mb`",
            "`esp32-s3-n16r8`",
            "`waveshare-esp32-s3-lcd-147b`",
            "`esp32-c3-4mb`",
            "`rpi-pico2-w`",
            "firmware-v0.6.0",
            "0c7230d6708797c241160ba71fbd37e6b22f180a",
            "MicroPython v1.28.0",
            "ESP-IDF v5.5.1",
            "four ESP profiles",
            "verified UF2",
            "BOOTSEL",
            "all five HIL rows passed",
            "https://pyble.dev/flash",
        ):
            self.assertIn(wording, v060)

        unreleased = markdown_section(self.changelog, "Unreleased")
        for stale in (
            "Abandoned the unpublished local `firmware-v0.6.0` candidate",
            "Pico remains absent from public release metadata",
            "all candidate/HIL gates restart",
        ):
            self.assertNotIn(stale, unreleased)

    def test_public_specifications_distinguish_beta_and_qualified_release(
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
            r"(?s)`esp32-4mb`.{0,240}Qualified in v0\.6\.0; current "
            r"v0\.6\.1 source requires fresh exact-byte qualification\."
            r".{0,240}`esp32-s3-n16r8`.{0,240}Qualified in v0\.6\.0; "
            r"current v0\.6\.1 source requires independent exact-byte "
            r"qualification\.",
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
