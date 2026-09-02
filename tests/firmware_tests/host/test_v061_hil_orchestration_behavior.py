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

            preflight_token = object()

            def token_publish(
                preflight,
                scenario_results,
                raw_log,
                result,
            ):
                if preflight is not preflight_token:
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
                        return_value=preflight_token,
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


class FakeRebootCentral:
    def __init__(self, bench, events):
        self.bench = bench
        self.events = events
        self.is_connected = True

    async def send_cmd(self, opcode, command_id, payload=b"", **_kwargs):
        self.events.append(("command", opcode, command_id, bytes(payload)))
        return self.bench.wire.Frame(
            self.bench.wire.RSP,
            opcode,
            command_id,
            bytes((self.bench.wire.ST_OK,)),
        )


class V061VmResetOrchestrationTests(unittest.TestCase):
    def test_vm_rotation_probes_use_bounded_executable_source_and_exact_markers(self):
        bench = load_bench()
        captured = []
        state = bench.LiveState(
            SimpleNamespace(
                profile="esp32-4mb",
                address="private-address",
                expect_agent="0.6.1",
            )
        )

        async def run_program(_state, mode, source, description):
            source = bytes(source)
            compile(source, "<v061-vm-probe>", "exec")
            captured.append((mode, source, description))
            if "setup" in description:
                return bench.VM_ROTATION_SET_MARKER
            return bench.VM_ROTATION_FRESH_MARKER

        with mock.patch.object(bench, "_run_program", new=run_program):
            asyncio.run(bench._set_vm_rotation_sentinel(state))
            asyncio.run(bench._assert_vm_rotation_sentinel_absent(state))

        self.assertEqual([row[0] for row in captured], [1, 1])
        self.assertTrue(all(len(row[1]) <= 256 for row in captured))
        self.assertTrue(
            all(
                bench.VM_ROTATION_SENTINEL.encode("ascii") in row[1]
                for row in captured
            )
        )
        self.assertIn(bench.VM_ROTATION_SET_MARKER, captured[0][1])
        self.assertIn(b"not in sys.path", captured[1][1])

    def test_soft_reboot_helper_reconnects_without_implicitly_negotiating(self):
        bench = load_bench()
        helper = getattr(bench, "_soft_reboot_connect_unnegotiated", None)
        self.assertTrue(
            callable(helper),
            "[red] the HIL runner needs a reusable acknowledged reboot seam "
            "that deliberately leaves the successor session unnegotiated",
        )
        if not callable(helper):
            return

        events = []
        args = SimpleNamespace(
            profile="esp32-4mb",
            address="private-address",
            expect_agent="0.6.1",
        )
        state = bench.LiveState(args)
        old_central = FakeRebootCentral(bench, events)
        new_central = FakeRebootCentral(bench, events)
        state.central = old_central

        async def wait_disconnected(central, timeout_s=None):
            self.assertIs(central, old_central)
            events.append(("disconnected", timeout_s))
            central.is_connected = False

        async def wait_advertisement(received_state, name):
            self.assertIs(received_state, state)
            events.append(("advertisement", name))

        async def connect(received_state):
            self.assertIs(received_state, state)
            self.assertIsNone(state.central)
            events.append(("connect", None))
            state.central = new_central
            return new_central

        async def forbidden_negotiate(_state):
            raise AssertionError("reboot helper negotiated before the scenario probe")

        with (
            mock.patch.object(bench, "_wait_disconnected", new=wait_disconnected),
            mock.patch.object(bench, "_wait_advertisement", new=wait_advertisement),
            mock.patch.object(bench, "_connect", new=connect),
            mock.patch.object(bench, "_negotiate", new=forbidden_negotiate),
        ):
            returned = asyncio.run(helper(state, "PyBLE-1234"))

        self.assertIs(returned, new_central)
        self.assertIs(state.central, new_central)
        self.assertEqual(events[0][0:2], ("command", bench.wire.OP_SOFT_REBOOT))
        self.assertEqual(
            [event[0] for event in events],
            ["command", "disconnected", "advertisement", "connect"],
        )


