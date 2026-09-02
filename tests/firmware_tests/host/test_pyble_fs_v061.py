#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] v0.6.1 filesystem hardening tests.  These tests intentionally pin the
# additive, wire-compatible behaviour before the portable and native agents
# implement it:
#
# * transfer scratch is never visible through FILE_LIST;
# * namespace mutations are rejected while a PUT owns the transaction;
# * one DATA chunk may never cross the total declared by PUT_BEGIN;
# * PUT admission keeps a fixed 64 KiB filesystem safety reserve; and
# * malformed scratch is either normalised safely or rejected without touching
#   the previous destination.
#
# The existing F-25 suite remains the baseline.  This file imports its wire
# builders and tmpdir fixture so the RED increment is isolated from that large
# test file and can be reverted or reviewed independently.

import errno
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_pyble_fs import (  # noqa: E402
    EACCES,
    EBADREQ,
    EBUSY,
    EIO,
    ENOSPC,
    ERANGE,
    FS,
    OK,
    OP_PUT_ACK,
    FsTestBase,
    crc32,
    path_pl,
    p32,
    put_begin_pl,
    put_data_pl,
    rename_pl,
    u32,
)


SAFETY_RESERVE = 64 * 1024
UINT64_MAX = (1 << 64) - 1
_DEFAULT_STATVFS = object()


class V061FsTestBase(FsTestBase):
    """Baseline fixture plus best-effort cleanup for intentionally RED PUTs."""

    def svc(self, criterion, **kwargs):
        service, events = super().svc(criterion, **kwargs)

        def close_open_test_file():
            # Several RED assertions intentionally stop before PUT_END.  Avoid
            # leaking a CPython buffered writer while preserving the production
            # disconnect semantics tested by the baseline suite.
            open_file = getattr(service, "_put_file", None)
            if open_file is not None:
                try:
                    open_file.close()
                except Exception:
                    pass

        self.addCleanup(close_open_test_file)
        return service, events


class ScratchVisibilityTest(V061FsTestBase):
    """Reserved transport state is not part of the user's workspace view."""

    def test_root_and_nested_lists_omit_scratch_files_and_directories(self):
        self.put_file("/visible.py", b"print('visible')\n")
        self.put_file("/visible.py.pbltmp", b"partial")
        os.mkdir(self.hpath("/hidden-dir.pbltmp"))
        os.mkdir(self.hpath("/lib"))
        self.put_file("/lib/module.py", b"VALUE = 1\n")
        self.put_file("/lib/module.py.pbltmp", b"partial")

        service, _events = self.svc(
            "v0.6.1/FR-FS scratch entries are absent from every FILE_LIST")

        root_more, _root_count, root_entries = self.parse_list(
            service.handle_list(path_pl(b"/")))
        nested_more, _nested_count, nested_entries = self.parse_list(
            service.handle_list(path_pl(b"/lib")))

        self.assertEqual(root_more, 0)
        self.assertEqual(
            set(name for _kind, _size, name in root_entries),
            {"visible.py", "lib"},
            "a case-sensitive '.pbltmp' basename is internal transport state, "
            "whether it names a file or a directory")
        self.assertEqual(nested_more, 0)
        self.assertEqual(
            [name for _kind, _size, name in nested_entries],
            ["module.py"],
            "nested scratch must be hidden by the same listing rule")

    def test_hidden_entries_consume_no_budget_count_or_more_flag(self):
        # Force a deterministic directory order.  On the current implementation
        # these phantom scratch names fill the 480-byte response before the one
        # real visible file is reached.  A correct implementation skips them
        # before stat, response-budget, count, and `more` processing.
        visible = "answer.py"
        self.put_file("/" + visible, b"42\n")
        hidden = [
            "scratch_%02d_%s.pbltmp" % (index, "x" * 26)
            for index in range(16)
        ]
        module = FS.obj(
            self, "v0.6.1 hidden scratch does not truncate visible listings")
        service, _events = self.svc(
            "v0.6.1 hidden scratch does not consume LIST response budget")

        with mock.patch.object(module.os, "listdir",
                               return_value=hidden + [visible]):
            more, count, entries = self.parse_list(
                service.handle_list(path_pl(b"/")))

        self.assertEqual(more, 0,
                         "hidden-only overflow must not advertise truncation")
        self.assertEqual(count, 1,
                         "hidden scratch must not increment FILE_LIST count")
        self.assertEqual(entries, [(0, 3, visible)])


