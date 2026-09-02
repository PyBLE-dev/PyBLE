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
import tempfile
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

PROFILE_BOARD_IDENTITIES = {
    "esp32-4mb": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32 development board",
        "module_marking": "ESP32-D0WD revision v1.0 (esptool)",
    },
    "esp32-s3-n16r8": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32-S3 development board",
        "module_marking": "ESP32-S3 QFN56 revision v0.1 (esptool)",
    },
    "waveshare-esp32-s3-lcd-147b": {
        "board_manufacturer": "Waveshare",
        "board_model": "ESP32-S3-LCD-1.47B",
        "module_marking": "ESP32-S3R8",
    },
    "esp32-c3-4mb": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32-C3 development board",
        "module_marking": "ESP32-C3 QFN32 revision v0.4 (esptool)",
    },
    "rpi-pico2-w": {
        "board_manufacturer": "Raspberry Pi Ltd",
        "board_model": "Raspberry Pi Pico 2 W",
        "module_marking": "RP2350 + CYW43439",
    },
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

EVIDENCE_OPTIONS = (
    "--candidate-dir",
    "--workspace-erased-receipt",
    "--workspace-nonblank-receipt",
    "--raw-log",
    "--result",
)


def evidence_argv(root="/private/v061", profile="esp32-4mb"):
    identity = PROFILE_BOARD_IDENTITIES[profile]
    return [
        "--candidate-dir",
        root + "/candidate",
        "--workspace-erased-receipt",
        root + "/erased-media.json",
        "--workspace-nonblank-receipt",
        root + "/nonblank-media.json",
        "--raw-log",
        root + "/hardening.jsonl",
        "--result",
        root + "/hardening-result.json",
        "--board-manufacturer",
        identity["board_manufacturer"],
        "--board-model",
        identity["board_model"],
        "--module-marking",
        identity["module_marking"],
    ]


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
    def test_cli_requires_exact_profile_address_and_candidate_bound_outputs(self):
        bench = load_bench()
        self.assertEqual(bench.PROFILE_CHIPS, PROFILE_CHIPS)
        self.assertEqual(bench.PROFILE_ORDER, tuple(PROFILE_CHIPS))

        for argv in (
            [],
            ["--address", "private-address"],
            ["--profile", "esp32-4mb"],
            [
                "--profile",
                "esp32",
                "--address",
                "private-address",
                *evidence_argv(),
            ],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                bench._parse_args(argv)

        with tempfile.TemporaryDirectory(prefix="pyble-v061-cli-valid-") as tmp:
            root = Path(tmp)
            (root / "candidate").mkdir()
            for name in ("erased-media.json", "nonblank-media.json"):
                receipt = root / name
                receipt.write_text("{}\n", encoding="utf-8")
                receipt.chmod(0o600)
            complete = [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                *evidence_argv(str(root)),
            ]
            for option in EVIDENCE_OPTIONS:
                index = complete.index(option)
                incomplete = complete[:index] + complete[index + 2 :]
                with self.subTest(missing=option), self.assertRaises(SystemExit):
                    bench._parse_args(incomplete)

            try:
                args = bench._parse_args(complete)
            except SystemExit as exc:
                self.fail(
                    "[red] complete candidate-bound v0.6.1 CLI was rejected: %s"
                    % exc
                )
            self.assertEqual(args.profile, "esp32-4mb")
            self.assertEqual(args.expect_agent, "0.6.1")
            self.assertEqual(args.address, "private-address")
            self.assertEqual(args.candidate_dir, root / "candidate")
            self.assertEqual(
                args.workspace_erased_receipt,
                root / "erased-media.json",
            )
            self.assertEqual(
                args.workspace_nonblank_receipt,
                root / "nonblank-media.json",
            )
            self.assertEqual(args.raw_log, root / "hardening.jsonl")
            self.assertEqual(args.result, root / "hardening-result.json")
            for substituted_version in ("0.6.0", "0.6.2", "1.0.0"):
                with self.subTest(expect_agent=substituted_version):
                    with self.assertRaises(SystemExit):
                        bench._parse_args(
                            [
                                *complete,
                                "--expect-agent",
                                substituted_version,
                            ]
                        )

    def test_workspace_not_run_and_legacy_acknowledgement_flags_are_ineligible(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-cli-legacy-") as tmp:
            root = Path(tmp)
            (root / "candidate").mkdir()
            for name in ("erased-media.json", "nonblank-media.json"):
                receipt = root / name
                receipt.write_text("{}\n", encoding="utf-8")
                receipt.chmod(0o600)
            base = [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                *evidence_argv(str(root)),
            ]
            try:
                bench._parse_args(base)
            except SystemExit as exc:
                self.fail("[red] safe v0.6.1 base CLI was rejected: %s" % exc)
            for legacy in (
                "--require-workspace-provisioning",
                "--sacrificial-media",
            ):
                with self.subTest(option=legacy), self.assertRaises(SystemExit):
                    bench._parse_args([*base, legacy])

        source = BENCH_PATH.read_text(encoding="utf-8")
        self.assertNotIn("NOT-RUN(nondestructive)", source)
        self.assertNotIn(
            "requires-out-of-band-blank-and-nonblank-boot-observations",
            source,
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
            "_set_vm_rotation_sentinel",
            "_soft_reboot_connect_unnegotiated",
            "_assert_vm_rotation_sentinel_absent",
        ):
            self.assertIn(token, transport)
        reboot = transport.find("_soft_reboot_connect_unnegotiated")
        workspace = transport.find("preflight_board_workspace")
        sentinel = transport.find("_set_vm_rotation_sentinel")
        pre_hello = transport.find('"post-VM-reset pre-HELLO DEVICE_INFO"')
        renegotiate = transport.find("_negotiate(state)", pre_hello)
        freshness = transport.find("_assert_vm_rotation_sentinel_absent")
        self.assertTrue(
            -1
            < workspace
            < sentinel
            < reboot
            < pre_hello
            < renegotiate
            < freshness,
            "transport-session must prove VM rotation, reject a pre-HELLO "
            "command, negotiate, then prove volatile state was cleared",
        )
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
                "soft-reboot",
                "reboot-stale",
                "reboot-fresh",
                "_soft_reboot_connect_unnegotiated",
            ),
            bench.run_label_durability: (
                "OP_SET_LABEL",
                "LABEL_24",
                "OP_SET_AUTORUN",
                "auto_run",
                "OP_IDENTIFY",
                "has_identify",
                "identify_led",
                "OP_SOFT_REBOOT",
                "advertisement",
                "restore",
            ),
            bench.run_filesystem_hardening: (
                ".pbltmp",
                "OP_FILE_LIST",
                "OP_FILE_STAT",
                "OP_FILE_GET_BEGIN",
                "OP_FILE_DELETE",
                "OP_FILE_RENAME",
                "OP_MKDIR",
                "ST_EBUSY",
                "ST_EBADREQ",
                "ST_EACCES",
                "ST_ENOSPC",
                "CAPACITY_RESERVE",
                "_get_with_active_probe",
            ),
        }
        for function, tokens in expectations.items():
            source = inspect.getsource(function)
            for token in tokens:
                with self.subTest(function=function.__name__, token=token):
                    self.assertIn(token, source)
        reboot_helper = inspect.getsource(
            bench._soft_reboot_connect_unnegotiated
        )
        for token in ("OP_SOFT_REBOOT", "ST_OK", "_wait_disconnected"):
            self.assertIn(token, reboot_helper)

        stdin = inspect.getsource(bench.run_stdin_isolation)
        positions = [
            stdin.find('"soft-reboot"'),
            stdin.find("reboot-stale"),
            stdin.find("_soft_reboot_connect_unnegotiated"),
            stdin.find("_negotiate(state)", stdin.find("reboot-stale")),
            stdin.find('"reboot-successor"'),
            stdin.find("_assert_run_still_active", stdin.find("reboot-stale")),
            stdin.find("reboot-fresh"),
        ]
        self.assertTrue(
            all(position >= 0 for position in positions)
            and positions == sorted(positions),
            "stdin VM-reset case must queue stale input, reboot, negotiate, "
            "then require fresh successor input",
        )
        self.assertNotIn(
            "OP_SET_IDENTIFY_LED",
            inspect.getsource(bench.run_label_durability),
            "the target-neutral runner must preserve owner Identify configuration",
        )

        self.assertEqual(len(bench.LABEL_24.encode("utf-8")), 24)
        self.assertEqual(bench.SEQUENTIAL_RUNS, 50)
        self.assertEqual(bench.CAPACITY_RESERVE, 65536)
        self.assertEqual(bench.ACTIVE_GET_BYTES, 16384)
        active_get = inspect.getsource(bench._get_with_active_probe)
        for token in (
            "DownloadVerifier",
            "OP_FILE_GET_BEGIN",
            "OP_FILE_GET_DATA",
            "OP_FILE_GET_END",
            "on_written",
            "GET ended before",
        ):
            self.assertIn(token, active_get)

    def test_resource_evaluation_and_redacted_console_result_are_deterministic(self):
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
        self.assertIn(
            "monotonic",
            " ".join(bench.resource_failures(leaking, thresholds)),
        )
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
            "passed",
        )
        self.assertEqual(
            result,
            "V061 HARDENING PASS (profile=esp32-4mb chip=esp32 "
            "agent=0.6.1 scenarios=7 workspace=passed)",
        )
        for private in ("private-address", "SECRET", "private-label"):
            self.assertNotIn(private, result)

    def test_runner_uses_the_shared_gate_and_publishes_only_after_all_scenarios(self):
        bench = load_bench()
        writer = getattr(bench, "write_private_result", None)
        self.assertTrue(
            callable(writer),
            "[red] v0.6.1 HIL needs a canonical exclusive private-result writer",
        )
        self.assertEqual(
            set(inspect.signature(writer).parameters),
            {
                "candidate_dir",
                "profile_id",
                "scenario_results",
                "workspace_erased_receipt",
                "workspace_nonblank_receipt",
                "raw_log",
                "result",
                "qualification_repo_root",
            },
        )
        token_writer = getattr(
            bench,
            "write_private_result_from_preflight",
            None,
        )
        self.assertTrue(
            callable(token_writer),
            "[red] long-running HIL must publish from its original preflight token",
        )
        if callable(token_writer):
            self.assertEqual(
                set(inspect.signature(token_writer).parameters),
                {"preflight", "scenario_results", "raw_log", "result"},
            )

        source = inspect.getsource(bench.run)
        positions = [source.find('"%s"' % name) for name in SCENARIOS]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))
        preflight_position = source.find("preflight_result_inputs(")
        self.assertGreaterEqual(preflight_position, 0)
        self.assertLess(preflight_position, positions[0])
        board_preflight_position = source.find("preflight_board_workspace(")
        self.assertGreater(board_preflight_position, positions[0])
        self.assertLess(board_preflight_position, positions[1])
        writer_position = source.find("write_private_result_from_preflight(")
        self.assertGreater(writer_position, positions[-1])
        self.assertIn("workspace_erased_receipt", source)
        self.assertIn("workspace_nonblank_receipt", source)
        self.assertIn("raw_log", source)

    def test_result_and_raw_log_paths_are_new_and_outside_candidate(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-hil-cli-") as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            candidate.mkdir()
            for name in ("erased-media.json", "nonblank-media.json"):
                receipt = root / name
                receipt.write_text("{}\n", encoding="utf-8")
                receipt.chmod(0o600)
            valid = [
                "--profile",
                "esp32-4mb",
                "--address",
                "private-address",
                *evidence_argv(str(root)),
            ]
            (root / "hardening-result.json").write_text(
                "owner data\n", encoding="utf-8"
            )
            with self.assertRaises(SystemExit):
                bench._parse_args(valid)

            (root / "hardening-result.json").unlink()
            (root / "hardening.jsonl").write_text(
                "owner data\n", encoding="utf-8"
            )
            with self.assertRaises(SystemExit):
                bench._parse_args(valid)

            (root / "hardening.jsonl").unlink()
            try:
                accepted = bench._parse_args(valid)
            except SystemExit as exc:
                self.fail(
                    "[red] safe output paths were rejected before path cases: %s"
                    % exc
                )
            self.assertEqual(accepted.result, root / "hardening-result.json")
            self.assertEqual(accepted.raw_log, root / "hardening.jsonl")

            inside = list(valid)
            inside[inside.index("--result") + 1] = str(candidate / "result.json")
            with self.assertRaises(SystemExit):
                bench._parse_args(inside)

            inside = list(valid)
            inside[inside.index("--raw-log") + 1] = str(candidate / "raw.jsonl")
            with self.assertRaises(SystemExit):
                bench._parse_args(inside)

            same = list(valid)
            same[same.index("--result") + 1] = same[
                same.index("--raw-log") + 1
            ]
            with self.assertRaises(SystemExit):
                bench._parse_args(same)

            symlink_parent_target = root / "external-output-parent"
            symlink_parent_target.mkdir()
            symlink_parent = root / "linked-output-parent"
            symlink_parent.symlink_to(
                symlink_parent_target,
                target_is_directory=True,
            )
            linked = list(valid)
            linked[linked.index("--result") + 1] = str(
                symlink_parent / "result.json"
            )
            with self.assertRaises(SystemExit):
                bench._parse_args(linked)
            self.assertFalse((symlink_parent_target / "result.json").exists())

            broken = root / "broken-result.json"
            broken.symlink_to(root / "missing-target.json")
            broken_output = list(valid)
            broken_output[broken_output.index("--result") + 1] = str(broken)
            with self.assertRaises(SystemExit):
                bench._parse_args(broken_output)

            candidate_target = root / "candidate-target"
            candidate_target.mkdir()
            candidate_link = root / "candidate-link"
            candidate_link.symlink_to(candidate_target, target_is_directory=True)
            linked_candidate = list(valid)
            linked_candidate[linked_candidate.index("--candidate-dir") + 1] = str(
                candidate_link
            )
            with self.assertRaises(SystemExit):
                bench._parse_args(linked_candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
