#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Adversarial RED contract for V5 HIL completion materialization.

The suite is host-only.  It uses synthetic JSON and temporary paths; it never
opens hardware, scans BLE, flashes firmware, or records a qualification pass.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_PATH = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
INPUT_LIMIT = 4 * 1024 * 1024
sys.path.insert(0, str(HERE))
import test_release_v060_promotion_lifecycle as fixture  # noqa: E402


def load_release():
    spec = importlib.util.spec_from_file_location(
        "pyble_v060_completion_safety_release", RELEASE_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load release_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release()


def operator_input(profile_id: str = "esp32-4mb") -> dict[str, object]:
    spec = RELEASE.PROFILE_SPECS[profile_id]
    return {
        "board_manufacturer": "Fixture vendor",
        "board_model": "Fixture board",
        "module_marking": "fixture marking",
        "device_flash_capacity_bytes": spec["flash_size_bytes"],
        "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
        "tested_at": "2026-08-12T12:00:00Z",
        "operator": "release operator",
        "maintainer_signoff": "release maintainer",
        "desktop_os": "FixtureOS 1",
        "chromium_version": "Chromium 140",
        "ble_backend": "fixture BLE",
        "ble_adapter": "fixture adapter",
        "python_version": "3.13.5",
        "redacted_console_log": "redacted fixture log",
        "checks": {
            name: "passed" for name in RELEASE._V5_OPERATOR_CHECKS
        },
        "app_hil": {
            platform: {
                "app_version": "0.1.0",
                "app_build": "2",
                "os_major": "18" if platform == "ipad" else "16",
                "status": "passed",
            }
            for platform in ("ipad", "android")
        },
    }


class CompletionInputValidationTests(unittest.TestCase):
    def test_c3_requires_the_strict_2m_transfer_shape(self) -> None:
        facts = {
            "dle": {
                "request_attempts": 1,
                "max_tx_octets": 251,
                "max_tx_time_us": 17_040,
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
                "updates": [{"status": 0, "interval_units": 23}],
                "settled_interval_units": 23,
            },
            "tx_mbuf_starve_count": 0,
        }
        self.assertEqual(
            RELEASE._validate_transfer_link_facts(facts, "esp32-c3-4mb"),
            facts,
        )

    def test_pico_budget_is_exact_and_zero_capacity_rejects_bool(self) -> None:
        facts = {
            "ble_host": "btstack",
            "observed_att_mtu": 247,
            "observed_window": 4,
            "observed_chunk_bytes": 229,
            "console_tx_budget_ms": 103,
        }
        self.assertEqual(
            RELEASE._validate_transfer_link_facts(facts, "rpi-pico2-w"), facts
        )
        for invalid in (102, 104, True):
            with self.subTest(console_tx_budget_ms=invalid), self.assertRaises(
                RELEASE.ReleaseError
            ):
                RELEASE._validate_transfer_link_facts(
                    {**facts, "console_tx_budget_ms": invalid}, "rpi-pico2-w"
                )

        value = operator_input("esp32-4mb")
        value["device_psram_capacity_bytes"] = False
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._validate_v5_operator_input(value, "esp32-4mb")

    def test_inputs_are_bounded_and_calendar_valid(self) -> None:
        self.assertEqual(
            getattr(RELEASE, "_V5_COMPLETION_INPUT_MAX_BYTES", None), INPUT_LIMIT
        )
        invalid_time = operator_input()
        invalid_time["tested_at"] = "2026-02-30T12:00:00Z"
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._validate_v5_operator_input(invalid_time, "esp32-4mb")

        with tempfile.TemporaryDirectory(prefix="pyble-v5-input-bound-") as tmp:
            path = Path(tmp) / "oversize.json"
            path.write_bytes(
                (
                    json.dumps(
                        {"value": "x" * INPUT_LIMIT},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._read_canonical_json_object(path, "oversize fixture")


class CompletionPublicationSafetyTests(unittest.TestCase):
    def test_output_rejects_lexical_navigation_and_nested_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v5-path-") as tmp:
            root = Path(tmp).resolve()
            inner = root / "real" / "inner"
            inner.mkdir(parents=True)
            link = root / "linked"
            link.symlink_to(inner, target_is_directory=True)
            cases = (
                inner / ".." / "lexical.json",
                link / "symlink.json",
            )
            for output in cases:
                with self.subTest(output=output), self.assertRaises(
                    RELEASE.ReleaseError
                ):
                    RELEASE._write_completion_fragment_no_replace(
                        output,
                        b"{}\n",
                        pre_publish_check=lambda: None,
                        post_publish_check=lambda: None,
                    )
                self.assertFalse(output.exists())

    def test_every_post_publish_failure_rolls_back_exact_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v5-rollback-") as tmp:
            root = Path(tmp).resolve()
            interrupted = root / "interrupted.json"

            def interrupt() -> None:
                raise KeyboardInterrupt("fixture interruption")

            with self.assertRaises(KeyboardInterrupt):
                RELEASE._write_completion_fragment_no_replace(
                    interrupted,
                    b"{}\n",
                    pre_publish_check=lambda: None,
                    post_publish_check=interrupt,
                )
            self.assertFalse(interrupted.exists())

            mutated = root / "mutated.json"

            def mutate_visible_output() -> None:
                mutated.write_bytes(b"changed\n")

            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._write_completion_fragment_no_replace(
                    mutated,
                    b"{}\n",
                    pre_publish_check=lambda: None,
                    post_publish_check=mutate_visible_output,
                )
            self.assertFalse(mutated.exists())

    def test_v5_hil_capacity_comparison_is_bool_safe(self) -> None:
        payload = fixture.pending_v5_payload()
        payload["records"][0]["device_psram_capacity_bytes"] = False
        policy = payload["qualification_policy"]
        with tempfile.TemporaryDirectory(prefix="pyble-v5-capacity-") as tmp:
            root = Path(tmp)
            report = root / "HIL_REPORT.md"
            report.write_text(fixture.hil_report(payload), encoding="utf-8")
            identity = {
                "version": "0.6.0",
                "tag": "firmware-v0.6.0",
                "_source_commit": "1" * 40,
            }
            with mock.patch.object(
                RELEASE, "_validate_qualification_policy", return_value=policy
            ), mock.patch.object(
                RELEASE,
                "_load_qualification_policy",
                return_value=(policy, payload["qualification_policy_sha256"]),
            ), mock.patch.object(
                RELEASE, "_validate_qualification_build", return_value=None
            ), mock.patch.object(
                RELEASE,
                "_qualification_build_measurement",
                return_value={},
            ), self.assertRaises(RELEASE.ReleaseError):
                RELEASE._validate_hil(
                    root,
                    report,
                    fixture.lifecycle_fixture.pending_profiles(),
                    identity,
                    False,
                    repo_root=root,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
