#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Workspace acquisition contract; all fixtures are synthetic, never HIL."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v061_hardening_release_gate as fixture

GATE = fixture.GATE
SERVICE = "7079626c-1ab1-4d50-9e3a-000000000001"
COLLECTOR = fixture.ROOT / "tests/firmware_tests/hil/v061_workspace_acquire.py"
CHALLENGE = "a" * 32
BOOT_ID = "b" * 32
ADDRESS = "synthetic-selected-board"
RECOVERY = b"PyBLE workspace recovery is required; reconnect by USB.\r\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def synthetic_binding(profile_id="esp32-4mb"):
    if profile_id == "rpi-pico2-w":
        import test_v061_workspace_pico as pico_fixture
        value = pico_fixture.binding()
    else:
        import test_v061_workspace_hardware as hardware_fixture
        value = hardware_fixture.binding()
        value["profile_id"] = profile_id
        if profile_id in ("esp32-4mb", "esp32-c3-4mb"):
            value["flash"].update(chip="ESP32" if profile_id == "esp32-4mb" else "ESP32-C3",
                                  chip_id=0 if profile_id == "esp32-4mb" else 5,
                                  jedec_id=0x164068, size_bytes=0x400000)
        if profile_id == "waveshare-esp32-s3-lcd-147b":
            for key in ("application_usb", "loader_usb"):
                value[key].update(vid=0x303A, pid=0x1001, product="USB JTAG/serial debug unit")
    value["ble_address"] = ADDRESS
    return value


def boot_observation(kind):
    erased = kind == fixture.WORKSPACE_ORDER[0]
    return {
        "schema_version": 1,
        "boot_id": BOOT_ID if erased else "c" * 32,
        "challenge": CHALLENGE if erased else "d" * 32,
        "mount_attempts": 1,
        "format_attempts": int(erased),
        "format_completions": int(erased),
        "remount_attempts": int(erased),
        "remount_completions": int(erased),
        "program_calls": 2 if erased else 0,
        "erase_calls": 1 if erased else 0,
        "workspace_attached": erased,
        "recovery_attempts": int(not erased),
        "recovery_emissions": int(not erased),
        "complete": True,
        "fault": False,
        "overflow": False,
        "media_state": "erased" if erased else "nonblank",
    }


