#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0028 OI-1 bench contracts for two independent S3 images."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


HOST_DIR = Path(__file__).resolve().parent
HIL_DIR = HOST_DIR.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_bench as bench  # noqa: E402
import oi1_profile_bench as profile_bench  # noqa: E402


EXACT_PROFILE = "waveshare-esp32-s3-lcd-147b"
PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    EXACT_PROFILE,
)


def _s3_link_facts() -> dict:
    return {
        "dle": {
            "request_attempts": 1,
            "max_tx_octets": 251,
            "max_tx_time_us": 2120,
        },
        "phy": {
            "required_2m": True,
            "request_attempts": 1,
            "updates": [{"status": 0, "tx": 2, "rx": 2}],
            "settled_tx": 2,
            "settled_rx": 2,
        },
        "connection_parameters": {
            "request_return_codes": [0],
            "updates": [{"status": 0, "interval_units": 12}],
            "settled_interval_units": 12,
        },
        "tx_mbuf_starve_count": 0,
    }


class ExactBoardOi1MatrixTests(unittest.TestCase):
    def test_current_bench_order_has_three_distinct_profile_ids(self):
        self.assertEqual(tuple(bench.PROFILE_ORDER), PROFILE_ORDER)
        self.assertEqual(
            bench.PROFILE_TARGETS,
            {
                "esp32-4mb": "esp32",
                "esp32-s3-n16r8": "esp32-s3",
                EXACT_PROFILE: EXACT_PROFILE,
            },
        )
        self.assertEqual(
            bench.PROFILE_CHIPS,
            {
                "esp32-4mb": "esp32",
                "esp32-s3-n16r8": "esp32-s3",
                EXACT_PROFILE: "esp32-s3",
            },
        )
        self.assertEqual(
            profile_bench.PROFILE_CAPACITIES[EXACT_PROFILE],
            (16 * 1024 * 1024, 8 * 1024 * 1024),
        )

    def test_exact_board_payload_and_baseline_identity_are_independent(self):
        generic = bench.deterministic_payload("esp32-s3-n16r8", 0, 4096)
        exact = bench.deterministic_payload(EXACT_PROFILE, 0, 4096)
        self.assertNotEqual(generic, exact)
        profile = profile_bench.build_baseline_profile(
            profile_id=EXACT_PROFILE,
            board_manufacturer="Waveshare",
            board_model="ESP32-S3-LCD-1.47B",
            module_marking="ESP32-S3",
            device_flash_capacity_bytes=16 * 1024 * 1024,
            device_psram_capacity_bytes=8 * 1024 * 1024,
            firmware_sha256="1" * 64,
            manifest_sha256="2" * 64,
            environment={
                "desktop_os": "host-test",
                "ble_backend": "host-test",
                "ble_adapter": "host-test",
                "python_version": "host-test",
            },
            oi1_build={},
            oi1_observation={},
        )
        self.assertEqual(profile["profile_id"], EXACT_PROFILE)
        self.assertEqual(profile["target"], EXACT_PROFILE)

    def test_exact_board_requires_the_same_strict_2m_shape_as_generic_s3(self):
        facts = _s3_link_facts()
        self.assertEqual(
            bench.validate_transfer_link_facts(
                facts,
                profile_id=EXACT_PROFILE,
            ),
            facts,
        )
        facts["phy"]["required_2m"] = False
        with self.assertRaises(bench.BenchError):
            bench.validate_transfer_link_facts(
                facts,
                profile_id=EXACT_PROFILE,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
