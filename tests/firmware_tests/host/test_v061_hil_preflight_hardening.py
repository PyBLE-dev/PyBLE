#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Focused REDs for v0.6.1 HIL preflight and publication hardening.

These tests exercise host-only seams with synthetic inputs.  They are not
physical HIL evidence and cannot qualify a firmware release.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, redirect_stderr
import importlib.util
import inspect
from io import StringIO
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
HIL = HERE.parent / "hil"
BENCH_PATH = HIL / "v061_hardening_bench.py"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HIL))

import test_v061_hardening_release_gate as gate_fixture  # noqa: E402


GATE = gate_fixture.GATE
HAVE_GATE = gate_fixture.HAVE_GATE

QUALIFICATION_SOURCE_PATHS = (
    "firmware/qualification/v061_hardening_release_gate.py",
    "tests/firmware_tests/hil/v061_workspace_acquire.py",
    "tests/firmware_tests/hil/_v061_workspace_hardware.py",
    "tests/firmware_tests/hil/_v061_workspace_pico.py",
    "tests/firmware_tests/hil/v061_hardening_bench.py",
    "tests/firmware_tests/hil/_pble_bench.py",
    "tests/firmware_tests/hil/_pble_central.py",
    "tests/firmware_tests/hil/_pble_wire.py",
    "tests/firmware_tests/hil/target_smoke.py",
    "firmware/qualification/oi1-gates.json",
    "firmware/versions.lock",
)

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


def load_bench():
    spec = importlib.util.spec_from_file_location(
        "pyble_v061_hardening_preflight_probe",
        BENCH_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load v0.6.1 hardening bench")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def identity_argv(profile_id: str) -> list[str]:
    identity = PROFILE_BOARD_IDENTITIES[profile_id]
    return [
        "--board-manufacturer",
        identity["board_manufacturer"],
        "--board-model",
        identity["board_model"],
        "--module-marking",
        identity["module_marking"],
    ]


def live_argv(root: Path, profile_id: str = "esp32-4mb") -> list[str]:
    candidate = root / "candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    for name in ("erased.json", "nonblank.json"):
        receipt = root / name
        if not receipt.exists():
            private_write(receipt, b"{}\n")
    return [
        "--profile",
        profile_id,
        "--address",
        "private-address",
        "--candidate-dir",
        os.fspath(candidate),
        "--workspace-erased-receipt",
        os.fspath(root / "erased.json"),
        "--workspace-nonblank-receipt",
        os.fspath(root / "nonblank.json"),
        "--raw-log",
        os.fspath(root / "hardening.jsonl"),
        "--result",
        os.fspath(root / "hardening-result.json"),
        *identity_argv(profile_id),
    ]


def make_clean_qualification_checkout(root: Path) -> Path:
    """Create a clean synthetic checkout containing the exact source closure."""

    checkout = root / "qualification-checkout"
    checkout.mkdir()
    for relative in QUALIFICATION_SOURCE_PATHS:
        source = ROOT / relative
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    commands = (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "PyBLE test"),
        ("git", "config", "user.email", "tests@pyble.invalid"),
        ("git", "add", *QUALIFICATION_SOURCE_PATHS),
        ("git", "commit", "-q", "-m", "synthetic qualification checkout"),
    )
    for command in commands:
        subprocess.run(command, cwd=checkout, check=True, capture_output=True)
    return checkout


def qualification_identity(checkout: Path) -> tuple[str, str]:
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    digest = gate_fixture.hashlib.sha256(
        (checkout / "tests/firmware_tests/hil/v061_hardening_bench.py").read_bytes()
    ).hexdigest()
    return commit, digest


