#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for one-field v0.6 physical-power fact lineage.

The fixtures are synthetic and host-only.  They do not claim a hardware
observation or turn baseline evidence into release evidence.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_PATH = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def load_release():
    spec = importlib.util.spec_from_file_location(
        "pyble_v060_physical_fact_lineage_release", RELEASE_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load release_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release()
PROFILE = "esp32-4mb"
BUILD = {
    "application_image_bytes": 100,
    "factory_partition_bytes": 200,
    "application_headroom_bytes": 100,
}
EXPECTED_SOURCE_DIFF = (
    (
        "A",
        "docs/validation/firmware/oi1/"
        "a8be631df46590166307aa41afaea30b39e29230.json",
    ),
    ("M", "firmware/qualification/oi1-gates.json"),
    ("M", "tests/firmware_tests/host/test_oi1_profile_bench.py"),
)


def _event(sequence: int, event: str, **fields: object) -> dict[str, object]:
    return {"event": event, "sequence": sequence, **fields}


def automatic_raw() -> bytes:
    events: list[dict[str, object]] = []

    def add(event: str, **fields: object) -> None:
        events.append(_event(len(events) + 1, event, **fields))

    add("measurement_start", mode="verify", profile_id=PROFILE, **BUILD)
    heap = {
        "gc_allocated_bytes": 100,
        "gc_free_bytes": 100_000,
        "idf_internal_free_bytes": 80_000,
        "idf_internal_largest_block_bytes": 60_000,
        "idf_internal_minimum_free_bytes": 70_000,
    }
    for sample in range(10):
        if sample == 9:
            add("transfer_link_capture_started", profile_id=PROFILE)
        add("reset_advertisement", sample_index=sample, latency_ms=500 + sample)
        add(
            "hello",
            sample_index=sample,
            backend_mtu=247,
            hello_mtu=247,
            window=8,
            chunk=229,
            heap_default_free_bytes=90_000,
        )
        add("heap_snapshot", **heap)
        if sample < 9:
            add("disconnect")
    add("transfer_link_settled")
    for _sample in range(5):
        add(
            "roundtrip",
            payload_bytes=65_536,
            put_duration_ns=2_000_000_000,
            get_duration_ns=1_000_000_000,
            put_retransmitted_chunks=0,
            put_retransmitted_bytes=0,
            get_retransmitted_chunks=0,
            get_retransmitted_bytes=0,
        )
        add("heap_snapshot", **heap)
    add(
        "reliability",
        attempted_files=20,
        completed_files=20,
        verified_files=20,
        bytes_per_file=16_384,
        total_payload_bytes=327_680,
        unexpected_disconnects=0,
        integrity_failures=0,
        failed_statuses=0,
        retransmitted_chunks=0,
        retransmitted_bytes=0,
        rewinds=0,
    )
    add("heap_snapshot", **heap)
    add("disconnect")
    add(
        "transfer_link_facts",
        facts={
            "dle": {
                "request_attempts": 1,
                "max_tx_octets": 251,
                "max_tx_time_us": 2_120,
            },
            "phy": {
                "required_2m": False,
                "request_attempts": 0,
                "updates": [],
                "settled_tx": 0,
                "settled_rx": 0,
            },
            "connection_parameters": {
                "request_return_codes": [0],
                "updates": [{"status": 0, "interval_units": 24}],
                "settled_interval_units": 24,
            },
            "tx_mbuf_starve_count": 0,
        },
    )
    add("measurement_failed", failure_type="EOFError")
    return b"".join(
        (
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        for item in events
    )


def lineage_summary() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "physical-fact-lineage-v1",
        "claims_new_observation": False,
        "reuse_scope": ["physical_power_cycle_advertising"],
        "record_sha256": "1" * 64,
        "baseline_source_commit": "2" * 40,
        "baseline_raw_log_sha256": "3" * 64,
        "candidate_automatic_raw_log_sha256": "4" * 64,
        "qualification_source_commit": "5" * 40,
        "qualification_executable_sha256": "6" * 64,
    }


class PhysicalFactLineageContractTests(unittest.TestCase):
    def test_replacement_candidate_source_diff_is_exactly_frozen(self) -> None:
        self.assertEqual(
            getattr(RELEASE, "_PHYSICAL_FACT_LINEAGE_SOURCE_DIFF", None),
            EXPECTED_SOURCE_DIFF,
        )

    def test_creator_api_and_no_replace_cli_are_frozen(self) -> None:
        creator = getattr(RELEASE, "create_physical_fact_lineage", None)
        self.assertTrue(callable(creator), "the lineage creator is missing")
        if callable(creator):
            self.assertEqual(
                set(inspect.signature(creator).parameters),
                {
                    "candidate_dir",
                    "profile_id",
                    "baseline_fragment_path",
                    "baseline_raw_log_path",
                    "baseline_inputs_dir",
                    "candidate_automatic_raw_log_path",
                    "candidate_automatic_executor_path",
                    "output_path",
                    "qualification_repo_root",
                },
            )
        help_result = subprocess.run(
            [sys.executable, str(RELEASE_PATH), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("create-physical-fact-lineage", help_result.stdout)

    def test_fresh_automatic_log_reconstructs_every_nonphysical_field(self) -> None:
        replay = getattr(
            RELEASE, "_reconstruct_lineage_automatic_observation", None
        )
        self.assertTrue(callable(replay), "strict automatic replay is missing")
        if not callable(replay):
            return
        raw = automatic_raw()
        result = replay(
            raw,
            profile_id=PROFILE,
            expected_build=BUILD,
            candidate_identity=None,
        )
        self.assertNotIn("physical_power_cycle_advertising", result)
        self.assertEqual(result["reset_to_service_advertisement_ms"], list(range(500, 510)))
        self.assertEqual(result["put_unique_committed_bytes"], [65_536] * 5)
        self.assertEqual(result["put_committed_goodput_bytes_per_second"], [32_768] * 5)
        self.assertEqual(result["get_verified_goodput_bytes_per_second"], [65_536] * 5)
        self.assertEqual(result["roundtrip_integrity_verified"], 5)
        self.assertEqual(result["raw_log_sha256"], hashlib.sha256(raw).hexdigest())

        for mutation in (
            raw.replace(b'"sequence":2', b'"sequence":3', 1),
            raw.replace(b'"mode":"verify"', b'"mode":"baseline"', 1),
            raw.replace(b'"failure_type":"EOFError"', b'"failure_type":"ValueError"', 1),
        ):
            with self.subTest(mutation=mutation[:80]), self.assertRaises(
                RELEASE.ReleaseError
            ):
                replay(
                    mutation,
                    profile_id=PROFILE,
                    expected_build=BUILD,
                    candidate_identity=None,
                )

    def test_summary_reuses_exactly_one_fact_and_rejects_every_binding_mutation(self) -> None:
        validate = getattr(RELEASE, "_validate_physical_fact_lineage_summary", None)
        self.assertTrue(callable(validate), "lineage summary validator is missing")
        if not callable(validate):
            return
        expected = lineage_summary()
        self.assertEqual(validate(copy.deepcopy(expected)), expected)
        mutations: list[dict[str, object]] = []
        extra_scope = copy.deepcopy(expected)
        extra_scope["reuse_scope"] = [
            "physical_power_cycle_advertising",
            "reset_to_service_advertisement_ms",
        ]
        mutations.append(extra_scope)
        claims_new = copy.deepcopy(expected)
        claims_new["claims_new_observation"] = True
        mutations.append(claims_new)
        for key in (
            "record_sha256",
            "baseline_source_commit",
            "baseline_raw_log_sha256",
            "candidate_automatic_raw_log_sha256",
            "qualification_source_commit",
            "qualification_executable_sha256",
        ):
            changed = copy.deepcopy(expected)
            changed[key] = "x"
            mutations.append(changed)
        direct_baseline = copy.deepcopy(expected)
        direct_baseline["kind"] = "oi1-five-profile-v1"
        mutations.append(direct_baseline)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(
                RELEASE.ReleaseError
            ):
                validate(mutation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
