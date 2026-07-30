#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Frozen OI-1 single-profile HIL orchestrator.  Baseline mode emits one
# canonical profile fragment for later two-profile assembly; verify mode emits
# the exact completed oi1_observation object after applying the committed
# profile thresholds.

import argparse
import asyncio
import json
import platform
import re
import sys
import time
from pathlib import Path

from _pble_central import PbleCentral, SERVICE_UUID
from _pble_bench import (
    BenchError,
    CommandIds,
    DERIVATION,
    PROFILE_ORDER,
    PROFILE_TARGETS,
    RedactedRawLog,
    THRESHOLD_KEYS,
    WORKLOAD,
    atomic_write_canonical_json,
    canonical_json_bytes,
    derive_thresholds,
    ensure_directory,
    evaluate_thresholds,
    goodput_bps,
    hello,
    measure_reset_to_advertisement,
    oi1_build_from_paths,
    roundtrip_file,
    run_heap_probe,
    run_reliability,
    validate_observation,
    validate_oi1_caps,
    validate_reliability,
    deterministic_payload,
)


PROFILE_CAPACITIES = {
    "esp32-4mb": (4 * 1024 * 1024, 0),
    "esp32-s3-n16r8": (16 * 1024 * 1024, 8 * 1024 * 1024),
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise BenchError("%s must be a non-empty string" % label)
    return value.strip()


def _require_sha256(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BenchError("%s must be a lowercase SHA-256" % label)
    return value


def _require_nonnegative_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchError("%s must be a non-negative integer" % label)
    return value


def build_baseline_profile(
        *,
        profile_id,
        board_manufacturer,
        board_model,
        module_marking,
        device_flash_capacity_bytes,
        device_psram_capacity_bytes,
        firmware_sha256,
        manifest_sha256,
        environment,
        oi1_build,
        oi1_observation):
    if profile_id not in PROFILE_ORDER:
        raise BenchError("profile is outside the current OI-1 order")
    if not isinstance(environment, dict) or set(environment) != {
        "desktop_os",
        "ble_backend",
        "ble_adapter",
        "python_version",
    }:
        raise BenchError("environment has the wrong keys")
    normalized_environment = {
        key: _require_text(environment[key], "environment.%s" % key)
        for key in (
            "desktop_os",
            "ble_backend",
            "ble_adapter",
            "python_version",
        )
    }
    return {
        "profile_id": profile_id,
        "target": PROFILE_TARGETS[profile_id],
        "board_manufacturer": _require_text(
            board_manufacturer, "board_manufacturer"
        ),
        "board_model": _require_text(board_model, "board_model"),
        "module_marking": _require_text(module_marking, "module_marking"),
        "device_flash_capacity_bytes": _require_nonnegative_int(
            device_flash_capacity_bytes, "device_flash_capacity_bytes"
        ),
        "device_psram_capacity_bytes": _require_nonnegative_int(
            device_psram_capacity_bytes, "device_psram_capacity_bytes"
        ),
        "firmware_sha256": _require_sha256(firmware_sha256, "firmware_sha256"),
        "manifest_sha256": _require_sha256(manifest_sha256, "manifest_sha256"),
        "environment": normalized_environment,
        "oi1_build": oi1_build,
        "oi1_observation": oi1_observation,
    }


def output_for_mode(mode, baseline_profile, observation):
    if mode == "baseline":
        return baseline_profile
    if mode == "verify":
        return observation
    raise BenchError("unknown mode %s" % mode)


def _checked_roundtrip_result(result, payload_size):
    if not isinstance(result, dict):
        raise BenchError("roundtrip result is not an object")
    required = {
        "put_unique_committed_bytes",
        "put_duration_ns",
        "put_retransmitted_chunks",
        "put_retransmitted_bytes",
        "get_unique_verified_bytes",
        "get_duration_ns",
        "get_retransmitted_chunks",
        "get_retransmitted_bytes",
        "integrity_verified",
        "offset_sequence_validated",
    }
    missing = required - set(result)
    if missing:
        raise BenchError("roundtrip result is missing %s" % sorted(missing))
    for key in (
        "put_unique_committed_bytes",
        "put_duration_ns",
        "put_retransmitted_chunks",
        "put_retransmitted_bytes",
        "get_unique_verified_bytes",
        "get_duration_ns",
        "get_retransmitted_chunks",
        "get_retransmitted_bytes",
    ):
        _require_nonnegative_int(result[key], "roundtrip.%s" % key)
    if result["put_unique_committed_bytes"] != payload_size:
        raise BenchError("PUT did not commit the exact frozen payload")
    if result["get_unique_verified_bytes"] != payload_size:
        raise BenchError("GET did not verify the exact frozen payload")
    if result["put_duration_ns"] <= 0 or result["get_duration_ns"] <= 0:
        raise BenchError("roundtrip durations must be positive")
    if result["integrity_verified"] is not True:
        raise BenchError("roundtrip integrity was not verified")
    if result["offset_sequence_validated"] is not True:
        raise BenchError("GET offsets were not validated")
    return result


async def collect_observation(profile_id, executor):
    """Run the frozen workload through an injected profile executor."""
    if profile_id not in PROFILE_ORDER:
        raise BenchError("profile is outside the current OI-1 order")
    expected_chip = PROFILE_TARGETS[profile_id]
    reset_samples = []
    default_heap = []
    post_hello_heap = []
    current_connection = None
    observed_transport = None

    try:
        for sample_index in range(WORKLOAD["reset_samples"]):
            latency, caps, backend_mtu, connection = (
                await executor.reset_connect_hello(sample_index)
            )
            try:
                latency = _require_nonnegative_int(
                    latency, "reset_to_service_advertisement_ms"
                )
                transport = validate_oi1_caps(
                    caps,
                    expected_chip=expected_chip,
                    backend_mtu=backend_mtu,
                )
                if observed_transport is None:
                    observed_transport = transport[:3]
                elif observed_transport != transport[:3]:
                    raise BenchError("HELLO transport caps changed between resets")
                snapshot = await executor.heap_snapshot(connection)
                reset_samples.append(latency)
                default_heap.append(transport[3])
                post_hello_heap.append(snapshot)
            except Exception:
                await executor.disconnect(connection)
                raise
            if sample_index + 1 < WORKLOAD["reset_samples"]:
                await executor.disconnect(connection)
            else:
                current_connection = connection

        put_unique = []
        put_duration = []
        put_goodput = []
        get_unique = []
        get_duration = []
        get_goodput = []
        put_rtx_chunks = []
        put_rtx_bytes = []
        get_rtx_chunks = []
        get_rtx_bytes = []
        post_roundtrip_heap = []
        integrity_verified = 0
        offsets_validated = 0

        for sample_index in range(WORKLOAD["roundtrip_samples"]):
            payload = deterministic_payload(
                profile_id,
                sample_index,
                WORKLOAD["roundtrip_payload_bytes"],
            )
            result = _checked_roundtrip_result(
                await executor.roundtrip(
                    current_connection,
                    "oi1/roundtrip_%02d.bin" % sample_index,
                    payload,
                ),
                len(payload),
            )
            put_unique.append(result["put_unique_committed_bytes"])
            put_duration.append(result["put_duration_ns"])
            put_goodput.append(
                goodput_bps(
                    result["put_unique_committed_bytes"],
                    result["put_duration_ns"],
                )
            )
            get_unique.append(result["get_unique_verified_bytes"])
            get_duration.append(result["get_duration_ns"])
            get_goodput.append(
                goodput_bps(
                    result["get_unique_verified_bytes"],
                    result["get_duration_ns"],
                )
            )
            put_rtx_chunks.append(result["put_retransmitted_chunks"])
            put_rtx_bytes.append(result["put_retransmitted_bytes"])
            get_rtx_chunks.append(result["get_retransmitted_chunks"])
            get_rtx_bytes.append(result["get_retransmitted_bytes"])
            integrity_verified += 1
            offsets_validated += 1
            post_roundtrip_heap.append(
                await executor.heap_snapshot(current_connection)
            )

        reliability = validate_reliability(
            await executor.reliability(current_connection, profile_id)
        )
        post_reliability_heap = await executor.heap_snapshot(current_connection)
        await executor.disconnect(current_connection)
        current_connection = None

        physical = await executor.physical_power_cycle()
        raw_log_sha256 = executor.raw_log_sha256()
        observation = {
            "observed_att_mtu": observed_transport[0],
            "observed_window": observed_transport[1],
            "observed_chunk_bytes": observed_transport[2],
            "reset_to_service_advertisement_ms": reset_samples,
            "heap_default_free_post_hello_bytes": default_heap,
            "heap_post_hello": post_hello_heap,
            "put_unique_committed_bytes": put_unique,
            "put_duration_ns": put_duration,
            "put_committed_goodput_bytes_per_second": put_goodput,
            "get_unique_verified_bytes": get_unique,
            "get_duration_ns": get_duration,
            "get_verified_goodput_bytes_per_second": get_goodput,
            "put_retransmitted_chunks": put_rtx_chunks,
            "put_retransmitted_bytes": put_rtx_bytes,
            "get_retransmitted_chunks": get_rtx_chunks,
            "get_retransmitted_bytes": get_rtx_bytes,
            "roundtrip_integrity_verified": integrity_verified,
            "get_offset_sequences_validated": offsets_validated,
            "roundtrip_unexpected_disconnects": 0,
            "roundtrip_integrity_failures": 0,
            "heap_post_roundtrip": post_roundtrip_heap,
            "reliability": reliability,
            "heap_post_reliability": post_reliability_heap,
            "physical_power_cycle_advertising": physical,
            "raw_log_sha256": raw_log_sha256,
        }
        return validate_observation(observation)
    finally:
        if current_connection is not None:
            await executor.disconnect(current_connection)


class SerialResetController:
    """Explicit RTS-to-EN reset controller; DTR stays deasserted (GPIO0 high)."""

    def __init__(self, port, baudrate=115200):
        try:
            import serial
        except Exception as exc:  # pragma: no cover - HIL-only dependency
            raise BenchError(
                "pyserial is required for reset control (pip install pyserial)"
            ) from exc
        try:
            device = serial.Serial()
            device.port = port
            device.baudrate = baudrate
            device.timeout = 1
            device.write_timeout = 1
            device.dsrdtr = False
            device.rtscts = False
            device.dtr = False
            device.rts = False
            device.open()
            device.dtr = False
            device.rts = False
        except Exception as exc:
            raise BenchError("cannot open explicit reset serial device: %s" % exc) from exc
        self._device = device

    def assert_reset(self):
        self._device.dtr = False
        self._device.rts = True

    def release_reset(self):
        self._device.rts = False

    def close(self):
        try:
            self._device.rts = False
            self._device.dtr = False
        finally:
            self._device.close()


class AdvertisementWatcher:
    """Streaming, address-bound, service-UUID-filtered Bleak scanner."""

    def __init__(self, address):
        self._address = address.casefold()
        self._scanner = None
        self._first_match_ns = None
        self._match_event = asyncio.Event()

    @property
    def first_match_ns(self):
        return self._first_match_ns

    def _on_advertisement(self, device, advertisement):
        address = str(getattr(device, "address", "")).casefold()
        advertised = {
            str(value).casefold()
            for value in (getattr(advertisement, "service_uuids", None) or [])
        }
        if address != self._address or SERVICE_UUID.casefold() not in advertised:
            return
        if self._first_match_ns is None:
            self._first_match_ns = time.monotonic_ns()
            self._match_event.set()

    async def start(self):
        try:
            from bleak import BleakScanner
        except Exception as exc:  # pragma: no cover - HIL-only dependency
            raise BenchError("bleak is required for HIL (pip install bleak)") from exc
        self._first_match_ns = None
        self._match_event = asyncio.Event()
        self._scanner = BleakScanner(
            detection_callback=self._on_advertisement,
            service_uuids=[SERVICE_UUID],
        )
        await self._scanner.start()

    async def wait_for_match(self, timeout_ms):
        if self._first_match_ns is None:
            await asyncio.wait_for(
                self._match_event.wait(),
                timeout=timeout_ms / 1000.0,
            )
        return self._first_match_ns

    async def stop(self):
        if self._scanner is not None:
            scanner = self._scanner
            self._scanner = None
            await scanner.stop()


class HardwareExecutor:
    def __init__(self, args, reset, raw_log):
        self.args = args
        self.reset = reset
        self.log = raw_log
        self.ids = CommandIds()
        self._workspace_ready = False

    async def reset_connect_hello(self, sample_index):
        watcher = AdvertisementWatcher(self.args.address)
        latency = await measure_reset_to_advertisement(
            self.reset,
            watcher,
        )
        self.log.write(
            "reset_advertisement",
            sample_index=sample_index,
            latency_ms=latency,
        )
        central = await PbleCentral.connect(self.args.address)
        try:
            caps, observed = await hello(
                central,
                self.ids.next,
                expected_chip=self.args.expect_chip,
            )
        except Exception:
            await central.disconnect()
            raise
        self.log.write(
            "hello",
            sample_index=sample_index,
            backend_mtu=central.backend_mtu,
            hello_mtu=observed[0],
            window=observed[1],
            chunk=observed[2],
            heap_default_free_bytes=observed[3],
        )
        return latency, caps, central.backend_mtu, central

    async def heap_snapshot(self, connection):
        snapshot = await run_heap_probe(connection, self.ids.next)
        self.log.write("heap_snapshot", **snapshot)
        return snapshot

    async def disconnect(self, connection):
        await connection.disconnect()
        self.log.write("disconnect")

    async def _ensure_workspace(self, connection):
        if not self._workspace_ready:
            await ensure_directory(connection, "oi1", self.ids.next)
            self._workspace_ready = True

    async def roundtrip(self, connection, path, payload):
        await self._ensure_workspace(connection)
        result = await roundtrip_file(
            connection,
            path,
            payload,
            next_id=self.ids.next,
        )
        self.log.write(
            "roundtrip",
            payload_bytes=len(payload),
            put_duration_ns=result["put_duration_ns"],
            get_duration_ns=result["get_duration_ns"],
            put_retransmitted_chunks=result["put_retransmitted_chunks"],
            put_retransmitted_bytes=result["put_retransmitted_bytes"],
            get_retransmitted_chunks=result["get_retransmitted_chunks"],
            get_retransmitted_bytes=result["get_retransmitted_bytes"],
        )
        return result

    async def reliability(self, connection, profile_id):
        result = await run_reliability(
            connection,
            profile_id,
            next_id=self.ids.next,
        )
        self.log.write("reliability", **result)
        return result

    async def physical_power_cycle(self):
        await asyncio.to_thread(
            input,
            "\nDisconnect all power from the board, wait until it is off, "
            "then press Enter: ",
        )
        watcher = AdvertisementWatcher(self.args.address)
        await watcher.start()
        try:
            await asyncio.sleep(1.0)
            if watcher.first_match_ns is not None:
                raise BenchError(
                    "board still advertised during the physical-power-off check"
                )
            await asyncio.to_thread(
                input,
                "Reconnect board power now, then press Enter; the scanner is active: ",
            )
            if watcher.first_match_ns is None:
                await watcher.wait_for_match(WORKLOAD["advertising_timeout_ms"])
        except asyncio.TimeoutError as exc:
            raise BenchError(
                "no fresh advertisement after physical power cycle"
            ) from exc
        finally:
            await watcher.stop()
        self.log.write("physical_power_cycle", result="passed")
        return "passed"

    def raw_log_sha256(self):
        self.log.write("measurement_complete")
        return self.log.sha256()


def _load_policy_thresholds(path, profile_id):
    try:
        payload = Path(path).read_bytes()
        policy = json.loads(payload.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError("cannot load qualification policy: %s" % exc) from exc
    if not isinstance(policy, dict):
        raise BenchError("qualification policy is not an object")
    expected_keys = {
        "schema_version",
        "qualification_scope",
        "profile_order",
        "deferred_profiles",
        "workload",
        "derivation",
        "baseline_evidence",
        "profiles",
    }
    if set(policy) != expected_keys:
        raise BenchError("qualification policy has the wrong top-level keys")
    if policy.get("schema_version") != 1:
        raise BenchError("qualification policy schema_version must be 1")
    if policy.get("qualification_scope") != "pre-v1":
        raise BenchError("qualification policy scope must be pre-v1")
    if policy.get("profile_order") != list(PROFILE_ORDER):
        raise BenchError("qualification policy has the wrong profile order")
    if policy.get("deferred_profiles") != ["esp32-c3-4mb"]:
        raise BenchError("qualification policy has the wrong deferred profile")
    if policy.get("workload") != WORKLOAD or policy.get("derivation") != DERIVATION:
        raise BenchError("qualification policy workload/derivation has drifted")
    profiles = policy.get("profiles")
    if (
        not isinstance(profiles, list)
        or len(profiles) != len(PROFILE_ORDER)
        or [
            item.get("profile_id") if isinstance(item, dict) else None
            for item in profiles
        ]
        != list(PROFILE_ORDER)
    ):
        raise BenchError("qualification policy profiles have the wrong order")
    for item in profiles:
        if set(item) != {"profile_id", "target", "thresholds"}:
            raise BenchError("qualification policy profile has the wrong keys")
    matches = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise BenchError("qualification policy lacks one matching profile")
    entry = matches[0]
    if entry.get("target") != PROFILE_TARGETS[profile_id]:
        raise BenchError("qualification policy target disagrees with profile")
    thresholds = entry.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(THRESHOLD_KEYS):
        raise BenchError("qualification policy thresholds have the wrong keys")
    return thresholds


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Frozen OI-1 single-profile PBLE/1 HIL bench"
    )
    parser.add_argument("--mode", required=True, choices=("baseline", "verify"))
    parser.add_argument("--profile", required=True, choices=PROFILE_ORDER)
    parser.add_argument("--expect-chip", required=True)
    parser.add_argument("--address", required=True, help="exact BLE UUID/MAC from scan")
    parser.add_argument(
        "--reset-port",
        required=True,
        help="explicit USB serial device whose RTS is wired to EN/reset",
    )
    parser.add_argument("--reset-baud", type=int, default=115200)
    parser.add_argument("--application-bin", required=True)
    parser.add_argument("--partition-table-bin", required=True)
    parser.add_argument(
        "--policy",
        help="committed oi1-gates.json (required only in verify mode)",
    )
    parser.add_argument("--raw-log", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--board-manufacturer")
    parser.add_argument("--board-model")
    parser.add_argument("--module-marking")
    parser.add_argument("--device-flash-capacity-bytes", type=int)
    parser.add_argument("--device-psram-capacity-bytes", type=int)
    parser.add_argument("--firmware-sha256")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--ble-backend")
    parser.add_argument("--ble-adapter")
    args = parser.parse_args(argv)
    expected = PROFILE_TARGETS[args.profile]
    if args.expect_chip != expected:
        parser.error(
            "--expect-chip must be %s for profile %s" % (expected, args.profile)
        )
    if args.mode == "verify" and not args.policy:
        parser.error("--policy is required in verify mode")
    return args


def _validate_run_metadata(args):
    fields = (
        "board_manufacturer",
        "board_model",
        "module_marking",
        "firmware_sha256",
        "manifest_sha256",
        "ble_backend",
        "ble_adapter",
    )
    for field in fields:
        if not getattr(args, field):
            raise BenchError("--%s is required for a real run" % field.replace("_", "-"))
    expected_flash, expected_psram = PROFILE_CAPACITIES[args.profile]
    if args.device_flash_capacity_bytes != expected_flash:
        raise BenchError(
            "physical flash capacity must equal %d for %s"
            % (expected_flash, args.profile)
        )
    if args.device_psram_capacity_bytes != expected_psram:
        raise BenchError(
            "physical PSRAM capacity must equal %d for %s"
            % (expected_psram, args.profile)
        )
    paths = [
        Path(args.raw_log).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        Path(args.application_bin).expanduser().resolve(),
        Path(args.partition_table_bin).expanduser().resolve(),
    ]
    if len(set(paths)) != len(paths):
        raise BenchError("raw log, output, and build inputs must be distinct paths")


async def _run(args):
    _validate_run_metadata(args)
    oi1_build = oi1_build_from_paths(
        args.application_bin,
        args.partition_table_bin,
    )
    raw_log = RedactedRawLog(args.raw_log)
    reset = None
    try:
        raw_log.write(
            "measurement_start",
            mode=args.mode,
            profile_id=args.profile,
            application_image_bytes=oi1_build["application_image_bytes"],
            factory_partition_bytes=oi1_build["factory_partition_bytes"],
            application_headroom_bytes=oi1_build["application_headroom_bytes"],
        )
        reset = SerialResetController(args.reset_port, args.reset_baud)
        executor = HardwareExecutor(args, reset, raw_log)
        try:
            observation = await collect_observation(args.profile, executor)
        except Exception as exc:
            raw_log.write("measurement_failed", failure_type=type(exc).__name__)
            raise
    finally:
        if reset is not None:
            reset.close()
        raw_log.close()

    if args.mode == "verify":
        thresholds = _load_policy_thresholds(args.policy, args.profile)
        evaluate_thresholds(oi1_build, observation, thresholds)
    baseline_profile = build_baseline_profile(
        profile_id=args.profile,
        board_manufacturer=args.board_manufacturer,
        board_model=args.board_model,
        module_marking=args.module_marking,
        device_flash_capacity_bytes=args.device_flash_capacity_bytes,
        device_psram_capacity_bytes=args.device_psram_capacity_bytes,
        firmware_sha256=args.firmware_sha256,
        manifest_sha256=args.manifest_sha256,
        environment={
            "desktop_os": platform.platform(),
            "ble_backend": args.ble_backend,
            "ble_adapter": args.ble_adapter,
            "python_version": platform.python_version(),
        },
        oi1_build=oi1_build,
        oi1_observation=observation,
    )
    output = output_for_mode(args.mode, baseline_profile, observation)
    atomic_write_canonical_json(args.output, output)
    if args.mode == "baseline":
        sys.stderr.buffer.write(
            b"Derived profile thresholds (not a release policy):\n"
            + canonical_json_bytes(derive_thresholds(oi1_build, observation))
        )
    return 0


def main(argv=None):
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except BenchError as exc:
        print("OI-1 HIL FAIL: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("OI-1 HIL interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
