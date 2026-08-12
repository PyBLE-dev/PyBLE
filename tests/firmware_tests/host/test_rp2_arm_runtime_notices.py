#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for exact contribution-scoped Arm GNU RP2 notices."""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs/specifications/firmware.md"
ATTRIBUTION = (
    ROOT
    / "firmware/licenses/evidence/rp2/arm-gnu-toolchain/14.2.rel1"
    / "runtime-attribution-v1.json"
)
NOTICE_EVIDENCE = ATTRIBUTION.with_name("runtime-notices-v1.json")
PUBLIC_NOTICE = (
    ROOT
    / "firmware/licenses/notices/rp2/"
    "arm-gnu-toolchain-14.2.rel1-selected-runtime.txt"
)
RELEASE_BUNDLE = ROOT / "firmware/scripts/release_bundle.py"

ATTRIBUTION_SHA256 = (
    "69d9dc56335dc27ddb9d9adde7775c339afe1259ecb2a3a0bcd48db83ff2ef9a"
)
SOURCE_ARCHIVE_SHA256 = (
    "e6405f20f8a817a50d92dbf7974d0ee77708dfdf9e79900a59c5d343b464ef9c"
)
NOTICE_EVIDENCE_SHA256 = (
    "66fb08b53797ece8dd29700a16f8efa2ec90b8fde97d4aea3124381112b991ea"
)
PUBLIC_NOTICE_SHA256 = (
    "6c88b3ed73bac10b85416aebfba654e7a9fb59a43c73cefc5e657f806d765316"
)
SELECTED_SOURCES_SHA256 = (
    "70006b1b7bcf19f1ca569fdeed1803e7ca066c295a8e6537f7c7660c46b79312"
)

SOURCE_SCHEMA = [
    "owner_id",
    "source_path",
    "source_sha256",
    "selection_reasons",
    "notice_block_indices",
]
BLOCK_SCHEMA = [
    "sha256",
    "base64",
    "first_owner_id",
    "first_source_path",
    "source_block_ordinal",
]
REASONS = {
    "allocated-archive-member",
    "compiler-dependency-header",
    "contributing-direct-input",
    "generated-header-template",
}
OWNERS = {"arm-gnu-gcc-runtime", "arm-gnu-newlib-runtime"}
NOTICE_ASSETS_EXIST = NOTICE_EVIDENCE.is_file() and PUBLIC_NOTICE.is_file()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def selected_source_rows(attribution: dict) -> list[list[object]]:
    selected: dict[tuple[str, str], tuple[str, set[str]]] = {}

    def add(owner: str, path: str, digest: str, reason: str) -> None:
        if owner not in OWNERS:
            return
        prior_digest, reasons = selected.setdefault(
            (owner, path), (digest, set())
        )
        if prior_digest != digest:
            raise AssertionError("one source path has conflicting digests")
        reasons.add(reason)

    for row in attribution["headers"]:
        add(row[0], row[3], row[2], "compiler-dependency-header")
    for row in attribution["generated_headers"]:
        for path, digest in row[3]:
            if not path.endswith(("configure", "Makefile.am", "Makefile.in")):
                add(row[0], path, digest, "generated-header-template")
    for row in attribution["archive_members"]:
        add(row[0], row[4], row[5], "allocated-archive-member")
    for row in attribution["direct_inputs"]:
        if row[3]:
            add(row[0], row[4], row[5], "contributing-direct-input")
    return [
        [owner, path, digest, sorted(reasons)]
        for (owner, path), (digest, reasons) in sorted(selected.items())
    ]


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "release_bundle_arm_notices_red", RELEASE_BUNDLE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


