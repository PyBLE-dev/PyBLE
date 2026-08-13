#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Frozen OI-1 single-profile HIL orchestrator.  Baseline mode emits one
# canonical profile fragment for later source-era assembly; verify mode emits
# the exact completed oi1_observation object after applying the committed
# profile thresholds.

import argparse
import asyncio
import errno
import importlib.util
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
    ESP_PROFILE_ORDER,
    PROFILE_CHIPS,
    PROFILE_ORDER,
    PROFILE_REQUIRES_2M,
    PROFILE_RESOURCE_KINDS,
    PROFILE_TARGETS,
    PROFILE_TRANSPORTS,
    RedactedRawLog,
    RP2_THRESHOLD_KEYS,
    THRESHOLD_KEYS,
    V051_PROFILE_ORDER,
    V051_WORKLOAD,
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
    parse_rp2_heap_probe_output,
    rp2_heap_probe_source,
    rp2_oi1_build_from_paths,
    roundtrip_file,
    run_heap_probe,
    run_rp2_heap_probe,
    run_reliability,
    validate_observation,
    validate_oi1_caps,
    validate_reliability,
    validate_transfer_link_facts,
    deterministic_payload,
)


PROFILE_CAPACITIES = {
    "esp32-4mb": (4 * 1024 * 1024, 0),
    "esp32-s3-n16r8": (16 * 1024 * 1024, 8 * 1024 * 1024),
    "waveshare-esp32-s3-lcd-147b": (
        16 * 1024 * 1024,
        8 * 1024 * 1024,
    ),
    "esp32-c3-4mb": (4 * 1024 * 1024, 0),
    "rpi-pico2-w": (4 * 1024 * 1024, 0),
}

SERIAL_ENDPOINT_GONE_ERRNOS = frozenset(
    (errno.EIO, errno.ENXIO, errno.ENODEV, errno.EBADF)
)
PRE_CAPTURE_SESSION_END_TIMEOUT_MS = 2000
SERIAL_POLL_INTERVAL_SECONDS = 0.01


