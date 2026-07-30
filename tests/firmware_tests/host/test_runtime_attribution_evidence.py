#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Exact GCC/newlib linked-runtime attribution evidence.

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = (
    REPO_ROOT
    / "firmware"
    / "licenses"
    / "evidence"
    / "toolchain-runtime-attribution-v1.json"
)
NOTICE = (
    REPO_ROOT
    / "firmware"
    / "licenses"
    / "evidence"
    / "toolchain-runtime-copyrights.txt"
)

GCC_COMMIT = "673953b409379e2250f831307ba79579535b1b85"
NEWLIB_COMMIT = "9a0d39153510ec5cbb51eb8c70cecbfeffdbb6ba"
EXPECTED_EVIDENCE_SHA256 = (
    "d900c139bc26f30e53d81700b016c92ea303cc089fb1d9d1c67684c4731c8b7e"
)
EXPECTED_NOTICE_SHA256 = (
    "067dc06b4bbf565170014475d27bca8864a705b2fed63fdd012ef19a1ec57865"
)

SOURCE_SCHEMA = [
    "component",
    "path",
    "sha256",
    "copyright_basis",
    "copyright_records",
    "occurrence_count",
]
ARCHIVE_SCHEMA = ["toolchain_family", "path", "sha256"]
BINDING_SCHEMA = [
    "archive_index",
    "member",
    "object_sha256",
    "source_index",
]
COVERAGE_SCHEMA = [
    "profile_id",
    "role",
    "map_path",
    "map_sha256",
    "binding_indices",
    "occurrence_manifest_sha256",
]


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


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


class RuntimeAttributionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = EVIDENCE.read_bytes()
        cls.evidence = json.loads(cls.raw)

    def test_file_is_exact_canonical_json(self):
        self.assertEqual(self.raw, canonical_bytes(self.evidence))
        self.assertEqual(sha256_bytes(self.raw), EXPECTED_EVIDENCE_SHA256)

    def test_schema_and_immutable_sources_are_exact(self):
        self.assertEqual(
            set(self.evidence),
            {
                "schema_version",
                "canonicalization",
                "record_schemas",
                "components",
                "copyright_notices",
                "sources",
                "archives",
                "bindings",
                "coverage",
                "summary",
            },
        )
        self.assertEqual(self.evidence["schema_version"], 1)
        self.assertEqual(
            self.evidence["canonicalization"],
            "UTF-8 JSON; sorted keys; compact separators; LF terminator",
        )
        self.assertEqual(
            self.evidence["record_schemas"],
            {
                "source": SOURCE_SCHEMA,
                "archive": ARCHIVE_SCHEMA,
                "binding": BINDING_SCHEMA,
                "coverage": COVERAGE_SCHEMA,
            },
        )
        self.assertEqual(
            self.evidence["components"],
            [
                {
                    "id": "gcc",
                    "source_commit": GCC_COMMIT,
                    "source_url_prefix": (
                        "https://raw.githubusercontent.com/espressif/gcc/"
                        + GCC_COMMIT
                        + "/"
                    ),
                    "license_evidence": [
                        {
                            "path": (
                                "firmware/licenses/texts/"
                                "GCC-exception-3.1.txt"
                            ),
                            "sha256": (
                                "9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b"
                                "75178153e3af6a815bdc90f74"
                            ),
                        },
                        {
                            "path": (
                                "firmware/licenses/texts/"
                                "GPL-3.0-or-later.txt"
                            ),
                            "sha256": (
                                "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b"
                                "165a1dcd80c7c545eb65b903"
                            ),
                        },
                    ],
                },
                {
                    "id": "newlib",
                    "source_commit": NEWLIB_COMMIT,
                    "source_url_prefix": (
                        "https://raw.githubusercontent.com/espressif/"
                        "newlib-esp32/"
                        + NEWLIB_COMMIT
                        + "/"
                    ),
                    "license_evidence": [
                        {
                            "path": (
                                "firmware/licenses/texts/"
                                "COPYING.NEWLIB.toolchain.txt"
                            ),
                            "sha256": (
                                "422aa40293093fb54fc66e692a0d68fd0b24ed560"
                                "2e5d1d33ad05ba3909057e9"
                            ),
                        }
                    ],
                },
            ],
        )
        for component in self.evidence["components"]:
            for record in component["license_evidence"]:
                path = REPO_ROOT / record["path"]
                self.assertTrue(path.is_file() and not path.is_symlink())
                self.assertEqual(
                    sha256_bytes(path.read_bytes()),
                    record["sha256"],
                )

    def test_every_source_has_hash_bound_attribution(self):
        notices = self.evidence["copyright_notices"]
        self.assertEqual(len(notices), 40)
        self.assertEqual(len(notices), len(set(notices)))
        self.assertTrue(all(isinstance(item, str) and item for item in notices))

        sources = self.evidence["sources"]
        self.assertEqual(len(sources), 246)
        self.assertEqual(
            Counter(source[0] for source in sources),
            Counter({"gcc": 55, "newlib": 191}),
        )
        identities = set()
        for source in sources:
            self.assertEqual(len(source), len(SOURCE_SCHEMA))
            component, path, digest, basis, records, occurrence_count = source
            self.assertIn(component, {"gcc", "newlib"})
            self.assertIsInstance(path, str)
            self.assertNotIn("..", Path(path).parts)
            self.assertFalse(path.startswith("/"))
            self.assertTrue(is_sha256(digest))
            self.assertGreater(occurrence_count, 0)
            self.assertNotIn((component, path), identities)
            identities.add((component, path))
            self.assertIn(
                basis,
                {"source-header", "newlib-default-compilation"},
            )
            self.assertEqual(
                basis == "newlib-default-compilation",
                component == "newlib" and records == [],
            )
            if basis == "source-header":
                self.assertTrue(records)
            for record in records:
                self.assertEqual(len(record), 2)
                line, notice_index = record
                self.assertIsInstance(line, int)
                self.assertGreater(line, 0)
                self.assertIsInstance(notice_index, int)
                self.assertGreaterEqual(notice_index, 0)
                self.assertLess(notice_index, len(notices))

    def test_public_notice_is_exactly_derived_without_source_bodies(self):
        expected_lines = [
            "PyBLE linked GCC/newlib runtime copyright notices",
            "",
            (
                "Scope: runtime object code proven linked by the six "
                "hash-bound profile/role maps."
            ),
            "GCC source commit: " + GCC_COMMIT,
            "newlib source commit: " + NEWLIB_COMMIT,
            "",
            "Exact deduplicated source-header statements:",
            "",
            *self.evidence["copyright_notices"],
            "",
            (
                "Header-silent newlib sources are governed by the complete "
                "hash-bound"
            ),
            (
                "firmware/licenses/texts/COPYING.NEWLIB.toolchain.txt "
                "compilation."
            ),
            "",
        ]
        expected = "\n".join(expected_lines).encode("utf-8")
        actual = NOTICE.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(sha256_bytes(actual), EXPECTED_NOTICE_SHA256)
        self.assertNotIn(b"source body", actual.lower())

    def test_all_720_occurrences_resolve_to_all_699_bindings(self):
        archives = self.evidence["archives"]
        bindings = self.evidence["bindings"]
        sources = self.evidence["sources"]
        coverage = self.evidence["coverage"]
        self.assertEqual(len(archives), 15)
        self.assertEqual(len(bindings), 699)
        self.assertEqual(len(coverage), 6)

        archive_identities = set()
        for archive in archives:
            self.assertEqual(len(archive), len(ARCHIVE_SCHEMA))
            family, path, digest = archive
            self.assertIn(family, {"riscv32-esp-elf", "xtensa-esp-elf"})
            self.assertIsInstance(path, str)
            self.assertFalse(path.startswith("/"))
            self.assertTrue(is_sha256(digest))
            self.assertNotIn((family, path), archive_identities)
            archive_identities.add((family, path))

        binding_identities = set()
        for binding in bindings:
            self.assertEqual(len(binding), len(BINDING_SCHEMA))
            archive_index, member, object_sha256, source_index = binding
            self.assertIn(archive_index, range(len(archives)))
            self.assertIsInstance(member, str)
            self.assertTrue(member.endswith(".o"))
            self.assertTrue(is_sha256(object_sha256))
            self.assertIn(source_index, range(len(sources)))
            identity = (archive_index, member)
            self.assertNotIn(identity, binding_identities)
            binding_identities.add(identity)

        used_bindings: list[int] = []
        expected_roles = {
            ("esp32-4mb", "application"): 217,
            ("esp32-4mb", "bootloader"): 23,
            ("esp32-c3-4mb", "application"): 244,
            ("esp32-c3-4mb", "bootloader"): 9,
            ("esp32-s3-n16r8", "application"): 216,
            ("esp32-s3-n16r8", "bootloader"): 11,
        }
        observed_roles = {}
        for record in coverage:
            self.assertEqual(len(record), len(COVERAGE_SCHEMA))
            profile, role, map_path, map_sha256, indices, manifest = record
            identity = (profile, role)
            self.assertNotIn(identity, observed_roles)
            observed_roles[identity] = len(indices)
            self.assertTrue(map_path.startswith("firmware/build/"))
            self.assertTrue(is_sha256(map_sha256))
            self.assertTrue(is_sha256(manifest))
            self.assertEqual(len(indices), len(set(indices)))
            self.assertTrue(all(index in range(len(bindings)) for index in indices))
            expanded = [
                {
                    "profile_id": profile,
                    "role": role,
                    "map_path": map_path,
                    "map_sha256": map_sha256,
                    "archive": archives[bindings[index][0]],
                    "binding": bindings[index],
                    "source": sources[bindings[index][3]],
                }
                for index in indices
            ]
            self.assertEqual(
                sha256_bytes(canonical_bytes(expanded)),
                manifest,
            )
            used_bindings.extend(indices)
        self.assertEqual(observed_roles, expected_roles)
        self.assertEqual(len(used_bindings), 720)
        self.assertEqual(set(used_bindings), set(range(699)))

        source_occurrences = Counter(
            bindings[index][3] for index in used_bindings
        )
        self.assertEqual(set(source_occurrences), set(range(246)))
        self.assertEqual(
            [source_occurrences[index] for index in range(246)],
            [source[5] for source in sources],
        )

        self.assertEqual(
            self.evidence["summary"],
            {
                "archive_count": 15,
                "binding_count": 699,
                "covered_occurrence_count": 720,
                "profile_role_count": 6,
                "source_count": 246,
                "unresolved_occurrence_count": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
