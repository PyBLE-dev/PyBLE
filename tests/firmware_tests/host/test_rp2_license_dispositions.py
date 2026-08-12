#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Exact reviewed disposition contract for the initial RP2 release policy."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "firmware/licenses/rp2-license-policy.json"


class RP2LicenseDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        value = json.loads(POLICY.read_text(encoding="utf-8"))
        cls.owners = {item["id"]: item for item in value["source_owners"]}

    def test_resolved_owners_are_exact_and_allowed(self) -> None:
        expected_copyright = {
            "btstack": (
                "Copyright (C) 2009, 2014, 2016-2018 BlueKitchen GmbH"
            ),
            "libm-fdlibm-sun": (
                "Copyright (C) 1993 by Sun Microsystems, Inc.; "
                "Copyright (c) 2013-2026 Damien P. George"
            ),
            "libm-musl": (
                "Copyright © 2005-2014 Rich Felker, et al.; "
                "Copyright (c) 2013-2026 Damien P. George"
            ),
            "libm-musl-sun": (
                "Copyright © musl contributors; Copyright (C) 1993 by Sun "
                "Microsystems, Inc.; Copyright (c) 2013-2026 Damien P. George"
            ),
        }
        for owner_id, copyright_value in expected_copyright.items():
            with self.subTest(owner=owner_id):
                owner = self.owners[owner_id]
                self.assertEqual(owner["disposition"], "allow")
                self.assertEqual(owner["copyright"], copyright_value)

    def test_fdlibm_binds_mit_sun_and_shared_header(self) -> None:
        owner = self.owners["libm-fdlibm-sun"]
        expression = "LicenseRef-PyBLE-Fdlibm-Sun AND MIT"
        self.assertEqual(owner["source_spdx_expression"], expression)
        self.assertEqual(owner["selected_spdx_expression"], expression)
        self.assertEqual(
            {item["identifier"] for item in owner["license_texts"]},
            {"LicenseRef-PyBLE-Fdlibm-Sun", "MIT"},
        )
        self.assertIn(
            {"namespace": "micropython", "path": "lib/libm/libm.h"},
            owner["source_roots"],
        )

    def test_unresolved_owners_remain_release_blocking(self) -> None:
        self.assertEqual(
            {
                owner_id
                for owner_id, owner in self.owners.items()
                if owner["disposition"] == "review-required"
            },
            {
                "arm-gnu-gcc-runtime",
                "arm-gnu-newlib-runtime",
                "cyw43-driver",
                "pico-sdk-cmsis",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
