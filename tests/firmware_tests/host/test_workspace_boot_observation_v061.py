#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Measured first-boot workspace observations; synthetic host cases, not HIL.

Each test imports a fresh module instance to represent one MicroPython VM.
Counters must observe real constructor/mkfs/remount and block-device calls,
including attempted writes that fail or leave storage bytes unchanged.
"""

import ast
import errno
import importlib.util
from pathlib import Path
import types
import unittest
import sys
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "firmware/pyble/pyble_workspace.py"
CHALLENGE = "0123456789abcdef0123456789abcdef"
SECOND_CHALLENGE = "fedcba9876543210fedcba9876543210"
COUNTERS = (
    "mount_attempts", "format_attempts", "format_completions",
    "remount_attempts", "remount_completions", "program_calls", "erase_calls",
    "recovery_attempts", "recovery_emissions",
)
FLAGS = ("workspace_attached", "complete", "fault", "overflow")
FIELDS = {"schema_version", "boot_id", "challenge", "media_state", *COUNTERS, *FLAGS}
RECOVERY = "PyBLE workspace recovery is required; reconnect by USB."


def fresh_workspace():
    spec = importlib.util.spec_from_file_location("_pyble_workspace_observer_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Media:
    """Idempotent fake writes expose why a checksum cannot prove zero calls."""

    def __init__(self, *, blank=True, geometry_error=None, read_error=None):
        self.contents = bytearray(b"\xff" * 8192)
        if not blank:
            self.contents[-1] = 0x7F
        self.geometry_error = geometry_error
        self.read_error = read_error
        self.program_error = None
        self.erase_error = None
        self.read_calls = []
        self.ioctl_calls = []
        self.program_calls = 0
        self.erase_calls = 0
        self.last_program_arguments = None
        self.before_program = None
        self.before_erase = None

    def readblocks(self, block, destination, *offset):
        self.read_calls.append((block, destination, offset))
        if self.read_error is not None:
            raise self.read_error
        start = block * 4096 + (offset[0] if offset else 0)
        destination[:] = self.contents[start:start + len(destination)]
        return 0

    def writeblocks(self, block, source, *offset):
        self.program_calls += 1
        self.last_program_arguments = (block, source, offset)
        if self.before_program:
            self.before_program()
        if self.program_error is not None:
            raise self.program_error
        # Deliberately do not mutate the bytes: this is still a write attempt.
        return 0

    def ioctl(self, command, argument):
        self.ioctl_calls.append((command, argument))
        if command in (4, 5):
            if self.geometry_error is not None:
                raise self.geometry_error
            return 2 if command == 4 else 4096
        if command == 6:
            self.erase_calls += 1
            if self.before_erase:
                self.before_erase()
            if self.erase_error is not None:
                raise self.erase_error
        return 0


def vfs_fixture(effects, *, format_action=None):
    state = types.SimpleNamespace(effects=list(effects), constructions=[], formats=[])

    class VfsLfs2:
        def __new__(cls, bdev, *, progsize):
            state.constructions.append((bdev, progsize))
            if not state.effects:
                raise AssertionError("Unexpected extra constructor")
            effect = state.effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            if callable(effect):
                return effect(bdev)
            return types.SimpleNamespace(bdev=bdev) if effect is None else effect

        @staticmethod
        def mkfs(bdev, *, progsize):
            state.formats.append((bdev, progsize))
            if format_action is not None:
                return format_action(bdev)

    return types.SimpleNamespace(VfsLfs2=VfsLfs2), state


class WorkspaceBootObservationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = fresh_workspace()

    def api(self, name):
        function = getattr(self.workspace, name, None)
        self.assertTrue(
            callable(function),
            "[red] measured first-boot observation API {} is missing".format(name))
        return function

    def observe(self, bdev, vfs):
        self.api("read_boot_observation")
        return self.workspace.mount_lfs2(bdev, vfs, progsize=256, observe_boot=True)

    def snapshot(self, challenge=CHALLENGE):
        value = self.api("read_boot_observation")(challenge)
        self.assertIs(type(value), dict)
        self.assertEqual(set(value), FIELDS)
        self.assertIs(type(value["schema_version"]), int)
        self.assertEqual(value["schema_version"], 1)
        self.assertIs(type(value["boot_id"]), str)
        self.assertRegex(value["boot_id"], r"\A[0-9a-f]{32}\Z")
        self.assertEqual(value["challenge"], challenge)
        for name in COUNTERS:
            self.assertIs(type(value[name]), int, name)
            self.assertGreaterEqual(value[name], 0, name)
            self.assertLessEqual(value[name], 65535, name)
        for name in FLAGS:
            self.assertIs(type(value[name]), bool, name)
        self.assertIn(value["media_state"], ("uninspected", "erased", "nonblank", "uncertain"))
        return value

    def assert_counts(self, value, **expected):
        for name in COUNTERS:
            self.assertEqual(value[name], expected.get(name, 0), name)

    def healthy(self):
        media = Media(blank=False)
        vfs, state = vfs_fixture([None])
        mounted = self.observe(media, vfs)
        return media, vfs, state, mounted

    def recover(self):
        with mock.patch("builtins.print") as output:
            self.api("boot_recovery")()
        output.assert_called_once_with(RECOVERY)
        return self.snapshot()

    def test_unobserved_mount_keeps_original_device_and_no_diagnostic_side_effect(self):
        media = Media(blank=False)
        vfs, state = vfs_fixture([None])
        mounted = self.workspace.mount_lfs2(media, vfs, progsize=256)
        self.assertIs(mounted.bdev, media)
        self.assertEqual(state.constructions, [(media, 256)])
        self.assertEqual(media.read_calls, [])
        self.assertEqual(media.ioctl_calls, [])
        if callable(getattr(self.workspace, "read_boot_observation", None)):
            with self.assertRaises(Exception):
                self.workspace.read_boot_observation(CHALLENGE)

    def test_no_boot_record_is_not_reported_as_zero(self):
        getter = self.api("read_boot_observation")
        with self.assertRaises(Exception):
            getter(CHALLENGE)

    def test_initial_constructor_attempt_is_visible_before_the_call(self):
        seen = []
        def construct(bdev):
            seen.append(self.snapshot())
            return types.SimpleNamespace(bdev=bdev)
        vfs, _state = vfs_fixture([construct])
        self.observe(Media(), vfs)
        self.assert_counts(seen[0], mount_attempts=1)
        self.assertFalse(seen[0]["complete"])
        self.assertFalse(seen[0]["workspace_attached"])

    def test_healthy_constructor_does_not_claim_attachment_or_inspect_media(self):
        media, _vfs, state, _mounted = self.healthy()
        value = self.snapshot()
        self.assert_counts(value, mount_attempts=1)
        self.assertEqual(value["media_state"], "uninspected")
        self.assertFalse(value["workspace_attached"])
        self.assertFalse(value["complete"])
        self.assertFalse(value["fault"])
        self.assertEqual(len(state.constructions), 1)
        self.assertEqual(media.ioctl_calls, [])
        self.assertEqual(media.read_calls, [])

    def test_only_actual_attachment_seals_healthy_boot(self):
        self.healthy()
        self.api("boot_attached")()
        value = self.snapshot()
        self.assert_counts(value, mount_attempts=1)
        self.assertTrue(value["workspace_attached"])
        self.assertTrue(value["complete"])
        self.assertFalse(value["fault"])
        self.assertFalse(value["overflow"])

    def test_erased_scan_records_real_format_and_remount_attempts_and_completions(self):
        samples = []
        def format_action(bdev):
            samples.append(self.snapshot())
            bdev.ioctl(6, 0)
            bdev.writeblocks(0, b"\xff" * 256, 0)
        def remount(bdev):
            samples.append(self.snapshot())
            return types.SimpleNamespace(bdev=bdev)
        media = Media()
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank"), remount], format_action=format_action)
        self.observe(media, vfs)
        self.api("boot_attached")()
        value = self.snapshot()
        self.assert_counts(samples[0], mount_attempts=1, format_attempts=1)
        self.assert_counts(samples[1], mount_attempts=1, format_attempts=1,
                           format_completions=1, remount_attempts=1, program_calls=1, erase_calls=1)
        self.assert_counts(value, mount_attempts=1, format_attempts=1,
                           format_completions=1, remount_attempts=1, remount_completions=1,
                           program_calls=1, erase_calls=1)
        self.assertEqual(value["media_state"], "erased")
        self.assertTrue(value["workspace_attached"])
        self.assertTrue(value["complete"])
        self.assertFalse(value["fault"])
        self.assertEqual(len(state.constructions), 2)
        self.assertEqual(len(state.formats), 1)
        self.assertEqual([item[0] for item in media.read_calls], [0, 1])

    def test_nonblank_refusal_is_measured_without_guessing_zero_writes(self):
        media = Media(blank=False)
        before = bytes(media.contents)
        failure = OSError(errno.EIO, "incompatible")
        vfs, state = vfs_fixture([failure])
        with self.assertRaises(OSError) as raised:
            self.observe(media, vfs)
        self.assertIs(raised.exception, failure)
        value = self.recover()
        self.assert_counts(value, mount_attempts=1, recovery_attempts=1, recovery_emissions=1)
        self.assertEqual(value["media_state"], "nonblank")
        self.assertFalse(value["workspace_attached"])
        self.assertTrue(value["complete"])
        self.assertFalse(value["fault"])
        self.assertEqual(bytes(media.contents), before)
        self.assertEqual(state.formats, [])

    def test_idempotent_program_attempt_cannot_be_reported_as_zero(self):
        media = Media(blank=False)
        before = bytes(media.contents)
        def constructor(bdev):
            bdev.writeblocks(0, b"\xff" * 256)
            raise OSError(errno.EIO, "incompatible after write attempt")
        vfs, state = vfs_fixture([constructor])
        with self.assertRaises(OSError):
            self.observe(media, vfs)
        value = self.recover()
        self.assertEqual(value["program_calls"], 1)
        self.assertEqual(media.program_calls, 1)
        self.assertEqual(bytes(media.contents), before)
        self.assertEqual(state.formats, [])

    def test_failed_program_attempt_is_counted_before_backend_dispatch(self):
        media = Media(blank=False)
        failure = OSError(errno.EIO, "program failed")
        media.program_error = failure
        seen = []
        media.before_program = lambda: seen.append(self.snapshot()["program_calls"])
        def constructor(bdev):
            bdev.writeblocks(1, b"x", 256)
        vfs, state = vfs_fixture([constructor])
        with self.assertRaises(OSError) as raised:
            self.observe(media, vfs)
        self.assertIs(raised.exception, failure)
        value = self.recover()
        self.assertEqual(seen, [1])
        self.assertEqual(value["program_calls"], 1)
        self.assertEqual(state.formats, [])

    def test_failed_erase_attempt_is_counted_before_backend_dispatch(self):
        media = Media(blank=False)
        failure = OSError(errno.EIO, "erase failed")
        media.erase_error = failure
        seen = []
        media.before_erase = lambda: seen.append(self.snapshot()["erase_calls"])
        def constructor(bdev):
            bdev.ioctl(6, 1)
        vfs, state = vfs_fixture([constructor])
        with self.assertRaises(OSError) as raised:
            self.observe(media, vfs)
        self.assertIs(raised.exception, failure)
        value = self.recover()
        self.assertEqual(seen, [1])
        self.assertEqual(value["erase_calls"], 1)
        self.assertEqual(state.formats, [])

    def test_program_buffer_identity_and_optional_offset_are_forwarded(self):
        media, _vfs, _state, mounted = self.healthy()
        payload = bytearray(b"sample")
        self.assertEqual(mounted.bdev.writeblocks(1, payload), 0)
        self.assertIs(media.last_program_arguments[1], payload)
        self.assertEqual(media.last_program_arguments[2], ())
        self.assertEqual(mounted.bdev.writeblocks(1, payload, 256), 0)
        self.assertIs(media.last_program_arguments[1], payload)
        self.assertEqual(media.last_program_arguments[2], (256,))
        self.assertEqual(self.snapshot()["program_calls"], 2)

    def test_readblocks_forwards_original_bound_method_without_observer_copy(self):
        media, _vfs, _state, mounted = self.healthy()
        self.assertEqual(mounted.bdev.readblocks, media.readblocks)
        target = bytearray(8)
        self.assertEqual(mounted.bdev.readblocks(1, target, 100), 0)
        self.assertIs(media.read_calls[-1][1], target)
        self.assertEqual(media.read_calls[-1][2], (100,))
        self.assertEqual(self.snapshot()["program_calls"], 0)
        self.assertEqual(self.snapshot()["erase_calls"], 0)

    def test_nonmutating_ioctl_commands_do_not_increment_erase_count(self):
        media, _vfs, _state, mounted = self.healthy()
        for command in (1, 2, 3, 4, 5):
            mounted.bdev.ioctl(command, 0)
        self.assertEqual(self.snapshot()["erase_calls"], 0)
        self.assertEqual(media.erase_calls, 0)
        mounted.bdev.ioctl(6, 1)
        self.assertEqual(self.snapshot()["erase_calls"], 1)
        self.assertEqual(media.erase_calls, 1)

    def test_format_failure_has_attempt_without_completion_or_remount(self):
        failure = OSError(errno.EIO, "format failed")
        def failed_format(_bdev):
            raise failure
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank")], format_action=failed_format)
        with self.assertRaises(OSError) as raised:
            self.observe(Media(), vfs)
        self.assertIs(raised.exception, failure)
        value = self.recover()
        self.assert_counts(value, mount_attempts=1, format_attempts=1,
                           recovery_attempts=1, recovery_emissions=1)
        self.assertTrue(value["fault"])
        self.assertEqual(len(state.constructions), 1)
        self.assertEqual(len(state.formats), 1)

    def test_remount_failure_has_attempt_without_completion_or_second_format(self):
        failure = OSError(errno.EIO, "remount failed")
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank"), failure])
        with self.assertRaises(OSError) as raised:
            self.observe(Media(), vfs)
        self.assertIs(raised.exception, failure)
        value = self.recover()
        self.assert_counts(value, mount_attempts=1, format_attempts=1, format_completions=1,
                           remount_attempts=1, recovery_attempts=1, recovery_emissions=1)
        self.assertTrue(value["fault"])
        self.assertEqual(len(state.constructions), 2)
        self.assertEqual(len(state.formats), 1)

    def test_geometry_fault_remains_uncertain_and_never_formats(self):
        media = Media(geometry_error=OSError(errno.EIO, "geometry failed"))
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank")])
        with self.assertRaises(OSError):
            self.observe(media, vfs)
        value = self.recover()
        self.assertEqual(value["media_state"], "uncertain")
        self.assertTrue(value["fault"])
        self.assertEqual(value["format_attempts"], 0)
        self.assertEqual(state.formats, [])

    def test_read_fault_remains_uncertain_and_never_formats(self):
        media = Media(read_error=OSError(errno.EIO, "read failed"))
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank")])
        with self.assertRaises(OSError):
            self.observe(media, vfs)
        value = self.recover()
        self.assertEqual(value["media_state"], "uncertain")
        self.assertTrue(value["fault"])
        self.assertEqual(value["format_attempts"], 0)
        self.assertEqual(state.formats, [])

    def test_unexpected_constructor_fault_is_not_erased_media_authority(self):
        for failure in (MemoryError("constructor allocation"), RuntimeError("constructor bug")):
            with self.subTest(error=type(failure).__name__):
                self.workspace = fresh_workspace()
                media = Media()
                vfs, state = vfs_fixture([failure])
                with self.assertRaises(type(failure)) as raised:
                    self.observe(media, vfs)
                self.assertIs(raised.exception, failure)
                value = self.recover()
                self.assertTrue(value["fault"])
                self.assertEqual(value["format_attempts"], 0)
                self.assertEqual(state.formats, [])
                self.assertEqual(media.read_calls, [])

    def test_snapshot_is_detached_and_challenge_echo_does_not_mutate_record(self):
        self.healthy()
        self.api("boot_attached")()
        first = self.snapshot()
        expected = dict(first)
        first.update(mount_attempts=99, program_calls=0, complete=False, boot_id="0" * 32)
        again = self.snapshot()
        self.assertEqual(again, expected)
        other = self.snapshot(SECOND_CHALLENGE)
        expected["challenge"] = SECOND_CHALLENGE
        self.assertEqual(other, expected)

    def test_challenge_must_be_exact_lowercase_128_bit_hex(self):
        self.healthy()
        self.api("boot_attached")()
        before = self.snapshot()
        getter = self.api("read_boot_observation")
        for invalid in (None, True, 1, b"a" * 32, "", "a" * 31, "a" * 33,
                        "A" * 32, "g" * 32, "a" * 31 + "\n"):
            with self.subTest(value=repr(invalid)), self.assertRaises((TypeError, ValueError)):
                getter(invalid)
        self.assertEqual(self.snapshot(), before)

    def test_sealed_record_does_not_count_later_user_storage_operations(self):
        media, _vfs, _state, mounted = self.healthy()
        self.api("boot_attached")()
        before = self.snapshot()
        mounted.bdev.writeblocks(0, b"user file", 0)
        mounted.bdev.ioctl(6, 0)
        self.assertEqual(media.program_calls, 1)
        self.assertEqual(media.erase_calls, 1)
        self.assertEqual(self.snapshot(), before)

    def test_second_observed_mount_cannot_replace_first_vm_record(self):
        self.healthy()
        self.api("boot_attached")()
        before = self.snapshot()
        vfs, state = vfs_fixture([None])
        with self.assertRaises(Exception):
            self.observe(Media(), vfs)
        self.assertEqual(state.constructions, [])
        self.assertEqual(self.snapshot(), before)

    def test_unobserved_later_mount_cannot_replace_first_vm_record(self):
        self.healthy()
        self.api("boot_attached")()
        before = self.snapshot()
        media = Media()
        vfs, state = vfs_fixture([None])
        mounted = self.workspace.mount_lfs2(media, vfs, progsize=256)
        self.assertIs(mounted.bdev, media)
        self.assertEqual(state.constructions, [(media, 256)])
        self.assertEqual(self.snapshot(), before)

    def test_repeated_attachment_or_recovery_cannot_change_sealed_record(self):
        self.healthy()
        self.api("boot_attached")()
        before = self.snapshot()
        for name in ("boot_attached", "boot_recovery"):
            with self.subTest(api=name), mock.patch("builtins.print") as output:
                with self.assertRaises(Exception):
                    self.api(name)()
                output.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_recovery_emission_is_counted_only_after_print_returns(self):
        media = Media(blank=False)
        vfs, _state = vfs_fixture([OSError(errno.EIO, "incompatible")])
        with self.assertRaises(OSError):
            self.observe(media, vfs)
        seen = []
        def output(message):
            self.assertEqual(message, RECOVERY)
            seen.append(self.snapshot())
        with mock.patch("builtins.print", side_effect=output):
            self.api("boot_recovery")()
        self.assertEqual(seen[0]["recovery_attempts"], 1)
        self.assertEqual(seen[0]["recovery_emissions"], 0)
        self.assertFalse(seen[0]["complete"])
        self.assertEqual(self.snapshot()["recovery_emissions"], 1)

    def test_recovery_print_failure_never_claims_successful_emission(self):
        media = Media(blank=False)
        vfs, _state = vfs_fixture([OSError(errno.EIO, "incompatible")])
        with self.assertRaises(OSError):
            self.observe(media, vfs)
        with mock.patch("builtins.print", side_effect=OSError(errno.EIO, "console failed")):
            with self.assertRaises(OSError):
                self.api("boot_recovery")()
        value = self.snapshot()
        self.assertEqual(value["recovery_attempts"], 1)
        self.assertEqual(value["recovery_emissions"], 0)
        self.assertTrue(value["fault"])

    def test_attachment_failure_is_faulted_recovery_not_successful_mount(self):
        self.healthy()
        # The overlay calls recovery when the real vfs.mount raises, never
        # boot_attached. A successful constructor is not attachment evidence.
        value = self.recover()
        self.assertFalse(value["workspace_attached"])
        self.assertTrue(value["fault"])
        self.assert_counts(value, mount_attempts=1, recovery_attempts=1, recovery_emissions=1)

    def test_boot_ids_are_new_for_distinct_module_vm_instances(self):
        identities = []
        for _index in range(3):
            self.workspace = fresh_workspace()
            self.healthy()
            self.api("boot_attached")()
            identities.append(self.snapshot()["boot_id"])
        self.assertEqual(len(set(identities)), 3)

    def test_random_identity_failure_permits_no_constructor_or_format(self):
        self.api("read_boot_observation")
        media = Media()
        vfs, state = vfs_fixture([OSError(errno.EIO, "blank"), None])
        with mock.patch("os.urandom", side_effect=OSError(errno.EIO, "entropy failed")):
            with self.assertRaises(Exception):
                self.observe(media, vfs)
        self.assertEqual(state.constructions, [])
        self.assertEqual(state.formats, [])
        self.assertEqual(media.program_calls, 0)
        self.assertEqual(media.erase_calls, 0)
        try:
            value = self.workspace.read_boot_observation(CHALLENGE)
        except Exception:
            return
        self.assertTrue(value["fault"])
        self.assertFalse(value["complete"])

    def test_missing_or_wrong_sized_entropy_does_not_create_a_valid_record(self):
        self.api("read_boot_observation")
        for entropy in (None, b"", b"a" * 15, b"a" * 17, "a" * 16):
            with self.subTest(entropy=repr(entropy)):
                self.workspace = fresh_workspace()
                media = Media()
                vfs, state = vfs_fixture([None])
                with mock.patch("os.urandom", return_value=entropy):
                    with self.assertRaises(Exception):
                        self.observe(media, vfs)
                self.assertEqual(state.constructions, [])
                self.assertEqual(state.formats, [])

    def test_entropy_failure_still_emits_one_fixed_recovery_line_without_record(self):
        self.api("read_boot_observation")
        vfs, _state = vfs_fixture([None])
        with mock.patch("os.urandom", side_effect=MemoryError("identity allocation")):
            with self.assertRaises(Exception):
                self.observe(Media(), vfs)
        with mock.patch("builtins.print") as output:
            self.api("boot_recovery")()
        output.assert_called_once_with(RECOVERY)
        with self.assertRaises(Exception):
            self.workspace.read_boot_observation(CHALLENGE)
        with mock.patch("builtins.print") as output:
            with self.assertRaises(Exception):
                self.workspace.boot_recovery()
        output.assert_not_called()

    def test_counter_overflow_inside_initial_constructor_cannot_authorize_format(self):
        media = Media()
        def constructor(bdev):
            for _index in range(65536):
                try:
                    bdev.writeblocks(0, b"", 0)
                except (RuntimeError, OverflowError):
                    break
            raise OSError(errno.EIO, "mount failed after counter overflow")
        vfs, state = vfs_fixture([constructor, None])
        with self.assertRaises(Exception):
            self.observe(media, vfs)
        value = self.snapshot()
        self.assertTrue(value["overflow"])
        self.assertTrue(value["fault"])
        self.assertEqual(value["format_attempts"], 0)
        self.assertEqual(state.formats, [])
        self.assertEqual(len(state.constructions), 1)

    def test_program_counter_saturates_and_marks_unusable_observation(self):
        _media, _vfs, _state, mounted = self.healthy()
        for _index in range(65536):
            try:
                mounted.bdev.writeblocks(0, b"", 0)
            except (RuntimeError, OverflowError):
                break
        value = self.snapshot()
        self.assertEqual(value["program_calls"], 65535)
        self.assertTrue(value["overflow"])
        self.assertTrue(value["fault"])

    def test_erase_counter_saturates_and_marks_unusable_observation(self):
        _media, _vfs, _state, mounted = self.healthy()
        for _index in range(65536):
            try:
                mounted.bdev.ioctl(6, 0)
            except (RuntimeError, OverflowError):
                break
        value = self.snapshot()
        self.assertEqual(value["erase_calls"], 65535)
        self.assertTrue(value["overflow"])
        self.assertTrue(value["fault"])


class WorkspaceBootOverlayObservationTests(unittest.TestCase):
    PROFILES = ("esp32", "esp32-s3", "esp32-c3", "waveshare-esp32-s3-lcd-147b", "rpi-pico2-w")

    def load(self, profile):
        path = ROOT / "firmware/board_overlays" / profile / "_boot.py"
        return path, ast.parse(path.read_bytes(), filename=str(path))

    @staticmethod
    def called(node):
        return node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")

    def test_all_five_profiles_explicitly_enable_observed_mount(self):
        for profile in self.PROFILES:
            with self.subTest(profile=profile):
                _path, tree = self.load(profile)
                calls = [node for node in ast.walk(tree)
                         if isinstance(node, ast.Call) and self.called(node) == "mount_lfs2"]
                self.assertEqual(len(calls), 1)
                observed = [item.value for item in calls[0].keywords if item.arg == "observe_boot"]
                self.assertEqual(len(observed), 1, "[red] official overlay must opt into measured boot")
                self.assertIsInstance(observed[0], ast.Constant)
                self.assertIs(observed[0].value, True)

    def test_all_five_profiles_attach_and_recover_through_observer(self):
        for profile in self.PROFILES:
            with self.subTest(profile=profile):
                _path, tree = self.load(profile)
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
                for name in ("boot_attached", "boot_recovery"):
                    self.assertEqual(sum(self.called(node) == name for node in calls), 1,
                                     "[red] official overlay must call {} once".format(name))

    def execute_mount_prefix(self, profile, *, failure=None):
        path, tree = self.load(profile)
        nodes = []
        for node in tree.body:
            nodes.append(node)
            if isinstance(node, ast.Try) and any(
                    isinstance(child, ast.Call) and self.called(child) == "mount_lfs2"
                    for child in ast.walk(node)):
                break
        else:
            self.fail("Overlay lacks its guarded workspace mount block")
        events = []
        media, filesystem = object(), object()
        def mount(bdev, _vfs, *, progsize, observe_boot=False):
            self.assertIs(bdev, media)
            self.assertEqual(progsize, 256)
            self.assertIs(observe_boot, True, "[red] overlay omitted observed boot")
            events.append("construct")
            if failure == "constructor":
                raise OSError(errno.EIO, "nonblank incompatible")
            return filesystem
        def attach(fs, target):
            self.assertIs(fs, filesystem)
            self.assertEqual(target, "/")
            events.append("attach")
            if failure == "attachment":
                raise OSError(errno.EIO, "attachment failed")
        def sealed():
            events.append("seal")
            if failure == "seal":
                raise MemoryError("observation seal failed")
        def recovery():
            events.append("recovery")
        workspace = types.SimpleNamespace(mount_lfs2=mount, boot_attached=sealed, boot_recovery=recovery)
        modules = {
            "vfs": types.SimpleNamespace(mount=attach),
            "flashbdev": types.SimpleNamespace(bdev=media),
            "rp2": types.SimpleNamespace(Flash=lambda: media),
            "pyble_boot": workspace,
            "pyble_workspace": workspace,
        }
        namespace = {"__name__": "_overlay_boot_observation_test"}
        code = compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec")
        with mock.patch.dict(sys.modules, modules), mock.patch("builtins.print") as output:
            exec(code, namespace)
        output.assert_not_called()  # only boot_recovery owns the fixed line
        return events, namespace["workspace_ready"]

    def test_attachment_seals_only_after_successful_actual_vfs_mount(self):
        for profile in self.PROFILES:
            with self.subTest(profile=profile):
                events, ready = self.execute_mount_prefix(profile)
                self.assertEqual(events, ["construct", "attach", "seal"])
                self.assertTrue(ready)

    def test_all_mount_attachment_and_seal_failures_prevent_workspace_readiness(self):
        for profile in self.PROFILES:
            for failure, expected in (
                    ("constructor", ["construct", "recovery"]),
                    ("attachment", ["construct", "attach", "recovery"]),
                    ("seal", ["construct", "attach", "seal", "recovery"])):
                with self.subTest(profile=profile, failure=failure):
                    events, ready = self.execute_mount_prefix(profile, failure=failure)
                    self.assertEqual(events, expected)
                    self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main(verbosity=2)
