#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""[red] v0.6.1 label validation and Pico configuration durability.

The tests use real temporary files and inject failures only at the filesystem
operation named by each case.  They deliberately do not mock a successful
transaction: a passing implementation must write a loadable, independently
verified record and preserve the prior record at every pre-rename failure cut.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


HOST_DIR = os.path.dirname(os.path.abspath(__file__))
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)

import _support  # noqa: E402
import pyble_fs  # noqa: E402
import pyble_proto  # noqa: E402


DC = _support.RedReason("pyble_device_config", owner="v0.6.1-config-engineer")

OK = 0x00
EBADREQ = 0x01
EIO = 0x05
ERANGE = 0x09
VERSION = 1
CONF_NAME = "pyble_conf.json"
CONF_TMP_NAME = ".pyble_conf.json.pbltmp"
CONFIG_FAULT_NONE = 0
CONFIG_FAULT_CORRUPT = 1


def canonical_crc(label, autorun):
    encoded = label.encode("utf-8")
    canonical = b"PBLECFG" + bytes((VERSION, autorun, len(encoded))) + encoded
    return pyble_proto.crc32(canonical) & 0xFFFFFFFF


def record(label="", autorun=0, **updates):
    value = {
        "version": VERSION,
        "label": label,
        "autorun": autorun,
        "crc32": canonical_crc(label, autorun),
    }
    value.update(updates)
    return value


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pyble_v061_config_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.adv = []

    @property
    def module(self):
        return DC.obj(self, "v0.6.1 portable configuration module")

    @property
    def primary(self):
        return os.path.join(self.root, CONF_NAME)

    @property
    def temporary(self):
        return os.path.join(self.root, CONF_TMP_NAME)

    def make(self):
        cls = DC.attr(self, "DeviceConfig", "v0.6.1 durable DeviceConfig")
        return cls(self.root, "9F3A", set_adv_name=self.adv.append)

    def write_json(self, path, value):
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"))

    def read_json(self, path=None):
        with open(path or self.primary, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def assert_fault(self, config, expected):
        self.assertTrue(
            hasattr(config, "config_fault"),
            "v0.6.1 requires a bounded in-RAM DeviceConfig.config_fault marker",
        )
        self.assertEqual(config.config_fault, expected)

    def seed(self, label="old", autorun=1):
        config = self.make()
        self.assertEqual(config.set_label(label.encode("utf-8")), OK)
        self.assertEqual(config.set_autorun(autorun), OK)
        self.adv[:] = []
        return config, Path(self.primary).read_bytes()


class StrictLabelValidationTests(ConfigCase):
    def label_status(self):
        return DC.attr(self, "label_status", "v0.6.1 strict UTF-8 label validator")

    def test_valid_multibyte_label_at_24_byte_limit(self):
        encoded = "€".encode("utf-8") * 8
        self.assertEqual(len(encoded), 24)
        self.assertEqual(self.label_status()(encoded), OK)

    def test_malformed_utf8_is_ebadreq(self):
        malformed = (
            b"\x80",                 # lone continuation
            b"\xc0\x80",            # overlong NUL
            b"\xe0\x80\x80",       # overlong three-byte form
            b"\xed\xa0\x80",       # UTF-16 surrogate U+D800
            b"\xf4\x90\x80\x80",  # above U+10FFFF
            b"\xe2\x82",            # truncated sequence
        )
        for value in malformed:
            with self.subTest(value=value.hex()):
                self.assertEqual(
                    self.label_status()(value),
                    EBADREQ,
                    "malformed UTF-8 must be rejected before persistence",
                )

    def test_c0_c1_and_del_controls_are_ebadreq(self):
        controls = tuple(bytes((value,)) for value in (0, 1, 9, 10, 13, 27, 31, 127))
        controls += ("\u0080".encode("utf-8"), "\u0085".encode("utf-8"),
                     "\u009f".encode("utf-8"))
        for value in controls:
            with self.subTest(value=value.hex()):
                self.assertEqual(
                    self.label_status()(value),
                    EBADREQ,
                    "control scalar must not enter LF-delimited capabilities",
                )

    def test_length_precedes_content_validation(self):
        value = b"x" * 24 + b"\x80"
        self.assertEqual(self.label_status()(value), ERANGE)

    def test_rejected_newline_keeps_ram_file_and_advertisement(self):
        config, before = self.seed()
        self.assertEqual(config.set_label(b"x\nauto_run=1"), EBADREQ)
        self.assertEqual(config.label, "old")
        self.assertEqual(Path(self.primary).read_bytes(), before)
        self.assertEqual(self.adv, [])


class PortableStrictUtf8BoundaryTests(ConfigCase):
    """Pin a decoder-independent strict-scalar UTF-8 authority on RP2."""

    def strict_decode(self):
        helper = getattr(pyble_proto, "strict_utf8_decode", None)
        self.assertIsNotNone(
            helper,
            "portable wire text must use one explicit strict UTF-8 decoder; "
            "the pinned MicroPython bytes.decode accepts invalid scalars",
        )
        return helper

    def test_shared_decoder_accepts_only_shortest_form_unicode_scalars(self):
        valid = (
            (b"ASCII", "ASCII"),
            (b"\xc2\x80", "\u0080"),
            (b"\xe2\x82\xac", "\u20ac"),
            (b"\xf4\x8f\xbf\xbf", "\U0010ffff"),
        )
        invalid = (
            b"\x80", b"\xc0\x80", b"\xc1\xbf", b"\xe0\x80\x80",
            b"\xed\xa0\x80", b"\xf0\x80\x80\x80",
            b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
            b"\xe2\x82", b"\xf0\x9f\x92", b"\xe2(\xa1",
        )
        decode = self.strict_decode()
        for encoded, expected in valid:
            with self.subTest(valid=encoded.hex()):
                self.assertEqual(decode(encoded), expected)
        for encoded in invalid:
            with self.subTest(invalid=encoded.hex()):
                self.assertIsNone(decode(encoded))

    def test_path_and_label_share_the_explicit_decoder(self):
        with mock.patch.object(
            pyble_proto,
            "strict_utf8_decode",
            return_value=None,
            create=True,
        ) as strict:
            self.assertEqual(
                DC.attr(self, "label_status", "strict label UTF-8")(b"safe"),
                EBADREQ,
            )
            self.assertEqual(pyble_fs.resolve(b"/safe"), (EBADREQ, None))
        self.assertEqual(
            strict.call_count,
            2,
            "both portable wire-text chokepoints must delegate to the one "
            "decoder-independent scalar validator",
        )


class VersionedRecordTests(ConfigCase):
    def test_v1_constants_and_exact_record_are_persisted(self):
        self.assertEqual(
            DC.attr(self, "CONFIG_VERSION", "v0.6.1 config schema version"), VERSION)
        self.assertEqual(
            DC.attr(self, "CONF_TMP_NAME", "v0.6.1 reserved config temp"),
            CONF_TMP_NAME,
        )
        config = self.make()
        self.assertEqual(config.set_label("€".encode("utf-8")), OK)
        self.assertEqual(config.set_autorun(1), OK)
        persisted = self.read_json()
        self.assertEqual(
            set(persisted), {"version", "label", "autorun", "crc32"},
            "v1 has one unambiguous, integrity-covered schema",
        )
        self.assertEqual(persisted["version"], VERSION)
        self.assertEqual(persisted["label"], "€")
        self.assertEqual(persisted["autorun"], 1)
        self.assertIs(type(persisted["crc32"]), int)
        self.assertEqual(persisted["crc32"], canonical_crc("€", 1))

    def test_missing_primary_is_clean_first_boot(self):
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_NONE)

    def test_crc_mismatch_fails_closed_without_rewriting_evidence(self):
        corrupt = record("unsafe", 1)
        corrupt["crc32"] ^= 1
        self.write_json(self.primary, corrupt)
        before = Path(self.primary).read_bytes()
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assertEqual(Path(self.primary).read_bytes(), before)

    def test_unknown_version_wrong_types_extra_keys_and_controls_fail_closed(self):
        cases = (
            record("unsafe", 1, version=2),
            {"version": 1, "label": 7, "autorun": 1, "crc32": 0},
            record("unsafe", 1, extension=True),
            record("line\nbreak", 1),
        )
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                self.write_json(self.primary, value)
                config = self.make()
                self.assertEqual((config.label, config.auto_run), ("", 0))
                self.assert_fault(config, CONFIG_FAULT_CORRUPT)

    def test_v1_autorun_requires_an_exact_integer_zero_or_one(self):
        for value in (-1, 2, True, False, 1.0, "1", None):
            with self.subTest(value=repr(value)):
                invalid = {
                    "version": 1,
                    "label": "unsafe",
                    "autorun": value,
                    "crc32": 0,
                }
                self.write_json(self.primary, invalid)
                config = self.make()
                self.assertEqual((config.label, config.auto_run), ("", 0))
                self.assert_fault(config, CONFIG_FAULT_CORRUPT)

    def test_oversize_record_is_rejected_before_unbounded_json_loading(self):
        with open(self.primary, "wb") as stream:
            stream.write(b" " * 257 + b"{}")
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)

    def test_bounded_decoder_failure_selects_defaults_and_fault_marker(self):
        self.write_json(self.primary, record("would-run", 1))
        cls = DC.attr(self, "DeviceConfig", "v0.6.1 guarded record decoder")

        with mock.patch.object(
                cls, "_decode_record",
                side_effect=MemoryError("injected bounded decode failure")):
            config = cls(self.root, "9F3A", set_adv_name=self.adv.append)

        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)

    def test_legacy_record_loads_and_migrates_only_on_next_successful_set(self):
        legacy = {"label": "legacy", "autorun": 1}
        self.write_json(self.primary, legacy)
        before = Path(self.primary).read_bytes()
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("legacy", 1))
        self.assert_fault(config, CONFIG_FAULT_NONE)
        self.assertEqual(Path(self.primary).read_bytes(), before,
                         "boot must not perform a migration write")
        self.assertEqual(config.set_autorun(0), OK)
        migrated = self.read_json()
        self.assertEqual(set(migrated), {"version", "label", "autorun", "crc32"})
        self.assertEqual(migrated["crc32"], canonical_crc("legacy", 0))

    def test_legacy_record_requires_exactly_two_valid_keys(self):
        invalid_legacy = (
            {"label": "legacy", "autorun": 1, "extra": 0},
            {"label": "legacy"},
            {"autorun": 1},
            {"label": 7, "autorun": 1},
            {"label": "line\nbreak", "autorun": 1},
            {"label": "legacy", "autorun": -1},
            {"label": "legacy", "autorun": 2},
            {"label": "legacy", "autorun": True},
            {"label": "legacy", "autorun": False},
            {"label": "legacy", "autorun": 1.0},
            {"label": "legacy", "autorun": "1"},
            {"label": "legacy", "autorun": None},
        )
        for index, value in enumerate(invalid_legacy):
            with self.subTest(index=index, value=value):
                self.write_json(self.primary, value)
                config = self.make()
                self.assertEqual((config.label, config.auto_run), ("", 0))
                self.assert_fault(config, CONFIG_FAULT_CORRUPT)

    def test_orphan_temp_is_never_promoted(self):
        self.write_json(self.temporary, record("uncommitted", 1))
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_NONE)
        self.assertFalse(os.path.exists(self.primary))

    def test_valid_primary_wins_over_an_orphan_temp(self):
        self.write_json(self.primary, record("committed", 0))
        self.write_json(self.temporary, record("uncommitted", 1))
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("committed", 0))
        self.assertFalse(
            os.path.exists(self.temporary),
            "a valid primary triggers best-effort stale-temp cleanup",
        )
        self.assert_fault(config, CONFIG_FAULT_NONE)

    def test_stale_temp_cleanup_failure_does_not_hide_a_valid_primary(self):
        self.write_json(self.primary, record("committed", 1))
        self.write_json(self.temporary, record("stale", 0))
        with mock.patch.object(
                os, "remove", side_effect=OSError("synthetic stale-temp cleanup")) \
                as remove:
            config = self.make()
        remove.assert_called_once_with(self.temporary)
        self.assertEqual((config.label, config.auto_run), ("committed", 1))
        self.assert_fault(config, CONFIG_FAULT_NONE)
        self.assertTrue(os.path.exists(self.temporary),
                        "best-effort cleanup failure may leave the stale temp")

    def test_corrupt_primary_never_promotes_a_valid_temp(self):
        corrupt = record("corrupt-primary", 1)
        corrupt["crc32"] ^= 1
        self.write_json(self.primary, corrupt)
        self.write_json(self.temporary, record("tempting-temp", 1))
        primary_before = Path(self.primary).read_bytes()
        temp_before = Path(self.temporary).read_bytes()
        config = self.make()
        self.assertEqual((config.label, config.auto_run), ("", 0))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assertEqual(
            Path(self.primary).read_bytes(), primary_before,
            "boot must preserve corrupt-primary evidence instead of promoting temp",
        )
        self.assertNotEqual(Path(self.primary).read_bytes(), temp_before)