def _load_rp2_console_pacing():
    """Import and validate the exact source-bound Pico pacing constants."""

    source = (
        Path(__file__).resolve().parents[3]
        / "firmware"
        / "pyble"
        / "pyble_console.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pyble_oi1_rp2_console_contract",
        source,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the Pico console pacing contract")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError("cannot import the Pico console pacing contract") from exc
    values = (
        getattr(module, "TX_CAPACITY", None),
        getattr(module, "TX_REFILL_PER_MS", None),
        getattr(module, "TX_BUDGET_MS", None),
    )
    if not all(type(value) is int and value > 0 for value in values):
        raise RuntimeError("Pico console pacing constants must be positive integers")
    capacity, refill_per_ms, budget_ms = values
    if budget_ms != (capacity + refill_per_ms - 1) // refill_per_ms:
        raise RuntimeError("Pico console pacing refill horizon changed")
    return values


(
    RP2_CONSOLE_TX_CAPACITY,
    RP2_CONSOLE_TX_REFILL_PER_MS,
    RP2_CONSOLE_TX_BUDGET_MS,
) = _load_rp2_console_pacing()


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
        install_sha256=None,
        resource_image_sha256=None,
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
    common = {
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
        "environment": normalized_environment,
        "oi1_build": oi1_build,
        "oi1_observation": oi1_observation,
    }
    if profile_id == "rpi-pico2-w":
        common.update(
            {
                "resource_kind": "rp2",
                "install_sha256": _require_sha256(
                    install_sha256, "install_sha256"
                ),
                "resource_image_sha256": _require_sha256(
                    resource_image_sha256, "resource_image_sha256"
                ),
            }
        )
    elif install_sha256 is not None:
        common.update(
            {
                "resource_kind": "esp-idf",
                "install_sha256": _require_sha256(
                    install_sha256, "install_sha256"
                ),
                "manifest_sha256": _require_sha256(
                    manifest_sha256, "manifest_sha256"
                ),
            }
        )
    else:
        common.update(
            {
                "firmware_sha256": _require_sha256(
                    firmware_sha256, "firmware_sha256"
                ),
                "manifest_sha256": _require_sha256(
                    manifest_sha256, "manifest_sha256"
                ),
            }
        )
    return common


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


class LinkFactParser:
    """Parse only the fixed, identifier-free ADR-0027 serial grammar."""

    _REQUEST = re.compile(
        r"link tune req phase=(dle|phy|conn-param) "
        r"attempt=(0|[1-9][0-9]*) "
        r"context=(connect|timer|retry) rc=(0|[1-9][0-9]*)"
    )
    _DLE_COMPLETE = re.compile(
        r"link tune complete phase=dle "
        r"max_tx_octets=(0|[1-9][0-9]*) "
        r"max_tx_time_us=(0|[1-9][0-9]*)"
    )
    _PHY_COMPLETE = re.compile(
        r"link tune complete phase=phy status=(0|[1-9][0-9]*) "
        r"tx=(0|[1-9][0-9]*) rx=(0|[1-9][0-9]*)"
    )
    _CP_COMPLETE = re.compile(
        r"link tune complete phase=conn-param "
        r"status=(0|[1-9][0-9]*) "
        r"interval_units=(0|[1-9][0-9]*)"
    )
    _CLASSIC_PHY_SKIP = re.compile(
        r"link tune skip phase=phy context=classic-compiled-out"
    )
    _SESSION_END = re.compile(
        r"link tune session end tx_mbuf_starve_count=(0|[1-9][0-9]*)"
    )

    def __init__(self, profile_id):
        if profile_id not in ESP_PROFILE_ORDER:
            raise BenchError("NimBLE link parsing requires an ESP profile")
        self.profile_id = profile_id
        self._stage = "dle"
        self._attempts = {"dle": 0, "phy": 0, "conn-param": 0}
        self._dle = None
        self._phy_updates = []
        self._classic_phy_skipped = False
        self._cp_return_codes = []
        self._cp_updates = []
        self._settled_phy = (0, 0)
        self._settled_interval = None
        self._session_end = None
        self._sealed = False
        self._new_records = []

    @staticmethod
    def _payload(line):
        if isinstance(line, bytes):
            if b"link tune" not in line:
                return None
            try:
                line = line.decode("ascii", errors="strict")
            except UnicodeDecodeError as exc:
                raise BenchError("link-tune record is not strict ASCII") from exc
        if not isinstance(line, str):
            raise BenchError("serial line must be bytes or text")
        if "link tune" not in line:
            return None
        line = line.rstrip("\r\n")
        # ESP-IDF may wrap ERROR records in its fixed color transport framing;
        # the reset code is not part of the parser-owned payload grammar.
        if line.endswith("\x1b[0m"):
            line = line[:-4]
        start = line.find("link tune")
        if line.find("link tune", start + 1) >= 0:
            raise BenchError("serial line contains duplicate link-tune records")
        return line[start:]

    def _record(self, record_type, **fields):
        self._new_records.append({"record_type": record_type, **fields})

    def take_records(self):
        records = self._new_records
        self._new_records = []
        return records

    @property
    def is_settled(self):
        return self._stage == "settled"

    @property
    def has_session_end(self):
        return self._session_end is not None

    def feed_line(self, line):
        payload = self._payload(line)
        if payload is None:
            return False
        if self._sealed:
            raise BenchError("link-fact parser is already sealed")

        match = self._REQUEST.fullmatch(payload)
        if match is not None:
            phase, raw_attempt, context, raw_rc = match.groups()
            if phase == "phy" and not PROFILE_REQUIRES_2M[self.profile_id]:
                raise BenchError("this profile must not request PHY tuning")
            if phase != self._stage:
                raise BenchError(
                    "link-tune request is out of order for phase %s" % phase
                )
            attempt = int(raw_attempt)
            expected = self._attempts[phase] + 1
            maximum = 3 if phase == "conn-param" else 4
            if attempt != expected or not 1 <= attempt <= maximum:
                raise BenchError(
                    "%s request attempt must be sequential in 1..%d"
                    % (phase, maximum)
                )
            return_code = int(raw_rc)
            self._attempts[phase] = attempt
            if phase == "conn-param":
                self._cp_return_codes.append(return_code)
            self._record(
                "request",
                phase=phase,
                attempt=attempt,
                context=context,
                return_code=return_code,
            )
            return True

        match = self._DLE_COMPLETE.fullmatch(payload)
        if match is not None:
            if self._attempts["dle"] == 0:
                raise BenchError("DLE completion is out of order")
            max_tx_octets, max_tx_time_us = (int(item) for item in match.groups())
            self._dle = {
                "request_attempts": self._attempts["dle"],
                "max_tx_octets": max_tx_octets,
                "max_tx_time_us": max_tx_time_us,
            }
            if (
                self._stage == "dle"
                and max_tx_octets >= 244
                and max_tx_time_us > 0
            ):
                self._stage = (
                    "phy"
                    if PROFILE_REQUIRES_2M[self.profile_id]
                    else "phy-skip"
                )
            self._record(
                "completion",
                phase="dle",
                max_tx_octets=max_tx_octets,
                max_tx_time_us=max_tx_time_us,
            )
            return True

        match = self._PHY_COMPLETE.fullmatch(payload)
        if match is not None:
            if not PROFILE_REQUIRES_2M[self.profile_id]:
                raise BenchError("this profile must not report PHY updates")
            status, tx, rx = (int(item) for item in match.groups())
            update = {"status": status, "tx": tx, "rx": rx}
            self._phy_updates.append(update)
            self._record("completion", phase="phy", **update)
            if (
                self._stage == "phy"
                and self._attempts["phy"] > 0
                and (status, tx, rx) == (0, 2, 2)
            ):
                self._settled_phy = (tx, rx)
                self._stage = "conn-param"
            return True

        if self._CLASSIC_PHY_SKIP.fullmatch(payload) is not None:
            if PROFILE_REQUIRES_2M[self.profile_id]:
                raise BenchError("2M profile must not compile out PHY tuning")
            if self._stage != "phy-skip" or self._classic_phy_skipped:
                raise BenchError("classic PHY skip is out of order")
            self._classic_phy_skipped = True
            self._stage = "conn-param"
            self._record("skip", phase="phy", context="classic-compiled-out")
            return True

        match = self._CP_COMPLETE.fullmatch(payload)
        if match is not None:
            status, interval_units = (int(item) for item in match.groups())
            update = {"status": status, "interval_units": interval_units}
            self._cp_updates.append(update)
            self._record("completion", phase="conn-param", **update)
            if (
                self._stage == "conn-param"
                and self._attempts["conn-param"] > 0
                and status == 0
                and 12 <= interval_units <= 24
            ):
                self._settled_interval = interval_units
                self._stage = "settled"
            return True

        match = self._SESSION_END.fullmatch(payload)
        if match is not None:
            if not self.is_settled:
                raise BenchError("link-tune session ended before settlement")
            if self._session_end is not None:
                raise BenchError("duplicate link-tune session end")
            self._session_end = int(match.group(1))
            self._record(
                "session_end", tx_mbuf_starve_count=self._session_end
            )
            return True

        raise BenchError("malformed or unsupported link-tune record")

    def _facts(self, tx_mbuf_starve_count):
        if PROFILE_REQUIRES_2M[self.profile_id]:
            phy = {
                "required_2m": True,
                "request_attempts": self._attempts["phy"],
                "updates": [dict(item) for item in self._phy_updates],
                "settled_tx": self._settled_phy[0],
                "settled_rx": self._settled_phy[1],
            }
        else:
            phy = {
                "required_2m": False,
                "request_attempts": 0,
                "updates": [],
                "settled_tx": 0,
                "settled_rx": 0,
            }
        return {
            "dle": dict(self._dle or {}),
            "phy": phy,
            "connection_parameters": {
                "request_return_codes": list(self._cp_return_codes),
                "updates": [dict(item) for item in self._cp_updates],
                "settled_interval_units": self._settled_interval,
            },
            "tx_mbuf_starve_count": tx_mbuf_starve_count,
        }

    def require_settled(self):
        if not self.is_settled:
            phase = self._stage
            attempts = self._attempts.get(phase, 0)
            maximum = 3 if phase == "conn-param" else 4
            suffix = " after exhausted attempts" if attempts >= maximum else ""
            raise BenchError("link-tune session is unsettled in %s%s" % (phase, suffix))
        validate_transfer_link_facts(
            self._facts(0), profile_id=self.profile_id
        )

    def seal(self):
        self.require_settled()
        if self._session_end is None:
            raise BenchError(
                "link-tune session end/starve fact is required before seal"
            )
        facts = self._facts(self._session_end)
        validate_transfer_link_facts(facts, profile_id=self.profile_id)
        self._sealed = True
        return facts


async def collect_observation(profile_id, executor):
    """Run the frozen workload through an injected profile executor."""
    if profile_id not in PROFILE_ORDER:
        raise BenchError("profile is outside the current OI-1 order")
    expected_chip = PROFILE_CHIPS[profile_id]
    reset_samples = []
    default_heap = []
    post_hello_heap = []
    current_connection = None
    observed_transport = None

    try:
        for sample_index in range(WORKLOAD["reset_samples"]):
            if sample_index + 1 == WORKLOAD["reset_samples"]:
                await executor.begin_transfer_link_capture(profile_id)
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
                    profile_id=profile_id,
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

        await executor.await_transfer_link_settlement(5000)

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
        transfer_link_facts = await executor.seal_transfer_link_facts(2000)

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
            "transfer_link_facts": transfer_link_facts,
            "physical_power_cycle_advertising": physical,
            "raw_log_sha256": raw_log_sha256,
        }
        return validate_observation(observation, profile_id=profile_id)
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
        # Drop any bytes that raced with the pre-reset clear only after EN is
        # held low. The following release therefore starts an isolated UART
        # session without losing that session's boot/link facts.
        self._device.reset_input_buffer()

    def release_reset(self):
        self._device.rts = False

    def prepare_after_advertisement(self):
        """External UART bridges remain open across an ESP reset."""
        return None

    def clear_input_buffer(self):
        if self._device is None:
            raise BenchError("reset serial device is closed")
        self._device.reset_input_buffer()

    def read_available(self):
        """Return only bytes already buffered by the private serial handle."""
        if self._device is None:
            raise BenchError("reset serial device is closed")
        waiting = self._device.in_waiting
        if isinstance(waiting, bool) or not isinstance(waiting, int) or waiting < 0:
            raise BenchError("reset serial device reported invalid buffered length")
        if waiting == 0:
            return b""
        payload = self._device.read(waiting)
        if not isinstance(payload, bytes):
            raise BenchError("reset serial device returned non-byte data")
        return payload

    def close(self, *, allow_endpoint_gone=False):
        device = self._device
        if device is None:
            return
        self._device = None
        first_error = None
        actions = (
            lambda: setattr(device, "rts", False),
            lambda: setattr(device, "dtr", False),
            device.close,
        )
        for action in actions:
            try:
                action()
            except Exception as exc:
                endpoint_gone = (
                    allow_endpoint_gone
                    and isinstance(exc, OSError)
                    and exc.errno in SERIAL_ENDPOINT_GONE_ERRNOS
                )
                if not endpoint_gone and first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