class RP2ArmRuntimeNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.attribution_raw = ATTRIBUTION.read_bytes()
        cls.attribution = json.loads(cls.attribution_raw)
        cls.selected_sources = selected_source_rows(cls.attribution)
        if NOTICE_ASSETS_EXIST:
            cls.evidence_raw = NOTICE_EVIDENCE.read_bytes()
            cls.evidence = json.loads(cls.evidence_raw)
            cls.notice_raw = PUBLIC_NOTICE.read_bytes()

    def test_spec_freezes_exact_contribution_only_notice_rules(self) -> None:
        value = SPEC.read_text(encoding="utf-8")
        for required in (
            "giving exactly 96 unique",
            "complete source comment block",
            "original comment delimiters",
            "blocks are emitted once",
            "46 block occurrences",
            "41 unique blocks",
            "notice-silent sources",
            "LOAD-only archives",
            "noncontributing direct inputs",
        ):
            with self.subTest(required=required):
                self.assertIn(required, value)

    def test_notice_assets_exist_as_regular_nonsymlink_files(self) -> None:
        for path in (NOTICE_EVIDENCE, PUBLIC_NOTICE):
            with self.subTest(path=path):
                self.assertTrue(
                    path.is_file() and not path.is_symlink(),
                    "missing reviewed RP2 Arm GNU runtime notice asset: %s"
                    % path.relative_to(ROOT),
                )

    @unittest.skipUnless(NOTICE_ASSETS_EXIST, "RED notice assets are pending")
    def test_notice_evidence_is_exact_canonical_and_hash_bound(self) -> None:
        self.assertEqual(sha256_bytes(self.attribution_raw), ATTRIBUTION_SHA256)
        self.assertEqual(self.evidence_raw, canonical_bytes(self.evidence))
        self.assertEqual(
            sha256_bytes(self.evidence_raw), NOTICE_EVIDENCE_SHA256
        )
        self.assertEqual(sha256_bytes(self.notice_raw), PUBLIC_NOTICE_SHA256)
        self.assertEqual(
            self.evidence["identity"],
            {
                "runtime_attribution": {
                    "path": (
                        "firmware/licenses/evidence/rp2/arm-gnu-toolchain/"
                        "14.2.rel1/runtime-attribution-v1.json"
                    ),
                    "sha256": ATTRIBUTION_SHA256,
                },
                "source_archive": {
                    "bytes": 311_500_280,
                    "filename": (
                        "arm-gnu-toolchain-src-snapshot-14.2.rel1.tar.xz"
                    ),
                    "sha256": SOURCE_ARCHIVE_SHA256,
                },
            },
        )
        self.assertEqual(
            self.evidence["public_notice"],
            {
                "bytes": 62_114,
                "path": (
                    "firmware/licenses/notices/rp2/"
                    "arm-gnu-toolchain-14.2.rel1-selected-runtime.txt"
                ),
                "sha256": PUBLIC_NOTICE_SHA256,
            },
        )

    def test_exact_96_sources_come_only_from_contributing_attribution(self) -> None:
        sources = self.selected_sources
        self.assertEqual(len(sources), 96)
        self.assertEqual(
            sha256_bytes(canonical_bytes(sources)), SELECTED_SOURCES_SHA256
        )
        self.assertEqual(
            Counter(row[0] for row in sources),
            Counter(
                {"arm-gnu-gcc-runtime": 23, "arm-gnu-newlib-runtime": 73}
            ),
        )
        for row in sources:
            self.assertEqual(len(row), len(SOURCE_SCHEMA) - 1)
            _owner, _path, digest, reasons = row
            self.assertEqual(reasons, sorted(reasons))
            self.assertTrue(set(reasons) <= REASONS)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        selected_paths = {row[1] for row in sources}
        self.assertNotIn("newlib-cygwin/libgloss/arm/crt0.S", selected_paths)
        self.assertNotIn("gcc/libgcc/config/arm/crtn.S", selected_paths)
        self.assertNotIn("newlib-cygwin/newlib/configure", selected_paths)
        self.assertNotIn("gcc/libstdc++-v3/include/Makefile.am", selected_paths)

        if NOTICE_ASSETS_EXIST:
            self.assertEqual(
                [row[:4] for row in self.evidence["sources"]], sources
            )

    @unittest.skipUnless(NOTICE_ASSETS_EXIST, "RED notice assets are pending")
    def test_blocks_are_exact_ordered_bytes_with_canonical_deduplication(
        self,
    ) -> None:
        self.assertEqual(
            self.evidence["record_schemas"],
            {"source": SOURCE_SCHEMA, "notice_block": BLOCK_SCHEMA},
        )
        blocks = self.evidence["notice_blocks"]
        self.assertEqual(len(blocks), 41)
        self.assertEqual(
            sum(len(row[4]) for row in self.evidence["sources"]), 46
        )
        self.assertEqual(
            sum(not row[4] for row in self.evidence["sources"]), 50
        )
        digests = []
        first_uses: dict[int, tuple[str, str]] = {}
        for owner, path, _digest, _reasons, indices in self.evidence["sources"]:
            for index in indices:
                first_uses.setdefault(index, (owner, path))
        for index, row in enumerate(blocks):
            self.assertEqual(len(row), len(BLOCK_SCHEMA))
            digest, encoded, owner, path, ordinal = row
            raw = base64.b64decode(encoded, validate=True)
            self.assertEqual(sha256_bytes(raw), digest)
            self.assertIn(b"copyright", raw.lower())
            self.assertEqual((owner, path), first_uses[index])
            self.assertIsInstance(ordinal, int)
            self.assertGreaterEqual(ordinal, 0)
            digests.append(digest)
        self.assertEqual(len(digests), len(set(digests)))

    @unittest.skipUnless(NOTICE_ASSETS_EXIST, "RED notice assets are pending")
    def test_public_notice_replays_every_unique_block_byte_for_byte(self) -> None:
        cursor = 0
        for digest, encoded, owner, path, ordinal in self.evidence[
            "notice_blocks"
        ]:
            raw = base64.b64decode(encoded, validate=True)
            marker = (
                "Owner: %s\nSource: %s\nSource block: %d\nBlock SHA-256: %s\n"
                % (owner, path, ordinal, digest)
            ).encode("ascii")
            marker_index = self.notice_raw.find(marker, cursor)
            self.assertGreaterEqual(marker_index, cursor)
            block_index = self.notice_raw.find(raw, marker_index + len(marker))
            self.assertGreaterEqual(block_index, marker_index + len(marker))
            self.assertEqual(self.notice_raw.count(raw), 1)
            cursor = block_index + len(raw)
        self.assertIn(ATTRIBUTION_SHA256.encode("ascii"), self.notice_raw)
        self.assertIn(SOURCE_ARCHIVE_SHA256.encode("ascii"), self.notice_raw)

    def test_release_validator_requires_the_exact_notice_evidence(self) -> None:
        validator = getattr(
            RELEASE, "_audit_validate_rp2_arm_runtime_notices", None
        )
        self.assertTrue(
            callable(validator),
            "missing fail-closed RP2 Arm GNU runtime notice validator",
        )
        self.assertTrue(
            NOTICE_ASSETS_EXIST,
            "RP2 Arm GNU runtime notice validator lacks its reviewed assets",
        )
        result = validator(
            self.attribution,
            self.evidence,
            repo_root=ROOT,
        )
        self.assertEqual(result["public_notice_path"], PUBLIC_NOTICE)
        self.assertEqual(result["public_notice_sha256"], PUBLIC_NOTICE_SHA256)
        self.assertEqual(set(result["public_notice_owner_ids"]), OWNERS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