def acquisition_fixture(directory, kind=fixture.WORKSPACE_ORDER[0], *,
                        receipt_name="workspace.json", profile_id="esp32-4mb",
                        validation=None, install=None):
    """Fabricate byte-level host fixtures, explicitly not hardware evidence."""
    receipt = directory / receipt_name
    erased = kind == fixture.WORKSPACE_ORDER[0]
    media = dict(GATE.WORKSPACE_MEDIA[profile_id])
    pre = b"\xff" * media["size"] if erased else b"\x00" * media["size"]
    marker = b"synthetic-lfs2"
    post = marker + pre[len(marker):] if erased else pre
    observation = boot_observation(kind)
    challenge, boot_id = observation["challenge"], observation["boot_id"]
    binding = synthetic_binding(profile_id)
    blocks = media["size"] // media["block_size"]
    response = (b"" if erased else RECOVERY) + b"PYBLE_WORKSPACE_OBSERVATION:"
    response += json.dumps({
        "observation": observation,
        "workspace_probe": [4096, 4096, blocks, blocks-4, blocks-4, 0, 0, 0, 0, 255] if erased else None,
    }, separators=(",", ":")).encode() + b"\r\n"
    watch = [{"event": "watch-start", "challenge": challenge, "monotonic_ns": 4}]
    if erased:
        watch.append({"event": "advertisement", "monotonic_ns": 8,
                      "address": ADDRESS, "local_name": "PyBLE-synthetic",
                      "service_uuids": [SERVICE]})
    watch.append({"event": "watch-end", "challenge": challenge,
                  "monotonic_ns": 10_000_000_010, "status": "complete"})
    install = b"synthetic candidate loadable bytes" if install is None else install
    validation = fixture.validation_kwargs(profile_id) if validation is None else dict(validation)
    validation["expected_install_sha256"] = sha(install)
    values = {
        "schema_version": 1,
        "measurement_contract": "v061-workspace-acquisition-v1",
        "observation_kind": kind,
        "profile_id": profile_id,
        "target": fixture.PROFILE_TARGETS[profile_id],
        "firmware_version": "0.6.1",
        "source_commit": validation["expected_source_commit"],
        "candidate_release_json_sha256": validation["candidate_release_json_sha256"],
        "install_sha256": sha(install),
        "qualification_source_commit": validation["expected_qualification_source_commit"],
        "qualification_executable_sha256": validation["expected_qualification_executable_sha256"],
        "collector_sha256": sha(COLLECTOR.read_bytes()) if COLLECTOR.is_file() else "c" * 64,
        "challenge": challenge,
        "boot_id": boot_id,
        "media": media,
        "transport": "pble-run" if erased else "usb-repl",
        "board_binding": {"device_id": binding["device_id"], "ble_address": ADDRESS},
        "install_readback_sha256": sha(install),
        "pre_media_sha256": sha(pre),
        "post_media_sha256": sha(post),
        "response_sha256": sha(response),
        "advertisements_sha256": sha(fixture.canonical_json_lines(watch)),
        "measurement_sha256": "d" * 64,
        "status": "passed",
    }
    measurement = [
        {"event": "acquisition-start", "challenge": challenge, "monotonic_ns": 1,
         "binding": binding},
        {"event": "install-verified", "device_id": binding["device_id"],
         "install_readback_sha256": sha(install), "monotonic_ns": 2},
        {"event": "media-read", "phase": "pre", "offset": media["offset"],
         "size": media["size"], "sha256": sha(pre), "monotonic_ns": 3},
        {"event": "boot-start", "device_id": binding["device_id"], "monotonic_ns": 5},
        {"event": "boot-complete", "monotonic_ns": 6},
        {"event": "observation-read", "challenge": challenge, "boot_id": boot_id,
         "transport": values["transport"], "response_sha256": sha(response), "monotonic_ns": 9},
        {"event": "media-read", "phase": "post", "offset": media["offset"],
         "size": media["size"], "sha256": sha(post), "monotonic_ns": 10_000_000_011},
        {"event": "acquisition-end", "status": "complete", "monotonic_ns": 10_000_000_012},
    ]
    values["measurement_sha256"] = sha(fixture.canonical_json_lines(measurement))
    files = {
        "install.bin": install, "pre.bin": pre, "post.bin": post,
        "response.bin": response,
        "advertisements.jsonl": fixture.canonical_json_lines(watch),
        "measurement.jsonl": fixture.canonical_json_lines(measurement),
    }
    for suffix, raw in files.items():
        fixture.private_write(directory / (receipt.stem + "-" + suffix), raw)
    fixture.private_write(directory / (receipt.stem + "-acquisition.json"),
                          fixture.canonical_json_bytes(values))
    return receipt, kind, validation, values