WAVESHARE_RESET_HOLD_PROMPT = (
    "Press and hold RESET on the Waveshare ESP32-S3-LCD-1.47B, "
    "keep holding it, then press Enter: "
)
WAVESHARE_RESET_RELEASE_PROMPT = (
    "Release RESET now, then press Enter immediately: "
)


class WaveshareOperatorResetController:
    """Native-USB UART capture plus the exact-board physical RESET seam.

    The board's USB serial control lines are not wired evidence of EN/reset.
    They are therefore never changed by assert_reset()/release_reset(); those
    methods only collect the two frozen physical-action confirmations.
    """

    def __init__(self, port, baudrate=115200, operator_action=None):
        if operator_action is None:
            operator_action = input
        if not callable(operator_action):
            raise BenchError("Waveshare operator action must be callable")
        try:
            import serial
        except Exception as exc:  # pragma: no cover - HIL-only dependency
            raise BenchError(
                "pyserial is required for reset control (pip install pyserial)"
            ) from exc
        self._serial = serial
        self._port = port
        self._baudrate = baudrate
        self._device = None
        self._closed = False
        self._operator_action = operator_action
        self._open_device()

    @staticmethod
    def _open_without_modem_line_updates(device):
        """Open pyserial without applying its cached RTS/DTR states.

        POSIX pyserial normally applies both cached modem-line states after
        configuring a newly opened descriptor.  Its flow-control flags guard
        those two updates, but the port itself must still be configured with
        hardware flow control disabled.  While open() runs, present the guard
        values to that post-config branch and wrap pyserial's configuration
        hook so the actual termios state remains no-flow.  The private flags
        can then return to their truthful false values without another ioctl.
        """
        reconfigure = getattr(device, "_reconfigure_port", None)
        guards_posix_open = (
            callable(reconfigure)
            and hasattr(device, "_dsrdtr")
            and hasattr(device, "_rtscts")
        )

        if guards_posix_open:
            def reconfigure_without_flow_control(*args, **kwargs):
                saved_dsrdtr = device._dsrdtr
                saved_rtscts = device._rtscts
                device._dsrdtr = False
                device._rtscts = False
                try:
                    return reconfigure(*args, **kwargs)
                finally:
                    device._dsrdtr = saved_dsrdtr
                    device._rtscts = saved_rtscts

            device._reconfigure_port = reconfigure_without_flow_control

        # These are open-time guards, not the live port configuration.  On
        # pyserial POSIX the wrapper above keeps hardware flow control off.
        device.dsrdtr = True
        device.rtscts = True
        opened = False
        try:
            device.open()
            opened = True
        finally:
            if guards_posix_open:
                device._reconfigure_port = reconfigure
                device._dsrdtr = False
                device._rtscts = False
            elif opened:
                # Test doubles and non-POSIX implementations do not expose
                # pyserial's configuration hook.  Restore their public state
                # only after the guarded open has completed.
                device.dsrdtr = False
                device.rtscts = False

    def _open_device(self):
        if self._closed:
            raise BenchError("Waveshare reset controller is closed")
        if self._device is not None:
            raise BenchError("Waveshare native USB device is already open")
        try:
            device = self._serial.Serial()
            device.port = self._port
            device.baudrate = self._baudrate
            device.timeout = 1
            device.write_timeout = 1
            # Native USB control lines are deliberately never assigned or
            # implicitly applied: they are not wired proof of EN/reset on
            # this exact board.
            self._open_without_modem_line_updates(device)
        except Exception as exc:
            raise BenchError("cannot open explicit reset serial device: %s" % exc) from exc
        self._device = device

    def _close_device(self, *, allow_endpoint_gone=False):
        device = self._device
        if device is None:
            return
        self._device = None
        try:
            device.close()
        except Exception as exc:
            endpoint_gone = (
                allow_endpoint_gone
                and isinstance(exc, OSError)
                and exc.errno in SERIAL_ENDPOINT_GONE_ERRNOS
            )
            if not endpoint_gone:
                raise

    def _prompt(self, message):
        if self._closed:
            raise BenchError("Waveshare reset controller is closed")
        self._operator_action(message)

    def assert_reset(self):
        self._prompt(WAVESHARE_RESET_HOLD_PROMPT)
        # The chip-native USB endpoint disappears during physical RESET. Close
        # its stale descriptor after RESET-held confirmation; ENODEV here is
        # expected and is not a reason to lose the physical measurement.
        self._close_device(allow_endpoint_gone=True)

    def release_reset(self):
        self._prompt(WAVESHARE_RESET_RELEASE_PROMPT)

    def prepare_after_advertisement(self):
        # Reopen only after the first measured fresh advertisement and before
        # BLE HELLO/link-fact capture. Never toggle RTS or DTR.
        self._open_device()

    def clear_input_buffer(self):
        if self._device is None:
            raise BenchError("reset serial device is closed")
        self._device.reset_input_buffer()

    def read_available(self):
        if self._device is None:
            raise BenchError("reset serial device is closed")
        waiting = self._device.in_waiting
        if isinstance(waiting, bool) or not isinstance(waiting, int) or waiting < 0:
            raise BenchError("reset serial device reported invalid buffered length")
        if waiting == 0:
            return b""
        payload = self._device.read(waiting)
        if not isinstance(payload, bytes):
            raise BenchError("reset serial device returned non-byte data")
        return payload

    def close(self, *, allow_endpoint_gone=False):
        if self._closed:
            return
        self._closed = True
        self._close_device(allow_endpoint_gone=allow_endpoint_gone)


