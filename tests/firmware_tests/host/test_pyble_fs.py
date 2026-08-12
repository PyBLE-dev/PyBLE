#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for F-25 `pyble_fs` — the rpi-pico2-w portable filesystem
# bridge + workspace jail (the frozen-Python twin of the C reference
# firmware/user_c_modules/pyble/pble_fs.c). Sole [red] author:
# firmware-test-author. Production module owner (HAND-OFF for [green]):
# agent-engineer -> firmware/pyble/pyble_fs.py (plan C8).
#
# FROZEN references (authoritative — these tests transliterate them):
#   protocol.md §5  — FILE_* wire (LIST/STAT/GET/windowed PUT/DELETE/MKDIR/
#                     RENAME), Go-Back-N + cumulative ACK, resume-on-reconnect,
#                     workspace jail, exactly ONE active transfer (PUT or GET).
#   protocol.md §8  — 1-byte status set.
#   ports/rpi-pico2-w.md P2 (mailboxed GET/PUT), P5 (/pyble_conf.json shielded
#   by the reserved top-level `pyble` prefix), P6 (path ≤ 128 → ERANGE).
#   C reference invariants: pble_fs.c pble_fs_resolve / fs_reserved_prefix /
#   fs_has_tmp_suffix / pble_fs_errno_to_status / fs_do_* / fs_put_* /
#   pble_fs_resume_prefix / pble_fs_on_disconnect.
#
# Tests run over a host tmpdir root under CPython (tests/firmware_tests
# convention: wrapper test_pyble_fs.sh -> this file). No bluetooth/machine
# surface is touched — pyble_fs is pure os.* + injected seams.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (agent-engineer implements to it):
#
#   pyble_fs.FS_PATH_MAX : int == 128      # §5 max path bytes on the wire
#   pyble_fs.TMP_SUFFIX  : str == ".pbltmp"
#   pyble_fs.RSP_MAX     : int == 480      # LIST truncation budget (C twin)
#
#   pyble_fs.errno_to_status(e: int) -> int
#       # the FR-FS-15 errno -> §8 map (pble_fs_errno_to_status twin), incl.
#       # ENOTEMPTY -> EACCES and EEXIST -> EBADREQ; unclassified -> EIO.
#
#   pyble_fs.resolve(path: bytes) -> (status: int, jailed: str | None)
#       # THE single jail chokepoint (pble_fs_resolve twin). On OK returns the
#       # canonical root-relative absolute path ("/a/b"); else (status, None).
#       # empty/NUL -> EBADREQ; > FS_PATH_MAX bytes -> ERANGE; ".." escape,
#       # ".pbltmp" component suffix, reserved TOP-LEVEL prefixes
#       # (pyble*/pble*/_boot.py/boot.py) -> EACCES. Canonicalize FIRST, then
#       # check (a/../pyble_conf.json is still caught).
#
#   pyble_fs.FsService(root: str, emit, chunk_size: int = 229, open_fn=None)
#       # root     = host/vfs directory the jail maps "/" onto (tmpdir here).
#       # emit     = callable(opcode: int, payload: bytes) — EVT seam (id 0):
#       #            FILE_GET_DATA 0x13, FILE_GET_END 0x14, FILE_PUT_ACK 0x41.
#       # chunk_size = max DATA bytes per FILE_GET_DATA EVT (mtu-18 on device).
#       # open_fn  = file-open seam (path, mode) -> file-like; None = builtin
#       #            open. Modes used: "rb" / "wb" / "ab" (the C trio).
#       #
#       # Handlers take the CMD payload bytes and return the RSP payload
#       # (payload[0] = §8 status) — pyble_agent wires them into Dispatcher and
#       # owns RSP-before-EVT wire ordering (it emits the returned RSP, then
#       # calls pump()). handle_put_data returns None (no RSP, ACK-only).
#       #   .handle_list(payload)      -> bytes  # [st][more][count:u16]{...}
#       #   .handle_stat(payload)      -> bytes  # [st][size:u32][crc32:u32]
#       #   .handle_get_begin(payload) -> bytes  # [st](+[total:u32]); on OK
#       #                                        # the GET becomes the ACTIVE
#       #                                        # transfer (mailboxed, P2)
#       #   .pump()                    -> None   # drain the active GET: emits
#       #                                        # DATA* then END, clears the
#       #                                        # active transfer; no-op idle
#       #   .handle_put_begin(payload) -> bytes  # [st](+[resume_offset:u32])
#       #   .handle_put_data(payload)  -> None   # Go-Back-N; emits PUT_ACK
#       #   .handle_put_end(payload)   -> bytes  # [st]
#       #   .handle_delete(payload)    -> bytes  # [st]
#       #   .handle_mkdir(payload)     -> bytes  # [st]
#       #   .handle_rename(payload)    -> bytes  # [st]
#       #   .on_disconnect()           -> None   # reset in-RAM transfer state;
#       #                                        # KEEP <dest>.pbltmp on disk
#       #                                        # (F-10 resume contract)
# ---------------------------------------------------------------------------

import errno
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

import pyble_proto  # noqa: E402  (existing frozen scaffold — the CRC reference)

FS = _support.RedReason("pyble_fs", owner="agent-engineer")

# §8 statuses (FROZEN).
OK, EBADREQ, ENOENT, EACCES, ENOSPC, EIO = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ENOMEM, EBUSY, ECRC, ERANGE = 0x06, 0x07, 0x08, 0x09

# §4 EVT opcodes on the emit seam (FROZEN).
OP_GET_DATA, OP_GET_END, OP_PUT_ACK = 0x13, 0x14, 0x41

# MicroPython/LFS numeric for ENOTEMPTY (pble_fs.c names it 39 explicitly —
# the on-device value the map MUST cover in addition to the host's errno).
MP_ENOTEMPTY = 39

crc32 = pyble_proto.crc32


def p16(n):
    return struct.pack("<H", n)