class ActivePutMutationTest(V061FsTestBase):
    """A PUT transaction owns namespace mutation until it resolves."""

    def _begin_over_existing(self, dest="/target.py"):
        self.put_file(dest, b"OLD DESTINATION")
        service, events = self.svc(
            "v0.6.1 active PUT serialises namespace mutations")
        rsp = self.begin_put(service, dest.encode("utf-8"), b"NEW CONTENT")
        self.assertEqual(rsp[0], OK)
        return service, events

    def test_delete_active_destination_is_ebusy_and_has_no_effect(self):
        service, _events = self._begin_over_existing()
        rsp = service.handle_delete(path_pl(b"/target.py"))
        self.assertEqual(rsp[0], EBUSY)
        self.assertEqual(self.read_file("/target.py"), b"OLD DESTINATION")

    def test_mkdir_during_put_is_ebusy_even_when_path_is_missing(self):
        service, _events = self._begin_over_existing()
        rsp = service.handle_mkdir(path_pl(b"/unrelated"))
        self.assertEqual(
            rsp[0], EBUSY,
            "busy arbitration must happen before probing a valid namespace path")
        self.assertFalse(os.path.exists(self.hpath("/unrelated")))

    def test_rename_active_parent_is_ebusy_and_has_no_effect(self):
        self.put_file("/project/target.py", b"OLD DESTINATION")
        service, _events = self.svc(
            "v0.6.1 active PUT prevents its parent directory moving")
        self.assertEqual(
            self.begin_put(service, b"/project/target.py", b"NEW")[0], OK)

        rsp = service.handle_rename(rename_pl(b"/project", b"/moved"))
        self.assertEqual(rsp[0], EBUSY)
        self.assertTrue(os.path.isdir(self.hpath("/project")))
        self.assertFalse(os.path.exists(self.hpath("/moved")))
        self.assertEqual(self.read_file("/project/target.py"), b"OLD DESTINATION")

    def test_unrelated_rename_is_also_serialised_conservatively(self):
        service, _events = self._begin_over_existing()
        self.put_file("/other.txt", b"OTHER")
        rsp = service.handle_rename(rename_pl(b"/other.txt", b"/renamed.txt"))
        self.assertEqual(rsp[0], EBUSY)
        self.assertEqual(self.read_file("/other.txt"), b"OTHER")
        self.assertFalse(os.path.exists(self.hpath("/renamed.txt")))

    def test_valid_missing_delete_is_ebusy_not_enoent(self):
        service, _events = self._begin_over_existing()
        self.assertEqual(
            service.handle_delete(path_pl(b"/missing.txt"))[0], EBUSY,
            "once a path is syntactically valid and jailed, PUT ownership wins "
            "over namespace existence")

    def test_parse_and_jail_precede_active_put_busy_status(self):
        service, _events = self._begin_over_existing()
        self.put_file("/source.txt", b"source")

        self.assertEqual(service.handle_delete(b"\x01")[0], EBADREQ)
        self.assertEqual(service.handle_delete(path_pl(b"../escape"))[0], EACCES)
        self.assertEqual(service.handle_mkdir(path_pl(b"bad.pbltmp"))[0], EACCES)
        self.assertEqual(
            service.handle_rename(
                rename_pl(b"/source.txt", b"../escape"))[0],
            EACCES,
            "FILE_RENAME must resolve both paths before applying EBUSY")
        self.assertEqual(self.read_file("/source.txt"), b"source")


