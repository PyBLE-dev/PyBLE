#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Acquire private physical workspace evidence; never import operator counts.

The maintained hardware backend verifies an explicitly selected disposable
board. This module owns fresh challenges, live scanner chronology, retained
actual readbacks/responses, and exclusive candidate/source-bound publication.
Injected backends/scanners are host-test seams, not a CLI qualification mode.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import secrets
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "pyble_workspace_acquisition_gate",
    ROOT / "firmware/qualification/v061_hardening_release_gate.py",
)
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _PrivateStream:
    """Exclusive descriptor-relative live JSONL with immutable close checks."""

    def __init__(self, path):
        self.path = gate._absolute_lexical_path(Path(path), "acquisition live log")
        self.chain = gate._open_directory_chain(self.path.parent, label="acquisition live log parent")
        self.descriptor = -1
        self.raw = bytearray()
        try:
            self.descriptor = os.open(self.path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                dir_fd=self.chain[-1][0])
            os.fchmod(self.descriptor, 0o600)
            self.identity = os.fstat(self.descriptor)
            gate._require(self.identity.st_nlink == 1, "acquisition live log is linked")
        except BaseException:
            self.close(check=False)
            raise

    def append(self, value):
        raw = gate._canonical_json_line(value)
        gate._require(len(self.raw) + len(raw) <= gate._MAX_LOG_BYTES,
                      "acquisition live log exceeded its bound")
        position = 0
        while position < len(raw):
            count = os.write(self.descriptor, raw[position:])
            gate._require(count > 0, "acquisition live log write was short")
            position += count
        self.raw.extend(raw)
        os.fsync(self.descriptor)
        gate._verify_directory_chain(self.chain, "acquisition live log parent")

    def close(self, check=True):
        if self.descriptor >= 0:
            try:
                os.fsync(self.descriptor)
                current = os.fstat(self.descriptor)
                if check:
                    gate._require(current.st_dev == self.identity.st_dev
                                  and current.st_ino == self.identity.st_ino
                                  and current.st_nlink == 1
                                  and current.st_mode & 0o7777 == 0o600,
                                  "acquisition live log descriptor changed")
                    gate._verify_directory_chain(self.chain, "acquisition live log parent")
            finally:
                os.close(self.descriptor)
                self.descriptor = -1
        if self.chain:
            gate._close_directory_chain(self.chain)
            self.chain = []
        if check:
            raw, identity = gate._stable_regular_bytes(self.path,
                label="acquisition live log", maximum=gate._MAX_LOG_BYTES, private=True)
            gate._require(raw == bytes(self.raw) and identity[0] == self.identity.st_dev
                          and identity[1] == self.identity.st_ino,
                          "acquisition live log was replaced")


def _scanner_factory(callback):
    from bleak import BleakScanner
    return BleakScanner(detection_callback=callback,
                        service_uuids=[gate.WORKSPACE_SERVICE_UUID])


def _private_binding(value, profile_id):
    # The hardware backend owns complete USB/ROM/geometry validation. Retain
    # its entire explicit input here; compact observed identity must match it.
    raw = gate.canonical_json_bytes(value)
    gate._require(len(raw) <= 16 * 1024, "physical binding is oversized")
    binding = gate._decode_json(raw, "physical binding", canonical=True)
    gate._require(type(binding.get("schema_version")) is int
                  and binding["schema_version"] == 1
                  and binding.get("profile_id") == profile_id,
                  "physical binding profile or schema changed")
    for field in ("device_id", "ble_address"):
        gate._require(type(binding.get(field)) is str and 0 < len(binding[field]) <= 128,
                      "physical binding %s is missing" % field)
    return gate.validate_workspace_binding(binding)


