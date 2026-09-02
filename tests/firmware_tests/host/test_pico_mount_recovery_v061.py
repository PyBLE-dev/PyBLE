#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] v0.6.1 non-destructive Pico workspace mount recovery.
#
# Expected host-testable production seam:
#
#   pyble_boot.mount_lfs2(bdev, vfs_module, *, progsize=256) -> VfsLfs2
#
# A healthy constructor is returned immediately.  Only an OSError from that
# first constructor permits a read-only, complete-device erased-state scan.
# Exactly-all-0xff media may be formatted once and constructed once more.
# Nonblank or uncertain media is never formatted and the mount error escapes
# the helper; the overlay converts it into one bounded local USB recovery
# message and skips agent/autorun startup.
#
# The seam deliberately lives in the already-frozen pyble_boot module.  The
# board overlay contains only integration plumbing; this avoids creating a new
# release source-set entry merely to make a destructive boot decision testable.

import ast
import errno
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402


BOOT = _support.RedReason("pyble_boot", owner="rp2-agent-engineer")
WORKSPACE = _support.RedReason("pyble_workspace", owner="v0.6.1-storage-engineer")

BLOCK_COUNT_IOCTL = 4
BLOCK_SIZE_IOCTL = 5
REPO_ROOT = _support.REPO_ROOT
OVERLAY_BOOT = os.path.join(
    REPO_ROOT, "firmware", "board_overlays", "rpi-pico2-w", "_boot.py")


