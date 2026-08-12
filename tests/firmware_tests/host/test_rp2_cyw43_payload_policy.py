#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for exact CYW43 driver and opaque-payload ownership."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "firmware/licenses/rp2-license-policy.json"
RELEASE_BUNDLE = ROOT / "firmware/scripts/release_bundle.py"
CYW43 = ROOT / "firmware/upstream/micropython/lib/cyw43-driver"

spec = importlib.util.spec_from_file_location("release_bundle", RELEASE_BUNDLE)
assert spec is not None and spec.loader is not None
release_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_bundle)


PAYLOADS = {
    "cyw43-wifi-clm-payload": {
        "path": "lib/cyw43-driver/firmware/wb43439A0_7_95_49_00_combined.h",
        "symbol": "wb43439A0_7_95_49_00_combined",
        "bytes": 232_408,
        "sha256": "9c9879836c5267672c9cf3f5436d4585f2d0e6e2e212fb84f636f1aa28c38d4c",
        "header_sha256": "6b4b9a717c3c5d669b56a3bc38b58df3901f63e3a7363ccf5d74706460762176",
    },
    "cyw43-bt-firmware-payload": {
        "path": "lib/cyw43-driver/firmware/cyw43_btfw_43439.h",
        "symbol": "cyw43_btfw_43439",
        "bytes": 6_970,
        "sha256": "d974384d0aa8124d30084f30d13519a3ed3b9f759f7ddd6a34ef3dcf1441bcf7",
        "header_sha256": "d05a8dca7e232ada470d8ed723edaa1ea78000098870f9b979d490d83ad35b22",
    },
    "cyw43-nvram-payload": {
        "path": "lib/cyw43-driver/firmware/wifi_nvram_43439.h",
        "symbol": "wifi_nvram_4343",
        # C appends one implicit NUL to the adjacent string-literal initializer;
        # cyw43_ll.c uses sizeof(wifi_nvram_4343), so that byte is selected.
        "bytes": 743,
        "sha256": "36fa0ddfac5a899e2ec1fbe2f618cf319b58952bed24a26abe4f89f06c9a7664",
        "header_sha256": "ddc82b00667643f55d7687bba1b5e4028f24717ec8883f05bd7d435f4c9c01ad",
    },
}


class RP2Cyw43PayloadPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        cls.owners = {owner["id"]: owner for owner in policy["source_owners"]}

    def test_driver_and_each_payload_have_separate_exact_owners(self) -> None:
        driver = self.owners["cyw43-driver-code"]
        self.assertEqual(driver["disposition"], "allow")
        self.assertEqual(
            driver["selected_spdx_expression"],
            "LicenseRef-PyBLE-CYW43-Raspberry-Pi",
        )
        self.assertEqual(
            driver["source_roots"],
            [{"namespace": "micropython", "path": "lib/cyw43-driver"}],
        )

        for owner_id, expected in PAYLOADS.items():
            with self.subTest(owner=owner_id):
                owner = self.owners[owner_id]
                self.assertEqual(owner["disposition"], "review-required")
                self.assertEqual(
                    owner["source_roots"],
                    [{"namespace": "micropython", "path": expected["path"]}],
                )
                self.assertNotEqual(
                    owner["selected_spdx_expression"],
                    "LicenseRef-PyBLE-CYW43-Raspberry-Pi",
                    "the driver grant must not silently authorize opaque payloads",
                )

    def test_exact_headers_and_selected_c_array_bytes_are_bound(self) -> None:
        parser = getattr(release_bundle, "_audit_rp2_c_array_payload")
        for owner_id, expected in PAYLOADS.items():
            with self.subTest(owner=owner_id):
                header = CYW43 / expected["path"].removeprefix(
                    "lib/cyw43-driver/"
                )
                self.assertEqual(
                    hashlib.sha256(header.read_bytes()).hexdigest(),
                    expected["header_sha256"],
                )
                self.assertEqual(
                    parser(
                        header,
                        expected["symbol"],
                        expected["bytes"],
                    ),
                    {
                        "bytes": expected["bytes"],
                        "sha256": expected["sha256"],
                    },
                )

    def test_c_array_parser_rejects_nonliteral_or_ambiguous_inputs(self) -> None:
        parser = getattr(release_bundle, "_audit_rp2_c_array_payload")
        cases = {
            "expression": (
                "const unsigned char payload[] = {0x01, SOME_MACRO};\n",
                2,
            ),
            "designator": (
                "const unsigned char payload[] = {[0] = 0x01};\n",
                1,
            ),
            "duplicate": (
                "const unsigned char payload[] = {0x01};\n"
                "const unsigned char payload[] = {0x01};\n",
                1,
            ),
            "wrong-length": (
                "const unsigned char payload[] = {0x01};\n",
                2,
            ),
            "trailing-declaration": (
                "const unsigned char payload[] = {0x01};\nint surprise = 1;\n",
                1,
            ),
        }
        for label, (source, expected_length) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "payload.h"
                path.write_text(source, encoding="utf-8")
                with self.assertRaises(release_bundle.ReleaseError):
                    parser(path, "payload", expected_length)


if __name__ == "__main__":
    unittest.main(verbosity=2)