class Rp2OperatorResetController:
    """Prompt-only Pico reset/power seam; it deliberately owns no tty."""

    def __init__(self, operator_action=None):
        if operator_action is None:
            operator_action = input
        if not callable(operator_action):
            raise BenchError("RP2 operator action must be callable")
        self._operator_action = operator_action
        self._closed = False

    def _prompt(self, message):
        if self._closed:
            raise BenchError("RP2 operator reset controller is closed")
        self._operator_action(message)

    def assert_reset(self):
        self._prompt(
            "Disconnect all Pico 2 W power, confirm the board is off, "
            "then press Enter: "
        )

    def release_reset(self):
        self._prompt(
            "Reconnect Pico 2 W power now, then press Enter immediately: "
        )

    def power_off(self):
        self._prompt(
            "Disconnect all Pico 2 W power, confirm the board is off, "
            "then press Enter: "
        )

    def power_on(self):
        self._prompt("Reconnect Pico 2 W power now, then press Enter: ")

    def close(self, **_kwargs):
        self._closed = True


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
        self._link_parser = None
        self._serial_pending = bytearray()

    async def begin_transfer_link_capture(self, profile_id):
        if self._link_parser is not None:
            raise BenchError("transfer link capture has already started")
        self.reset.clear_input_buffer()
        self._serial_pending.clear()
        self._link_parser = LinkFactParser(profile_id)
        self.log.write("transfer_link_capture_started", profile_id=profile_id)

    async def _pump_transfer_link_serial(self):
        if self._link_parser is None:
            raise BenchError("transfer link capture has not started")
        chunk = self.reset.read_available()
        if chunk:
            self._serial_pending.extend(chunk)
        while b"\n" in self._serial_pending:
            raw_line, _, remainder = self._serial_pending.partition(b"\n")
            self._serial_pending = bytearray(remainder)
            # bytearray.partition() preserves the mutable container type, but
            # the strict parser intentionally admits only immutable bytes or
            # text.  Freeze each complete UART line at this boundary.
            recognized = self._link_parser.feed_line(bytes(raw_line))
            if recognized:
                for record in self._link_parser.take_records():
                    self.log.write("transfer_link_fact", **record)
        if len(self._serial_pending) > 65536:
            if b"link tune" in self._serial_pending:
                raise BenchError("unterminated link-tune serial record")
            self._serial_pending.clear()

    async def _wait_for_link_fact(self, predicate, timeout_ms, label):
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
        ):
            raise BenchError("%s timeout must be a positive integer" % label)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000.0
        while True:
            await self._pump_transfer_link_serial()
            if predicate():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise BenchError("%s was not observed within %d ms" % (label, timeout_ms))
            await asyncio.sleep(min(0.01, remaining))

    async def await_transfer_link_settlement(self, timeout_ms):
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms > 5000
        ):
            raise BenchError(
                "transfer link settlement timeout must be 1..5000 ms"
            )
        await self._wait_for_link_fact(
            lambda: self._link_parser is not None
            and self._link_parser.is_settled,
            timeout_ms,
            "settled transfer link",
        )
        self._link_parser.require_settled()
        self.log.write("transfer_link_settled")

    async def seal_transfer_link_facts(self, timeout_ms):
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms > 2000
        ):
            raise BenchError("transfer link seal timeout must be 1..2000 ms")
        if self._link_parser is None:
            raise BenchError("transfer link capture has not started")
        self._link_parser.require_settled()
        await self._wait_for_link_fact(
            lambda: self._link_parser.has_session_end,
            timeout_ms,
            "transfer link session end/starve fact",
        )
        facts = self._link_parser.seal()
        self.log.write("transfer_link_facts", facts=facts)
        return facts

    async def reset_connect_hello(self, sample_index):
        watcher = AdvertisementWatcher(self.args.address)
        latency = await measure_reset_to_advertisement(
            self.reset,
            watcher,
        )
        # External UART controllers keep their descriptor and no-op here. The
        # exact Waveshare native-USB controller reopens its post-reset endpoint
        # after the measured advertisement and before BLE/serial evidence.
        if self.args.profile == "waveshare-esp32-s3-lcd-147b":
            self.reset.prepare_after_advertisement()
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
                profile_id=self.args.profile,
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

    async def _drain_pre_capture_session_end(self, timeout_ms):
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms > PRE_CAPTURE_SESSION_END_TIMEOUT_MS
        ):
            raise BenchError(
                "pre-capture session-end timeout must be 1..%d ms"
                % PRE_CAPTURE_SESSION_END_TIMEOUT_MS
            )

        pending = bytearray()
        terminal_count = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000.0

        while True:
            chunk = self.reset.read_available()
            if chunk:
                pending.extend(chunk)

            while b"\n" in pending:
                raw_line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                payload = LinkFactParser._payload(bytes(raw_line))
                if (
                    payload is not None
                    and LinkFactParser._SESSION_END.fullmatch(payload)
                    is not None
                ):
                    terminal_count += 1

            if terminal_count > 1:
                raise BenchError("duplicate pre-capture session end")
            if terminal_count == 1:
                pending.clear()
                self._serial_pending.clear()
                self.reset.clear_input_buffer()
                return

            # Non-parser UART output is private and is never retained. Bound a
            # malformed stream without copying any of its contents into an
            # error or the qualification log.
            if len(pending) > 65536:
                pending.clear()

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise BenchError(
                    "pre-capture session end was not observed within %d ms"
                    % timeout_ms
                )
            await asyncio.sleep(
                min(SERIAL_POLL_INTERVAL_SECONDS, remaining)
            )

    async def disconnect(self, connection):
        await connection.disconnect()
        self.log.write("disconnect")
        if self._link_parser is None:
            # The first nine sessions are not link-fact evidence. Consume one
            # exact terminal boundary without retaining its private count or
            # any other UART bytes, then isolate the next controlled reset.
            await self._drain_pre_capture_session_end(
                PRE_CAPTURE_SESSION_END_TIMEOUT_MS
            )

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
            window=PROFILE_TRANSPORTS[self.args.profile][
                "required_put_window"
            ],
            chunk=PROFILE_TRANSPORTS[self.args.profile][
                "required_chunk_bytes"
            ],
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
        # No controlled resets occur after this point. Release the tty while it
        # still exists, before the operator intentionally removes board power.
        self.reset.close()
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