class FakeBlockDevice:
    """Small RP2-style block device with observable read/write effects."""

    def __init__(self, blocks, read_error_at=None, ioctl_error=None,
                 count_override=None, size_override=None, read_error=None,
                 read_return=None, wrong_size_at=None, partial_at=None,
                 block_size=4096):
        if any(len(block) > block_size for block in blocks):
            raise ValueError("fixture block exceeds its declared geometry")
        # Use an LFS2-compatible default geometry even when a test spells only
        # the significant prefix of a block. This keeps ordinary recovery
        # cases realistic while dedicated cases can select hostile geometry.
        self.blocks = [
            bytes(block) + b"\xff" * (block_size - len(block))
            for block in blocks
        ]
        self.block_size = block_size
        self.read_error_at = read_error_at
        self.read_error = read_error
        self.ioctl_error = ioctl_error
        self.count_override = count_override
        self.size_override = size_override
        self.read_return = read_return
        self.wrong_size_at = wrong_size_at
        self.partial_at = partial_at
        self.ioctl_calls = []
        self.read_calls = []
        self.read_buffers = []
        self.write_calls = []

    def ioctl(self, command, argument):
        self.ioctl_calls.append((command, argument))
        if self.ioctl_error is not None:
            raise self.ioctl_error
        if command == BLOCK_COUNT_IOCTL:
            if self.count_override is not None:
                return self.count_override
            return len(self.blocks)
        if command == BLOCK_SIZE_IOCTL:
            if self.size_override is not None:
                return self.size_override
            return self.block_size if self.blocks else 0
        return None

    def readblocks(self, block_number, destination):
        self.read_calls.append(block_number)
        self.read_buffers.append(destination)
        if block_number == self.read_error_at:
            if self.read_error is not None:
                raise self.read_error
            raise OSError(errno.EIO, "injected read fault")
        block = self.blocks[block_number]
        if block_number == self.wrong_size_at:
            destination[:] = block[:-1]  # malicious Python bdev shrinks bytearray
        elif block_number == self.partial_at:
            # Write only a strict prefix. A safe scanner poisons its reused
            # buffer before each read so stale all-FF bytes cannot make this
            # incomplete read look like conclusively erased media.
            prefix = max(1, len(block) // 2)
            destination[:prefix] = block[:prefix]
        else:
            destination[:] = block
        return self.read_return

    def writeblocks(self, block_number, source, *offset):
        self.write_calls.append((block_number, bytes(source), offset))
        raise AssertionError(
            "blank detection must be read-only; only VfsLfs2.mkfs owns writes")


def fake_vfs(constructor_effects, mkfs_effect=None):
    """Return (module, state) for deterministic VfsLfs2 construction."""
    state = types.SimpleNamespace(
        effects=list(constructor_effects),
        constructor_calls=[],
        mkfs_calls=[],
        order=[])

    class VfsLfs2:
        def __new__(cls, bdev, *, progsize):
            state.constructor_calls.append((bdev, progsize))
            state.order.append("construct")
            if not state.effects:
                raise AssertionError("unexpected extra VfsLfs2 construction")
            effect = state.effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            return effect

        @classmethod
        def mkfs(cls, bdev, *, progsize):
            state.mkfs_calls.append((bdev, progsize))
            state.order.append("mkfs")
            if mkfs_effect is not None:
                raise mkfs_effect

    return types.SimpleNamespace(VfsLfs2=VfsLfs2), state


class MountLfs2RecoveryTest(unittest.TestCase):
    def mount_fn(self, criterion):
        return BOOT.attr(self, "mount_lfs2", criterion)

    def test_pico_reexports_the_single_shared_workspace_mount_decision(self):
        shared = WORKSPACE.attr(
            self, "mount_lfs2", "v0.6.1 shared LFS2 recovery authority")
        self.assertIs(
            self.mount_fn("v0.6.1 Pico uses shared LFS2 recovery authority"),
            shared,
            "Pico and ESP boot must not drift into different erased-media "
            "format decisions",
        )

    def test_healthy_mount_does_not_inspect_or_format_storage(self):
        mounted = object()
        bdev = FakeBlockDevice([b"\xff" * 8, b"\xff" * 8])
        vfs_module, state = fake_vfs([mounted])

        result = self.mount_fn(
            "v0.6.1 healthy LFS2 construction has no recovery side effect")(
                bdev, vfs_module, progsize=256)

        self.assertIs(result, mounted)
        self.assertEqual(state.constructor_calls, [(bdev, 256)])
        self.assertEqual(state.mkfs_calls, [])
        self.assertEqual(bdev.ioctl_calls, [])
        self.assertEqual(bdev.read_calls, [])
        self.assertEqual(bdev.write_calls, [])

    def test_fully_erased_media_formats_exactly_once_then_reconstructs(self):
        mount_error = OSError(errno.EIO, "unformatted")
        mounted = object()
        blocks = [b"\xff" * 7 for _ in range(4)]
        bdev = FakeBlockDevice(blocks)
        vfs_module, state = fake_vfs([mount_error, mounted])

        result = self.mount_fn(
            "v0.6.1 only conclusively blank media may be formatted")(
                bdev, vfs_module, progsize=256)

        self.assertIs(result, mounted)
        self.assertEqual(bdev.read_calls, [0, 1, 2, 3],
                         "blank recovery must inspect every reported block")
        self.assertEqual(
            len(set(id(buffer) for buffer in bdev.read_buffers)), 1,
            "the complete flash scan must reuse one bounded block buffer")
        self.assertEqual(
            set(bdev.ioctl_calls),
            {(BLOCK_COUNT_IOCTL, 0), (BLOCK_SIZE_IOCTL, 0)})
        self.assertEqual(state.mkfs_calls, [(bdev, 256)])
        self.assertEqual(state.constructor_calls, [(bdev, 256), (bdev, 256)])
        self.assertEqual(state.order, ["construct", "mkfs", "construct"])
        self.assertEqual(bdev.write_calls, [],
                         "the scanner itself must perform no block write")

    def test_one_nonblank_byte_rejects_format_after_a_full_scan(self):
        mount_error = OSError(errno.EIO, "corrupt nonblank filesystem")
        blocks = [b"\x00" + b"\xff" * 7, b"\xff" * 8, b"\xff" * 8]
        bdev = FakeBlockDevice(blocks)
        vfs_module, state = fake_vfs([mount_error])

        with self.assertRaises(OSError) as raised:
            self.mount_fn(
                "v0.6.1 nonblank workspace is never auto-formatted")(
                    bdev, vfs_module, progsize=256)

        self.assertIs(raised.exception, mount_error,
                      "nonblank recovery must re-raise the original mount fault")
        self.assertEqual(
            bdev.read_calls, [0, 1, 2],
            "the erased-state decision is a complete scan, not a prefix probe")
        self.assertEqual(state.mkfs_calls, [])
        self.assertEqual(len(state.constructor_calls), 1)
        self.assertEqual(bdev.write_calls, [])

    def test_nonblank_last_block_is_also_detected(self):
        mount_error = OSError(errno.EIO, "corrupt nonblank filesystem")
        blocks = [b"\xff" * 8, b"\xff" * 8, b"\xff" * 7 + b"\x7f"]
        bdev = FakeBlockDevice(blocks)
        vfs_module, state = fake_vfs([mount_error])

        with self.assertRaises(OSError):
            self.mount_fn(
                "v0.6.1 final flash block participates in blank decision")(
                    bdev, vfs_module, progsize=256)

        self.assertEqual(bdev.read_calls, [0, 1, 2])
        self.assertEqual(state.mkfs_calls, [])

    def test_scan_read_failure_is_uncertain_and_never_formats(self):
        for read_error in (
                OSError(errno.EIO, "read fault"), MemoryError("scan allocation")):
            with self.subTest(exception=type(read_error).__name__):
                bdev = FakeBlockDevice(
                    [b"\xff" * 8, b"\xff" * 8, b"\xff" * 8],
                    read_error_at=1, read_error=read_error)
                vfs_module, state = fake_vfs(
                    [OSError(errno.EIO, "mount failed")])

                with self.assertRaises((OSError, MemoryError)):
                    self.mount_fn(
                        "v0.6.1 unreadable storage is not equivalent to blank storage")(
                            bdev, vfs_module, progsize=256)

                self.assertEqual(state.mkfs_calls, [])
                self.assertEqual(len(state.constructor_calls), 1)
                self.assertEqual(bdev.write_calls, [])

    def test_nonzero_readblocks_status_is_not_treated_as_blank(self):
        bdev = FakeBlockDevice(
            [b"\xff" * 8, b"\xff" * 8], read_return=1)
        vfs_module, state = fake_vfs([OSError(errno.EIO, "mount failed")])

        with self.assertRaises((OSError, ValueError)):
            self.mount_fn(
                "v0.6.1 nonzero readblocks result makes blank state uncertain")(
                    bdev, vfs_module, progsize=256)

        self.assertEqual(state.mkfs_calls, [])
        self.assertEqual(len(state.constructor_calls), 1)
        self.assertEqual(bdev.write_calls, [])

    def test_readblocks_may_not_shrink_the_reused_buffer(self):
        bdev = FakeBlockDevice(
            [b"\xff" * 8, b"\xff" * 8], wrong_size_at=1)
        vfs_module, state = fake_vfs([OSError(errno.EIO, "mount failed")])

        with self.assertRaises((OSError, ValueError)):
            self.mount_fn(
                "v0.6.1 wrong-sized read mutation is not conclusive blank media")(
                    bdev, vfs_module, progsize=256)

        self.assertEqual(state.mkfs_calls, [])
        self.assertEqual(len(state.constructor_calls), 1)
        self.assertEqual(bdev.write_calls, [])

    def test_short_second_block_write_cannot_inherit_prior_all_ff_tail(self):
        bdev = FakeBlockDevice(
            [b"\xff" * 8, b"\xff" * 8], partial_at=1)
        vfs_module, state = fake_vfs([OSError(errno.EIO, "mount failed")])

        with self.assertRaises((OSError, ValueError)):
            self.mount_fn(
                "v0.6.1 short read mutation cannot reuse stale erased bytes")(
                    bdev, vfs_module, progsize=256)

        self.assertEqual(state.mkfs_calls, [])
        self.assertEqual(len(state.constructor_calls), 1)
        self.assertEqual(bdev.write_calls, [])

    def test_geometry_failure_or_invalid_geometry_never_formats(self):
        cases = (
            (dict(ioctl_error=OSError(errno.EIO, "ioctl")), "ioctl failure"),
            (dict(count_override=0), "zero block count"),
            (dict(count_override=1), "one block cannot hold a metadata pair"),
            (dict(size_override=0), "zero block size"),
        )
        for kwargs, label in cases:
            with self.subTest(label=label):
                bdev = FakeBlockDevice([b"\xff" * 8], **kwargs)
                vfs_module, state = fake_vfs(
                    [OSError(errno.EIO, "mount failed")])
                with self.assertRaises((OSError, ValueError)):
                    self.mount_fn(
                        "v0.6.1 uncertain block geometry is fail-closed")(
                            bdev, vfs_module, progsize=256)
                self.assertEqual(state.mkfs_calls, [])
                self.assertEqual(len(state.constructor_calls), 1)
                self.assertEqual(bdev.write_calls, [])

    def test_positive_but_lfs_incompatible_geometry_never_formats(self):
        # MicroPython derives cache_size as
        # min(block_size, 4 * max(readsize=32, progsize)). LittleFS requires
        # cache % readsize == 0, cache % progsize == 0, block % cache == 0,
        # and block >= 128. Positive integers alone are therefore insufficient
        # authority for the destructive first-use format path.
        cases = (
            (64, 32, "block below LittleFS minimum"),
            (128, 256, "cache is not a multiple of progsize"),
            (1280, 256, "block is not a multiple of derived cache"),
        )
        for block_size, progsize, label in cases:
            with self.subTest(label=label):
                bdev = FakeBlockDevice(
                    [b"\xff", b"\xff"], block_size=block_size)
                vfs_module, state = fake_vfs(
                    [OSError(errno.EIO, "mount failed"), object()])

                with self.assertRaises(ValueError):
                    self.mount_fn(
                        "v0.6.1 LFS-incompatible geometry is fail-closed")(
                            bdev, vfs_module, progsize=progsize)

                self.assertEqual(state.mkfs_calls, [])
                self.assertEqual(len(state.constructor_calls), 1)
                self.assertEqual(bdev.read_calls, [])
                self.assertEqual(bdev.write_calls, [])

    def test_unexpected_constructor_exception_propagates_without_scan(self):
        for failure in (RuntimeError("bug"), MemoryError("allocation")):
            with self.subTest(exception=type(failure).__name__):
                bdev = FakeBlockDevice([b"\xff" * 8])
                vfs_module, state = fake_vfs([failure])
                with self.assertRaises(type(failure)) as raised:
                    self.mount_fn(
                        "v0.6.1 only OSError enters first-boot recovery")(
                            bdev, vfs_module, progsize=256)
                self.assertIs(raised.exception, failure)
                self.assertEqual(bdev.ioctl_calls, [])
                self.assertEqual(bdev.read_calls, [])
                self.assertEqual(state.mkfs_calls, [])

    def test_mkfs_failure_does_not_attempt_a_remount(self):
        bdev = FakeBlockDevice([b"\xff" * 8, b"\xff" * 8])
        mkfs_error = OSError(errno.EIO, "mkfs failed")
        vfs_module, state = fake_vfs(
            [OSError(errno.EIO, "unformatted")], mkfs_effect=mkfs_error)

        with self.assertRaises(OSError) as raised:
            self.mount_fn(
                "v0.6.1 blank recovery has one destructive attempt")(
                    bdev, vfs_module, progsize=256)

        self.assertIs(raised.exception, mkfs_error)
        self.assertEqual(len(state.mkfs_calls), 1)
        self.assertEqual(len(state.constructor_calls), 1)

    def test_post_format_constructor_failure_never_formats_again(self):
        first = OSError(errno.EIO, "unformatted")
        second = OSError(errno.EIO, "still unmountable")
        bdev = FakeBlockDevice([b"\xff" * 8, b"\xff" * 8])
        vfs_module, state = fake_vfs([first, second])

        with self.assertRaises(OSError) as raised:
            self.mount_fn(
                "v0.6.1 post-format mount failure has no format loop")(
                    bdev, vfs_module, progsize=256)

        self.assertIs(raised.exception, second)
        self.assertEqual(len(state.mkfs_calls), 1)
        self.assertEqual(len(state.constructor_calls), 2)
        self.assertEqual(state.order, ["construct", "mkfs", "construct"])


class OverlayIntegrationTest(unittest.TestCase):
    """The destructive decision belongs to the tested helper, not _boot.py."""

    @classmethod
    def setUpClass(cls):
        with open(OVERLAY_BOOT, "r", encoding="utf-8") as source_file:
            cls.source = source_file.read()
        cls.tree = ast.parse(cls.source, filename=OVERLAY_BOOT)

    @staticmethod
    def _call_name(call):
        fn = call.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            if isinstance(fn.value, ast.Name):
                return fn.value.id + "." + fn.attr
            return fn.attr
        return ""

    def call_names(self):
        return [
            self._call_name(node)
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
        ]

    def test_overlay_delegates_mount_recovery_once(self):
        call_names = self.call_names()
        helper_calls = [
            name for name in call_names
            if name in ("mount_lfs2", "pyble_boot.mount_lfs2")
        ]

        self.assertEqual(
            len(helper_calls), 1,
            "rpi-pico2-w/_boot.py must call the tested mount_lfs2 seam exactly once")

    def test_overlay_contains_no_direct_mkfs_authority(self):
        call_names = self.call_names()
        self.assertNotIn(
            "vfs.VfsLfs2.mkfs", call_names,
            "the board overlay must not retain an untested destructive fallback")
        self.assertFalse(
            any(name == "mkfs" or name.endswith(".mkfs") for name in call_names),
            "all formatting authority belongs inside pyble_boot.mount_lfs2")

    def test_agent_start_is_textually_after_mount_and_vfs_attachment(self):
        calls = [
            (node.lineno, self._call_name(node))
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
        ]
        mount_helper_lines = [
            line for line, name in calls
            if name in ("mount_lfs2", "pyble_boot.mount_lfs2")
        ]
        attach_lines = [line for line, name in calls if name == "vfs.mount"]
        agent_lines = [line for line, name in calls if name == "pyble_agent.main"]

        self.assertEqual(len(mount_helper_lines), 1,
                         "overlay must have one mount_lfs2 call")
        self.assertEqual(len(attach_lines), 1,
                         "overlay must attach the returned VFS exactly once")
        self.assertEqual(len(agent_lines), 1,
                         "overlay must start the agent exactly once")
        self.assertLess(mount_helper_lines[0], attach_lines[0])
        self.assertLess(
            attach_lines[0], agent_lines[0],
            "workspace attachment must resolve before BLE agent startup")

    def assert_one_bounded_recovery_print(self, printed):
        self.assertEqual(
            len(printed), 1,
            "a failed workspace mount must print exactly one local recovery message")
        args, kwargs = printed[0]
        self.assertEqual(kwargs, {},
                         "the recovery message must not depend on an output option")
        self.assertEqual(len(args), 1,
                         "exception objects or variable diagnostics must not be printed")
        self.assertIs(type(args[0]), str)
        self.assertIn("recovery", args[0].lower(),
                      "the fixed USB message must tell the operator it is recovery")

    def test_mount_recovery_failure_prints_once_and_skips_attach_and_agent(self):
        class MountFailure(OSError):
            pass

        calls = []
        printed = []
        bdev = object()

        class DirectLfs2:
            # Makes the legacy inline constructor path succeed, so this test's
            # RED is specifically failure to delegate/handle the helper—not
            # an incidental missing attribute in the fake VFS module.
            def __new__(cls, _bdev, *, progsize):
                calls.append(("direct-constructor", progsize))
                return object()

            @classmethod
            def mkfs(cls, _bdev, *, progsize):
                calls.append(("direct-mkfs", progsize))

        def mount_lfs2(_bdev, _vfs_module, *, progsize):
            calls.append(("recovery-helper", progsize))
            raise MountFailure(errno.EIO, "nonblank mount failed")

        fake_modules = {
            "rp2": types.SimpleNamespace(Flash=lambda: bdev),
            "vfs": types.SimpleNamespace(
                VfsLfs2=DirectLfs2,
                mount=lambda _fs, path: calls.append(("vfs-mount", path))),
            "pyble_boot": types.SimpleNamespace(mount_lfs2=mount_lfs2),
            "pyble_agent": types.SimpleNamespace(
                main=lambda: calls.append(("agent-main",))),
        }

        with mock.patch.dict(sys.modules, fake_modules), mock.patch(
                "builtins.print",
                side_effect=lambda *args, **kwargs: printed.append((args, kwargs))):
            try:
                exec(compile(self.source, OVERLAY_BOOT, "exec"),
                     {"__name__": "_pyble_boot_v061_probe"})
            except Exception as exc:
                self.fail(
                    "_boot.py must convert mount recovery failure into bounded "
                    "local USB recovery, not propagate {}: {}".format(
                        type(exc).__name__, exc))

        self.assertEqual(calls, [("recovery-helper", 256)])
        self.assert_one_bounded_recovery_print(printed)

    def test_vfs_mount_oserror_does_not_scan_format_or_start_agent(self):
        class MountFailure(OSError):
            pass

        calls = []
        printed = []
        bdev = object()
        constructed = object()

        class DirectLfs2:
            def __new__(cls, _bdev, *, progsize):
                calls.append(("direct-constructor", progsize))
                return object()

            @classmethod
            def mkfs(cls, _bdev, *, progsize):
                calls.append(("direct-mkfs", progsize))

        def mount_lfs2(_bdev, _vfs_module, *, progsize):
            calls.append(("recovery-helper", progsize))
            return constructed

        def attach(_fs, path):
            self.assertIs(_fs, constructed)
            calls.append(("vfs-mount", path))
            raise MountFailure(errno.EIO, "VFS attachment failed")

        fake_modules = {
            "rp2": types.SimpleNamespace(Flash=lambda: bdev),
            "vfs": types.SimpleNamespace(VfsLfs2=DirectLfs2, mount=attach),
            "pyble_boot": types.SimpleNamespace(mount_lfs2=mount_lfs2),
            "pyble_agent": types.SimpleNamespace(
                main=lambda: calls.append(("agent-main",))),
        }

        with mock.patch.dict(sys.modules, fake_modules), mock.patch(
                "builtins.print",
                side_effect=lambda *args, **kwargs: printed.append((args, kwargs))):
            try:
                exec(compile(self.source, OVERLAY_BOOT, "exec"),
                     {"__name__": "_pyble_boot_v061_attach_probe"})
            except Exception as exc:
                self.fail(
                    "vfs.mount OSError must enter bounded local recovery without "
                    "constructor rescan/format or propagation; got {}: {}".format(
                        type(exc).__name__, exc))

        self.assertEqual(
            calls,
            [("recovery-helper", 256), ("vfs-mount", "/")],
            "an attachment failure must not retry construction, scan, format, "
            "or start the agent")
        self.assert_one_bounded_recovery_print(printed)

    def test_unexpected_recovery_exceptions_use_one_fixed_local_message(self):
        observed_messages = []
        failures = (
            MemoryError("scan buffer allocation failed"),
            ValueError("invalid recovery geometry"),
            RuntimeError("unexpected recovery fault"),
        )

        for failure in failures:
            with self.subTest(exception=type(failure).__name__):
                calls = []
                printed = []
                bdev = object()

                class DirectLfs2:
                    def __new__(cls, _bdev, *, progsize):
                        calls.append(("direct-constructor", progsize))
                        return object()

                    @classmethod
                    def mkfs(cls, _bdev, *, progsize):
                        calls.append(("direct-mkfs", progsize))

                def mount_lfs2(_bdev, _vfs_module, *, progsize):
                    calls.append(("recovery-helper", progsize))
                    raise failure

                fake_modules = {
                    "rp2": types.SimpleNamespace(Flash=lambda: bdev),
                    "vfs": types.SimpleNamespace(
                        VfsLfs2=DirectLfs2,
                        mount=lambda _fs, path: calls.append(("vfs-mount", path))),
                    "pyble_boot": types.SimpleNamespace(mount_lfs2=mount_lfs2),
                    "pyble_agent": types.SimpleNamespace(
                        main=lambda: calls.append(("agent-main",))),
                }

                with mock.patch.dict(sys.modules, fake_modules), mock.patch(
                        "builtins.print",
                        side_effect=lambda *args, **kwargs:
                            printed.append((args, kwargs))):
                    try:
                        exec(compile(self.source, OVERLAY_BOOT, "exec"),
                             {"__name__": "_pyble_boot_v061_unexpected_probe"})
                    except Exception as exc:
                        self.fail(
                            "{} from mount_lfs2 must become bounded local "
                            "recovery, not propagate {}: {}".format(
                                type(failure).__name__, type(exc).__name__, exc))

                self.assertEqual(
                    calls, [("recovery-helper", 256)],
                    "unexpected recovery failure must neither attach VFS nor "
                    "start agent/autorun")
                self.assert_one_bounded_recovery_print(printed)
                observed_messages.append(printed[0][0][0])

        self.assertEqual(
            len(set(observed_messages)), 1,
            "allocation, validation, and unexpected recovery faults must emit "
            "one fixed bounded message without exception-dependent text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
