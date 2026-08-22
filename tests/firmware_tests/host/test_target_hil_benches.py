#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for target-neutral PBLE/1 smoke and RUN/STOP HIL tools."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tomllib
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HIL = HERE.parent / "hil"
LOCK_PATH = ROOT / "firmware" / "versions.lock"
sys.path.insert(0, str(HIL))

import _pble_wire as wire  # noqa: E402


CURRENT_VERSION = "0.6.0"
CURRENT_TARGET_MATRIX = {
    "esp32": ("esp32", "esp32"),
    "esp32-s3": ("esp32s3", "esp32-s3"),
    "waveshare-esp32-s3-lcd-147b": ("esp32s3", "esp32-s3"),
    "esp32-c3": ("esp32c3", "esp32-c3"),
    "rpi-pico2-w": ("RPI_PICO2_W", "rpi-pico2-w"),
}


def load_hil(name: str):
    path = HIL / (name + ".py")
    if not path.is_file():
        raise AssertionError("missing target-neutral HIL tool: %s" % path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load %s" % path.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def caps_fixture(**changes):
    value = {
        "proto": "1",
        "agent": CURRENT_VERSION,
        "chip": "future-port-x",
        "mpy": "1.28.0",
        "fs_root": "/",
        "mtu": "247",
        "window": "8",
        "chunk": "229",
        "free_mem": "65536",
        "has_sd": "0",
        "has_identify": "0",
        "identify_led": "255",
        "auto_run": "0",
        "device_id": "A1B2",
        "label": "private-label",
    }
    value.update(changes)
    return value


class TargetSmokeContractTests(unittest.TestCase):
    def test_generic_smoke_cli_caps_info_and_redaction_contract(self):
        smoke = load_hil("target_smoke")

        for argv in (["--address", "private-address"],
                     ["--address", "private-address", "--expect-chip", ""]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                smoke._parse_args(argv)
        args = smoke._parse_args([
            "--address", "private-address", "--expect-chip", "future-port-x"
        ])
        self.assertEqual(args.expect_chip, "future-port-x")
        self.assertEqual(args.expect_agent, CURRENT_VERSION)

        caps = caps_fixture()
        smoke.validate_caps(caps, args.expect_chip, args.expect_agent)
        for key, bad in {
            "proto": "2", "agent": "9.9.9", "chip": "another-target",
            "mtu": "23", "chunk": "228", "window": "0",
            "free_mem": "0", "device_id": "not-uppercase-hex",
        }.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                smoke.validate_caps(
                    caps_fixture(**{key: bad}), args.expect_chip, args.expect_agent
                )

        info = caps_fixture(free_mem="64000")
        self.assertTrue(smoke.info_matches_device_info(caps, info))
        self.assertFalse(
            smoke.info_matches_device_info(caps, caps_fixture(label="changed"))
        )
        summary = smoke.format_result("PASS", caps)
        self.assertIn("TARGET SMOKE PASS", summary)
        for secret in ("private-address", "A1B2", "private-label"):
            self.assertNotIn(secret, summary)


class TargetRunStopContractTests(unittest.TestCase):
    def test_console_input_hil_executes_real_input_round_trip(self):
        bench = load_hil("target_run_stop")
        nonce = "stdinfeed01"
        source = bench.build_stdin_roundtrip_source(nonce)
        self.assertIn(b"input()", source)
        self.assertIn(("__PYBLE_STDIN_READY_%s__" % nonce).encode(), source)
        self.assertIn(("__PYBLE_STDIN_ECHO_%s__" % nonce).encode(), source)

        roundtrip = inspect.getsource(bench.run_stdin_roundtrip)
        for token in (
            "OP_RUN",
            "OP_CONSOLE_INPUT",
            "send_cmd_no_rsp",
            "OP_CONSOLE_DATA",
            "OP_RUN_STATE",
            "ST_RUNNING, ST_DONE",
        ):
            self.assertIn(token, roundtrip)
        self.assertNotIn("Fake", roundtrip)
        live_run = inspect.getsource(bench.run)
        self.assertIn("run_stdin_roundtrip", live_run)

    def test_print_flood_exact_stop_order_and_bounded_follow_up_contract(self):
        bench = load_hil("target_run_stop")
        with self.assertRaises(SystemExit):
            bench._parse_args(["--address", "private-address"])
        args = bench._parse_args([
            "--address", "private-address", "--expect-chip", "future-port-x"
        ])
        self.assertEqual(args.expect_agent, CURRENT_VERSION)
        self.assertEqual(bench.STOP_DEADLINE_S, 0.5)
        self.assertEqual(bench.PRINT_FLOOD_SOURCE, b"while True: print('x')")
        self.assertEqual(bench.FIXTURE_PATH, "/target_hil_run.py")

        stop_id = 21
        good = [
            (10.10, wire.Frame(wire.RSP, wire.OP_STOP, stop_id, b"\x00")),
            (10.20, wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x00")),
        ]
        self.assertAlmostEqual(
            bench.validate_stop_trace(good, stop_id, 10.0), 0.20
        )
        bad_traces = (
            list(reversed(good)),
            good + [(10.25, wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x00"))],
            good + [(10.15, wire.Frame(wire.RSP, wire.OP_STOP, stop_id, b"\x00"))],
            [(10.10, good[0][1]), (10.50, good[1][1])],
        )
        for trace in bad_traces:
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                bench.validate_stop_trace(trace, stop_id, 10.0)

        nonce = "c3deadbeef01"
        follow_up = bench.build_follow_up_source(nonce)
        self.assertIsInstance(follow_up, bytes)
        self.assertLessEqual(len(follow_up), 256)
        self.assertEqual(follow_up.count(nonce.encode("ascii")), 1)
        with self.assertRaises(ValueError):
            bench.build_follow_up_source("x" * 257)

        # The live workload must prove the same link survived STOP: submit the
        # bounded nonce RUN and consume console + terminal state on that link.
        source = inspect.getsource(bench.run_and_stop)
        self.assertRegex(source, r"\brun_nonce_follow_up\s*\(")
        follow_source = inspect.getsource(bench.run_nonce_follow_up)
        for token in ("OP_RUN", "OP_CONSOLE_DATA", "OP_RUN_STATE"):
            self.assertIn(token, follow_source)
        summary = bench.format_result("PASS", caps_fixture())
        self.assertIn("TARGET RUN/STOP PASS", summary)
        self.assertNotRegex(summary, r"private-address|A1B2|private-label")


class CurrentFirmwareIdentityMatrixTests(unittest.TestCase):
    def test_versions_lock_feeds_every_current_target_without_rewriting_history(self):
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lock["pyble"]["agent_version"], CURRENT_VERSION)
        self.assertEqual(
            lock["targets"],
            {name: CURRENT_TARGET_MATRIX[name][0] for name in list(CURRENT_TARGET_MATRIX)[:4]},
        )
        self.assertEqual(lock["targets_rp2"], {"rpi-pico2-w": "RPI_PICO2_W"})

        overlays = ROOT / "firmware" / "board_overlays"
        for target, (_build_target, chip) in CURRENT_TARGET_MATRIX.items():
            header = (overlays / target / "mpconfigboard.h").read_text(encoding="utf-8")
            with self.subTest(target=target):
                self.assertIn("PBLE_AGENT_VERSION", header)
                self.assertIn(chip, header)
                self.assertNotIn(CURRENT_VERSION, header)

        build = (ROOT / "firmware/scripts/build.sh").read_text(encoding="utf-8")
        build_rp2 = (ROOT / "firmware/scripts/build_rp2.sh").read_text(encoding="utf-8")
        for source in (build, build_rp2):
            self.assertIn("versions.lock", source)
            self.assertIn("agent_version", source)
            self.assertIn("AGENT_VER", source)
            self.assertTrue(
                "_version.py" in source,
                "each ESP/RP2 build path must generate frozen _version.py",
            )

        runtime_sources = (
            ROOT / "firmware/user_c_modules/pyble/pble_info.c",
            ROOT / "firmware/pyble/pyble_info.py",
            ROOT / "firmware/pyble/__init__.py",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_sources)
        self.assertNotIn(CURRENT_VERSION, combined)
        self.assertIn("PBLE_AGENT_VERSION", combined)
        self.assertIn("_version.AGENT_VERSION", combined)

        # Current-source standardization must not relabel retained historical
        # qualification or erase the recorded earlier source-candidate line.
        historical = json.loads((
            ROOT / "docs/validation/browser-flashing/v0.4.2-production.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(historical["release"]["version"], "0.4.2")
        firmware_spec = (ROOT / "docs/specifications/firmware.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            firmware_spec,
            r"Version `0\.5\.1` remains the\s+earlier",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
