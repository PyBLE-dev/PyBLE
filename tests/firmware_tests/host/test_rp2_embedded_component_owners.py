#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Exact owner contract for RP2 depfile-only embedded components."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "firmware/licenses/rp2-license-policy.json"
MICROPYTHON = ROOT / "firmware/upstream/micropython"
MICROPYTHON_REF = "e0e9fbb17ed6fd06bb76e266ae554784c9c80804"
MICROPYTHON_URL = "https://github.com/micropython/micropython"

FDLIBM_HEADER = "lib/libm/fdlibm.h"
RE15_PATHS = {
    "lib/re1.5/charclass.c",
    "lib/re1.5/compilecode.c",
    "lib/re1.5/re1.5.h",
    "lib/re1.5/recursiveloop.c",
}
UZLIB_PATHS = {
    "lib/uzlib/adler32.c",
    "lib/uzlib/crc32.c",
    "lib/uzlib/header.c",
    "lib/uzlib/tinflate.c",
    "lib/uzlib/uzlib.h",
    "lib/uzlib/uzlib_conf.h",
}


class RP2EmbeddedComponentOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        value = json.loads(POLICY.read_text(encoding="utf-8"))
        cls.owners = {item["id"]: item for item in value["source_owners"]}

    def assert_policy_file(self, record: dict[str, str]) -> str:
        path = ROOT / record["path"]
        self.assertTrue(path.is_file(), record["path"])
        payload = path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])
        return payload.decode("utf-8")

    def test_retained_source_declares_the_three_distinct_license_classes(
        self,
    ) -> None:
        catalog = (MICROPYTHON / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("/re15 (BSD-3-clause)", catalog)
        self.assertIn("/uzlib (Zlib)", catalog)

        fdlibm = (MICROPYTHON / FDLIBM_HEADER).read_text(encoding="utf-8")
        self.assertIn("adapted from from newlib-nano-2", fdlibm)
        self.assertIn("Copyright (C) 1993 by Sun Microsystems, Inc.", fdlibm)
        self.assertIn("provided that this notice", fdlibm)

        re15 = (MICROPYTHON / "lib/re1.5/re1.5.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("Copyright 2007-2009 Russ Cox", re15)
        self.assertIn("Copyright 2014 Paul Sokolovsky", re15)
        self.assertIn("BSD-style", re15)

        uzlib = (MICROPYTHON / "lib/uzlib/uzlib.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("Copyright (c) 2003 by Joergen Ibsen / Jibz", uzlib)
        self.assertIn("Copyright (c) 2014-2018 by Paul Sokolovsky", uzlib)
        self.assertIn("Copyright (c) 2023 by Jim Mussared", uzlib)
        self.assertIn("This notice may not be removed or altered", uzlib)

    def test_fdlibm_header_is_owned_by_the_exact_combined_terms_class(
        self,
    ) -> None:
        owner = self.owners["libm-fdlibm-sun"]
        expression = "LicenseRef-PyBLE-Fdlibm-Sun AND MIT"
        self.assertEqual(owner["disposition"], "allow")
        self.assertEqual(owner["source_spdx_expression"], expression)
        self.assertEqual(owner["selected_spdx_expression"], expression)
        self.assertEqual(
            {item["identifier"] for item in owner["license_texts"]},
            {"LicenseRef-PyBLE-Fdlibm-Sun", "MIT"},
        )
        self.assertIn(
            {"namespace": "micropython", "path": FDLIBM_HEADER},
            owner["source_roots"],
        )
        self.assertEqual(
            [item["path"] for item in owner["notice_files"]],
            ["firmware/licenses/notices/rp2/libm-fdlibm.txt"],
        )
        notice = self.assert_policy_file(owner["notice_files"][0])
        self.assertIn(FDLIBM_HEADER, notice)

    def test_re15_dependencies_have_one_exact_bsd3_owner(self) -> None:
        owner = self.owners.get("re1.5-bsd")
        self.assertIsNotNone(owner, "missing re1.5-bsd owner")
        assert owner is not None
        self.assertEqual(owner["disposition"], "allow")
        self.assertEqual(owner["source_ref"], MICROPYTHON_REF)
        self.assertEqual(owner["source_url"], MICROPYTHON_URL)
        self.assertEqual(owner["source_spdx_expression"], "BSD-3-Clause")
        self.assertEqual(owner["selected_spdx_expression"], "BSD-3-Clause")
        self.assertEqual(
            owner["copyright"],
            "Copyright (c) 2007-2009 Russ Cox, Google Inc.; "
            "Copyright 2014 Paul Sokolovsky; MicroPython contributors",
        )
        self.assertEqual(
            {item["path"] for item in owner["source_roots"]}, RE15_PATHS
        )
        self.assertEqual(
            owner["license_texts"],
            [
                {
                    "identifier": "BSD-3-Clause",
                    "path": (
                        "firmware/licenses/evidence/rp2/re1.5/v0.8.2/LICENSE"
                    ),
                    "sha256": (
                        "df5c6cd09a47c05bd8529b3188b0daa5f5ffbd5c73398fd76"
                        "bafb64b75663fab"
                    ),
                }
            ],
        )
        self.assertEqual(
            [item["path"] for item in owner["notice_files"]],
            ["firmware/licenses/notices/rp2/re1.5-bsd.txt"],
        )
        self.assert_policy_file(owner["license_texts"][0])
        notice = self.assert_policy_file(owner["notice_files"][0])
        for path in RE15_PATHS:
            self.assertIn(path, notice)

    def test_uzlib_dependencies_have_one_exact_zlib_owner(self) -> None:
        owner = self.owners.get("uzlib-zlib")
        self.assertIsNotNone(owner, "missing uzlib-zlib owner")
        assert owner is not None
        self.assertEqual(owner["disposition"], "allow")
        self.assertEqual(owner["source_ref"], MICROPYTHON_REF)
        self.assertEqual(owner["source_url"], MICROPYTHON_URL)
        self.assertEqual(owner["source_spdx_expression"], "Zlib")
        self.assertEqual(owner["selected_spdx_expression"], "Zlib")
        self.assertEqual(
            owner["copyright"],
            "Copyright (c) 1998-2003 Joergen Ibsen / Jibz; "
            "Copyright (C) 1995-1998 Jean-loup Gailly and Mark Adler; "
            "Copyright (c) 2014-2018 Paul Sokolovsky; "
            "Copyright (c) 2023 Jim Mussared",
        )
        self.assertEqual(
            {item["path"] for item in owner["source_roots"]}, UZLIB_PATHS
        )
        self.assertEqual(
            owner["license_texts"],
            [
                {
                    "identifier": "Zlib",
                    "path": "firmware/licenses/texts/Zlib.txt",
                    "sha256": (
                        "bfb1112d49db5b1daecdfef24bd7e2f3ea0bafb33aa67aa0ab"
                        "51e2bf8407c03d"
                    ),
                }
            ],
        )
        self.assertEqual(
            [item["path"] for item in owner["notice_files"]],
            ["firmware/licenses/notices/rp2/uzlib-zlib.txt"],
        )
        self.assert_policy_file(owner["license_texts"][0])
        notice = self.assert_policy_file(owner["notice_files"][0])
        for path in UZLIB_PATHS:
            self.assertIn(path, notice)

    def test_each_observed_path_resolves_to_only_its_exact_owner(self) -> None:
        expected = {
            FDLIBM_HEADER: "libm-fdlibm-sun",
            **{path: "re1.5-bsd" for path in RE15_PATHS},
            **{path: "uzlib-zlib" for path in UZLIB_PATHS},
        }
        all_roots = [
            (owner["id"], item["path"])
            for owner in self.owners.values()
            for item in owner["source_roots"]
            if item["namespace"] == "micropython"
        ]
        forbidden_broad_roots = {
            "lib",
            "lib/libm",
            "lib/re1.5",
            "lib/uzlib",
        }
        self.assertTrue(
            forbidden_broad_roots.isdisjoint(root for _, root in all_roots)
        )

        for path, owner_id in sorted(expected.items()):
            with self.subTest(path=path):
                matches = [
                    (candidate_id, root)
                    for candidate_id, root in all_roots
                    if path == root or path.startswith(root + "/")
                ]
                self.assertTrue(matches, "unowned RP2 dependency %s" % path)
                specificity = max(
                    len(PurePosixPath(root).parts) for _, root in matches
                )
                winners = {
                    candidate_id
                    for candidate_id, root in matches
                    if len(PurePosixPath(root).parts) == specificity
                }
                self.assertEqual(winners, {owner_id})


if __name__ == "__main__":
    unittest.main(verbosity=2)