class AtomicFailureTests(ConfigCase):
    class _DelegatingFile:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return self._wrapped.__exit__(exc_type, exc, traceback)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    class _FlushFailure:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self._wrapped.close()
            return False

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def write(self, value):
            return self._wrapped.write(value)

        def flush(self):
            raise OSError("synthetic config flush failure")

    class _ShortWrite(_DelegatingFile):
        def write(self, value):
            count = max(0, len(value) - 1)
            self._wrapped.write(value[:count])
            return count

    class _CloseFailure(_DelegatingFile):
        def close(self):
            if self._wrapped.closed:
                return None
            self._wrapped.close()
            raise OSError("synthetic config close failure")

        def __exit__(self, exc_type, exc, traceback):
            if not self._wrapped.closed:
                self.close()
            return False

    def assert_old_survives(self, before):
        self.assertEqual(Path(self.primary).read_bytes(), before)
        loaded = self.make()
        self.assertEqual((loaded.label, loaded.auto_run), ("old", 1))

    def test_temp_flush_failure_returns_eio_and_keeps_old_commit(self):
        config, before = self.seed()
        real_open = open

        def failing_open(path, mode="r", *args, **kwargs):
            opened = real_open(path, mode, *args, **kwargs)
            if os.fspath(path) == self.temporary and "w" in mode:
                return self._FlushFailure(opened)
            return opened

        with mock.patch("builtins.open", side_effect=failing_open):
            status = config.set_label(b"new")
        self.assertEqual(status, EIO)
        self.assertEqual((config.label, config.auto_run), ("old", 1))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assertEqual(self.adv, [])
        self.assert_old_survives(before)

    def test_short_temp_write_returns_eio_and_keeps_old_commit(self):
        config, before = self.seed()
        real_open = open

        def short_open(path, mode="r", *args, **kwargs):
            opened = real_open(path, mode, *args, **kwargs)
            if os.fspath(path) == self.temporary and "w" in mode:
                return self._ShortWrite(opened)
            return opened

        with mock.patch("builtins.open", side_effect=short_open):
            status = config.set_label(b"new")
        self.assertEqual(status, EIO)
        self.assertEqual((config.label, config.auto_run), ("old", 1))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assertEqual(self.adv, [])
        self.assert_old_survives(before)

    def test_temp_close_failure_returns_eio_and_keeps_old_commit(self):
        config, before = self.seed()
        real_open = open

        def close_failing_open(path, mode="r", *args, **kwargs):
            opened = real_open(path, mode, *args, **kwargs)
            if os.fspath(path) == self.temporary and "w" in mode:
                return self._CloseFailure(opened)
            return opened

        with mock.patch("builtins.open", side_effect=close_failing_open):
            status = config.set_autorun(0)
        self.assertEqual(status, EIO)
        self.assertEqual((config.label, config.auto_run), ("old", 1))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assert_old_survives(before)

    def test_sync_failure_returns_eio_and_keeps_old_commit(self):
        config, before = self.seed()
        with mock.patch.object(
                os, "sync", side_effect=OSError("synthetic config sync failure"),
                create=True):
            status = config.set_autorun(0)
        self.assertEqual(status, EIO)
        self.assertEqual((config.label, config.auto_run), ("old", 1))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assert_old_survives(before)

    def test_rename_failure_returns_eio_and_keeps_old_commit(self):
        config, before = self.seed()
        with mock.patch.object(
                os, "rename", side_effect=OSError("synthetic config rename failure")):
            status = config.set_label(b"new")
        self.assertEqual(status, EIO)
        self.assertEqual((config.label, config.auto_run), ("old", 1))
        self.assert_fault(config, CONFIG_FAULT_CORRUPT)
        self.assertEqual(self.adv, [])
        self.assert_old_survives(before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