def rewrite_receipt_qualification(fixture: dict[str, object], checkout: Path) -> None:
    commit, executable_digest = qualification_identity(checkout)
    for key in ("erased", "nonblank"):
        path = Path(fixture[key])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["qualification_source_commit"] = commit
        value["qualification_executable_sha256"] = executable_digest
        acquisition_path = path.with_name(path.stem + "-acquisition.json")
        acquisition = json.loads(acquisition_path.read_text())
        acquisition["qualification_source_commit"] = commit
        acquisition["qualification_executable_sha256"] = executable_digest
        acquisition_raw = gate_fixture.canonical_json_bytes(acquisition)
        private_write(acquisition_path, acquisition_raw)
        value["acquisition_sha256"] = gate_fixture.hashlib.sha256(acquisition_raw).hexdigest()
        private_write(path, gate_fixture.canonical_json_bytes(value))


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is unavailable")
class V061ExclusivePublicationFinalReopenTests(unittest.TestCase):
    def test_visible_replacement_during_callback_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-final-reopen-") as tmp:
            output = Path(tmp) / "result.json"
            attacker = b"attacker-owned replacement\n"

            def replace_visible_name() -> None:
                output.unlink()
                private_write(output, attacker)

            with self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive(
                    output,
                    b"writer-owned evidence\n",
                    post_write_check=replace_visible_name,
                )
            self.assertEqual(
                output.read_bytes(),
                attacker,
                "failure cleanup must not unlink an attacker's replacement inode",
            )

    def test_hardlink_added_during_callback_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-final-link-") as tmp:
            root = Path(tmp)
            output = root / "result.json"
            second_link = root / "attacker-link.json"
            raw = b"writer-owned evidence\n"

            def add_link() -> None:
                os.link(output, second_link)

            with self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive(
                    output,
                    raw,
                    post_write_check=add_link,
                )
            self.assertFalse(
                output.exists(),
                "the writer-owned output name must be removed after link attack",
            )
            self.assertEqual(second_link.read_bytes(), raw)


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is unavailable")
class V061QualificationCheckoutClosureTests(unittest.TestCase):
    def test_every_authored_runtime_dependency_must_match_head(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-source-closure-") as tmp:
            checkout = make_clean_qualification_checkout(Path(tmp))
            baseline = GATE._qualification_snapshot(checkout)
            self.assertEqual(baseline["commit"], qualification_identity(checkout)[0])

            for relative in QUALIFICATION_SOURCE_PATHS:
                with self.subTest(relative=relative):
                    path = checkout / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# uncommitted qualification mutation\n")
                    try:
                        with self.assertRaises(GATE.QualificationError):
                            GATE._qualification_snapshot(checkout)
                    finally:
                        path.write_bytes(original)


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is unavailable")
class V061ResultInputLeaseSeamTests(unittest.TestCase):
    def test_gate_exposes_token_bound_preflight_and_publication_helpers(self):
        preflight = getattr(GATE, "preflight_result_inputs", None)
        publish = getattr(GATE, "create_result_from_preflight", None)
        self.assertTrue(
            callable(preflight),
            "[red] live HIL cannot validate all long-lived inputs before BLE",
        )
        self.assertTrue(
            callable(publish),
            "[red] final publication cannot consume the exact preflight snapshot",
        )
        if callable(preflight):
            self.assertEqual(
                set(inspect.signature(preflight).parameters),
                {
                    "candidate_dir",
                    "profile_id",
                    "workspace_erased_receipt",
                    "workspace_nonblank_receipt",
                    "qualification_repo_root",
                },
            )
        if callable(publish):
            self.assertEqual(
                set(inspect.signature(publish).parameters),
                {"preflight", "scenario_results", "raw_log", "output_path"},
            )


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is unavailable")
class V061QualificationOutputBoundaryTests(unittest.TestCase):
    def test_workspace_receipt_and_raw_log_cannot_live_in_qualification_checkout(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-output-boundary-") as tmp:
            root = Path(tmp)
            checkout = make_clean_qualification_checkout(root)
            fixture = gate_fixture.writer_fixture(root / "inputs", "esp32-c3-4mb")
            evidence = checkout / "private-evidence"
            output = evidence / "erased.json"
            raw = evidence / "erased-raw.jsonl"
            private_write(
                raw,
                gate_fixture.workspace_raw_log(
                    gate_fixture.WORKSPACE_ORDER[0]
                ),
            )

            with self.assertRaises(GATE.QualificationError):
                GATE.create_workspace_receipt(
                    candidate_dir=fixture["candidate"],
                    profile_id="esp32-c3-4mb",
                    observation_kind=gate_fixture.WORKSPACE_ORDER[0],
                    raw_boot_log=raw,
                    output_path=output,
                    qualification_repo_root=checkout,
                )
            self.assertFalse(output.exists())

    def test_hardening_result_cannot_live_in_qualification_checkout(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-result-boundary-") as tmp:
            root = Path(tmp)
            checkout = make_clean_qualification_checkout(root)
            fixture = gate_fixture.writer_fixture(root / "inputs", "esp32-c3-4mb")
            rewrite_receipt_qualification(fixture, checkout)
            output = checkout / "private-evidence" / "hardening-result.json"
            output.parent.mkdir()

            with self.assertRaises(GATE.QualificationError):
                GATE.create_result(
                    candidate_dir=fixture["candidate"],
                    profile_id="esp32-c3-4mb",
                    scenario_results=gate_fixture.scenario_results(),
                    workspace_erased_receipt=fixture["erased"],
                    workspace_nonblank_receipt=fixture["nonblank"],
                    raw_log=fixture["raw_log"],
                    output_path=output,
                    qualification_repo_root=checkout,
                )
            self.assertFalse(output.exists())

    def test_hardening_raw_log_cannot_live_in_qualification_checkout(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-log-boundary-") as tmp:
            root = Path(tmp)
            checkout = make_clean_qualification_checkout(root)
            fixture = gate_fixture.writer_fixture(root / "inputs", "esp32-c3-4mb")
            rewrite_receipt_qualification(fixture, checkout)
            raw = checkout / "private-evidence" / "hardening.jsonl"
            private_write(raw, Path(fixture["raw_log"]).read_bytes())

            with self.assertRaises(GATE.QualificationError):
                GATE.create_result(
                    candidate_dir=fixture["candidate"],
                    profile_id="esp32-c3-4mb",
                    scenario_results=gate_fixture.scenario_results(),
                    workspace_erased_receipt=fixture["erased"],
                    workspace_nonblank_receipt=fixture["nonblank"],
                    raw_log=raw,
                    output_path=fixture["output"],
                    qualification_repo_root=checkout,
                )
            self.assertFalse(Path(fixture["output"]).exists())


class V061ExactProfileAttributionTests(unittest.TestCase):
    def test_live_cli_requires_the_frozen_oi_board_identity_for_each_profile(self):
        bench = load_bench()
        self.assertEqual(
            getattr(bench, "PROFILE_BOARD_IDENTITIES", None),
            PROFILE_BOARD_IDENTITIES,
            "[red] hardening HIL has no exact-profile operator attestation map",
        )

        with tempfile.TemporaryDirectory(prefix="pyble-v061-profile-id-") as tmp:
            root = Path(tmp)
            for profile_id, expected in PROFILE_BOARD_IDENTITIES.items():
                with self.subTest(profile_id=profile_id):
                    profile_root = root / profile_id
                    argv = live_argv(profile_root, profile_id)
                    try:
                        args = bench._parse_args(argv)
                    except SystemExit as exc:
                        self.fail(
                            "[red] exact OI identity was rejected for %s: %s"
                            % (profile_id, exc)
                        )
                    self.assertEqual(args.board_manufacturer, expected["board_manufacturer"])
                    self.assertEqual(args.board_model, expected["board_model"])
                    self.assertEqual(args.module_marking, expected["module_marking"])

                    for option in (
                        "--board-manufacturer",
                        "--board-model",
                        "--module-marking",
                    ):
                        index = argv.index(option)
                        missing = argv[:index] + argv[index + 2 :]
                        with self.subTest(profile_id=profile_id, missing=option):
                            with self.assertRaises(SystemExit):
                                bench._parse_args(missing)

                        wrong = list(argv)
                        wrong[index + 1] = "operator-selected different hardware"
                        with self.subTest(profile_id=profile_id, wrong=option):
                            with self.assertRaises(SystemExit):
                                bench._parse_args(wrong)

    def test_live_outputs_are_rejected_inside_the_qualification_checkout(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-live-inputs-") as tmp:
            root = Path(tmp)
            base = live_argv(root)
            with tempfile.TemporaryDirectory(
                dir=ROOT,
                prefix=".pyble-v061-live-output-red-",
            ) as checkout_tmp:
                checkout_output = Path(checkout_tmp)
                for option, name in (
                    ("--raw-log", "hardening.jsonl"),
                    ("--result", "hardening-result.json"),
                ):
                    argv = list(base)
                    argv[argv.index(option) + 1] = os.fspath(checkout_output / name)
                    stderr = StringIO()
                    with self.subTest(option=option), redirect_stderr(stderr):
                        with self.assertRaises(SystemExit):
                            bench._parse_args(argv)
                        self.assertIn("qualification", stderr.getvalue().lower())


class V061WorkspaceReceiptCliTests(unittest.TestCase):
    def receipt_argv(
        self,
        root: Path,
        *,
        output: Path | None = None,
        raw: Path | None = None,
    ) -> tuple[list[str], dict[str, object]]:
        profile_id = "esp32-c3-4mb"
        fixture = gate_fixture.writer_fixture(root / "inputs", profile_id)
        selected_output = output or (root / "new-erased-receipt.json")
        selected_raw = raw or selected_output.with_name(
            selected_output.stem + "-raw.jsonl"
        )
        if not selected_raw.exists():
            private_write(
                selected_raw,
                gate_fixture.workspace_raw_log(gate_fixture.WORKSPACE_ORDER[0]),
            )
        argv = [
            "--create-workspace-receipt",
            "--profile",
            profile_id,
            "--candidate-dir",
            os.fspath(fixture["candidate"]),
            "--observation-kind",
            gate_fixture.WORKSPACE_ORDER[0],
            "--raw-boot-log",
            os.fspath(selected_raw),
            "--receipt-output",
            os.fspath(selected_output),
        ]
        return argv, fixture

    def test_same_executable_dispatches_the_separate_receipt_creation_mode(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-receipt-cli-") as tmp:
            root = Path(tmp)
            argv, fixture = self.receipt_argv(root)
            try:
                args = bench._parse_args(argv)
            except SystemExit as exc:
                self.fail("[red] workspace-receipt CLI mode is missing: %s" % exc)
            self.assertTrue(args.create_workspace_receipt)
            self.assertEqual(args.profile, "esp32-c3-4mb")
            self.assertEqual(
                args.observation_kind,
                gate_fixture.WORKSPACE_ORDER[0],
            )
            self.assertEqual(args.raw_boot_log, root / "new-erased-receipt-raw.jsonl")
            self.assertEqual(args.receipt_output, root / "new-erased-receipt.json")
            self.assertFalse(hasattr(args, "address") and args.address)

            with mock.patch.object(
                bench.hardening_gate,
                "create_workspace_receipt",
                return_value=args.receipt_output,
            ) as create, mock.patch.object(
                bench.asyncio,
                "run",
                side_effect=AssertionError("receipt mode attempted a BLE run"),
            ):
                self.assertEqual(bench.main(argv), 0)
            create.assert_called_once_with(
                candidate_dir=Path(fixture["candidate"]),
                profile_id="esp32-c3-4mb",
                observation_kind=gate_fixture.WORKSPACE_ORDER[0],
                raw_boot_log=args.raw_boot_log,
                output_path=args.receipt_output,
                qualification_repo_root=ROOT,
            )

    def test_receipt_mode_requires_only_its_exact_bounded_inputs(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-receipt-required-") as tmp:
            argv, _fixture = self.receipt_argv(Path(tmp))
            # A generic live-mode parse failure must not make the individual
            # receipt-mode required-input assertions pass vacuously.
            try:
                bench._parse_args(argv)
            except SystemExit as exc:
                self.fail("[red] receipt-mode base CLI is unavailable: %s" % exc)
            required = (
                "--profile",
                "--candidate-dir",
                "--observation-kind",
                "--raw-boot-log",
                "--receipt-output",
            )
            for option in required:
                index = argv.index(option)
                missing = argv[:index] + argv[index + 2 :]
                with self.subTest(missing=option), self.assertRaises(SystemExit):
                    bench._parse_args(missing)
            with self.assertRaises(SystemExit):
                bench._parse_args([*argv, "--address", "private-address"])

    def test_receipt_and_raw_outputs_are_rejected_inside_qualification_checkout(self):
        bench = load_bench()
        with tempfile.TemporaryDirectory(prefix="pyble-v061-receipt-inputs-") as tmp:
            root = Path(tmp)
            with tempfile.TemporaryDirectory(
                dir=ROOT,
                prefix=".pyble-v061-receipt-output-red-",
            ) as checkout_tmp:
                output = Path(checkout_tmp) / "erased.json"
                raw = Path(checkout_tmp) / "erased-raw.jsonl"
                argv, _fixture = self.receipt_argv(root, output=output, raw=raw)
                stderr = StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit):
                        bench._parse_args(argv)
                self.assertIn("qualification", stderr.getvalue().lower())


class FakeWorkspaceCentral:
    def __init__(self, bench, statuses):
        self.bench = bench
        self.statuses = dict(statuses)
        self.requests = []
        self.is_connected = True

    async def send_cmd(self, opcode, command_id, payload=b"", **_kwargs):
        if opcode != self.bench.wire.OP_FILE_STAT:
            raise AssertionError("workspace preflight issued a mutating opcode")
        size = int.from_bytes(payload[:2], "little")
        path = payload[2 : 2 + size].decode("utf-8", errors="strict")
        if 2 + size != len(payload):
            raise AssertionError("workspace preflight path was malformed")
        self.requests.append((opcode, path))
        status = self.statuses.get(path, self.bench.wire.ST_ENOENT)
        return self.bench.wire.Frame(
            self.bench.wire.RSP,
            opcode,
            command_id,
            bytes((status,)),
        )


class V061BoardWorkspacePreflightTests(unittest.TestCase):
    def test_only_absent_scratch_and_main_are_admitted_without_mutation(self):
        bench = load_bench()
        preflight = getattr(bench, "preflight_board_workspace", None)
        self.assertTrue(
            callable(preflight),
            "[red] HIL has no no-delete board workspace preflight",
        )
        if not callable(preflight):
            return

        state = bench.LiveState(
            SimpleNamespace(profile="esp32-4mb", expect_agent="0.6.1")
        )
        state.caps = {"chip": "esp32", "agent": "0.6.1"}
        state.central = FakeWorkspaceCentral(bench, {})
        asyncio.run(preflight(state))
        self.assertEqual(
            state.central.requests,
            [
                (bench.wire.OP_FILE_STAT, "/v061_hil"),
                (bench.wire.OP_FILE_STAT, "/main.py"),
            ],
        )

        for present in ("/v061_hil", "/main.py"):
            with self.subTest(present=present):
                state = bench.LiveState(
                    SimpleNamespace(profile="esp32-4mb", expect_agent="0.6.1")
                )
                state.caps = {"chip": "esp32", "agent": "0.6.1"}
                state.central = FakeWorkspaceCentral(
                    bench,
                    {present: bench.wire.ST_OK},
                )
                with self.assertRaises(bench.BenchFailure):
                    asyncio.run(preflight(state))
                self.assertTrue(
                    all(
                        opcode == bench.wire.OP_FILE_STAT
                        for opcode, _path in state.central.requests
                    )
                )


class V061LivePreflightOrchestrationTests(unittest.TestCase):
    def make_args(self, root: Path) -> SimpleNamespace:
        candidate = root / "candidate"
        candidate.mkdir()
        erased = root / "erased.json"
        nonblank = root / "nonblank.json"
        for receipt in (erased, nonblank):
            private_write(receipt, b"{}\n")
        identity = PROFILE_BOARD_IDENTITIES["esp32-4mb"]
        return SimpleNamespace(
            profile="esp32-4mb",
            address="private-address",
            expect_agent="0.6.1",
            candidate_dir=candidate,
            workspace_erased_receipt=erased,
            workspace_nonblank_receipt=nonblank,
            raw_log=root / "hardening.jsonl",
            result=root / "hardening-result.json",
            qualification_repo_root=ROOT,
            board_manufacturer=identity["board_manufacturer"],
            board_model=identity["board_model"],
            module_marking=identity["module_marking"],
        )

    def test_invalid_candidate_and_receipts_stop_before_any_live_scenario(self):
        bench = load_bench()
        observed = []

        async def scenario(_state):
            observed.append("live-scenario")

        with tempfile.TemporaryDirectory(prefix="pyble-v061-early-preflight-") as tmp:
            args = self.make_args(Path(tmp))
            with ExitStack() as stack:
                for name in (
                    "run_transport_session",
                    "run_fragment_hardening",
                    "run_fresh_globals",
                    "run_resource_stability",
                    "run_stdin_isolation",
                    "run_label_durability",
                    "run_filesystem_hardening",
                ):
                    stack.enter_context(mock.patch.object(bench, name, new=scenario))
                stack.enter_context(
                    mock.patch.object(bench, "_best_effort_stop", new=mock.AsyncMock())
                )
                stack.enter_context(
                    mock.patch.object(bench, "_disconnect", new=mock.AsyncMock())
                )
                stack.enter_context(mock.patch("builtins.print"))
                outcome = asyncio.run(bench.run(args))

            self.assertNotEqual(outcome, 0)
            self.assertEqual(
                observed,
                [],
                "candidate and both receipts must be fully validated before BLE work",
            )
            self.assertFalse(args.raw_log.exists() or args.result.exists())

    def test_same_opaque_snapshot_flows_from_preflight_to_publication(self):
        bench = load_bench()
        token = object()
        events = []

        def host_preflight(args):
            events.append("host-preflight")
            return token

        async def board_preflight(_state):
            events.append("board-preflight")

        def operation(name):
            async def probe(_state):
                events.append(name)

            return probe

        def publish(preflight, scenario_results, raw_log, result):
            self.assertIs(preflight, token)
            self.assertEqual(tuple(scenario_results), gate_fixture.SCENARIO_ORDER)
            self.assertEqual(Path(raw_log).suffix, ".jsonl")
            self.assertEqual(Path(result).suffix, ".json")
            events.append("token-publication")
            private_write(Path(result), b"token publication probe\n")
            return Path(result)

        def legacy_publish(*_args, **_kwargs):
            raise AssertionError("run bypassed token-bound publication")

        with tempfile.TemporaryDirectory(prefix="pyble-v061-token-flow-") as tmp:
            args = self.make_args(Path(tmp))
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "preflight_result_inputs",
                        new=host_preflight,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "preflight_board_workspace",
                        new=board_preflight,
                        create=True,
                    )
                )
                for name, function_name in zip(
                    gate_fixture.SCENARIO_ORDER,
                    (
                        "run_transport_session",
                        "run_fragment_hardening",
                        "run_fresh_globals",
                        "run_resource_stability",
                        "run_stdin_isolation",
                        "run_label_durability",
                        "run_filesystem_hardening",
                    ),
                ):
                    stack.enter_context(
                        mock.patch.object(bench, function_name, new=operation(name))
                    )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "write_private_result_from_preflight",
                        new=publish,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        bench,
                        "write_private_result",
                        new=legacy_publish,
                    )
                )
                stack.enter_context(
                    mock.patch.object(bench, "_best_effort_stop", new=mock.AsyncMock())
                )
                stack.enter_context(
                    mock.patch.object(bench, "_disconnect", new=mock.AsyncMock())
                )
                stack.enter_context(mock.patch("builtins.print"))
                outcome = asyncio.run(bench.run(args))

            self.assertEqual(outcome, 0)
            self.assertEqual(
                events,
                [
                    "host-preflight",
                    "transport-session",
                    "board-preflight",
                    "fragment-hardening",
                    "run-isolation",
                    "resource-stability",
                    "stdin-isolation",
                    "configuration-durability",
                    "filesystem-hardening",
                    "token-publication",
                ],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