class DeclaredTotalBoundaryTest(V061FsTestBase):
    def test_crossing_chunk_is_not_written_and_latches_erange(self):
        self.put_file("/bounded.bin", b"OLD")
        service, events = self.svc(
            "v0.6.1 PUT_DATA may not cross PUT_BEGIN total_size")
        expected = b"ABCD"
        self.assertEqual(
            service.handle_put_begin(
                put_begin_pl(len(expected), crc32(expected), b"/bounded.bin"))[0],
            OK)

        service.handle_put_data(put_data_pl(0, b"ABC"))
        service.handle_put_data(put_data_pl(3, b"DE"))  # crosses total by 1
        # A correct-looking retry must not clear a latched protocol-range fault.
        service.handle_put_data(put_data_pl(3, b"D"))

        acknowledgements = [
            u32(payload) for opcode, payload in events if opcode == OP_PUT_ACK
        ]
        self.assertEqual(
            acknowledgements, [3, 3, 3],
            "the crossing chunk and every post-fault chunk must leave the "
            "durable watermark unchanged")
        self.assertEqual(service.handle_put_end(p32(crc32(expected)))[0], ERANGE)
        self.assertEqual(self.read_file("/bounded.bin"), b"OLD")
        self.assertFalse(os.path.exists(self.hpath("/bounded.bin.pbltmp")))

    def test_chunk_ending_exactly_at_total_remains_valid(self):
        service, events = self.svc(
            "v0.6.1 declared-total check accepts the exact boundary")
        data = b"ABCD"
        self.assertEqual(self.begin_put(service, b"/exact.bin", data)[0], OK)
        service.handle_put_data(put_data_pl(0, data))
        self.assertEqual(
            [u32(payload) for opcode, payload in events if opcode == OP_PUT_ACK],
            [4])
        self.assertEqual(service.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/exact.bin"), data)


class StatvfsAdmissionTest(V061FsTestBase):
    """PUT_BEGIN admission uses f_frsize/f_bavail and a 64 KiB reserve."""

    @staticmethod
    def _statvfs_tuple(unit, available, free=None):
        # POSIX/MicroPython order: bsize, frsize, blocks, bfree, bavail,
        # files, ffree, favail, flags, namemax.
        if free is None:
            free = available
        return (unit, unit, 1_000_000, free, available,
                1_000_000, 1_000_000, 1_000_000, 0, 255)

    def _service_with_space(self, unit, available, free=None, effect=None,
                            stat_result=_DEFAULT_STATVFS):
        calls = []

        def statvfs_fn(path):
            calls.append(path)
            if effect is not None:
                raise effect
            if stat_result is not _DEFAULT_STATVFS:
                return stat_result
            return self._statvfs_tuple(unit, available, free=free)

        cls = FS.attr(
            self, "FsService",
            "v0.6.1 FsService statvfs admission seam")
        events = []
        try:
            service = cls(
                self.root,
                lambda opcode, payload: events.append((opcode, bytes(payload))),
                statvfs_fn=statvfs_fn)
        except TypeError as exc:
            self.fail(
                "[v0.6.1 filesystem admission] FsService must accept the "
                "deterministic `statvfs_fn(path)` seam; current constructor "
                "rejected it: {}".format(exc))
        open_file = getattr(service, "_put_file", None)
        if open_file is not None:
            self.addCleanup(open_file.close)
        else:
            def close_future_file():
                candidate = getattr(service, "_put_file", None)
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:
                        pass

            self.addCleanup(close_future_file)
        return service, events, calls

    def test_exact_reserve_plus_rounded_payload_is_admitted(self):
        unit = 4096
        total = unit + 1             # rounds to two allocation units
        available = (SAFETY_RESERVE + 2 * unit) // unit
        service, _events, calls = self._service_with_space(unit, available)
        self.assertEqual(calls, [],
                         "free space is dynamic and must not be cached at construction")

        rsp = service.handle_put_begin(
            put_begin_pl(total, crc32(b"x" * total), b"/exact-space.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 0)
        self.assertEqual(calls, [self.root],
                         "admission must query the injected workspace root once")
        # Abort the accepted empty transfer and remove its scratch.
        self.assertEqual(service.handle_put_end(p32(0))[0], ERANGE)

    def test_one_allocation_unit_below_boundary_is_enospc_before_open(self):
        unit = 4096
        total = unit + 1
        available = (SAFETY_RESERVE + unit) // unit
        self.put_file("/keep.bin", b"OLD DESTINATION")
        service, _events, _calls = self._service_with_space(unit, available)

        rsp = service.handle_put_begin(
            put_begin_pl(total, crc32(b"x" * total), b"/keep.bin"))
        self.assertEqual(rsp[0], ENOSPC)
        self.assertEqual(self.read_file("/keep.bin"), b"OLD DESTINATION")
        self.assertFalse(
            os.path.exists(self.hpath("/keep.bin.pbltmp")),
            "ENOSPC admission must happen before scratch creation/growth")

    def test_exact_64k_reserve_admits_zero_byte_upload(self):
        service, _events, _calls = self._service_with_space(
            unit=1, available=SAFETY_RESERVE)
        rsp = service.handle_put_begin(
            put_begin_pl(0, crc32(b""), b"/empty.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(service.handle_put_end(p32(crc32(b"")))[0], OK)
        self.assertEqual(self.read_file("/empty.bin"), b"")

    def test_one_byte_below_64k_reserve_rejects_even_zero_byte_upload(self):
        service, _events, _calls = self._service_with_space(
            unit=1, available=SAFETY_RESERVE - 1)
        rsp = service.handle_put_begin(
            put_begin_pl(0, crc32(b""), b"/empty.bin"))
        self.assertEqual(rsp[0], ENOSPC)
        self.assertFalse(os.path.exists(self.hpath("/empty.bin.pbltmp")))

    def test_bavail_not_bfree_is_the_admission_authority(self):
        unit = 4096
        # Plenty of privileged free blocks, but only the 16-block reserve is
        # available to this filesystem user: a one-byte upload must be refused.
        service, _events, _calls = self._service_with_space(
            unit=unit, available=16, free=10_000)
        rsp = service.handle_put_begin(
            put_begin_pl(1, crc32(b"x"), b"/bavail.bin"))
        self.assertEqual(rsp[0], ENOSPC)

    def test_resume_charges_only_bytes_after_verified_prefix(self):
        unit = 4096
        prefix = b"P" * unit
        total = 2 * unit
        self.put_file("/resume.bin", b"OLD")
        self.put_file("/resume.bin.pbltmp", prefix)
        service, _events, _calls = self._service_with_space(
            unit=unit,
            available=(SAFETY_RESERVE + unit) // unit)

        rsp = service.handle_put_begin(
            put_begin_pl(total, crc32(prefix + b"Q" * unit), b"/resume.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), unit)
        self.assertEqual(service.handle_put_end(p32(0))[0], ERANGE)
        self.assertEqual(self.read_file("/resume.bin"), b"OLD")

    def test_statvfs_failure_is_eio_and_never_opens_scratch(self):
        self.put_file("/keep.bin", b"OLD")
        service, _events, _calls = self._service_with_space(
            unit=4096, available=1000,
            effect=OSError(errno.EIO, "statvfs fault"))
        rsp = service.handle_put_begin(
            put_begin_pl(1, crc32(b"x"), b"/keep.bin"))
        self.assertEqual(rsp[0], EIO)
        self.assertEqual(self.read_file("/keep.bin"), b"OLD")
        self.assertFalse(os.path.exists(self.hpath("/keep.bin.pbltmp")))

    def test_zero_fragment_size_is_invalid_geometry_but_zero_bavail_is_enospc(self):
        zero_unit, _events, _calls = self._service_with_space(
            unit=0, available=1000)
        self.assertEqual(
            zero_unit.handle_put_begin(
                put_begin_pl(1, crc32(b"x"), b"/zero-unit.bin"))[0],
            EIO,
            "f_frsize=0 cannot define an allocation or rounding unit")
        self.assertFalse(os.path.exists(self.hpath("/zero-unit.bin.pbltmp")))

        zero_available, _events, _calls = self._service_with_space(
            unit=4096, available=0)
        self.assertEqual(
            zero_available.handle_put_begin(
                put_begin_pl(1, crc32(b"x"), b"/zero-free.bin"))[0],
            ENOSPC,
            "zero valid available blocks is capacity exhaustion, not bad geometry")
        self.assertFalse(os.path.exists(self.hpath("/zero-free.bin.pbltmp")))

    def test_negative_statvfs_fields_are_eio(self):
        cases = ((-1, 1000, "negative f_frsize"),
                 (4096, -1, "negative f_bavail"))
        for index, (unit, available, label) in enumerate(cases):
            with self.subTest(field=label):
                dest = "/negative-%d.bin" % index
                service, _events, _calls = self._service_with_space(
                    unit=unit, available=available)
                rsp = service.handle_put_begin(
                    put_begin_pl(1, crc32(b"x"), dest.encode("utf-8")))
                self.assertEqual(rsp[0], EIO)
                self.assertFalse(os.path.exists(self.hpath(dest + ".pbltmp")))

    def test_non_integer_statvfs_fields_are_eio(self):
        cases = (("4096", 1000, "text f_frsize"),
                 (4096.0, 1000, "float f_frsize"),
                 (4096, "1000", "text f_bavail"),
                 (4096, None, "None f_bavail"))
        for index, (unit, available, label) in enumerate(cases):
            with self.subTest(field=label):
                dest = "/noninteger-%d.bin" % index
                service, _events, _calls = self._service_with_space(
                    unit=unit, available=available)
                rsp = service.handle_put_begin(
                    put_begin_pl(1, crc32(b"x"), dest.encode("utf-8")))
                self.assertEqual(rsp[0], EIO)
                self.assertFalse(os.path.exists(self.hpath(dest + ".pbltmp")))

    def test_short_statvfs_result_is_eio(self):
        service, _events, _calls = self._service_with_space(
            unit=4096, available=1000,
            stat_result=(4096, 4096, 1000, 1000))  # no f_bavail field 4
        rsp = service.handle_put_begin(
            put_begin_pl(1, crc32(b"x"), b"/short-statvfs.bin"))
        self.assertEqual(rsp[0], EIO)
        self.assertFalse(os.path.exists(self.hpath("/short-statvfs.bin.pbltmp")))

    def test_available_byte_multiplication_overflow_is_eio(self):
        service, _events, _calls = self._service_with_space(
            unit=1 << 63, available=2)
        rsp = service.handle_put_begin(
            put_begin_pl(1, crc32(b"x"), b"/multiply-overflow.bin"))
        self.assertEqual(
            rsp[0], EIO,
            "f_bavail * f_frsize beyond UINT64_MAX is invalid geometry, "
            "not wrapped free space")
        self.assertFalse(
            os.path.exists(self.hpath("/multiply-overflow.bin.pbltmp")))

    def test_rounding_intermediate_overflow_is_eio(self):
        # Mathematically ceil(2 / UINT64_MAX) * UINT64_MAX is representable,
        # but the common `(remaining + unit - 1)` expression overflows.  The
        # admission code must detect that checked-u64 intermediate rather than
        # wrap it into a tiny requirement and accept the upload.
        service, _events, _calls = self._service_with_space(
            unit=UINT64_MAX, available=1)
        rsp = service.handle_put_begin(
            put_begin_pl(2, crc32(b"xx"), b"/round-overflow.bin"))
        self.assertEqual(rsp[0], EIO)
        self.assertFalse(os.path.exists(self.hpath("/round-overflow.bin.pbltmp")))

    def test_reserve_addition_overflow_is_eio(self):
        # `needed` itself is representable and free == needed.  Adding the
        # exact 64 KiB reserve is the checked operation that exceeds u64.
        unit = UINT64_MAX - SAFETY_RESERVE + 1
        service, _events, _calls = self._service_with_space(
            unit=unit, available=1)
        rsp = service.handle_put_begin(
            put_begin_pl(1, crc32(b"x"), b"/reserve-overflow.bin"))
        self.assertEqual(rsp[0], EIO)
        self.assertFalse(os.path.exists(self.hpath("/reserve-overflow.bin.pbltmp")))


class _ShortReader:
    """Read a strict prefix once, then report premature EOF."""

    def __init__(self, wrapped, first_length):
        self._wrapped = wrapped
        self._first_length = first_length
        self._read_once = False

    def read(self, _length=-1):
        if self._read_once:
            return b""
        self._read_once = True
        return self._wrapped.read(self._first_length)

    def close(self):
        return self._wrapped.close()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


class _PostScanMutationReader:
    """Mutate the scratch namespace after its declared prefix was read."""

    def __init__(self, wrapped, original_length, mutation):
        self._wrapped = wrapped
        self._original_length = original_length
        self._mutation = mutation
        self._mutated = False

    def read(self, length=-1):
        data = self._wrapped.read(length)
        if (not self._mutated and data
                and self._wrapped.tell() >= self._original_length):
            self._mutated = True
            self._mutation()
        return data

    def close(self):
        return self._wrapped.close()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


class MalformedScratchRecoveryTest(V061FsTestBase):
    def test_empty_scratch_directory_is_removed_and_upload_restarts(self):
        os.mkdir(self.hpath("/fresh.bin.pbltmp"))
        service, _events = self.svc(
            "v0.6.1 empty scratch directory is safely normalised")
        data = b"fresh"

        rsp = self.begin_put(service, b"/fresh.bin", data)
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 0)
        self.assertTrue(os.path.isfile(self.hpath("/fresh.bin.pbltmp")))
        self.send_put(service, data)
        self.assertEqual(service.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/fresh.bin"), data)

    def test_nonempty_scratch_directory_fails_closed_without_recursion(self):
        self.put_file("/keep.bin", b"OLD DESTINATION")
        self.put_file("/keep.bin.pbltmp/unknown.txt", b"DO NOT DELETE")
        service, _events = self.svc(
            "v0.6.1 nonempty scratch directory is an internal EIO")

        rsp = self.begin_put(service, b"/keep.bin", b"NEW")
        self.assertEqual(rsp[0], EIO)
        self.assertEqual(self.read_file("/keep.bin"), b"OLD DESTINATION")
        self.assertEqual(
            self.read_file("/keep.bin.pbltmp/unknown.txt"), b"DO NOT DELETE")
        self.assertEqual(service.handle_put_end(p32(0))[0], EBADREQ,
                         "a rejected BEGIN must not leave an active transfer")

    def test_short_read_never_becomes_a_nonzero_resume_offset(self):
        scratch = self.put_file("/short.bin.pbltmp", b"ABCDEFGH")

        def open_fn(path, mode):
            wrapped = open(path, mode)
            if path == scratch and mode == "rb":
                return _ShortReader(wrapped, 3)
            return wrapped

        service, _events = self.svc(
            "v0.6.1 resume offset equals bytes actually CRC-scanned",
            open_fn=open_fn)
        data = b"0123456789ABCDEF"

        rsp = self.begin_put(service, b"/short.bin", data)
        self.assertEqual(rsp[0], OK)
        self.assertEqual(
            u32(rsp, 1), 0,
            "a stat length of eight with only three readable bytes is malformed, "
            "not an eight-byte verified prefix")
        self.send_put(service, data)
        self.assertEqual(service.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/short.bin"), data)

    def test_failed_oversize_cleanup_is_eio_and_does_not_truncate(self):
        old = b"OLD DESTINATION"
        stale = b"X" * 64
        self.put_file("/keep.bin", old)
        scratch = self.put_file("/keep.bin.pbltmp", stale)
        module = FS.obj(self, "v0.6.1 malformed scratch cleanup is fail-closed")
        service, _events = self.svc(
            "v0.6.1 failed malformed-scratch removal returns EIO")
        real_remove = module.os.remove

        def remove_fn(path):
            if path == scratch:
                raise OSError(errno.EIO, "injected scratch removal failure")
            return real_remove(path)

        with mock.patch.object(module.os, "remove", side_effect=remove_fn):
            rsp = self.begin_put(service, b"/keep.bin", b"small")

        self.assertEqual(rsp[0], EIO)
        self.assertEqual(self.read_file("/keep.bin"), old)
        self.assertEqual(self.read_file("/keep.bin.pbltmp"), stale,
                         "failed cleanup must not fall through to wb truncation")
        self.assertEqual(service.handle_put_end(p32(0))[0], EBADREQ)

    def test_post_scan_length_change_is_not_accepted_as_a_resume_prefix(self):
        original = b"ABCDEFGH"
        scratch = self.put_file("/length-race.bin.pbltmp", original)
        self.put_file("/length-race.bin", b"OLD")

        def grow_after_scan():
            with open(scratch, "ab") as destination:
                destination.write(b"!")

        def open_fn(path, mode):
            wrapped = open(path, mode)
            if path == scratch and mode == "rb":
                return _PostScanMutationReader(
                    wrapped, len(original), grow_after_scan)
            return wrapped

        service, _events = self.svc(
            "v0.6.1 resume re-stats scratch length after CRC scan",
            open_fn=open_fn)
        data = b"0123456789ABCDEF"
        rsp = self.begin_put(service, b"/length-race.bin", data)

        self.assertEqual(rsp[0], OK)
        self.assertEqual(
            u32(rsp, 1), 0,
            "a scratch length changed after scan is malformed and must restart")
        self.assertEqual(self.read_file("/length-race.bin"), b"OLD")
        self.send_put(service, data)
        self.assertEqual(service.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/length-race.bin"), data)

    def test_post_scan_type_change_is_cleaned_without_touching_destination(self):
        original = b"ABCDEFGH"
        scratch = self.put_file("/type-race.bin.pbltmp", original)
        self.put_file("/type-race.bin", b"OLD")

        def replace_with_empty_directory():
            os.remove(scratch)
            os.mkdir(scratch)

        def open_fn(path, mode):
            wrapped = open(path, mode)
            if path == scratch and mode == "rb":
                return _PostScanMutationReader(
                    wrapped, len(original), replace_with_empty_directory)
            return wrapped

        service, _events = self.svc(
            "v0.6.1 resume re-stats scratch type after CRC scan",
            open_fn=open_fn)
        data = b"new payload"
        rsp = self.begin_put(service, b"/type-race.bin", data)

        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 0)
        self.assertTrue(os.path.isfile(scratch),
                        "the changed empty directory must be normalised before wb")
        self.assertEqual(self.read_file("/type-race.bin"), b"OLD")
        self.send_put(service, data)
        self.assertEqual(service.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/type-race.bin"), data)

    def test_successful_remove_that_leaves_regular_scratch_fails_closed(self):
        old = b"OLD DESTINATION"
        stale = b"X" * 64
        self.put_file("/lying-remove.bin", old)
        scratch = self.put_file("/lying-remove.bin.pbltmp", stale)
        module = FS.obj(
            self, "v0.6.1 scratch removal success is verified by absence")
        service, _events = self.svc(
            "v0.6.1 no-op remove cannot fall through to scratch truncation")
        real_remove = module.os.remove

        def remove_fn(path):
            if path == scratch:
                return None             # lying backend: reports success, leaves path
            return real_remove(path)

        with mock.patch.object(module.os, "remove", side_effect=remove_fn):
            rsp = self.begin_put(service, b"/lying-remove.bin", b"small")

        self.assertEqual(rsp[0], EIO)
        self.assertEqual(self.read_file("/lying-remove.bin"), old)
        self.assertEqual(self.read_file("/lying-remove.bin.pbltmp"), stale)
        self.assertEqual(service.handle_put_end(p32(0))[0], EBADREQ)

    def test_successful_rmdir_that_leaves_scratch_directory_fails_closed(self):
        self.put_file("/lying-rmdir.bin", b"OLD DESTINATION")
        scratch = self.hpath("/lying-rmdir.bin.pbltmp")
        os.mkdir(scratch)
        module = FS.obj(
            self, "v0.6.1 scratch rmdir success is verified by absence")
        service, _events = self.svc(
            "v0.6.1 no-op rmdir cannot fall through to scratch open")
        real_rmdir = module.os.rmdir

        def rmdir_fn(path):
            if path == scratch:
                return None             # lying backend: reports success, leaves path
            return real_rmdir(path)

        with mock.patch.object(module.os, "rmdir", side_effect=rmdir_fn):
            rsp = self.begin_put(service, b"/lying-rmdir.bin", b"new")

        self.assertEqual(rsp[0], EIO)
        self.assertEqual(self.read_file("/lying-rmdir.bin"), b"OLD DESTINATION")
        self.assertTrue(os.path.isdir(scratch))
        self.assertEqual(service.handle_put_end(p32(0))[0], EBADREQ)


if __name__ == "__main__":
    unittest.main(verbosity=2)