class Rp2HardwareExecutor(HardwareExecutor):
    """Pico executor with GC/BTstack evidence and no ESP UART dependency."""

    def __init__(self, args, reset, raw_log):
        super().__init__(args, reset, raw_log)
        self._capture_started = False
        self._hello_transport = None

    async def begin_transfer_link_capture(self, profile_id):
        if profile_id != "rpi-pico2-w":
            raise BenchError("RP2 executor requires the Pico 2 W profile")
        if self._capture_started:
            raise BenchError("RP2 transfer link capture has already started")
        self._capture_started = True
        self.log.write("transfer_link_capture_started", profile_id=profile_id)

    async def await_transfer_link_settlement(self, timeout_ms):
        if not self._capture_started:
            raise BenchError("RP2 transfer link capture has not started")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms > 5000
        ):
            raise BenchError(
                "RP2 transfer link settlement timeout must be 1..5000 ms"
            )
        self.log.write("transfer_link_settled")

    async def reset_connect_hello(self, sample_index):
        result = await super().reset_connect_hello(sample_index)
        _latency, caps, backend_mtu, _connection = result
        self._hello_transport = {
            "observed_att_mtu": backend_mtu,
            "observed_window": int(caps["window"]),
            "observed_chunk_bytes": int(caps["chunk"]),
        }
        return result

    def _btstack_facts(self):
        if self._hello_transport is None:
            raise BenchError(
                "RP2 HELLO transport observation has not been captured"
            )
        return {
            "ble_host": "btstack",
            **self._hello_transport,
            "console_tx_budget_ms": RP2_CONSOLE_TX_BUDGET_MS,
        }

    async def seal_transfer_link_facts(self, timeout_ms):
        if not self._capture_started:
            raise BenchError("RP2 transfer link capture has not started")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms > 2000
        ):
            raise BenchError("RP2 transfer link seal timeout must be 1..2000 ms")
        facts = self._btstack_facts()
        validate_transfer_link_facts(facts, profile_id="rpi-pico2-w")
        self.log.write("transfer_link_facts", facts=facts)
        return facts

    async def heap_snapshot(self, connection):
        snapshot = await run_rp2_heap_probe(connection, self.ids.next)
        self.log.write("heap_snapshot", **snapshot)
        return snapshot

    async def disconnect(self, connection):
        await connection.disconnect()
        self.log.write("disconnect")

    async def physical_power_cycle(self):
        self.reset.power_off()
        watcher = AdvertisementWatcher(self.args.address)
        await watcher.start()
        try:
            await asyncio.sleep(1.0)
            if watcher.first_match_ns is not None:
                raise BenchError(
                    "board still advertised during the physical-power-off check"
                )
            self.reset.power_on()
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


