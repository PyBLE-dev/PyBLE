#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Behavioral RED for v0.6.1 hardening-HIL orchestration.

These tests replace the physical operations with deterministic async probes.
They prove orchestration and configuration-opcode behavior only; they are not
physical HIL evidence.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HIL = HERE.parent / "hil"
BENCH_PATH = HIL / "v061_hardening_bench.py"
sys.path.insert(0, str(HIL))


SCENARIOS = (
    "transport-session",
    "fragment-hardening",
    "run-isolation",
    "resource-stability",
    "stdin-isolation",
    "configuration-durability",
    "filesystem-hardening",
)

SCENARIO_FUNCTIONS = (
    "run_transport_session",
    "run_fragment_hardening",
    "run_fresh_globals",
    "run_resource_stability",
    "run_stdin_isolation",
    "run_label_durability",
    "run_filesystem_hardening",
)


def load_bench():
    if not BENCH_PATH.is_file():
        raise AssertionError("missing v0.6.1 HIL bench: %s" % BENCH_PATH.name)
    spec = importlib.util.spec_from_file_location(
        "v061_hardening_bench_behavioral_probe",
        BENCH_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load %s" % BENCH_PATH.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def async_noop(*_args, **_kwargs):
    return None


class V061HilScenarioOrchestrationTests(unittest.TestCase):
    def exercise_run(self, bench, *, stop_at=None, failure_factory=None):
        observed = []
        publications = []

        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-orchestration-"
        ) as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            candidate.mkdir()
            erased = root / "erased-media.json"
            nonblank = root / "nonblank-media.json"
            for receipt in (erased, nonblank):
                receipt.write_text("{}\n", encoding="utf-8")
                receipt.chmod(0o600)
            args = SimpleNamespace(
                profile="esp32-4mb",
                address="private-address",
                expect_agent="0.6.1",
                candidate_dir=candidate,
                workspace_erased_receipt=erased,
                workspace_nonblank_receipt=nonblank,
                raw_log=root / "hardening.jsonl",
                result=root / "hardening-result.json",
                qualification_repo_root=ROOT,
                board_manufacturer="Espressif Systems",
                board_model="Electronically identified ESP32 development board",
                module_marking="ESP32-D0WD revision v1.0 (esptool)",
                # Legacy attributes keep this behavioral seam runnable against
                # the predecessor bench while the candidate-bound CLI is RED.
                require_workspace_provisioning=False,
                sacrificial_media=False,
            )

            def operation(name):
                async def probe(_state):
                    observed.append(name)
                    if name == stop_at:
                        if failure_factory is None:
                            raise AssertionError("missing failure factory")
                        raise failure_factory()

                return probe

            def publish(*positional, **keywords):
                publications.append((positional, keywords))
                output = Path(
                    keywords.get("result")
                    or keywords.get("output_path")
                    or args.result
                )
                if output.exists():
                    raise AssertionError("result existed before publication")
                output.write_bytes(b"behavioral publication probe\n")
                output.chmod(0o600)
                return output

            preflight = object()

            def token_publish(
                supplied_preflight,
                scenario_results,
                raw_log,
                result,
            ):
                if supplied_preflight is not preflight:
                    raise AssertionError("publication did not receive preflight token")
                return publish(
                    scenario_results=scenario_results,
                    raw_log=raw_log,
                    result=result,
                )

            with ExitStack() as stack:
                for scenario, function_name in zip(
                    SCENARIOS,
                    SCENARIO_FUNCTIONS,
                ):
                    stack.enter_context(
                        mock.patch.object(
                            bench,
                            function_name,
                            new=operation(scenario),
                        )
                    )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "workspace_prerequisite",
                        return_value="passed",
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "preflight_result_inputs",
                        return_value=preflight,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "preflight_board_workspace",
                        new=async_noop,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "write_private_result",
                        new=publish,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "write_private_result_from_preflight",
                        new=token_publish,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(bench, "_best_effort_stop", new=async_noop)
                )
                stack.enter_context(
                    mock.patch.object(bench, "_disconnect", new=async_noop)
                )
                stack.enter_context(mock.patch("builtins.print"))
                try:
                    outcome = asyncio.run(bench.run(args))
                except BaseException as exc:  # includes the interruption probe.
                    outcome = exc

            result_exists = args.result.exists()

        return outcome, observed, publications, result_exists

    def test_exact_seven_scenarios_run_once_in_order_before_one_publication(self):
        bench = load_bench()
        self.assertEqual(tuple(bench.SCENARIO_ORDER), SCENARIOS)

        outcome, observed, publications, result_exists = self.exercise_run(bench)

        self.assertEqual(outcome, 0)
        self.assertEqual(observed, list(SCENARIOS))
        self.assertEqual(
            len(publications),
            1,
            "all seven passes must publish exactly one private result",
        )
        self.assertTrue(result_exists)

    def test_every_failure_cut_stops_without_retry_or_result_publication(self):
        failure_kinds = (
            ("bench-failure", lambda bench: lambda: bench.BenchFailure("failed")),
            ("exception", lambda _bench: lambda: RuntimeError("failed")),
            ("interrupt", lambda _bench: lambda: KeyboardInterrupt()),
        )
        for stop_index, stop_at in enumerate(SCENARIOS):
            for failure_name, make_factory in failure_kinds:
                with self.subTest(stop_at=stop_at, failure=failure_name):
                    bench = load_bench()
                    outcome, observed, publications, result_exists = self.exercise_run(
                        bench,
                        stop_at=stop_at,
                        failure_factory=make_factory(bench),
                    )
                    self.assertEqual(
                        observed,
                        list(SCENARIOS[: stop_index + 1]),
                        "a failed scenario was retried or a later scenario ran",
                    )
                    self.assertTrue(
                        isinstance(outcome, BaseException)
                        or (type(outcome) is int and outcome != 0),
                        "a failed/interrupted orchestration reported success",
                    )
                    self.assertEqual(publications, [])
                    self.assertFalse(result_exists)