def p32(n):
    return struct.pack("<I", n)


def u16(b, o=0):
    return int.from_bytes(b[o:o + 2], "little")


def u32(b, o=0):
    return int.from_bytes(b[o:o + 4], "little")


def path_pl(path):
    b = path if isinstance(path, bytes) else path.encode("utf-8")
    return p16(len(b)) + b


def get_begin_pl(offset, path):
    return p32(offset) + path_pl(path)


def put_begin_pl(total, crc, path):
    return p32(total) + p32(crc) + path_pl(path)


def put_data_pl(offset, data):
    return p32(offset) + data


def rename_pl(src, dst):
    return path_pl(src) + path_pl(dst)


class _QuotaFile:
    """open_fn seam wrapper: a temp file whose writes fail with ENOSPC once a
    byte quota is exceeded (drives the C latched-write-error path on a host)."""

    def __init__(self, f, quota):
        self._f = f
        self._quota = quota
        self._wrote = 0

    def write(self, b):
        if self._wrote + len(b) > self._quota:
            raise OSError(errno.ENOSPC, "quota exceeded")
        self._f.write(b)
        self._wrote += len(b)
        return len(b)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()
        return False

    def __getattr__(self, name):
        return getattr(self._f, name)


class FsTestBase(unittest.TestCase):
    """Shared tmpdir root + FsService/emit-recorder factory."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pyble_fs_red_")
        self.addCleanup(shutil.rmtree, self.root, True)

    # -- host-side helpers over the tmpdir root -------------------------------
    def hpath(self, rel):
        return os.path.join(self.root, rel.lstrip("/"))

    def put_file(self, rel, data):
        p = self.hpath(rel)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def read_file(self, rel):
        with open(self.hpath(rel), "rb") as fh:
            return fh.read()

    # -- pinned-interface factories -------------------------------------------
    def svc(self, criterion, **kw):
        cls = FS.attr(self, "FsService", criterion)
        rec = []

        def emit(opcode, payload):
            rec.append((int(opcode), bytes(payload)))

        return cls(self.root, emit, **kw), rec

    def resolve_fn(self, criterion):
        return FS.attr(self, "resolve", criterion)

    def errno_fn(self, criterion):
        return FS.attr(self, "errno_to_status", criterion)

    # -- EVT recorder queries --------------------------------------------------
    @staticmethod
    def evts(rec, opcode):
        return [pl for (op, pl) in rec if op == opcode]

    def acks(self, rec):
        out = []
        for pl in self.evts(rec, OP_PUT_ACK):
            self.assertEqual(len(pl), 4, "FILE_PUT_ACK payload MUST be exactly [ack_offset:u32]")
            out.append(u32(pl))
        return out

    # -- composite drivers -----------------------------------------------------
    def begin_put(self, s, dest, data, declared_crc=None, total=None):
        total = len(data) if total is None else total
        crc = crc32(data) if declared_crc is None else declared_crc
        return s.handle_put_begin(put_begin_pl(total, crc, dest))

    def send_put(self, s, data, start=0, chunk=100):
        for off in range(start, len(data), chunk):
            s.handle_put_data(put_data_pl(off, data[off:off + chunk]))

    def parse_list(self, rsp):
        self.assertEqual(rsp[0], OK)
        more, count = rsp[1], u16(rsp, 2)
        entries = []
        o = 4
        for _ in range(count):
            etype = rsp[o]
            esize = u32(rsp, o + 1)
            nlen = u16(rsp, o + 5)
            name = rsp[o + 7:o + 7 + nlen].decode("utf-8")
            self.assertEqual(nlen, len(name.encode("utf-8")))
            entries.append((etype, esize, name))
            o += 7 + nlen
        self.assertEqual(o, len(rsp), "LIST payload MUST contain exactly `count` packed entries")
        return more, count, entries


# ============================================================================
# Module constants
# ============================================================================
class ModuleConstantsTest(FsTestBase):
    """§5 / P6 frozen bounds carried as module constants (C twin macros)."""

    def test_path_max_is_128(self):
        self.assertEqual(FS.attr(self, "FS_PATH_MAX", "F-25/§5 path max = 128 bytes"), 128)

    def test_tmp_suffix(self):
        self.assertEqual(FS.attr(self, "TMP_SUFFIX", "F-25/§5 reserved temp suffix"), ".pbltmp")

    def test_rsp_max_is_480(self):
        self.assertEqual(FS.attr(self, "RSP_MAX", "F-25 LIST truncation budget = 480"), 480)


# ============================================================================
# errno -> §8 status map (FR-FS-15, pble_fs_errno_to_status twin)
# ============================================================================
class ErrnoMapTest(FsTestBase):
    def test_frozen_map(self):
        fn = self.errno_fn("F-25/FR-FS-15 errno map")
        cases = [
            (errno.ENOENT, ENOENT), (errno.ENOTDIR, ENOENT),
            (errno.EACCES, EACCES), (errno.EPERM, EACCES),
            (errno.EROFS, EACCES), (errno.EISDIR, EACCES),
            (errno.ENOSPC, ENOSPC), (errno.ENOMEM, ENOMEM),
            (errno.EINVAL, ERANGE), (errno.ERANGE, ERANGE),
            (errno.EIO, EIO),
        ]
        for e, want in cases:
            self.assertEqual(fn(e), want,
                             "errno %d MUST map to §8 status 0x%02x" % (e, want))

    def test_enotempty_maps_to_eacces(self):
        fn = self.errno_fn("F-25/FR-FS-15 ENOTEMPTY -> EACCES")
        self.assertEqual(fn(errno.ENOTEMPTY), EACCES,
                         "host ENOTEMPTY MUST map to EACCES (non-empty dir delete/rename)")
        self.assertEqual(fn(MP_ENOTEMPTY), EACCES,
                         "the MicroPython/LFS ENOTEMPTY numeric (39) MUST also map to EACCES")

    def test_eexist_maps_to_ebadreq(self):
        fn = self.errno_fn("F-25/FR-FS-15 EEXIST -> EBADREQ")
        self.assertEqual(fn(errno.EEXIST), EBADREQ)

    def test_unclassified_maps_to_eio(self):
        fn = self.errno_fn("F-25/FR-FS-15 unclassified -> EIO")
        self.assertEqual(fn(9999), EIO, "an unclassified errno MUST fall back to EIO")


# ============================================================================
# The jail chokepoint — pyble_fs.resolve (F-17/SEC-4, pble_fs_resolve twin)
# ============================================================================
class JailResolveTest(FsTestBase):
    def test_plain_path_canonicalized(self):
        fn = self.resolve_fn("F-25/F-17 canonical join")
        self.assertEqual(fn(b"a//b/./c"), (OK, "/a/b/c"))

    def test_root_path_ok(self):
        fn = self.resolve_fn("F-25/F-17 '/' resolves to root")
        self.assertEqual(fn(b"/"), (OK, "/"))

    def test_interior_dotdot_pops(self):
        fn = self.resolve_fn("F-25/F-17 interior '..' pops, stays jailed")
        self.assertEqual(fn(b"a/../b"), (OK, "/b"))

    def test_dotdot_escape_is_eacces(self):
        fn = self.resolve_fn("F-25/F-17 '..' escape -> EACCES")
        for p in (b"..", b"../etc/passwd", b"a/../../b", b"/.."):
            st, jailed = fn(p)
            self.assertEqual(st, EACCES, "%r MUST be rejected EACCES (traversal escape)" % p)
            self.assertIsNone(jailed)

    def test_empty_path_is_ebadreq(self):
        fn = self.resolve_fn("F-25/F-17 empty path -> EBADREQ")
        self.assertEqual(fn(b""), (EBADREQ, None))

    def test_embedded_nul_is_ebadreq(self):
        fn = self.resolve_fn("F-25/F-17 embedded NUL -> EBADREQ")
        st, jailed = fn(b"a\x00b")
        self.assertEqual(st, EBADREQ, "NUL injection MUST be rejected EBADREQ")
        self.assertIsNone(jailed)

    def test_over_128_bytes_is_erange(self):
        fn = self.resolve_fn("F-25/P6 path > 128 bytes -> ERANGE")
        st, jailed = fn(b"a/" * 65)  # 130 wire bytes (canonical form is short)
        self.assertEqual(st, ERANGE,
                         "the WIRE length (not the canonical length) is the §5 bound")
        self.assertIsNone(jailed)

    def test_exactly_128_bytes_ok(self):
        fn = self.resolve_fn("F-25/P6 path == 128 bytes accepted")
        p = b"d/" + b"x" * 126
        self.assertEqual(len(p), 128)
        st, jailed = fn(p)
        self.assertEqual(st, OK)
        self.assertEqual(jailed, "/d/" + "x" * 126)

    def test_pbltmp_suffix_component_is_eacces(self):
        fn = self.resolve_fn("F-25/§5 reserved .pbltmp suffix -> EACCES")
        for p in (b"x.pbltmp", b"a/b.pbltmp", b"d.pbltmp/y"):
            st, jailed = fn(p)
            self.assertEqual(st, EACCES,
                             "%r MUST be rejected EACCES (reserved transfer-scratch suffix)" % p)
            self.assertIsNone(jailed)

    def test_reserved_top_level_prefixes_are_eacces(self):
        fn = self.resolve_fn("F-25/P5 reserved agent prefixes -> EACCES")
        for p in (b"pyble_conf.json", b"/pyble_conf.json", b"pyble_agent.py",
                  b"pyblex", b"pble_anything", b"pble", b"_boot.py", b"boot.py",
                  b"pyble/nested.txt"):
            st, jailed = fn(p)
            self.assertEqual(st, EACCES,
                             "%r MUST be rejected EACCES (reserved top-level prefix)" % p)
            self.assertIsNone(jailed)

    def test_dotdot_cannot_reach_reserved_names(self):
        # Canonicalize FIRST, then check: a/../pyble_conf.json == /pyble_conf.json.
        fn = self.resolve_fn("F-25/P5 canonicalize-then-check (no .. bypass)")
        st, jailed = fn(b"a/../pyble_conf.json")
        self.assertEqual(st, EACCES,
                         "'..' MUST NOT smuggle a path onto a reserved top-level name")
        self.assertIsNone(jailed)

    def test_reserved_check_is_top_level_only(self):
        # C twin: fs_reserved_prefix() is applied to parts[0] ONLY.
        fn = self.resolve_fn("F-25/P5 reserved prefixes bind to the TOP level only")
        self.assertEqual(fn(b"lib/pyble_helper.py"), (OK, "/lib/pyble_helper.py"))
        self.assertEqual(fn(b"sub/boot.py"), (OK, "/sub/boot.py"))

    def test_boot_py_is_exact_match(self):
        fn = self.resolve_fn("F-25/P5 boot.py reservation is exact-name")
        self.assertEqual(fn(b"boot.py.bak"), (OK, "/boot.py.bak"))


class JailChokepointAcrossOpsTest(FsTestBase):
    """P5: /pyble_conf.json (and every jailed path) is unreachable via EVERY
    FILE_* op — the resolve chokepoint is unbypassable (SEC-4)."""

    def each_single_path_op(self, s):
        return [
            ("FILE_LIST", lambda p: s.handle_list(path_pl(p))),
            ("FILE_STAT", lambda p: s.handle_stat(path_pl(p))),
            ("FILE_GET_BEGIN", lambda p: s.handle_get_begin(get_begin_pl(0, p))),
            ("FILE_PUT_BEGIN", lambda p: s.handle_put_begin(put_begin_pl(4, crc32(b"data"), p))),
            ("FILE_DELETE", lambda p: s.handle_delete(path_pl(p))),
            ("MKDIR", lambda p: s.handle_mkdir(path_pl(p))),
            ("FILE_RENAME src", lambda p: s.handle_rename(rename_pl(p, b"ok.txt"))),
            ("FILE_RENAME dst", lambda p: s.handle_rename(rename_pl(b"exists.txt", p))),
        ]

    def test_pyble_conf_json_unreachable_via_every_op(self):
        s, rec = self.svc("F-25/P5 /pyble_conf.json shielded from every FILE_* op")
        # The conf REALLY exists on the vfs — and must still be invisible.
        self.put_file("/pyble_conf.json", b'{"label": "x", "autorun": 0}')
        self.put_file("/exists.txt", b"src")
        for name, op in self.each_single_path_op(s):
            rsp = op(b"/pyble_conf.json")
            self.assertEqual(rsp[0], EACCES,
                             "%s over /pyble_conf.json MUST be EACCES" % name)
        self.assertEqual(self.read_file("/pyble_conf.json"),
                         b'{"label": "x", "autorun": 0}',
                         "the conf MUST be untouched after every attempt")
        self.assertEqual(rec, [], "a jailed request MUST emit no EVT")

    def test_traversal_rejected_via_every_op(self):
        s, _rec = self.svc("F-25/F-17 '..' escape rejected at every FILE_* op")
        self.put_file("/exists.txt", b"src")
        for name, op in self.each_single_path_op(s):
            rsp = op(b"../outside")
            self.assertEqual(rsp[0], EACCES, "%s with '..' MUST be EACCES" % name)


# ============================================================================
# FILE_LIST (0x10) — [more][count]{etype,esize,nlen,name} (fs_do_list twin)
# ============================================================================
class ListTest(FsTestBase):
    def test_layout_and_entries(self):
        s, _rec = self.svc("F-25/§5 LIST layout [more][count]{etype,esize,nlen,name}")
        self.put_file("/a.py", b"print(1)\n")
        self.put_file("/big.bin", b"\x00" * 300)
        os.mkdir(self.hpath("/sub"))
        more, count, entries = self.parse_list(s.handle_list(path_pl(b"/")))
        self.assertEqual(more, 0, "an un-truncated listing MUST carry more=0")
        self.assertEqual(count, 3)
        by_name = dict((n, (t, sz)) for (t, sz, n) in entries)
        self.assertEqual(by_name["a.py"], (0, 9), "files: etype=0, esize=stat size")
        self.assertEqual(by_name["big.bin"], (0, 300))
        self.assertEqual(by_name["sub"], (1, 0), "dirs: etype=1, esize=0 (C twin)")

    def test_missing_dir_is_enoent(self):
        s, _rec = self.svc("F-25/§5 LIST missing dir -> ENOENT")
        self.assertEqual(s.handle_list(path_pl(b"/nope"))[0], ENOENT)

    def test_list_of_a_file_is_enoent(self):
        # ENOTDIR maps to ENOENT (FR-FS-15).
        s, _rec = self.svc("F-25/FR-FS-15 LIST of a file -> ENOENT")
        self.put_file("/f.txt", b"x")
        self.assertEqual(s.handle_list(path_pl(b"/f.txt"))[0], ENOENT)

    def test_truncation_sets_more(self):
        s, _rec = self.svc("F-25/§5 LIST truncated to RSP_MAX -> more=1")
        names = ["file_%02d_%s.txt" % (i, "n" * 12) for i in range(40)]
        for n in names:
            self.put_file("/" + n, b"z")
        rsp = s.handle_list(path_pl(b"/"))
        self.assertLessEqual(len(rsp), 480,
                             "a LIST RSP payload MUST fit the 480-byte budget")
        more, count, entries = self.parse_list(rsp)
        self.assertEqual(more, 1, "a truncated listing MUST set more=1")
        self.assertLess(count, 40)
        self.assertGreater(count, 0)
        for _t, _sz, n in entries:
            self.assertIn(n, names, "every listed entry MUST be a real one")

    def test_malformed_payload_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 malformed LIST payload -> EBADREQ")
        self.assertEqual(s.handle_list(b"")[0], EBADREQ)
        self.assertEqual(s.handle_list(b"\x05")[0], EBADREQ)
        # plen overruns the payload
        self.assertEqual(s.handle_list(p16(10) + b"ab")[0], EBADREQ)


# ============================================================================
# FILE_STAT (0x11) — [size][whole-file crc] (fs_do_stat twin)
# ============================================================================
class StatTest(FsTestBase):
    def test_file_layout_size_and_crc(self):
        s, _rec = self.svc("F-25/§5 STAT [size:u32][crc32:u32]")
        data = bytes(range(256)) * 3
        self.put_file("/d.bin", data)
        rsp = s.handle_stat(path_pl(b"/d.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(len(rsp), 9, "STAT RSP payload MUST be [st][size:4][crc:4]")
        self.assertEqual(u32(rsp, 1), len(data))
        self.assertEqual(u32(rsp, 5), crc32(data), "STAT crc MUST be the whole-file CRC-32")

    def test_dir_stat_has_zero_crc(self):
        s, _rec = self.svc("F-25/§5 STAT of a dir -> crc 0 (C twin)")
        os.mkdir(self.hpath("/sub"))
        rsp = s.handle_stat(path_pl(b"/sub"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 5), 0)

    def test_missing_is_enoent(self):
        s, _rec = self.svc("F-25/FR-FS-2 STAT missing -> ENOENT")
        self.assertEqual(s.handle_stat(path_pl(b"/nope.txt"))[0], ENOENT)

    def test_malformed_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 malformed STAT payload -> EBADREQ")
        self.assertEqual(s.handle_stat(b"\x01")[0], EBADREQ)
        self.assertEqual(s.handle_stat(p16(9) + b"short")[0], EBADREQ)


# ============================================================================
# FILE_GET (0x12/0x13/0x14) — streaming + whole-file CRC (fs_do_get twin)
# ============================================================================
class GetStreamTest(FsTestBase):
    def drain(self, s, rec):
        s.pump()
        return self.evts(rec, OP_GET_DATA), self.evts(rec, OP_GET_END)

    def test_full_get_chunks_and_whole_file_crc(self):
        data = bytes((i * 7) & 0xFF for i in range(20))
        self.put_file("/f.bin", data)
        s, rec = self.svc("F-25/§5 GET streams one-chunk DATA + END[whole crc]",
                          chunk_size=8)
        rsp = s.handle_get_begin(get_begin_pl(0, b"/f.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 20, "GET_BEGIN RSP{OK} MUST carry [total_size:u32]")
        datas, ends = self.drain(s, rec)
        offs = [u32(pl) for pl in datas]
        lens = [len(pl) - 4 for pl in datas]
        self.assertEqual(offs, [0, 8, 16], "DATA offsets MUST advance by chunk_size")
        self.assertEqual(lens, [8, 8, 4])
        self.assertEqual(b"".join(pl[4:] for pl in datas), data)
        self.assertEqual(len(ends), 1, "exactly one FILE_GET_END MUST be emitted")
        self.assertEqual(u32(ends[0]), crc32(data), "END crc MUST cover the WHOLE file")

    def test_offset_get_crc_still_from_byte_zero(self):
        data = bytes((255 - i) & 0xFF for i in range(40))
        self.put_file("/g.bin", data)
        s, rec = self.svc("F-25/§5 offset-GET: CRC from byte 0, data from offset",
                          chunk_size=16)
        rsp = s.handle_get_begin(get_begin_pl(5, b"/g.bin"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 40)
        datas, ends = self.drain(s, rec)
        self.assertEqual(u32(datas[0]), 5, "the first DATA MUST start at the requested offset")
        pos = 5
        for pl in datas:
            self.assertEqual(u32(pl), pos, "DATA MUST be contiguous from the offset")
            self.assertLessEqual(len(pl) - 4, 16, "every DATA MUST fit one chunk")
            pos += len(pl) - 4
        self.assertEqual(b"".join(pl[4:] for pl in datas), data[5:])
        self.assertEqual(u32(ends[0]), crc32(data),
                         "a skipped prefix MUST still be CRC'd (whole-file CRC from byte 0)")

    def test_offset_at_total_ok_no_data(self):
        data = b"0123456789"
        self.put_file("/h.bin", data)
        s, rec = self.svc("F-25/§5 GET offset==total -> OK, END only", chunk_size=8)
        rsp = s.handle_get_begin(get_begin_pl(10, b"/h.bin"))
        self.assertEqual(rsp[0], OK)
        datas, ends = self.drain(s, rec)
        self.assertEqual(datas, [])
        self.assertEqual(u32(ends[0]), crc32(data))

    def test_offset_past_total_is_erange(self):
        self.put_file("/h.bin", b"0123")
        s, rec = self.svc("F-25/§5 GET offset > total -> ERANGE")
        self.assertEqual(s.handle_get_begin(get_begin_pl(5, b"/h.bin"))[0], ERANGE)
        s.pump()
        self.assertEqual(rec, [], "a refused GET MUST stream nothing")

    def test_get_of_a_dir_is_eacces(self):
        os.mkdir(self.hpath("/sub"))
        s, _rec = self.svc("F-25/§5 GET of a dir -> EACCES")
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/sub"))[0], EACCES)

    def test_get_missing_is_enoent(self):
        s, _rec = self.svc("F-25/FR-FS-2 GET missing -> ENOENT")
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/nope"))[0], ENOENT)

    def test_empty_file_get(self):
        self.put_file("/empty", b"")
        s, rec = self.svc("F-25/§5 GET of an empty file -> total 0, END crc 0")
        rsp = s.handle_get_begin(get_begin_pl(0, b"/empty"))
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 0)
        datas, ends = self.drain(s, rec)
        self.assertEqual(datas, [])
        self.assertEqual(u32(ends[0]), crc32(b""))

    def test_malformed_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 malformed GET_BEGIN -> EBADREQ")
        self.assertEqual(s.handle_get_begin(b"\x00\x00\x00")[0], EBADREQ)
        self.assertEqual(s.handle_get_begin(p32(0) + p16(9) + b"x")[0], EBADREQ)


# ============================================================================
# FILE_PUT happy path (0x15/0x16/0x41/0x17) — fs_do_put_* twins
# ============================================================================
class PutHappyPathTest(FsTestBase):
    def test_full_upload_atomic_rename(self):
        data = bytes((i * 13) & 0xFF for i in range(500))
        self.put_file("/prog.py", b"OLD CONTENT")
        s, rec = self.svc("F-25/§5 PUT happy path: temp -> atomic rename")
        rsp = self.begin_put(s, b"/prog.py", data)
        self.assertEqual(rsp[0], OK)
        self.assertEqual(len(rsp), 5, "PUT_BEGIN RSP{OK} MUST carry [resume_offset:u32]")
        self.assertEqual(u32(rsp, 1), 0, "a fresh upload MUST report resume_offset 0")
        self.assertTrue(os.path.exists(self.hpath("/prog.py.pbltmp")),
                        "PUT_BEGIN MUST open the jailed <dest>.pbltmp temp")
        self.send_put(s, data, chunk=200)
        self.assertEqual(self.acks(rec), [200, 400, 500],
                         "each in-order PUT_DATA MUST advance + ACK the watermark")
        self.assertEqual(self.read_file("/prog.py"), b"OLD CONTENT",
                         "the live target MUST NOT change before PUT_END verifies")
        end = s.handle_put_end(p32(crc32(data)))
        self.assertEqual(end[0], OK)
        self.assertEqual(self.read_file("/prog.py"), data,
                         "on success the temp MUST be renamed onto dest atomically")
        self.assertFalse(os.path.exists(self.hpath("/prog.py.pbltmp")),
                         "on success the temp MUST be gone (renamed)")

    def test_upload_into_subdir(self):
        os.mkdir(self.hpath("/lib"))
        data = b"import os\n"
        s, _rec = self.svc("F-25/§5 PUT into a subdirectory")
        self.assertEqual(self.begin_put(s, b"/lib/m.py", data)[0], OK)
        self.send_put(s, data)
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/lib/m.py"), data)


# ============================================================================
# PUT Go-Back-N (dup re-ACK / gap drop / no reorder buffer)
# ============================================================================
class PutGoBackNTest(FsTestBase):
    def test_duplicate_offset_re_acks_idempotently(self):
        data = b"A" * 100 + b"B" * 100
        s, rec = self.svc("F-25/§5 dup PUT_DATA (< watermark) -> re-ACK, no double write")
        self.begin_put(s, b"/f.bin", data)
        s.handle_put_data(put_data_pl(0, data[:100]))
        s.handle_put_data(put_data_pl(0, data[:100]))      # duplicate
        s.handle_put_data(put_data_pl(100, data[100:]))
        self.assertEqual(self.acks(rec), [100, 100, 200],
                         "a duplicate MUST re-ACK the unchanged watermark")
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK,
                         "the duplicate MUST NOT corrupt the file or the running CRC")
        self.assertEqual(self.read_file("/f.bin"), data)

    def test_gap_offset_dropped_and_re_acked(self):
        data = b"x" * 300
        s, rec = self.svc("F-25/§5 gap PUT_DATA (> watermark) -> drop + re-ACK")
        self.begin_put(s, b"/g.bin", data)
        s.handle_put_data(put_data_pl(0, data[:100]))
        s.handle_put_data(put_data_pl(200, data[200:]))    # gap: 100..200 missing
        self.assertEqual(self.acks(rec), [100, 100],
                         "a gap chunk MUST be dropped and the watermark re-ACKed")
        # Go-Back-N: the app retransmits from the ACK.
        s.handle_put_data(put_data_pl(100, data[100:200]))
        s.handle_put_data(put_data_pl(200, data[200:]))
        self.assertEqual(self.acks(rec), [100, 100, 200, 300])
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/g.bin"), data)

    def test_malformed_put_data_re_acks(self):
        s, rec = self.svc("F-25/§5 malformed PUT_DATA -> idempotent re-ACK")
        self.begin_put(s, b"/m.bin", b"abcd")
        s.handle_put_data(b"\x00\x00")                     # shorter than [offset:u32]
        self.assertEqual(self.acks(rec), [0],
                         "a malformed PUT_DATA MUST re-ACK the watermark (no RSP path)")

    def test_put_data_without_active_transfer_is_silent(self):
        s, rec = self.svc("F-25/§5 PUT_DATA with no active transfer -> no ACK")
        self.assertIsNone(s.handle_put_data(put_data_pl(0, b"zz")))
        self.assertEqual(rec, [], "no transfer -> nothing to ack, nothing emitted")


# ============================================================================
# PUT failure paths — temp deleted + OLD FILE KEPT on EVERY failure (FR-FS-14)
# ============================================================================
class PutFailureTest(FsTestBase):
    OLD = b"OLD KEEPS"

    def assert_failed_clean(self, dest, temp_rel):
        self.assertEqual(self.read_file(dest), self.OLD,
                         "on EVERY failure the old file MUST be kept byte-for-byte")
        self.assertFalse(os.path.exists(self.hpath(temp_rel)),
                         "on EVERY failure the temp MUST be deleted")

    def test_end_with_short_transfer_is_erange(self):
        data = b"q" * 120
        self.put_file("/t.py", self.OLD)
        s, _rec = self.svc("F-25/§5 PUT_END watermark != total -> ERANGE")
        self.begin_put(s, b"/t.py", data)
        s.handle_put_data(put_data_pl(0, data[:60]))       # only half arrives
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], ERANGE)
        self.assert_failed_clean("/t.py", "/t.py.pbltmp")

    def test_end_with_bad_crc_is_ecrc(self):
        data = b"w" * 80
        self.put_file("/c.py", self.OLD)
        s, _rec = self.svc("F-25/§5 PUT_END crc mismatch -> ECRC, old kept")
        self.begin_put(s, b"/c.py", data, declared_crc=crc32(data) ^ 0xDEADBEEF)
        self.send_put(s, data)
        self.assertEqual(s.handle_put_end(p32(crc32(data) ^ 0xDEADBEEF))[0], ECRC)
        self.assert_failed_clean("/c.py", "/c.py.pbltmp")

    def test_latched_write_error_keeps_acking_end_reports_it(self):
        data = b"L" * 12
        self.put_file("/n.py", self.OLD)

        def open_fn(path, mode):
            f = open(path, mode)
            if ("w" in mode or "a" in mode) and path.endswith(".pbltmp"):
                return _QuotaFile(f, 6)                    # ENOSPC after 6 bytes
            return f

        s, rec = self.svc("F-25/§5 latched write error: ACKs continue, END reports",
                          open_fn=open_fn)
        self.begin_put(s, b"/n.py", data)
        s.handle_put_data(put_data_pl(0, data[:6]))        # fits the quota
        s.handle_put_data(put_data_pl(6, data[6:]))        # write raises -> latched
        s.handle_put_data(put_data_pl(6, data[6:]))        # retransmit: latched re-ACK
        self.assertEqual(self.acks(rec), [6, 6, 6],
                         "after a latched write error the watermark MUST stop but "
                         "ACKs MUST continue (END reports the failure)")
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], ENOSPC,
                         "PUT_END MUST report the LATCHED status (ENOSPC here)")
        self.assert_failed_clean("/n.py", "/n.py.pbltmp")

    def test_end_without_begin_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 PUT_END without BEGIN -> EBADREQ")
        self.assertEqual(s.handle_put_end(p32(0))[0], EBADREQ)

    def test_malformed_end_aborts(self):
        data = b"k" * 10
        self.put_file("/e.py", self.OLD)
        s, _rec = self.svc("F-25/§5 malformed PUT_END -> EBADREQ + abort")
        self.begin_put(s, b"/e.py", data)
        self.send_put(s, data)
        self.assertEqual(s.handle_put_end(b"\x01")[0], EBADREQ)
        self.assert_failed_clean("/e.py", "/e.py.pbltmp")

    def test_malformed_begin_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 malformed PUT_BEGIN -> EBADREQ")
        self.assertEqual(s.handle_put_begin(b"\x00" * 9)[0], EBADREQ)
        self.assertEqual(s.handle_put_begin(p32(4) + p32(0) + p16(20) + b"x")[0], EBADREQ)

    def test_mpy_pyc_artifacts_rejected(self):
        s, _rec = self.svc("F-25/FR-FS-12 .mpy/.pyc PUT dest -> EACCES")
        for dest in (b"/mod.mpy", b"/mod.pyc", b"/lib/deep.mpy"):
            rsp = s.handle_put_begin(put_begin_pl(4, crc32(b"data"), dest))
            self.assertEqual(rsp[0], EACCES,
                             "%r MUST be refused (.py/data only, no compiled artifacts)" % dest)


# ============================================================================
# Resume on reconnect (F-10) — temp kept, prefix re-CRC'd, watermark re-seeded
# ============================================================================
class PutResumeTest(FsTestBase):
    def test_disconnect_keeps_temp_and_resets_ram_state(self):
        data = b"R" * 300
        s, _rec = self.svc("F-25/F-10 disconnect keeps .pbltmp, resets RAM state")
        self.begin_put(s, b"/r.bin", data)
        s.handle_put_data(put_data_pl(0, data[:100]))
        s.on_disconnect()
        self.assertTrue(os.path.exists(self.hpath("/r.bin.pbltmp")),
                        "on_disconnect MUST NOT delete the temp (the durable watermark)")
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], EBADREQ,
                         "after a disconnect there is NO active transfer (END -> EBADREQ)")

    def test_resume_prefix_recrc_and_completion(self):
        data = bytes((i * 31) & 0xFF for i in range(400))
        self.put_file("/big.py", b"OLD")
        s, rec = self.svc("F-25/F-10 resume: prefix re-CRC seeds resume_offset")
        self.begin_put(s, b"/big.py", data)
        self.send_put(s, data[:100], chunk=50)             # 100 verified bytes land
        s.on_disconnect()

        rsp = self.begin_put(s, b"/big.py", data)          # same dest + total + crc
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 100,
                         "PUT_BEGIN after a drop MUST return resume_offset = temp length "
                         "(the re-CRC'd verified prefix)")
        del rec[:]
        self.send_put(s, data, start=100, chunk=100)       # only the remainder
        self.assertEqual(self.acks(rec), [200, 300, 400])
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK,
                         "the re-seeded running CRC MUST verify without a temp re-scan")
        self.assertEqual(self.read_file("/big.py"), data)
        self.assertFalse(os.path.exists(self.hpath("/big.py.pbltmp")))

    def test_foreign_prefix_fails_crc_old_kept(self):
        data = b"GOOD" * 25                                # 100 bytes
        self.put_file("/f.py", b"OLD")
        self.put_file("/f.py.pbltmp", b"EVIL" * 10)        # 40 foreign bytes on flash
        s, _rec = self.svc("F-25/F-10 foreign prefix -> ECRC at END, old kept")
        rsp = self.begin_put(s, b"/f.py", data)
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 40,
                         "the temp length IS the resume offset (CRC gates correctness later)")
        self.send_put(s, data, start=40)
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], ECRC,
                         "the whole-file CRC is the ONLY correctness gate: a foreign "
                         "prefix MUST fail ECRC")
        self.assertEqual(self.read_file("/f.py"), b"OLD")
        self.assertFalse(os.path.exists(self.hpath("/f.py.pbltmp")))

    def test_oversize_temp_restarts_from_zero(self):
        data = b"S" * 100
        self.put_file("/o.py.pbltmp", b"X" * 200)          # stale temp LONGER than total
        s, _rec = self.svc("F-25/F-10 temp_len > total -> truncate, resume 0")
        rsp = self.begin_put(s, b"/o.py", data)
        self.assertEqual(rsp[0], OK)
        self.assertEqual(u32(rsp, 1), 0,
                         "an over-size temp MUST be truncated: resume_offset 0")
        self.send_put(s, data)
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.read_file("/o.py"), data)


# ============================================================================
# Exactly one active transfer (§5) — *_BEGIN while one is active -> EBUSY
# ============================================================================
class SingleTransferEbusyTest(FsTestBase):
    def test_second_begin_while_put_active_is_ebusy(self):
        s, _rec = self.svc("F-25/§5 second *_BEGIN while a PUT is active -> EBUSY")
        self.put_file("/src.bin", b"stream me")
        self.begin_put(s, b"/a.bin", b"12345678")
        self.assertEqual(self.begin_put(s, b"/b.bin", b"other")[0], EBUSY,
                         "a second PUT_BEGIN while a PUT is active MUST be EBUSY")
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/src.bin"))[0], EBUSY,
                         "a GET_BEGIN while a PUT is active MUST be EBUSY")

    def test_begin_while_get_active_is_ebusy_until_pumped(self):
        data = b"D" * 64
        self.put_file("/d.bin", data)
        s, rec = self.svc("F-25/§5 *_BEGIN while a GET is active -> EBUSY", chunk_size=16)
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/d.bin"))[0], OK)
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/d.bin"))[0], EBUSY)
        self.assertEqual(self.begin_put(s, b"/p.bin", b"xy")[0], EBUSY)
        s.pump()                                           # stream completes
        self.assertEqual(u32(self.evts(rec, OP_GET_END)[0]), crc32(data))
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/d.bin"))[0], OK,
                         "after the GET completes a new transfer MUST be accepted")

    def test_transfer_allowed_after_put_end(self):
        data = b"z" * 8
        s, _rec = self.svc("F-25/§5 transfer slot freed by PUT_END")
        self.begin_put(s, b"/q.bin", data)
        self.send_put(s, data)
        self.assertEqual(s.handle_put_end(p32(crc32(data)))[0], OK)
        self.assertEqual(self.begin_put(s, b"/q2.bin", data)[0], OK)

    def test_jail_beats_ebusy(self):
        # C twin ordering: resolve is the FIRST gate — a jailed path is EACCES
        # even while a transfer is active (the chokepoint is unbypassable).
        s, _rec = self.svc("F-25/F-17 jail is checked before the busy gate")
        self.begin_put(s, b"/a.bin", b"1234")
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"../x"))[0], EACCES)

    def test_pump_without_active_get_is_a_noop(self):
        s, rec = self.svc("F-25/P2 pump() with no active GET is a no-op")
        s.pump()
        self.assertEqual(rec, [])

    def test_disconnect_frees_the_get_slot(self):
        self.put_file("/d.bin", b"D" * 32)
        s, _rec = self.svc("F-25/F-10 disconnect clears an active GET", chunk_size=16)
        self.assertEqual(s.handle_get_begin(get_begin_pl(0, b"/d.bin"))[0], OK)
        s.on_disconnect()
        self.assertEqual(self.begin_put(s, b"/p.bin", b"ok")[0], OK,
                         "after a disconnect the transfer slot MUST be free")


# ============================================================================
# DELETE / MKDIR / RENAME (0x18/0x19/0x1A) — fs_do_delete/mkdir/rename twins
# ============================================================================
class DeleteMkdirRenameTest(FsTestBase):
    def test_delete_file(self):
        s, _rec = self.svc("F-25/§5 DELETE a file")
        self.put_file("/gone.txt", b"x")
        self.assertEqual(s.handle_delete(path_pl(b"/gone.txt"))[0], OK)
        self.assertFalse(os.path.exists(self.hpath("/gone.txt")))

    def test_delete_empty_dir(self):
        s, _rec = self.svc("F-25/§5 DELETE an empty dir")
        os.mkdir(self.hpath("/empty"))
        self.assertEqual(s.handle_delete(path_pl(b"/empty"))[0], OK)
        self.assertFalse(os.path.exists(self.hpath("/empty")))

    def test_delete_non_empty_dir_is_eacces(self):
        s, _rec = self.svc("F-25/§5 DELETE non-empty dir -> EACCES (no recursion)")
        self.put_file("/full/child.txt", b"x")
        self.assertEqual(s.handle_delete(path_pl(b"/full"))[0], EACCES,
                         "ENOTEMPTY MUST surface as EACCES; no recursive delete")
        self.assertTrue(os.path.exists(self.hpath("/full/child.txt")))

    def test_delete_missing_is_enoent(self):
        s, _rec = self.svc("F-25/§5 DELETE missing -> ENOENT")
        self.assertEqual(s.handle_delete(path_pl(b"/nope"))[0], ENOENT)

    def test_mkdir_creates(self):
        s, _rec = self.svc("F-25/§5 MKDIR creates a dir")
        self.assertEqual(s.handle_mkdir(path_pl(b"/newdir"))[0], OK)
        self.assertTrue(os.path.isdir(self.hpath("/newdir")))

    def test_mkdir_existing_dir_is_idempotent_ok(self):
        s, _rec = self.svc("F-25/§5 MKDIR over an existing dir -> OK (idempotent)")
        os.mkdir(self.hpath("/have"))
        self.assertEqual(s.handle_mkdir(path_pl(b"/have"))[0], OK)

    def test_mkdir_over_a_file_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 MKDIR over an existing file -> EBADREQ")
        self.put_file("/f.txt", b"x")
        self.assertEqual(s.handle_mkdir(path_pl(b"/f.txt"))[0], EBADREQ)

    def test_mkdir_missing_parent_is_enoent(self):
        s, _rec = self.svc("F-25/§5 MKDIR with a missing parent -> ENOENT")
        self.assertEqual(s.handle_mkdir(path_pl(b"/no/such/deep"))[0], ENOENT)

    def test_rename_moves(self):
        s, _rec = self.svc("F-25/§5 RENAME moves a file")
        self.put_file("/a.txt", b"payload")
        os.mkdir(self.hpath("/sub"))
        self.assertEqual(s.handle_rename(rename_pl(b"/a.txt", b"/sub/b.txt"))[0], OK)
        self.assertFalse(os.path.exists(self.hpath("/a.txt")))
        self.assertEqual(self.read_file("/sub/b.txt"), b"payload")

    def test_rename_missing_src_is_enoent(self):
        s, _rec = self.svc("F-25/§5 RENAME missing src -> ENOENT")
        self.assertEqual(s.handle_rename(rename_pl(b"/nope", b"/x"))[0], ENOENT)

    def test_rename_onto_non_empty_dir_is_eacces(self):
        s, _rec = self.svc("F-25/FR-FS-15 RENAME onto a non-empty dir -> EACCES")
        self.put_file("/src.txt", b"s")
        self.put_file("/ne/child", b"c")
        self.assertEqual(s.handle_rename(rename_pl(b"/src.txt", b"/ne"))[0], EACCES)
        self.assertTrue(os.path.exists(self.hpath("/ne/child")))

    def test_rename_malformed_is_ebadreq(self):
        s, _rec = self.svc("F-25/§5 malformed RENAME -> EBADREQ")
        self.assertEqual(s.handle_rename(b"\x00")[0], EBADREQ)
        self.assertEqual(s.handle_rename(p16(3) + b"src")[0], EBADREQ)   # dst missing
        self.assertEqual(s.handle_rename(p16(3) + b"src" + p16(9) + b"x")[0], EBADREQ)


if __name__ == "__main__":
    unittest.main(verbosity=2)