class FakeActiveGetCentral:
    def __init__(self, bench, expected, *, end_before_write_receipt=False):
        self.bench = bench
        self.expected = bytes(expected)
        self.end_before_write_receipt = end_before_write_receipt
        self.events = []
        self.commands = []
        self.write_receipts = 0

    def event_cursor(self):
        return len(self.events)

    def events_since(self, cursor):
        return len(self.events), self.events[cursor:]

    def _append_download(self):
        midpoint = len(self.expected) // 2
        for offset, data in (
            (0, self.expected[:midpoint]),
            (midpoint, self.expected[midpoint:]),
        ):
            self.events.append(
                self.bench.wire.Frame(
                    self.bench.wire.EVT,
                    self.bench.wire.OP_FILE_GET_DATA,
                    0,
                    offset.to_bytes(4, "little") + data,
                )
            )
        self.events.append(
            self.bench.wire.Frame(
                self.bench.wire.EVT,
                self.bench.wire.OP_FILE_GET_END,
                0,
                self.bench.wire.crc32(self.expected).to_bytes(4, "little"),
            )
        )

    async def send_cmd(
        self,
        opcode,
        command_id,
        payload=b"",
        on_written=None,
        **_kwargs,
    ):
        self.commands.append((opcode, command_id, bytes(payload)))
        if opcode == self.bench.wire.OP_FILE_GET_BEGIN:
            return self.bench.wire.Frame(
                self.bench.wire.RSP,
                opcode,
                command_id,
                bytes((self.bench.wire.ST_OK,))
                + len(self.expected).to_bytes(4, "little"),
            )
        if self.end_before_write_receipt:
            self._append_download()
        if on_written is not None:
            on_written()
            self.write_receipts += 1
        if not self.end_before_write_receipt:
            self._append_download()
        return self.bench.wire.Frame(
            self.bench.wire.RSP,
            opcode,
            command_id,
            bytes((self.bench.wire.ST_EBUSY,)),
        )


class V061ActiveGetOrchestrationTests(unittest.TestCase):
    def test_active_get_probe_binds_write_before_end_and_verifies_all_bytes(self):
        bench = load_bench()
        helper = getattr(bench, "_get_with_active_probe", None)
        self.assertTrue(
            callable(helper),
            "[red] filesystem HIL needs an active-GET admission probe",
        )
        if not callable(helper):
            return

        expected = b"0123456789abcdef"
        state = bench.LiveState(
            SimpleNamespace(profile="esp32-4mb", expect_agent="0.6.1")
        )
        state.central = FakeActiveGetCentral(bench, expected)
        asyncio.run(
            helper(
                state,
                "/v061_hil/active_get.bin",
                expected,
                bench.wire.OP_FILE_DELETE,
                bench.pble_bench.path_payload("/v061_hil/delete.bin"),
                bench.wire.ST_EBUSY,
                "active-GET DELETE",
            )
        )
        self.assertEqual(state.central.write_receipts, 1)
        self.assertEqual(
            [command[0] for command in state.central.commands],
            [bench.wire.OP_FILE_GET_BEGIN, bench.wire.OP_FILE_DELETE],
        )

    def test_active_get_probe_rejects_a_command_written_after_get_end(self):
        bench = load_bench()
        helper = getattr(bench, "_get_with_active_probe", None)
        self.assertTrue(callable(helper))
        if not callable(helper):
            return

        expected = b"0123456789abcdef"
        state = bench.LiveState(
            SimpleNamespace(profile="esp32-4mb", expect_agent="0.6.1")
        )
        state.central = FakeActiveGetCentral(
            bench,
            expected,
            end_before_write_receipt=True,
        )
        with self.assertRaises(bench.BenchFailure):
            asyncio.run(
                helper(
                    state,
                    "/v061_hil/active_get.bin",
                    expected,
                    bench.wire.OP_FILE_DELETE,
                    bench.pble_bench.path_payload("/v061_hil/delete.bin"),
                    bench.wire.ST_EBUSY,
                    "late active-GET DELETE",
                )
            )


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
