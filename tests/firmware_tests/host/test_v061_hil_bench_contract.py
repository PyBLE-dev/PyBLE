#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Contract for the target-neutral firmware-v0.6.1 hardening HIL bench.

These tests inspect deterministic host-side seams only.  They do not simulate a
board and cannot be cited as physical HIL evidence.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HIL = HERE.parent / "hil"
BENCH_PATH = HIL / "v061_hardening_bench.py"
sys.path.insert(0, str(HIL))


PROFILE_CHIPS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "esp32-s3",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}

SCENARIOS = (
    "transport-session",
    "fragment-hardening",
    "run-isolation",
    "resource-stability",
    "stdin-isolation",
    "configuration-durability",
    "filesystem-hardening",
)


def load_bench():
    if not BENCH_PATH.is_file():
        raise AssertionError("missing v0.6.1 HIL bench: %s" % BENCH_PATH.name)
    spec = importlib.util.spec_from_file_location("v061_hardening_bench", BENCH_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load %s" % BENCH_PATH.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V061HilBenchContractTests(unittest.TestCase):
    def test_cli_requires_one_exact_profile_and_private_address(self):
        bench = load_bench()
        self.assertEqual(bench.PROFILE_CHIPS, PROFILE_CHIPS)
        self.assertEqual(bench.PROFILE_ORDER, tuple(PROFILE_CHIPS))

        for argv in (
            [],
            ["--address", "private-address"],
            ["--profile", "esp32-4mb"],
            ["--profile", "esp32", "--address", "private-address"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                bench._parse_args(argv)

        args = bench._parse_args(
            ["--profile", "esp32-4mb", "--address", "private-address"]
        )
        self.assertEqual(args.profile, "esp32-4mb")
        self.assertEqual(args.expect_agent, "0.6.1")
        self.assertEqual(args.address, "private-address")

    def test_destructive_workspace_provisioning_is_never_silently_skipped(self):
        bench = load_bench()
        for argv in (
            [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                "--require-workspace-provisioning",
            ],
            [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                "--sacrificial-media",
            ],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                bench._parse_args(argv)

        ordinary = bench._parse_args(
            ["--profile", "esp32-4mb", "--address", "private-address"]
        )
        destructive = bench._parse_args(
            [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                "--require-workspace-provisioning",
                "--sacrificial-media",
            ]
        )
        self.assertEqual(
            bench.workspace_prerequisite(ordinary), "NOT-RUN(nondestructive)"
        )
        self.assertEqual(
            bench.workspace_prerequisite(destructive),
            "FAIL(requires-out-of-band-blank-and-nonblank-boot-observations)",
        )

    def test_scenario_inventory_is_v061_only_and_is_executed(self):
        bench = load_bench()
        self.assertEqual(bench.SCENARIO_ORDER, SCENARIOS)
        live_run = inspect.getsource(bench.run)
        required = {
            "transport-session": "run_transport_session",
            "fragment-hardening": "run_fragment_hardening",
            "run-isolation": "run_fresh_globals",
            "resource-stability": "run_resource_stability",
            "stdin-isolation": "run_stdin_isolation",
            "configuration-durability": "run_label_durability",
            "filesystem-hardening": "run_filesystem_hardening",
        }
        for scenario, function_name in required.items():
            with self.subTest(scenario=scenario):
                self.assertIn(function_name, live_run)
                self.assertTrue(callable(getattr(bench, function_name)))

        source = BENCH_PATH.read_text(encoding="utf-8")
        for helper in ("_pble_wire", "_pble_central", "target_smoke", "_pble_bench"):
            self.assertIn(helper, source)
        for forbidden_v070_name in (
            "FILE_LIST_V2",
            "TRANSFER_ABORT",
            "RUN_STATUS",
            "CONSOLE_INPUT_V2",
            "FORCE_RESET",
        ):
            self.assertNotIn(forbidden_v070_name, source)

    def test_wire_adversarial_contract_uses_real_central_writes(self):
        bench = load_bench()
        transport = inspect.getsource(bench.run_transport_session)
        fragment = inspect.getsource(bench.run_fragment_hardening)
        for token in (
            "OP_DEVICE_INFO",
            "OP_HELLO",
            "ST_EBADREQ",
            "ST_EUNSUPPORTED",
            "disconnect",
        ):
            self.assertIn(token, transport)
        for token in (
            "wire.encode",
            "TYPE",
            "ID",
            "ECRC",
            "REASSEMBLY_DEADLINE_S",
            "MALFORMED_BUDGET",
            "write_gatt_char",
            "is_connected",
        ):
            self.assertIn(token, fragment)

    def test_run_stdin_label_and_filesystem_scenarios_are_physical_operations(self):
        bench = load_bench()
        expectations = {
            bench.run_fresh_globals: (
                "OP_RUN",
                "put_file",
                "fresh-source",
                "fresh-file",
            ),
            bench.run_resource_stability: (
                "SEQUENTIAL_RUNS",
                "run_heap_probe",
                "gc_free_min_bytes",
            ),
            bench.run_stdin_isolation: (
                "OP_CONSOLE_INPUT",
                "OP_STOP",
                "idle",
                "terminal",
                "disconnect",
                "overflow",
            ),
            bench.run_label_durability: (
                "OP_SET_LABEL",
                "LABEL_24",
                "OP_SOFT_REBOOT",
                "advertisement",
            ),
            bench.run_filesystem_hardening: (
                ".pbltmp",
                "OP_FILE_LIST",
                "OP_FILE_DELETE",
                "OP_FILE_RENAME",
                "OP_MKDIR",
                "ST_EBUSY",
                "ST_ENOSPC",
                "CAPACITY_RESERVE",
            ),
        }
        for function, tokens in expectations.items():
            source = inspect.getsource(function)
            for token in tokens:
                with self.subTest(function=function.__name__, token=token):
                    self.assertIn(token, source)

        self.assertEqual(len(bench.LABEL_24.encode("utf-8")), 24)
        self.assertEqual(bench.SEQUENTIAL_RUNS, 50)
        self.assertEqual(bench.CAPACITY_RESERVE, 65536)

    def test_resource_evaluation_and_public_result_are_deterministic(self):
        bench = load_bench()
        thresholds = {"gc_free_min_bytes": 4096}
        healthy = [
            {"gc_free_bytes": 8192},
            {"gc_free_bytes": 7168},
            {"gc_free_bytes": 7680},
        ]
        leaking = [
            {"gc_free_bytes": 8192},
            {"gc_free_bytes": 7168},
            {"gc_free_bytes": 6144},
        ]
        below = healthy + [{"gc_free_bytes": 4095}]
        self.assertEqual(bench.resource_failures(healthy, thresholds), [])
        self.assertIn("monotonic", " ".join(bench.resource_failures(leaking, thresholds)))
        self.assertIn("floor", " ".join(bench.resource_failures(below, thresholds)))

        caps = {
            "chip": "esp32",
            "agent": "0.6.1",
            "device_id": "SECRET",
            "label": "private-label",
        }
        result = bench.format_result(
            "PASS",
            "esp32-4mb",
            caps,
            "NOT-RUN(nondestructive)",
        )
        self.assertEqual(
            result,
            "V061 HARDENING PASS (profile=esp32-4mb chip=esp32 "
            "agent=0.6.1 scenarios=7 workspace=NOT-RUN(nondestructive))",
        )
        for private in ("private-address", "SECRET", "private-label"):
            self.assertNotIn(private, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