class WorkspaceAcquisitionTests(unittest.TestCase):
    def validate(self, receipt, kind, validation):
        validator = getattr(GATE, "_workspace_acquisition_snapshot", None)
        self.assertTrue(callable(validator), "missing physical workspace acquisition validator")
        return validator(receipt, kind, validation)

    def mutate(self, directory, receipt, value, key, replacement):
        value = copy.deepcopy(value)
        value[key] = replacement
        fixture.private_write(directory / (receipt.stem + "-acquisition.json"),
                              fixture.canonical_json_bytes(value))

    def replace_raw(self, directory, receipt, value, suffix, digest_key, raw):
        value[digest_key] = sha(raw)
        fixture.private_write(directory / (receipt.stem + "-" + suffix), raw)
        if digest_key == "response_sha256":
            measurement_path = directory / (receipt.stem + "-measurement.jsonl")
            records = [json.loads(line) for line in measurement_path.read_bytes().splitlines()]
            records[5]["response_sha256"] = sha(raw)
            measurement = fixture.canonical_json_lines(records)
            fixture.private_write(measurement_path, measurement)
            value["measurement_sha256"] = sha(measurement)
        fixture.private_write(directory / (receipt.stem + "-acquisition.json"),
                              fixture.canonical_json_bytes(value))

    def test_both_complete_measured_acquisitions_are_admitted(self):
        for kind in fixture.WORKSPACE_ORDER:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                path, kind, validation, value = acquisition_fixture(Path(temp), kind)
                digest, snapshots = self.validate(path, kind, validation)
                self.assertEqual(digest, sha(fixture.canonical_json_bytes(value)))
                self.assertEqual(len(snapshots), 7)

    def test_missing_raw_measurements_are_not_four_line_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workspace.json"
            fixture.private_write(path.with_name("workspace-raw.jsonl"),
                                  fixture.workspace_raw_log(fixture.WORKSPACE_ORDER[0]))
            validator = getattr(GATE, "_workspace_acquisition_snapshot", None)
            self.assertTrue(callable(validator), "missing physical workspace acquisition validator")
            with self.assertRaises(GATE.QualificationError):
                validator(path, fixture.WORKSPACE_ORDER[0], fixture.validation_kwargs())

    def test_every_raw_sibling_is_reopened_and_byte_bound(self):
        for suffix in ("install.bin", "pre.bin", "post.bin", "response.bin",
                       "advertisements.jsonl", "measurement.jsonl"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, _ = acquisition_fixture(directory)
                sibling = directory / (path.stem + "-" + suffix)
                fixture.private_write(sibling, sibling.read_bytes() + b"corruption")
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_stale_challenge_or_boot_id_fails(self):
        for key in ("challenge", "boot_id"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                self.mutate(directory, path, value, key, "e" * 32)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_wrong_geometry_or_candidate_or_source_fails(self):
        mutations = {
            "media": {"offset": 0, "size": 0x200000, "block_size": 4096},
            "source_commit": "e" * 40,
            "candidate_release_json_sha256": "e" * 64,
            "install_sha256": "e" * 64,
            "qualification_source_commit": "e" * 40,
            "collector_sha256": "e" * 64,
        }
        for key, replacement in mutations.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                self.mutate(directory, path, value, key, replacement)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_private_acquisition_symlink_and_mode_rejected(self):
        for unsafe in ("symlink", "mode"):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, _ = acquisition_fixture(directory)
                sibling = directory / "workspace-pre.bin"
                if unsafe == "symlink":
                    moved = directory / "outside.bin"
                    sibling.rename(moved)
                    sibling.symlink_to(moved)
                else:
                    sibling.chmod(0o644)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_measured_counters_not_unchanged_media_decide_zero_write(self):
        for field in ("program_calls", "erase_calls", "format_attempts",
                      "format_completions", "remount_attempts", "remount_completions"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory, fixture.WORKSPACE_ORDER[1])
                observed = boot_observation(kind)
                observed[field] = 1
                raw = b"PYBLE_WORKSPACE_OBSERVATION:" + json.dumps({
                    "observation": observed, "workspace_probe": None,
                }).encode() + b"\n"
                self.replace_raw(directory, path, value, "response.bin", "response_sha256", raw)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_incomplete_faulted_overflowed_or_boolean_counter_fails(self):
        mutations = {"complete": False, "fault": True, "overflow": True,
                     "mount_attempts": True, "format_completions": 0,
                     "remount_completions": 0, "workspace_attached": False,
                     "media_state": "uninspected"}
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                observed = boot_observation(kind)
                observed[field] = replacement
                raw = b"PYBLE_WORKSPACE_OBSERVATION:" + json.dumps({
                    "observation": observed,
                    "workspace_probe": [4096, 4096, 512, 508, 508, 0, 0, 0, 0, 255],
                }).encode() + b"\n"
                self.replace_raw(directory, path, value, "response.bin", "response_sha256", raw)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_missing_or_duplicate_response_or_probe_fails(self):
        for mutation in ("missing", "duplicate", "no-probe"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                raw = (directory / "workspace-response.bin").read_bytes()
                if mutation == "missing":
                    raw = b"no runtime observation\n"
                elif mutation == "duplicate":
                    raw += raw
                else:
                    raw = b"PYBLE_WORKSPACE_OBSERVATION:" + json.dumps({
                        "observation": boot_observation(kind), "workspace_probe": None,
                    }).encode() + b"\n"
                self.replace_raw(directory, path, value, "response.bin", "response_sha256", raw)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_watch_missing_short_interrupted_or_wrong_board_fails(self):
        for mutation in ("missing-start", "short", "interrupted", "wrong-board"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                records = [json.loads(line) for line in (directory / "workspace-advertisements.jsonl").read_bytes().splitlines()]
                if mutation == "missing-start":
                    records.pop(0)
                elif mutation == "short":
                    records[-1]["monotonic_ns"] = 100
                elif mutation == "interrupted":
                    records[-1]["status"] = "interrupted"
                else:
                    records[1]["address"] = "another-board"
                self.replace_raw(directory, path, value, "advertisements.jsonl",
                                 "advertisements_sha256", fixture.canonical_json_lines(records))
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_refusal_rejects_one_real_selected_advertisement(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path, kind, validation, value = acquisition_fixture(directory, fixture.WORKSPACE_ORDER[1])
            records = [json.loads(line) for line in (directory / "workspace-advertisements.jsonl").read_bytes().splitlines()]
            records.insert(1, {"event": "advertisement", "monotonic_ns": 8,
                               "address": ADDRESS, "local_name": "PyBLE-synthetic",
                               "service_uuids": [SERVICE]})
            self.replace_raw(directory, path, value, "advertisements.jsonl",
                             "advertisements_sha256", fixture.canonical_json_lines(records))
            with self.assertRaises(GATE.QualificationError):
                self.validate(path, kind, validation)

    def test_native_usb_refusal_does_not_invent_unavailable_boot_text(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path, kind, validation, value = acquisition_fixture(directory, fixture.WORKSPACE_ORDER[1])
            raw = (directory / "workspace-response.bin").read_bytes().removeprefix(RECOVERY)
            self.replace_raw(directory, path, value, "response.bin", "response_sha256", raw)
            self.validate(path, kind, validation)

    def test_reordered_or_nonce_mismatched_measurement_fails(self):
        for mutation in ("reordered", "nonce", "boot-after-watch"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                records = [json.loads(line) for line in (directory / "workspace-measurement.jsonl").read_bytes().splitlines()]
                if mutation == "reordered":
                    records[2], records[3] = records[3], records[2]
                elif mutation == "nonce":
                    records[5]["challenge"] = "e" * 32
                else:
                    records[3]["monotonic_ns"] = 10_000_000_100
                self.replace_raw(directory, path, value, "measurement.jsonl",
                                 "measurement_sha256", fixture.canonical_json_lines(records))
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_full_retained_binding_is_revalidated_beyond_compact_ids(self):
        for mutation in ("truncated", "usb-path", "flash-size", "unknown-transfer"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path, kind, validation, value = acquisition_fixture(directory)
                records = [json.loads(line) for line in (directory / "workspace-measurement.jsonl").read_bytes().splitlines()]
                binding = records[0]["binding"]
                if mutation == "truncated":
                    binding.pop("flash")
                elif mutation == "usb-path":
                    binding["loader_usb"]["port"] = "/tmp/not-a-physical-device"
                elif mutation == "flash-size":
                    binding["flash"]["size_bytes"] = 16 * 1024 * 1024
                else:
                    binding["transfer"]["operator_count"] = 0
                self.replace_raw(directory, path, value, "measurement.jsonl",
                                 "measurement_sha256", fixture.canonical_json_lines(records))
                with self.assertRaises(GATE.QualificationError):
                    self.validate(path, kind, validation)

    def test_unbound_legacy_receipt_is_rejected(self):
        receipt = fixture.valid_receipt(fixture.WORKSPACE_ORDER[0])
        receipt.pop("acquisition_sha256", None)
        with self.assertRaises(GATE.QualificationError):
            GATE.validate_workspace_receipt_payload(
                receipt, observation_kind=fixture.WORKSPACE_ORDER[0],
                **fixture.validation_kwargs())

    def test_private_result_reopens_every_workspace_sibling(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            artifact = directory / "firmware.bin"
            artifact.write_bytes(b"synthetic candidate bytes")
            result = directory / "hardening.json"
            value = fixture.valid_result()
            value["install_sha256"] = sha(artifact.read_bytes())
            fixture.attach_result_workspace(result, value, artifact.read_bytes())
            fixture.private_write(result, fixture.canonical_json_bytes(value))
            kwargs = fixture.validation_kwargs()
            kwargs.pop("expected_install_sha256")
            GATE.validate_result_file(result, artifact, **kwargs)
            for kind in fixture.WORKSPACE_ORDER:
                receipt = directory / value["workspace_provisioning"][kind]["receipt_file"]
                paths = [receipt]
                paths.extend(receipt.with_name(receipt.stem + "-" + suffix) for suffix in (
                    "raw.jsonl", "acquisition.json", "install.bin", "pre.bin", "post.bin",
                    "response.bin", "advertisements.jsonl", "measurement.jsonl"))
                for path in paths:
                    with self.subTest(kind=kind, sibling=path.suffix):
                        original = path.read_bytes()
                        fixture.private_write(path, original + b"tampered")
                        with self.assertRaises(GATE.QualificationError):
                            GATE.validate_result_file(result, artifact, **kwargs)
                        fixture.private_write(path, original)

    def test_private_result_receipt_paths_cannot_escape_its_directory(self):
        for name in ("../outside.json", "/outside.json", "sub/receipt.json", "receipt.json/..", ".hidden.json"):
            with self.subTest(name=name):
                value = fixture.valid_result()
                value["workspace_provisioning"][fixture.WORKSPACE_ORDER[0]]["receipt_file"] = name
                with self.assertRaises(GATE.QualificationError):
                    GATE.validate_result_payload(value, **fixture.validation_kwargs())

    def test_two_acquisitions_need_same_board_distinct_nonce_and_boot(self):
        for mutation in ("device", "challenge", "boot_id"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                first = acquisition_fixture(directory, receipt_name="erased.json")
                second = acquisition_fixture(directory, fixture.WORKSPACE_ORDER[1], receipt_name="nonblank.json")
                erased, nonblank = first[3], second[3]
                if mutation == "device":
                    nonblank["board_binding"]["device_id"] = "a-different-device"
                else:
                    nonblank[mutation] = erased[mutation]
                snapshots = [((directory / name, (fixture.canonical_json_bytes(value), (), "")),)
                             for name, value in (("erased-acquisition.json", erased),
                                                 ("nonblank-acquisition.json", nonblank))]
                with self.assertRaises(GATE.QualificationError):
                    GATE._validate_workspace_acquisition_pair(*snapshots)

    def test_real_firmware_getter_json_roundtrip_ignores_mapping_order(self):
        import test_workspace_boot_observation_v061 as runtime
        for kind in fixture.WORKSPACE_ORDER:
            with self.subTest(kind=kind):
                workspace = runtime.fresh_workspace()
                erased = kind == fixture.WORKSPACE_ORDER[0]
                media = runtime.Media(blank=erased)

                def format_media(bdev):
                    bdev.ioctl(6, 0)
                    bdev.writeblocks(0, b"\0" * 256, 0)

                vfs, _ = runtime.vfs_fixture(
                    [OSError(errno.EIO, "synthetic blank or incompatible media")] + ([None] if erased else []),
                    format_action=format_media)
                if erased:
                    workspace.mount_lfs2(media, vfs, observe_boot=True)
                    workspace.boot_attached()
                else:
                    with self.assertRaises(OSError):
                        workspace.mount_lfs2(media, vfs, observe_boot=True)
                    with mock.patch("builtins.print"):
                        workspace.boot_recovery()
                observed = workspace.read_boot_observation(CHALLENGE)
                # MicroPython's object key iteration/serialization ordering is
                # not the canonical host evidence ordering contract.
                observed = dict(reversed(tuple(observed.items())))
                reply = {"workspace_probe": [4096, 4096, 2, 0, 0, 0, 0, 0, 0, 255] if erased else None,
                         "observation": observed}
                raw = b"PYBLE_WORKSPACE_OBSERVATION:" + json.dumps(reply).encode() + b"\n"
                decoded = GATE.parse_workspace_response(raw)
                GATE._validate_boot_observation(
                    {"challenge": CHALLENGE, "boot_id": observed["boot_id"]}, decoded, kind)


if __name__ == "__main__":
    unittest.main()