async def acquire(*, candidate_dir, profile_id, observation_kind, binding,
                  output_path, qualification_repo_root, backend,
                  allow_disposable_erase=False, scanner_factory=None,
                  clock_ns=time.monotonic_ns, wait=asyncio.sleep):
    """Run one actual destructive preparation/boot/readback observation.

    No precomputed response, snapshot, media bytes, counters, or event log can
    be supplied through this interface. The only production backend is the
    reviewed hardware adapter instantiated by main(). A failed run retains
    partial raw evidence and never publishes a passing receipt.
    """
    gate._require(allow_disposable_erase is True,
                  "workspace acquisition requires an explicitly disposable board")
    gate._require(observation_kind in gate.WORKSPACE_PROVISIONING_ORDER,
                  "workspace observation kind is unsupported")
    binding = _private_binding(binding, profile_id)
    output = gate._absolute_lexical_path(Path(output_path), "workspace receipt output")
    gate._require(output.suffix == ".json", "workspace receipt must end in .json")
    candidate = gate._candidate_snapshot(Path(candidate_dir), profile_id)
    candidate["profile_id"] = profile_id
    qualification = gate._qualification_snapshot(Path(qualification_repo_root))
    gate._require(qualification["root"] == ROOT, "collector is outside qualification checkout")
    paths = [output, gate._workspace_raw_path(output),
             gate._workspace_sibling(output, "acquisition.json")]
    paths.extend(gate._workspace_sibling(output, suffix)
                 for suffix, _field in gate.WORKSPACE_RAW_SIBLINGS)
    for path in paths:
        gate._require_private_evidence_outside(path, label="workspace acquisition",
                                               candidate=candidate, qualification=qualification)
        chain = gate._open_directory_chain(path.parent, label="workspace acquisition parent")
        try:
            try:
                os.stat(path.name, dir_fd=chain[-1][0], follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise gate.QualificationError("workspace acquisition output already exists")
            gate._verify_directory_chain(chain, "workspace acquisition parent")
        finally:
            gate._close_directory_chain(chain)

    challenge = secrets.token_hex(16)
    media = dict(gate.WORKSPACE_MEDIA[profile_id])
    transport = "pble-run" if observation_kind == gate.WORKSPACE_PROVISIONING_ORDER[0] else "usb-repl"
    measurement = _PrivateStream(gate._workspace_sibling(output, "measurement.jsonl"))
    watch = None
    scanner = None
    scanner_started = False
    backend_closed = False
    capture_error = None
    raw_outputs = {}
    stamps = []

    def event(name, **fields):
        stamp = clock_ns()
        gate._require(type(stamp) is int and (not stamps or stamp > stamps[-1]),
                      "acquisition clock did not advance")
        stamps.append(stamp)
        measurement.append({"event": name, **fields, "monotonic_ns": stamp})
        return stamp

    def save(suffix, raw):
        gate._require(type(raw) is bytes, "hardware measurement is not raw bytes")
        path = gate._workspace_sibling(output, suffix)
        gate._require(len(raw) <= gate._workspace_evidence_maximum(path),
                      "hardware measurement exceeded its bound")
        gate._write_exclusive(path, raw, post_write_check=lambda: None)
        raw_outputs[suffix] = raw
        return _sha(raw)

    def callback(device, advertisement):
        nonlocal capture_error
        if watch is None or device.address != binding["ble_address"]:
            return
        try:
            watch.append({"event": "advertisement", "monotonic_ns": clock_ns(),
                          "address": device.address, "local_name": advertisement.local_name,
                          "service_uuids": list(advertisement.service_uuids)})
        except BaseException as exc:
            # Scanner callbacks may run outside our await stack. A callback
            # failure is a terminal acquisition error, never an empty watch.
            capture_error = exc

    try:
        event("acquisition-start", challenge=challenge, binding=binding)
        observed_binding, install_readback = await asyncio.wait_for(
            backend.prepare(candidate, profile_id, observation_kind), timeout=900)
        gate._require(type(observed_binding) is dict
                      and tuple(observed_binding) == ("device_id", "ble_address")
                      and observed_binding == {key: binding[key] for key in ("device_id", "ble_address")},
                      "hardware preparation returned a different physical board")
        install_digest = save("install.bin", install_readback)
        gate._require(install_digest == candidate["install_sha256"],
                      "actual install readback differs from candidate")
        event("install-verified", device_id=observed_binding["device_id"],
              install_readback_sha256=install_digest)
        pre = await asyncio.wait_for(backend.read_media(media["offset"], media["size"]), timeout=900)
        pre_digest = save("pre.bin", pre)
        gate._require(len(pre) == media["size"], "workspace pre-read is incomplete")
        if observation_kind == gate.WORKSPACE_PROVISIONING_ORDER[0]:
            gate._require(pre == b"\xff" * len(pre), "workspace pre-read is not blank")
        else:
            first = 2 * media["block_size"]
            gate._require(pre == b"\0" * len(pre)
                          or (pre[:first] == b"\0" * first and pre[first:] == b"\xff" * (len(pre)-first)),
                          "workspace pre-read is not deliberately incompatible")
        event("media-read", phase="pre", offset=media["offset"], size=media["size"], sha256=pre_digest)
        scanner = (scanner_factory or _scanner_factory)(callback)
        await asyncio.wait_for(scanner.start(), timeout=30)
        scanner_started = True
        watch = _PrivateStream(gate._workspace_sibling(output, "advertisements.jsonl"))
        watch.append({"event": "watch-start", "challenge": challenge, "monotonic_ns": clock_ns()})
        boot_stamp = event("boot-start", device_id=observed_binding["device_id"])
        boot_raw = await asyncio.wait_for(backend.boot(), timeout=90)
        gate._require(type(boot_raw) is bytes, "boot transcript is not raw bytes")
        event("boot-complete")
        observed_raw = await asyncio.wait_for(backend.observe(challenge, transport), timeout=120)
        gate._require(type(observed_raw) is bytes, "observation response is not raw bytes")
        response = boot_raw + observed_raw
        response_digest = save("response.bin", response)
        reply = gate.parse_workspace_response(response)
        observed = reply["observation"]
        gate._require(type(observed) is dict, "firmware observation is not a mapping")
        boot_id = observed.get("boot_id")
        gate._validate_boot_observation({"challenge": challenge, "boot_id": boot_id}, reply, observation_kind)
        event("observation-read", challenge=challenge, boot_id=boot_id,
              transport=transport, response_sha256=response_digest)
        await wait(max(0.001, (boot_stamp + 10_000_000_001 - clock_ns()) / 1_000_000_000))
        await asyncio.wait_for(scanner.stop(), timeout=30)
        scanner_started = False
        if capture_error is not None:
            raise gate.QualificationError("live advertisement capture failed") from capture_error
        watch.append({"event": "watch-end", "challenge": challenge,
                      "monotonic_ns": clock_ns(), "status": "complete"})
        watch.close()
        raw_outputs["advertisements.jsonl"] = bytes(watch.raw)
        post = await asyncio.wait_for(backend.read_media(media["offset"], media["size"]), timeout=900)
        post_digest = save("post.bin", post)
        event("media-read", phase="post", offset=media["offset"], size=media["size"], sha256=post_digest)
        await asyncio.wait_for(backend.close(), timeout=30)
        backend_closed = True
        event("acquisition-end", status="complete")
        measurement.close()
        raw_outputs["measurement.jsonl"] = bytes(measurement.raw)
        gate._same_candidate(Path(candidate_dir), profile_id, candidate)
        gate._same_qualification(Path(qualification_repo_root), qualification)
        value = {
            "schema_version": 1, "measurement_contract": gate.WORKSPACE_ACQUISITION_CONTRACT,
            "observation_kind": observation_kind, "profile_id": profile_id,
            "target": gate.PROFILE_TARGETS[profile_id], "firmware_version": "0.6.1",
            "source_commit": candidate["source_commit"],
            "candidate_release_json_sha256": candidate["release_sha256"],
            "install_sha256": candidate["install_sha256"],
            "qualification_source_commit": qualification["commit"],
            "qualification_executable_sha256": qualification["executable_sha256"],
            "collector_sha256": _sha(Path(__file__).read_bytes()),
            "challenge": challenge, "boot_id": boot_id, "media": media,
            "transport": transport, "board_binding": observed_binding,
            **{field: _sha(raw_outputs[suffix]) for suffix, field in gate.WORKSPACE_RAW_SIBLINGS},
            "status": "passed",
        }
        gate._write_exclusive(gate._workspace_sibling(output, "acquisition.json"),
                              gate.canonical_json_bytes(value), post_write_check=lambda: None)
        gate._workspace_acquisition_snapshot(output, observation_kind,
                                              gate._validation_from(candidate, qualification))
        summary = b"".join(gate._canonical_json_line(row)
                           for row in gate._expected_workspace_values(observation_kind))
        gate._write_exclusive(gate._workspace_raw_path(output), summary, post_write_check=lambda: None)
        return gate.create_workspace_receipt(candidate_dir=Path(candidate_dir), profile_id=profile_id,
            observation_kind=observation_kind, raw_boot_log=gate._workspace_raw_path(output),
            output_path=output, qualification_repo_root=Path(qualification_repo_root))
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors = []
        if scanner_started:
            try:
                await asyncio.wait_for(scanner.stop(), timeout=30)
            except BaseException as exc:
                cleanup_errors.append(exc)
            finally:
                scanner_started = False
        for stream in (watch, measurement):
            if stream is not None and stream.descriptor >= 0:
                try:
                    stream.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        if not backend_closed:
            try:
                await asyncio.wait_for(backend.close(), timeout=30)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            if primary_error is not None:
                primary_error.add_note("Workspace acquisition cleanup also failed; partial evidence retained.")
            else:
                raise gate.QualificationError("workspace acquisition cleanup failed") from cleanup_errors[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(gate.PROFILE_TARGETS), required=True)
    parser.add_argument("--kind", choices=gate.WORKSPACE_PROVISIONING_ORDER, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-disposable-erase", action="store_true")
    args = parser.parse_args()
    raw, _ = gate._stable_regular_bytes(args.binding, label="private physical binding",
                                       maximum=16 * 1024, private=True)
    binding = gate._decode_json(raw, "private physical binding", canonical=True)
    from _v061_workspace_hardware import WorkspaceHardware
    backend = WorkspaceHardware(binding, repo_root=ROOT, candidate_dir=args.candidate_dir)
    output = asyncio.run(acquire(candidate_dir=args.candidate_dir, profile_id=args.profile,
        observation_kind=args.kind, binding=binding, output_path=args.output,
        qualification_repo_root=ROOT, backend=backend,
        allow_disposable_erase=args.allow_disposable_erase))
    print("Workspace acquisition receipt:", output)


if __name__ == "__main__":
    main()