def _load_policy_thresholds(path, profile_id):
    try:
        payload = Path(path).read_bytes()
        policy = json.loads(payload.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError("cannot load qualification policy: %s" % exc) from exc
    if not isinstance(policy, dict):
        raise BenchError("qualification policy is not an object")
    schema_version = policy.get("schema_version")
    common_keys = {
        "schema_version",
        "qualification_scope",
        "profile_order",
        "workload",
        "derivation",
        "baseline_evidence",
        "profiles",
    }
    if schema_version == 2:
        expected_keys = common_keys | {"deferred_profiles"}
        profile_order = V051_PROFILE_ORDER
        expected_scope = "pre-v1"
        expected_workload = V051_WORKLOAD
        if policy.get("deferred_profiles") != ["esp32-c3-4mb"]:
            raise BenchError("qualification policy has the wrong deferred profile")
    elif schema_version == 3:
        expected_keys = common_keys
        profile_order = PROFILE_ORDER
        expected_scope = "v0.6.0-five-profile"
        expected_workload = WORKLOAD
    else:
        raise BenchError("qualification policy schema_version must be 2 or 3")
    if set(policy) != expected_keys:
        raise BenchError("qualification policy has the wrong top-level keys")
    if policy.get("qualification_scope") != expected_scope:
        raise BenchError("qualification policy has the wrong scope")
    if policy.get("profile_order") != list(profile_order):
        raise BenchError("qualification policy has the wrong profile order")
    if (
        policy.get("workload") != expected_workload
        or policy.get("derivation") != DERIVATION
    ):
        raise BenchError("qualification policy workload/derivation has drifted")
    profiles = policy.get("profiles")
    if (
        not isinstance(profiles, list)
        or len(profiles) != len(profile_order)
        or [
            item.get("profile_id") if isinstance(item, dict) else None
            for item in profiles
        ]
        != list(profile_order)
    ):
        raise BenchError("qualification policy profiles have the wrong order")
    if profile_id not in profile_order:
        raise BenchError("qualification policy does not cover this profile")
    for item in profiles:
        current_profile_id = item["profile_id"]
        if schema_version == 2:
            if set(item) != {"profile_id", "target", "thresholds"}:
                raise BenchError("qualification policy profile has the wrong keys")
            threshold_keys = THRESHOLD_KEYS
        else:
            if set(item) != {
                "profile_id",
                "target",
                "resource_kind",
                "transport",
                "thresholds",
            }:
                raise BenchError("qualification policy profile has the wrong keys")
            if item.get("resource_kind") != PROFILE_RESOURCE_KINDS[current_profile_id]:
                raise BenchError("qualification policy resource kind disagrees")
            if item.get("transport") != PROFILE_TRANSPORTS[current_profile_id]:
                raise BenchError("qualification policy transport disagrees")
            threshold_keys = (
                RP2_THRESHOLD_KEYS
                if PROFILE_RESOURCE_KINDS[current_profile_id] == "rp2"
                else THRESHOLD_KEYS
            )
        if item.get("target") != PROFILE_TARGETS[current_profile_id]:
            raise BenchError("qualification policy target disagrees with profile")
        thresholds = item.get("thresholds")
        if not isinstance(thresholds, dict) or set(thresholds) != set(threshold_keys):
            raise BenchError("qualification policy thresholds have the wrong keys")
        for key in threshold_keys:
            if (
                isinstance(thresholds[key], bool)
                or not isinstance(thresholds[key], int)
                or thresholds[key] <= 0
            ):
                raise BenchError("qualification policy threshold must be positive")
    matches = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise BenchError("qualification policy lacks one matching profile")
    entry = matches[0]
    return entry["thresholds"]


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
        help="explicit USB serial device whose RTS is wired to EN/reset",
    )
    parser.add_argument("--reset-baud", type=int, default=115200)
    parser.add_argument("--application-bin")
    parser.add_argument("--partition-table-bin")
    parser.add_argument(
        "--operator-reset",
        action="store_true",
        help="use the exact physical reset seam for Waveshare or Pico 2 W",
    )
    parser.add_argument("--firmware-bin")
    parser.add_argument("--firmware-uf2")
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
    parser.add_argument("--install-sha256")
    parser.add_argument("--ble-backend")
    parser.add_argument("--ble-adapter")
    args = parser.parse_args(argv)
    expected = PROFILE_CHIPS[args.profile]
    if args.expect_chip != expected:
        parser.error(
            "--expect-chip must be %s for profile %s" % (expected, args.profile)
        )
    if args.mode == "verify" and not args.policy:
        parser.error("--policy is required in verify mode")
    is_rp2 = args.profile == "rpi-pico2-w"
    esp_inputs = (
        args.reset_port,
        args.application_bin,
        args.partition_table_bin,
    )
    rp2_inputs = (
        args.firmware_bin,
        args.firmware_uf2,
    )
    is_waveshare = args.profile == "waveshare-esp32-s3-lcd-147b"
    if is_rp2:
        if not args.operator_reset or any(value is None for value in rp2_inputs):
            parser.error(
                "Pico 2 W requires --operator-reset, --firmware-bin, "
                "and --firmware-uf2"
            )
        if any(value is not None for value in esp_inputs):
            parser.error("Pico 2 W forbids ESP reset and build inputs")
    else:
        if any(value is None for value in esp_inputs):
            parser.error(
                "ESP profiles require --reset-port, --application-bin, "
                "and --partition-table-bin"
            )
        if any(value is not None for value in rp2_inputs):
            parser.error("ESP profiles forbid RP2 reset and build inputs")
        if is_waveshare and not args.operator_reset:
            parser.error("Waveshare requires --operator-reset")
        if not is_waveshare and args.operator_reset:
            parser.error("operator reset is forbidden for UART-reset ESP profiles")
    return args


