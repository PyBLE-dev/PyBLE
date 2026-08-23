# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class CitationMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.citation_path = REPO_ROOT / "CITATION.cff"
        cls.citation = (
            cls.citation_path.read_text(encoding="utf-8")
            if cls.citation_path.exists()
            else ""
        )
        cls.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        cls.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
        cls.contributor_guidelines = (REPO_ROOT / "AGENTS.md").read_text(
            encoding="utf-8"
        )

    def test_root_citation_file_identifies_the_project(self) -> None:
        self.assertTrue(self.citation_path.is_file())
        for field in (
            "cff-version: 1.2.0",
            'title: "PyBLE: Python over Bluetooth Low Energy"',
            "type: software",
            "license: MIT",
            'repository-code: "https://github.com/PyBLE-dev/PyBLE"',
            'url: "https://pyble.dev"',
        ):
            self.assertIn(field, self.citation)

    def test_citation_names_only_the_evidenced_author_identity(self) -> None:
        self.assertIn("family-names: Vchirawongkwin", self.citation)
        self.assertIn("given-names: Viwat", self.citation)
        self.assertNotRegex(self.citation, r"(?im)^\s*(orcid|affiliation):")

    def test_citation_describes_the_open_ble_first_software(self) -> None:
        normalized = " ".join(self.citation.split())
        for wording in (
            "tablet-first MicroPython integrated development environment",
            "Bluetooth Low Energy",
            "PBLE/1",
            "Flutter",
            "physical computing",
            "embedded systems",
        ):
            self.assertIn(wording, normalized)

    def test_release_identity_is_complete_for_the_project_snapshot(self) -> None:
        has_doi = re.search(r"(?m)^doi:\s*", self.citation) is not None
        has_version = re.search(r"(?m)^version:\s*", self.citation) is not None
        has_release_date = (
            re.search(r"(?m)^date-released:\s*", self.citation) is not None
        )
        self.assertTrue(has_doi)
        self.assertTrue(has_version)
        self.assertEqual(has_version, has_release_date)
        self.assertIn('version: "source-2026.08.23"', self.citation)
        self.assertIn('date-released: "2026-08-23"', self.citation)
        self.assertIn('doi: "10.5281/zenodo.22064468"', self.citation)
        self.assertNotIn("10.5281/zenodo.22064467", self.citation)

    def test_metadata_contains_no_placeholder_identifiers(self) -> None:
        self.assertNotRegex(
            self.citation,
            r"(?i)(todo|fixme|your[-_ ]?(doi|orcid)|0000-0000-0000-0000)",
        )

    def test_repository_contract_and_public_docs_expose_the_citation(self) -> None:
        governance_start = self.contributor_guidelines.index(
            "Root governance files are:"
        )
        governance_end = self.contributor_guidelines.index(
            "```", governance_start + len("Root governance files are:") + 4
        )
        governance_files = self.contributor_guidelines[
            governance_start:governance_end
        ]
        normalized_readme = " ".join(self.readme.split())
        self.assertIn("CITATION.cff", governance_files)
        self.assertIn("## Citation", self.readme)
        self.assertIn("[CITATION.cff](CITATION.cff)", self.readme)
        self.assertIn(
            "app and firmware are versioned independently", normalized_readme
        )
        self.assertIn("https://doi.org/10.5281/zenodo.22064468", self.readme)
        self.assertIn("https://doi.org/10.5281/zenodo.22064467", self.readme)
        self.assertIn(
            "https://zenodo.org/badge/DOI/10.5281/zenodo.22064467.svg",
            self.readme,
        )
        self.assertIn("CITATION.cff", self.changelog)
        self.assertIn("10.5281/zenodo.22064468", self.changelog)


if __name__ == "__main__":
    unittest.main()
