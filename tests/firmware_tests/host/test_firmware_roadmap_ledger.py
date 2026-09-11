#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Currentness guard for the firmware roadmap and retired G1 ledgers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFORMANCE = REPO_ROOT / "tests" / "firmware_tests" / "host" / "conformance"
GATES = REPO_ROOT / "tests" / "firmware_tests" / "gates"

ARCHIVED_LEDGERS = {
    "s3_pending.json":
        "7d9f9089c390a5f02a8b14ef8cc8fad77189a2270ab7a2132fbcbceed5b4327a",
    "s4_pending.json":
        "89f3f6f6e57172041715317cfa7f6cb0ca07c24ed0ac212632ef64a305a60b43",
    "s5_pending.json":
        "05e7b01e404155d332fb91c217d33214a92bb70aa1b3c3d0a3943cdc6cbbf737",
    "s6_pending.json":
        "96c51e3dbd0c591fdc2b3b148770ec9b1845f65e2ca22d09132035c8fad6a212",
}


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class FirmwareRoadmapLedgerTests(unittest.TestCase):
    def test_public_roadmap_distinguishes_v061_publication_and_v060_history(self):
        roadmap = _text("docs/ROADMAP.md")
        normalized = " ".join(roadmap.split())
        self.assertIn("published firmware v0.6.1", normalized)
        self.assertIn("owner confirmation", normalized)
        self.assertIn("Incomplete automated evidence is preserved unchanged", normalized)
        self.assertIn("qualified v0.6.0 release remains a separate historical baseline", normalized)
        self.assertNotIn("current qualified firmware v0.6.0", normalized)
        self.assertNotIn("exact v0.4.2 bytes", roadmap)
        self.assertNotIn("before enabling the ESP32-C3 installer", roadmap)

    def test_detailed_roadmap_records_only_approved_split_checkbox(self):
        roadmap = _text(
            "docs/planning/firmware-v0.6.1-v0.7.0-roadmap.md")
        checked = re.findall(r"^- \[x\] (.+)$", roadmap, re.MULTILINE)
        self.assertEqual(
            ["the v0.6.1 hardening / v0.7.0 feature-release split;"],
            checked,
        )
        self.assertIn("Resolved for v0.6.1", roadmap)
        self.assertIn("official images standardize on LFS2", roadmap)

    def test_normative_contract_preserves_future_persistent_mode(self):
        protocol = _text("docs/specifications/protocol.md")
        specs = _text("docs/specifications/firmware/specs.md")
        trace = re.compile(
            r"fresh globals.*future.*persistent.*interactive|"
            r"persistent.*interactive.*fresh globals",
            re.IGNORECASE | re.DOTALL,
        )
        for document in (protocol, specs):
            self.assertRegex(document, trace)

    def test_lfs2_standardization_has_an_indexed_adr(self):
        index = _text("docs/decisions/README.md")
        self.assertRegex(index, r"\[0047\].*LFS2")
        adr = (
            REPO_ROOT / "docs" / "decisions" /
            "0047-standardize-official-workspaces-on-lfs2.md"
        )
        self.assertTrue(adr.is_file())
        body = adr.read_text(encoding="utf-8")
        self.assertIn("Status: **Accepted**", body)
        self.assertIn("all five", body)
        self.assertIn("explicit operator action", body)

    def test_pre_freeze_ledgers_are_archived_byte_for_byte(self):
        archive = CONFORMANCE / "archive" / "pre-freeze"
        if not (archive / "README.md").is_file():
            self.fail("pre-freeze ledger archive README is missing")
        for name, expected_sha256 in ARCHIVED_LEDGERS.items():
            self.assertFalse((CONFORMANCE / name).exists(), name)
            payload = (archive / name).read_bytes()
            self.assertEqual(expected_sha256, hashlib.sha256(payload).hexdigest())

    def test_active_corpus_and_g1_docs_do_not_claim_frozen_wire_is_draft(self):
        corpus = (CONFORMANCE / "corpus.json").read_text(encoding="utf-8")
        readme = _text("tests/firmware_tests/README.md")
        current_path = CONFORMANCE / "README.md"
        if not current_path.is_file():
            self.fail("current conformance ledger README is missing")
        current = current_path.read_text(encoding="utf-8")
        active = "\n".join((corpus, readme, current))
        self.assertNotIn("still DRAFT", active)
        self.assertNotIn("DoR-BLOCKED", active)
        for name in ARCHIVED_LEDGERS:
            self.assertNotIn(f"conformance/{name}", active)

        for sprint in (3, 4, 5, 6):
            gate = (GATES / f"g1_s{sprint}_check.sh").read_text(
                encoding="utf-8")
            self.assertNotIn("DEFERRED-DOCS", gate)
            self.assertNotIn(f"s{sprint}_pending.json", gate)
            self.assertIn("DEFERRED-HIL", gate)


if __name__ == "__main__":
    unittest.main()