def _validate_run_metadata(args):
    is_rp2 = args.profile == "rpi-pico2-w"
    fields = [
        "board_manufacturer",
        "board_model",
        "module_marking",
        "ble_backend",
        "ble_adapter",
    ]
    fields.extend(
        ("firmware_sha256", "install_sha256")
        if is_rp2
        else ("install_sha256", "manifest_sha256")
    )
    for field in fields:
        if not getattr(args, field):
            raise BenchError("--%s is required for a real run" % field.replace("_", "-"))
    forbidden_digest = "manifest_sha256" if is_rp2 else "firmware_sha256"
    if getattr(args, forbidden_digest) is not None:
        raise BenchError(
            "--%s is forbidden for %s"
            % (forbidden_digest.replace("_", "-"), args.profile)
        )
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
    build_inputs = (
        [args.firmware_bin, args.firmware_uf2]
        if is_rp2
        else [args.application_bin, args.partition_table_bin]
    )
    paths = [
        Path(args.raw_log).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        *(Path(path).expanduser().resolve() for path in build_inputs),
    ]
    if len(set(paths)) != len(paths):
        raise BenchError("raw log, output, and build inputs must be distinct paths")


def _close_run_resources(reset, raw_log):
    try:
        if reset is not None:
            reset.close()
    finally:
        raw_log.close()


async def _run(args):
    _validate_run_metadata(args)
    is_rp2 = args.profile == "rpi-pico2-w"
    if is_rp2:
        oi1_build = rp2_oi1_build_from_paths(
            args.firmware_bin,
            args.firmware_uf2,
        )
    else:
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
            **oi1_build,
        )
        if is_rp2:
            reset = Rp2OperatorResetController()
            executor = Rp2HardwareExecutor(args, reset, raw_log)
        elif args.profile == "waveshare-esp32-s3-lcd-147b":
            reset = WaveshareOperatorResetController(
                args.reset_port,
                args.reset_baud,
            )
            executor = HardwareExecutor(args, reset, raw_log)
        else:
            reset = SerialResetController(args.reset_port, args.reset_baud)
            executor = HardwareExecutor(args, reset, raw_log)
        try:
            observation = await collect_observation(args.profile, executor)
        except Exception as exc:
            raw_log.write("measurement_failed", failure_type=type(exc).__name__)
            raise
    finally:
        _close_run_resources(reset, raw_log)

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
        install_sha256=args.install_sha256,
        resource_image_sha256=(
            args.firmware_sha256 if is_rp2 else None
        ),
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
    if args.mode == "baseline" and output is baseline_profile:
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