class FakeConfigurationCentral:
    def __init__(self, bench, configuration, events):
        self.bench = bench
        self.configuration = configuration
        self.events = events
        self.is_connected = True

    async def send_cmd(self, opcode, command_id, payload=b"", **_kwargs):
        self.events.append(("opcode", opcode))
        if opcode == self.bench.wire.OP_SET_AUTORUN and payload:
            self.configuration["auto_run"] = str(payload[0])
        if opcode == self.bench.wire.OP_SET_IDENTIFY_LED and payload:
            self.configuration["identify_led"] = str(payload[0])
        return self.bench.wire.Frame(
            self.bench.wire.RSP,
            opcode,
            command_id,
            bytes((self.bench.wire.ST_OK,)),
        )


class V061IdentifyDurabilityBehaviorTests(unittest.TestCase):
    def exercise_identify_profile(self, has_identify):
        bench = load_bench()
        events = []
        configuration = {
            "label": "owner-label",
            "auto_run": "1",
            "has_identify": "1" if has_identify else "0",
            "identify_led": "7" if has_identify else "255",
        }
        args = SimpleNamespace(
            profile="esp32-4mb",
            address="private-address",
            expect_agent="0.6.1",
        )
        state = bench.LiveState(args)
        state.central = FakeConfigurationCentral(bench, configuration, events)

        def caps():
            return {
                "chip": "esp32",
                "agent": "0.6.1",
                "device_id": "PRIVATE",
                **configuration,
            }

        async def device_info(_state):
            return dict(caps())

        async def set_label(_state, payload, expected):
            if expected == bench.wire.ST_OK:
                configuration["label"] = payload.decode("utf-8", errors="strict")
            return bench.wire.Frame(
                bench.wire.RSP,
                bench.wire.OP_SET_LABEL,
                1,
                bytes((expected,)),
            )

        async def reboot(_state, _expected_name):
            events.append(("reboot", None))
            return dict(caps())

        with (
            mock.patch.object(bench, "_device_info", new=device_info),
            mock.patch.object(bench, "_set_label", new=set_label),
            mock.patch.object(
                bench,
                "_soft_reboot_to_advertisement",
                new=reboot,
            ),
        ):
            asyncio.run(bench.run_label_durability(state))

        opcodes = [value for kind, value in events if kind == "opcode"]
        identify_positions = [
            index
            for index, event in enumerate(events)
            if event == ("opcode", bench.wire.OP_IDENTIFY)
        ]
        reboot_positions = [
            index
            for index, event in enumerate(events)
            if event[0] == "reboot"
        ]
        return bench, configuration, opcodes, identify_positions, reboot_positions

    def test_identify_capable_profile_identifies_once_before_and_after_reboot(self):
        bench, configuration, opcodes, identifies, reboots = (
            self.exercise_identify_profile(True)
        )

        self.assertNotIn(bench.wire.OP_SET_IDENTIFY_LED, opcodes)
        self.assertEqual(len(identifies), 2)
        self.assertTrue(
            any(identifies[0] < reboot < identifies[1] for reboot in reboots),
            "Identify was not proven on both sides of a reboot",
        )
        self.assertEqual(configuration["identify_led"], "7")
        self.assertEqual(configuration["label"], "owner-label")
        self.assertEqual(configuration["auto_run"], "1")

    def test_non_identify_profile_invents_no_identify_and_never_reconfigures_led(self):
        bench, configuration, opcodes, identifies, _reboots = (
            self.exercise_identify_profile(False)
        )

        self.assertNotIn(bench.wire.OP_SET_IDENTIFY_LED, opcodes)
        self.assertNotIn(bench.wire.OP_IDENTIFY, opcodes)
        self.assertEqual(identifies, [])
        self.assertEqual(configuration["identify_led"], "255")
        self.assertEqual(configuration["label"], "owner-label")
        self.assertEqual(configuration["auto_run"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
