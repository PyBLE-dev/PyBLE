#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Read-status admission must match the pinned MicroPython block protocol.

Synthetic host tests only, not hardware evidence. In particular False is an
explicit failed read, although it compares equal to integer zero in Python.
"""

import errno
import importlib.util
from pathlib import Path
import types
import unittest


SOURCE = Path(__file__).resolve().parents[3] / "firmware/pyble/pyble_workspace.py"
CHALLENGE = "0123456789abcdef0123456789abcdef"


def fresh_workspace():
    spec = importlib.util.spec_from_file_location("_workspace_read_status_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EqualsZero:
    """A non-status object must not gain format authority through equality."""

    def __eq__(self, other):
        return type(other) is int and other == 0


class Media:
    def __init__(self, read_status):
        self.contents = bytearray(b"\xff" * 8192)
        self.read_status = read_status
        self.reads = []
        self.programs = 0
        self.erases = 0

    def readblocks(self, block, destination, *offset):
        self.reads.append(block)
        start = block * 4096 + (offset[0] if offset else 0)
        destination[:] = self.contents[start:start + len(destination)]
        # Even a fully populated FF buffer is not valid evidence when the
        # device reports an error or an unsupported status type.
        return self.read_status

    def writeblocks(self, block, source, *offset):
        self.programs += 1
        start = block * 4096 + (offset[0] if offset else 0)
        self.contents[start:start + len(source)] = source
        return None

    def ioctl(self, command, argument):
        if command == 4:
            return 2
        if command == 5:
            return 4096
        if command == 6:
            self.erases += 1
            start = argument * 4096
            self.contents[start:start + 4096] = b"\xff" * 4096
        return 0


def vfs_fixture():
    calls = types.SimpleNamespace(constructors=0, formats=0)

    class VfsLfs2:
        def __new__(cls, bdev, *, progsize):
            calls.constructors += 1
            if calls.constructors == 1:
                raise OSError(errno.EIO, "initial mount failed")
            return types.SimpleNamespace(bdev=bdev)

        @staticmethod
        def mkfs(bdev, *, progsize):
            calls.formats += 1
            bdev.ioctl(6, 0)
            bdev.writeblocks(0, b"formatted", 0)

    return types.SimpleNamespace(VfsLfs2=VfsLfs2), calls


class WorkspaceReadStatusTests(unittest.TestCase):
    def assert_admitted(self, status):
        for observed in (False, True):
            with self.subTest(observe_boot=observed):
                workspace = fresh_workspace()
                media = Media(status)
                vfs, calls = vfs_fixture()
                workspace.mount_lfs2(media, vfs, progsize=256, observe_boot=observed)
                self.assertEqual(media.reads, [0, 1])
                self.assertEqual(calls.formats, 1)
                self.assertEqual(calls.constructors, 2)
                self.assertEqual((media.programs, media.erases), (1, 1))
                if observed:
                    workspace.boot_attached()
                    record = workspace.read_boot_observation(CHALLENGE)
                    self.assertEqual(record["media_state"], "erased")
                    self.assertTrue(record["complete"])
                    self.assertTrue(record["workspace_attached"])
                    self.assertFalse(record["fault"])
                    self.assertFalse(record["overflow"])
                    for key in ("mount_attempts", "format_attempts", "format_completions",
                                "remount_attempts", "remount_completions", "program_calls", "erase_calls"):
                        self.assertEqual(record[key], 1, key)
                else:
                    with self.assertRaises(RuntimeError):
                        workspace.read_boot_observation(CHALLENGE)

    def assert_refused(self, status):
        for observed in (False, True):
            with self.subTest(observe_boot=observed):
                workspace = fresh_workspace()
                media = Media(status)
                before = bytes(media.contents)
                vfs, calls = vfs_fixture()
                with self.assertRaises((ValueError, OSError, TypeError)):
                    workspace.mount_lfs2(media, vfs, progsize=256, observe_boot=observed)
                self.assertEqual(media.reads, [0])
                self.assertEqual(calls.formats, 0)
                self.assertEqual(calls.constructors, 1)
                self.assertEqual((media.programs, media.erases), (0, 0))
                self.assertEqual(bytes(media.contents), before)
                if observed:
                    record = workspace.read_boot_observation(CHALLENGE)
                    self.assertEqual(record["media_state"], "uncertain")
                    self.assertTrue(record["fault"])
                    self.assertFalse(record["complete"])
                    self.assertFalse(record["workspace_attached"])
                    self.assertEqual(record["mount_attempts"], 1)
                    for key in ("format_attempts", "format_completions", "remount_attempts",
                                "remount_completions", "program_calls", "erase_calls"):
                        self.assertEqual(record[key], 0, key)
                else:
                    with self.assertRaises(RuntimeError):
                        workspace.read_boot_observation(CHALLENGE)

    def test_none_is_success(self):
        self.assert_admitted(None)

    def test_exact_integer_zero_is_success(self):
        self.assert_admitted(0)

    def test_boolean_true_is_protocol_success(self):
        self.assert_admitted(True)

    def test_boolean_false_is_failed_read_not_erased_authority(self):
        self.assert_refused(False)

    def test_float_zero_is_not_a_read_status(self):
        self.assert_refused(0.0)

    def test_custom_equality_to_zero_is_not_a_read_status(self):
        self.assert_refused(EqualsZero())


if __name__ == "__main__":
    unittest.main()
