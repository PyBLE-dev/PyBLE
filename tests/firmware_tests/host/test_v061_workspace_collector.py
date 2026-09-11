#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only collector simulation; no fixture is physical qualification."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v061_hardening_release_gate as fixture
import test_v061_workspace_acquisition as acquisition

SPEC = importlib.util.spec_from_file_location("pyble_workspace_collector_host_test", acquisition.COLLECTOR)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


class SyntheticClock:
    def __init__(self):
        self.value = 1_000_000

    def now(self):
        self.value += 1_000_000
        return self.value

    async def wait(self, seconds):
        self.value += math.ceil(seconds * 1_000_000_000)


class SyntheticScanner:
    def __init__(self, callback, history, *, stop_failure=False):
        self.callback = callback
        self.history = history
        self.stop_failure = stop_failure

    async def start(self):
        self.history.append("scanner-start")

    async def stop(self):
        self.history.append("scanner-stop")
        if self.stop_failure:
            raise OSError("synthetic scanner stop failed")


class SyntheticBackend:
    def __init__(self, artifact, binding, kind, history):
        self.artifact = artifact
        self.binding = binding
        self.kind = kind
        self.history = history
        self.reads = 0
        self.scanner = None
        self.mutation = None

    async def prepare(self, candidate, profile_id, kind):
        self.history.append("prepare")
        return {key: self.binding[key] for key in ("device_id", "ble_address")}, self.artifact.read_bytes()

    async def read_media(self, offset, size):
        self.history.append("pre-read" if self.reads == 0 else "post-read")
        erased = self.kind == fixture.WORKSPACE_ORDER[0]
        result = b"\xff" * size if erased else b"\0" * size
        if self.reads and erased:
            result = b"synthetic-lfs2" + result[len(b"synthetic-lfs2"):]
        self.reads += 1
        return result

    async def boot(self):
        self.history.append("boot")
        if self.kind == fixture.WORKSPACE_ORDER[0]:
            self.scanner.callback(SimpleNamespace(address=self.binding["ble_address"]),
                SimpleNamespace(local_name="PyBLE-host-fixture", service_uuids=[acquisition.SERVICE]))
        return b""  # native USB need not capture an earlier printed line

    async def observe(self, challenge, transport):
        self.history.append("observe")
        observed = acquisition.boot_observation(self.kind)
        observed["challenge"] = challenge
        if self.mutation:
            self.mutation(observed)
        response = {"observation": observed,
                    "workspace_probe": [4096, 4096, 512, 500, 500, 0, 0, 0, 0, 255]
                    if self.kind == fixture.WORKSPACE_ORDER[0] else None}
        return b"PYBLE_WORKSPACE_OBSERVATION:" + json.dumps(response).encode() + b"\r\n"

    async def close(self):
        self.history.append("close")


class WorkspaceCollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-host-workspace-collector-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = fixture.writer_fixture(self.root, "esp32-4mb")
        self.output = self.root / "measured.json"
        self.kind = fixture.WORKSPACE_ORDER[0]
        self.binding = acquisition.synthetic_binding("esp32-4mb")
        self.history = []
        self.clock = SyntheticClock()
        self.backend = SyntheticBackend(self.files["artifact"], self.binding, self.kind, self.history)
        self.scanner_stop_failure = False
        # Only the checkout authority is replaced for this host simulation.
        # Dirty-source rejection is separately exercised with an actual Git
        # checkout in test_v061_hil_preflight_hardening; no production bypass.
        qualification = {"root": fixture.ROOT,
                         "commit": self.files["qualification_source_commit"],
                         "executable_sha256": self.files["qualification_executable_sha256"]}
        self.qual = self.enterContext(mock.patch.object(COLLECTOR.gate, "_qualification_snapshot", return_value=qualification))
        self.same_qual = self.enterContext(mock.patch.object(COLLECTOR.gate, "_same_qualification", return_value=None))

    def scanner(self, callback):
        scanner = SyntheticScanner(callback, self.history, stop_failure=self.scanner_stop_failure)
        self.backend.scanner = scanner
        return scanner

    async def run_collector(self, **overrides):
        options = dict(candidate_dir=self.files["candidate"], profile_id="esp32-4mb",
                       observation_kind=self.kind, binding=self.binding,
                       output_path=self.output, qualification_repo_root=fixture.ROOT,
                       backend=self.backend, allow_disposable_erase=True,
                       scanner_factory=self.scanner, clock_ns=self.clock.now, wait=self.clock.wait)
        options.update(overrides)
        return await COLLECTOR.acquire(**options)

    async def test_live_sequence_collects_actual_raw_siblings_and_receipt(self):
        self.assertEqual(await self.run_collector(), self.output.resolve())
        self.assertEqual(self.history,
                         ["prepare", "pre-read", "scanner-start", "boot", "observe",
                          "scanner-stop", "post-read", "close"])
        receipt = json.loads(self.output.read_bytes())
        envelope = json.loads(self.root.joinpath("measured-acquisition.json").read_bytes())
        self.assertEqual(receipt["acquisition_sha256"], acquisition.sha(
            self.root.joinpath("measured-acquisition.json").read_bytes()))
        self.assertEqual(envelope["challenge"], json.loads(
            self.root.joinpath("measured-measurement.jsonl").read_bytes().splitlines()[0])["challenge"])
        self.assertEqual(self.root.joinpath("measured-install.bin").read_bytes(), self.files["artifact"].read_bytes())
        for path in self.root.glob("measured*"):
            self.assertEqual(path.stat().st_mode & 0o7777, 0o600)

    async def test_refusal_uses_live_counter_not_a_substituted_boot_message(self):
        self.kind = self.backend.kind = fixture.WORKSPACE_ORDER[1]
        await self.run_collector()
        response = self.root.joinpath("measured-response.bin").read_bytes()
        self.assertNotIn(acquisition.RECOVERY, response)
        self.assertEqual(self.root.joinpath("measured-pre.bin").read_bytes(),
                         self.root.joinpath("measured-post.bin").read_bytes())

    async def test_preexisting_any_sibling_refuses_before_hardware(self):
        for suffix in ("install.bin", "pre.bin", "response.bin", "measurement.jsonl"):
            path = self.root / ("measured-" + suffix)
            fixture.private_write(path, b"owner bytes\n")
            with self.assertRaises(COLLECTOR.gate.QualificationError):
                await self.run_collector()
            self.assertEqual(path.read_bytes(), b"owner bytes\n")
            self.assertEqual(self.history, [])
            path.unlink()

    async def test_explicit_erase_and_clean_source_required_before_hardware(self):
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector(allow_disposable_erase=False)
        self.qual.side_effect = COLLECTOR.gate.QualificationError("dirty synthetic source")
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertEqual(self.history, [])

    async def test_wrong_nonce_fails_and_closes_scanner_and_backend(self):
        self.backend.mutation = lambda observed: observed.__setitem__("challenge", "e" * 32)
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertIn("scanner-stop", self.history)
        self.assertEqual(self.history[-1], "close")

    async def test_source_changed_after_measurement_mints_no_receipt(self):
        self.same_qual.side_effect = COLLECTOR.gate.QualificationError("changed source closure")
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertTrue(self.root.joinpath("measured-post.bin").exists())
        self.assertEqual(self.history[-1], "close")

    async def test_scanner_failure_does_not_become_an_absent_advertisement(self):
        self.kind = self.backend.kind = fixture.WORKSPACE_ORDER[1]
        self.scanner_stop_failure = True
        with self.assertRaises(OSError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.history[-1], "close")

    async def test_zero_write_assertion_cannot_override_actual_nonzero_count(self):
        self.kind = self.backend.kind = fixture.WORKSPACE_ORDER[1]
        self.backend.mutation = lambda observed: observed.__setitem__("program_calls", 1)
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertFalse(self.output.exists())

    async def test_cancellation_retains_partial_evidence_and_closes_every_owner(self):
        async def cancelled(*args):
            raise asyncio.CancelledError()
        self.backend.observe = cancelled
        with self.assertRaises(asyncio.CancelledError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.history[-2:], ["scanner-stop", "close"])
        self.assertTrue(self.root.joinpath("measured-measurement.jsonl").exists())

    async def test_wrong_install_readback_never_reaches_boot(self):
        original = self.backend.prepare

        async def wrong_readback(*args):
            binding, raw = await original(*args)
            return binding, raw + b"different actual flash bytes"

        self.backend.prepare = wrong_readback
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertEqual(self.history, ["prepare", "close"])
        self.assertFalse(self.output.exists())

    async def test_truncated_pre_media_never_reaches_boot(self):
        async def short_read(*args):
            self.history.append("pre-read")
            return b"\xff" * 4096

        self.backend.read_media = short_read
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertEqual(self.history, ["prepare", "pre-read", "close"])
        self.assertFalse(self.output.exists())

    async def test_timeout_is_a_failure_not_a_missing_response_success(self):
        async def timed_out(*args):
            raise TimeoutError("synthetic acquisition timeout")

        self.backend.observe = timed_out
        with self.assertRaises(TimeoutError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.history[-2:], ["scanner-stop", "close"])

    async def test_candidate_changed_during_boot_mints_no_receipt(self):
        original = self.backend.boot

        async def mutate_candidate():
            raw = await original()
            self.files["artifact"].write_bytes(b"changed source candidate")
            return raw

        self.backend.boot = mutate_candidate
        with self.assertRaises(COLLECTOR.gate.QualificationError):
            await self.run_collector()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.history[-1], "close")


if __name__ == "__main__":
    unittest.main()
