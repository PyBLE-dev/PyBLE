# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_fs — PBLE/1 filesystem bridge + workspace jail (rpi-pico2-w portable
# agent, plan C8). The frozen-Python twin of the C reference pble_fs.c,
# transliterated invariant-for-invariant. Clean-room vs protocol.md §5 (FROZEN)
# + ports/rpi-pico2-w.md P2/P5/P6:
#   F-08  read : FILE_LIST (0x10) / FILE_STAT (0x11) / FILE_GET_* (0x12/13/14)
#   F-09  write: windowed FILE_PUT_* (0x15/16/41/17) + DELETE/MKDIR/RENAME
#   F-17  jail : resolve() — the single, unbypassable vfs chokepoint (SEC-4)
#
# Reliability invariants (protocol.md §5 / FR-FS-9/14, pble_fs.c twins):
#   - Upload is temp-write-then-rename: PUT_BEGIN opens `<dest>.pbltmp`
#     (truncated unless resuming); PUT_END verifies watermark == total_size +
#     whole-file CRC, then close + rename(temp, dest) (atomic on LittleFS). On
#     ANY failure the temp is deleted and the OLD file is kept byte-for-byte —
#     the live target is never partially overwritten.
#   - Exactly one active transfer (PUT or GET). A second *_BEGIN while one is
#     active → EBUSY. The jail is checked FIRST (a jailed path is EACCES even
#     while busy — the chokepoint is unbypassable).
#   - `.py`/data only: .mpy/.pyc are never accepted as transfer artifacts.
#   - Resume on reconnect (F-10): a link drop leaves `<dest>.pbltmp` + its
#     on-flash length on storage (on_disconnect only resets in-RAM state). A
#     later FILE_PUT_BEGIN for the same dest re-derives the verified prefix
#     length from flash, re-seeds the running whole-file CRC over it, and
#     returns it as resume_offset so the app sends only the remaining bytes.
#     The whole-file CRC at PUT_END is the ONLY correctness gate (a bad/foreign
#     prefix → ECRC, old file kept). The running whole-file CRC is maintained
#     incrementally across PUT_DATA so PUT_END need not re-scan the temp
#     (NFR-PERF-2).
#
# Execution model (ports/rpi-pico2-w.md P2): pyble_agent defers every PUT step
# through its bounded supervisor mailbox, so these handlers and their VFS calls
# run only on the supervisor. GET_BEGIN validates + reserves inline, while the
# supervisor later calls pump() to emit DATA*/END. Other small filesystem
# operations retain their scheduled-context behavior.
#
# Injectable seams (host suite drives this without BLE):
#   emit(opcode, payload)  — EVT sink (id 0): FILE_GET_DATA 0x13,
#                            FILE_GET_END 0x14, FILE_PUT_ACK 0x41.
#   open_fn(path, mode)    — file-open seam ("rb"/"wb"/"ab"); None = builtin.
#
# MicroPython v1.28-safe AND CPython 3.9+ importable: os.* only, no shutil/
# pathlib/typing/dataclasses; bytes/int.from_bytes idioms.

import os

import pyble_proto

# --- Frozen bounds (protocol.md §5 / ports/rpi-pico2-w.md P6) -----------------
FS_PATH_MAX = 128          # max path bytes on the wire (§5), else ERANGE
TMP_SUFFIX = ".pbltmp"     # reserved transfer-scratch suffix (jailed)
RSP_MAX = 480              # LIST truncation budget (C twin PBLE_RSP_MAX)
FS_SAFETY_RESERVE = 65536  # bytes kept free after PUT admission (D11)

_READ_BLK = 256            # streaming read block (CRC/resume scans)
_UINT64_MAX = (1 << 64) - 1

# --- §8 statuses (single-sourced from the frozen proto table) -----------------
_ST = pyble_proto.STATUS
OK = _ST["OK"]
EBADREQ = _ST["EBADREQ"]
ENOENT = _ST["ENOENT"]
EACCES = _ST["EACCES"]
ENOSPC = _ST["ENOSPC"]
EIO = _ST["EIO"]
ENOMEM = _ST["ENOMEM"]
EBUSY = _ST["EBUSY"]
ECRC = _ST["ECRC"]
ERANGE = _ST["ERANGE"]

# --- §4 EVT opcodes on the emit seam ------------------------------------------
_OP_GET_DATA = pyble_proto.OPCODES["FILE_GET_DATA"]   # 0x13
_OP_GET_END = pyble_proto.OPCODES["FILE_GET_END"]     # 0x14
_OP_PUT_ACK = pyble_proto.OPCODES["FILE_PUT_ACK"]     # 0x41

_S_IFMT = 0xF000           # complete POSIX/MicroPython file-type field
_S_IFDIR = 0x4000
_S_IFREG = 0x8000


# --- Streaming IEEE CRC-32 (bit-identical to pyble_proto.crc32) ---------------
# Native fast path where available (CPython + rp2 MicroPython both ship
# binascii.crc32); pure fallback mirrors pble_fs.c crc32_update. Both take and
# return the FINALIZED (post-xor) form: continue with crc32_update(chunk, crc).
try:
    from binascii import crc32 as crc32_update  # crc32_update(data, crc=0)
except ImportError:
    def crc32_update(data, crc=0):
        c = crc ^ 0xFFFFFFFF
        for byte in data:
            c ^= byte
            for _ in range(8):
                if c & 1:
                    c = (c >> 1) ^ 0xEDB88320
                else:
                    c >>= 1
        return c ^ 0xFFFFFFFF


# --- Little-endian helpers ----------------------------------------------------
def _u16(b, o):
    return b[o] | (b[o + 1] << 8)


def _u32(b, o):
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)


def _p16(n):
    return bytes((n & 0xFF, (n >> 8) & 0xFF))


def _p32(n):
    return bytes((n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF, (n >> 24) & 0xFF))


def _oserrno(exc):
    """errno of an OSError on both CPython and MicroPython (args[0])."""
    args = exc.args
    if args and isinstance(args[0], int):
        return args[0]
    return 0


# ============================================================================
# errno -> §8 status map (FR-FS-15, pble_fs_errno_to_status twin)
# ============================================================================
# Seeded with the portable POSIX/newlib numerics (the on-device MicroPython
# values), then overlaid with the host platform's errno module so the same
# frozen module is correct under CPython on macOS/Linux and on rp2.
_ERRNO_STATUS = {
    2: ENOENT, 20: ENOENT,                       # ENOENT, ENOTDIR
    13: EACCES, 1: EACCES, 30: EACCES,           # EACCES, EPERM, EROFS
    21: EACCES,                                  # EISDIR
    28: ENOSPC, 12: ENOMEM,
    22: ERANGE, 34: ERANGE,                      # EINVAL, ERANGE
    17: EBADREQ,                                 # EEXIST
    5: EIO,
}
try:
    import errno as _errno

    for _name, _status in (
        ("ENOENT", ENOENT), ("ENOTDIR", ENOENT),
        ("EACCES", EACCES), ("EPERM", EACCES), ("EROFS", EACCES),
        ("EISDIR", EACCES), ("ENOTEMPTY", EACCES),
        ("ENOSPC", ENOSPC), ("ENOMEM", ENOMEM),
        ("EINVAL", ERANGE), ("ERANGE", ERANGE),
        ("EEXIST", EBADREQ),
        ("EIO", EIO),
    ):
        _val = getattr(_errno, _name, None)
        if _val is not None:
            _ERRNO_STATUS[_val] = _status
    del _name, _status, _val
except ImportError:
    pass
# The MicroPython/LFS ENOTEMPTY numeric (pble_fs.c names 39 explicitly) —
# non-empty dir delete/rename MUST surface as EACCES on device too.
_ERRNO_STATUS[39] = EACCES


def errno_to_status(e):
    """Map an errno to its §8 status; unclassified → EIO (FR-FS-15)."""
    return _ERRNO_STATUS.get(e, EIO)


# ============================================================================
# resolve() — the single jail chokepoint (F-17 / SEC-4, pble_fs_resolve twin)
# ============================================================================
def _reserved_prefix(component):
    """Reserved agent prefixes on the TOP-LEVEL component (P5 / FR-FS-11):
    the frozen agent modules + /pyble_conf.json + boot scaffolds can never be
    shadowed, read, or replaced via PBLE/1."""
    return (component.startswith("pyble") or component.startswith("pble")
            or component == "_boot.py" or component == "boot.py")


def resolve(path):
    """Canonicalize + jail a wire path. Returns (status, jailed) where jailed
    is the canonical root-relative absolute path ("/a/b") on OK, else None.

    empty → EBADREQ; > FS_PATH_MAX WIRE bytes → ERANGE; embedded NUL →
    EBADREQ; ".." escape, ".pbltmp" component suffix, reserved TOP-LEVEL
    prefixes → EACCES. Canonicalize FIRST, then check reserved names
    (a/../pyble_conf.json is still caught)."""
    path = bytes(path)
    if len(path) == 0:
        return (EBADREQ, None)
    if len(path) > FS_PATH_MAX:
        return (ERANGE, None)           # the WIRE length is the §5 bound
    for byte in path:
        if byte == 0:
            return (EBADREQ, None)      # NUL injection
    text = pyble_proto.strict_utf8_decode(path)
    if text is None:
        return (EBADREQ, None)

    # Canonicalize: split on '/', drop ''/'.', pop on '..' (never above root).
    parts = []
    for tok in text.split("/"):
        if tok == "" or tok == ".":
            continue
        if tok == "..":
            if not parts:
                return (EACCES, None)   # traversal escape outside fs_root
            parts.pop()
            continue
        if tok.endswith(TMP_SUFFIX):
            return (EACCES, None)       # reserved transfer-scratch suffix
        parts.append(tok)
    if parts and _reserved_prefix(parts[0]):
        return (EACCES, None)           # reserved agent prefix (top level only)
    return (OK, "/" + "/".join(parts))


def _forbidden_artifact(jailed):
    """.mpy/.pyc are never accepted as transfer artifacts (FR-FS-12)."""
    return jailed.endswith(".mpy") or jailed.endswith(".pyc")


# ============================================================================
# FsService — handlers 0x10..0x1A + windowed PUT emitting FILE_PUT_ACK EVTs
# ============================================================================
class FsService:
    """Filesystem bridge over an injectable root. Handlers take the CMD
    payload bytes and return the RSP payload (payload[0] = §8 status);
    handle_put_data returns None (ACK-only, no RSP path)."""

    def __init__(self, root, emit, chunk_size=229, open_fn=None,
                 statvfs_fn=None):
        root = root or "/"
        if root != "/" and root.endswith("/"):
            root = root[:-1]
        self._root = root
        self._emit = emit
        self._chunk = chunk_size
        self._open = open_fn if open_fn is not None else open
        self._statvfs = (statvfs_fn if statvfs_fn is not None
                         else getattr(os, "statvfs", None))
        self._transfer_generation = 0
        self._operation_generation = None
        self._operation_session = None
        # Active-GET mailbox slot (P2):
        # (host_path, offset, advertised_total, generation, session) or None.
        self._get = None
        # PUT state machine (worker-local twin of pble_fs.c g_put_*). The open
        # temp file object is kept separate from resettable state. The
        # synchronous BLE disconnect callback clears only RAM ownership; the
        # next worker-context PUT_BEGIN closes the old object before scanning
        # its durable resumable prefix.
        self._put_file = None
        self._reset_put()

    # -- state helpers ---------------------------------------------------------
    def generation_token(self):
        return self._transfer_generation

    def set_operation_owner(self, generation, session):
        """Install the immutable owner of one supervisor mailbox item."""
        self._operation_generation = generation
        self._operation_session = session

    def clear_operation_owner(self):
        self._operation_generation = None
        self._operation_session = None

    def _operation_valid(self):
        generation = self._operation_generation
        return (generation is None or
                generation == self._transfer_generation)

    def _owner_generation(self):
        generation = self._operation_generation
        return (self._transfer_generation if generation is None else generation)

    def _put_owned(self):
        if not self._put_active or not self._operation_valid():
            return False
        return (self._put_generation == self._owner_generation() and
                self._put_session == self._operation_session)

    def _reconcile_stale_put(self):
        """Make a disconnected predecessor inert before successor admission.

        The old stream remains in ``_put_file`` and is closed in this same
        supervisor operation before any resume scan. No VFS call occurs here.
        """
        if (self._put_active and
                self._put_generation != self._transfer_generation):
            self._reset_put()

    def _reset_put(self):
        self._put_active = False
        self._put_temp = None       # host path of "<dest>.pbltmp"
        self._put_dest = None       # host path of the final destination
        self._put_total = 0
        self._put_crc_target = 0
        self._put_watermark = 0     # highest contiguous byte written
        self._put_crc_run = 0       # streaming whole-file CRC (finalized form)
        self._put_latched = 0       # 0, or a latched §8 write status
        self._put_generation = None
        self._put_session = None

    def _close_put_file(self):
        f = self._put_file
        if f is None:
            return OK
        self._put_file = None
        try:
            f.close()               # flush to storage (fsync on LittleFS close)
        except Exception:
            return EIO
        return OK

    def _abort_put(self, originating_status):
        """Abort the exactly owned PUT and return its authoritative status.

        Cleanup failure overrides the originating protocol/write status with
        EIO.  If ownership becomes stale during a VFS call, the caller emits no
        response and never clears successor state.
        """
        if not self._put_owned():
            return None
        generation = self._put_generation
        session = self._put_session
        temp = self._put_temp
        close_status = self._close_put_file()
        if (not self._operation_valid() or not self._put_active or
                self._put_generation != generation or
                self._put_session != session):
            return None
        cleanup_status = self._remove_scratch(
            temp, valid=self._put_owned)
        if cleanup_status is None or not self._put_owned():
            return None
        self._reset_put()
        if close_status != OK or cleanup_status != OK:
            return EIO
        return originating_status

    def _busy(self):
        return self._put_active or self._get is not None

    def _emit_owned(self, opcode, payload, session):
        if session is None:
            return self._emit(opcode, payload)
        return self._emit(opcode, payload, session)

    def _host(self, jailed):
        """Map a canonical jailed path onto the injected root."""
        root = self._root
        if root == "/":
            return jailed
        if jailed == "/":
            return root
        return root + jailed

    def _stat(self, hpath):
        """(status, size, isdir) — missing → ENOENT (FR-FS-2)."""
        try:
            st = os.stat(hpath)
        except OSError as exc:
            return (errno_to_status(_oserrno(exc)), 0, False)
        return (OK, st[6], (st[0] & _S_IFDIR) != 0)

    def _crc_file(self, hpath, expected):
        """CRC exactly the stat-advertised extent, rejecting hostile reads."""
        try:
            f = self._open(hpath, "rb")
        except OSError as exc:
            return (errno_to_status(_oserrno(exc)), 0)
        except Exception:
            return (EIO, 0)
        crc = 0
        status = OK
        try:
            remaining = expected
            while remaining > 0:
                want = _READ_BLK if remaining > _READ_BLK else remaining
                block = f.read(want)
                if (type(block) is not bytes or len(block) == 0 or
                        len(block) > want):
                    status = EIO
                    break
                crc = crc32_update(block, crc)
                remaining -= len(block)
        except OSError as exc:
            status = errno_to_status(_oserrno(exc))
        except Exception:
            status = EIO
        finally:
            try:
                f.close()
            except Exception:
                status = EIO
        if status != OK:
            return (status, 0)
        return (OK, crc)

    @staticmethod
    def _parse_path(payload, off):
        """[plen:u16][path] at `off` → (path_bytes | None, next_off)."""
        if len(payload) < off + 2:
            return (None, 0)
        plen = _u16(payload, off)
        if off + 2 + plen > len(payload):
            return (None, 0)
        return (payload[off + 2:off + 2 + plen], off + 2 + plen)

    # -- FILE_LIST (0x10): [st][more:u8][count:u16]{etype,esize,nlen,name} -----
    def handle_list(self, payload):
        payload = bytes(payload)
        path, _ = self._parse_path(payload, 0)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))
        hpath = self._host(jailed)
        try:
            names = os.listdir(hpath)
        except OSError as exc:
            return bytes((errno_to_status(_oserrno(exc)),))  # ENOTDIR → ENOENT
        body = bytearray()
        more = 0
        count = 0
        for name in names:
            # Transport scratch is control-plane state, whether a backend
            # reports it as a file or directory. Skip it before it can consume
            # stat work, response bytes, count, or the truncation flag.
            if name.endswith(TMP_SUFFIX):
                continue
            nbytes = name.encode("utf-8")
            need = 1 + 4 + 2 + len(nbytes)
            if 4 + len(body) + need > RSP_MAX:
                more = 1                 # over the RSP budget → truncate
                break
            if hpath.endswith("/"):
                child = hpath + name
            else:
                child = hpath + "/" + name
            etype = 0
            esize = 0
            cst, csize, cisdir = self._stat(child)
            if cst == OK:
                if cisdir:
                    etype = 1            # dirs: etype=1, esize=0 (C twin)
                else:
                    esize = csize        # files: best-effort stat size
            body += bytes((etype,)) + _p32(esize) + _p16(len(nbytes)) + nbytes
            count += 1
        return bytes((OK, more)) + _p16(count) + bytes(body)

    # -- FILE_STAT (0x11): [st][size:u32][crc32:u32] ---------------------------
    def handle_stat(self, payload):
        payload = bytes(payload)
        path, _ = self._parse_path(payload, 0)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))
        hpath = self._host(jailed)
        st, size, isdir = self._stat(hpath)
        if st != OK:
            return bytes((st,))
        crc = 0
        if not isdir:
            st, crc = self._crc_file(hpath, size)
            if st != OK:
                return bytes((st,))
        return bytes((OK,)) + _p32(size) + _p32(crc)

    # -- FILE_GET_BEGIN (0x12): validate + reserve; pump() streams (P2) --------
    def handle_get_begin(self, payload):
        payload = bytes(payload)
        if len(payload) < 6:
            return bytes((EBADREQ,))
        offset = _u32(payload, 0)
        path, _ = self._parse_path(payload, 4)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))         # jail beats the busy gate
        if self._busy():
            return bytes((EBUSY,))      # single active transfer (§5)
        hpath = self._host(jailed)
        st, total, isdir = self._stat(hpath)
        if st != OK:
            return bytes((st,))         # ENOENT
        if isdir:
            return bytes((EACCES,))     # cannot GET a directory
        if offset > total:
            return bytes((ERANGE,))
        self._get = (hpath, offset, total, self._owner_generation(),
                     self._operation_session)
        return bytes((OK,)) + _p32(total)

    def pump(self):
        """Drain the active GET on the supervisor: emit FILE_GET_DATA chunks
        (bytes ≥ offset only) then FILE_GET_END [crc32] over the WHOLE file
        (a skipped prefix is CRC'd too), then free the transfer slot. No-op
        when idle. RSP{OK} already went out — a mid-stream fault cannot
        retract it, so it omits END and lets the client timeout the incomplete
        transfer (C twin)."""
        if self._get is None:
            return
        transfer = self._get
        hpath, offset, total, generation, session = transfer
        if generation != self._transfer_generation:
            if self._get is transfer:
                self._get = None
            return
        try:
            crc = 0
            pos = 0
            remaining = total
            stream_complete = False
            try:
                f = self._open(hpath, "rb")
            except Exception:
                f = None
            if f is not None:
                try:
                    read_ok = True
                    while remaining > 0:
                        if generation != self._transfer_generation:
                            read_ok = False
                            break
                        want = self._chunk if remaining > self._chunk else remaining
                        block = f.read(want)
                        if generation != self._transfer_generation:
                            read_ok = False
                            break
                        if (type(block) is not bytes or len(block) == 0 or
                                len(block) > want):
                            read_ok = False
                            break
                        crc = crc32_update(block, crc)  # whole-file (from 0)
                        end = pos + len(block)
                        if end > offset:                # emit only bytes ≥ offset
                            start = offset if pos < offset else pos
                            self._emit_owned(
                                _OP_GET_DATA,
                                _p32(start) + block[start - pos:], session)
                            if generation != self._transfer_generation:
                                read_ok = False
                                break
                        pos = end
                        remaining -= len(block)
                    if read_ok and remaining == 0:
                        stream_complete = True
                except Exception:
                    stream_complete = False
                try:
                    f.close()
                except Exception:
                    stream_complete = False
            if (stream_complete and
                    generation == self._transfer_generation):
                self._emit_owned(_OP_GET_END, _p32(crc), session)
        finally:
            if self._get is transfer:
                self._get = None        # never clear a successor transfer

    # -- FILE_PUT_BEGIN (0x15): [st](+[resume_offset:u32]) ---------------------
    @staticmethod
    def _path_absent(path, valid=None):
        if valid is not None and not valid():
            return None
        try:
            os.stat(path)
        except OSError as exc:
            absent = errno_to_status(_oserrno(exc)) == ENOENT
        else:
            absent = False
        if valid is not None and not valid():
            return None
        return absent

    def _remove_scratch(self, temp, st=None, valid=None):
        """Remove one malformed scratch object without recursion.

        A backend reporting success while leaving the object behind is an I/O
        failure, not permission to truncate or replace it on the next open.
        """
        if valid is not None and not valid():
            return None
        if st is None:
            try:
                st = os.stat(temp)
            except OSError as exc:
                if errno_to_status(_oserrno(exc)) == ENOENT:
                    return OK
                return EIO
            if valid is not None and not valid():
                return None
        try:
            kind = st[0] & _S_IFMT
        except (IndexError, TypeError):
            return EIO
        if kind != _S_IFDIR and kind != _S_IFREG:
            return EIO                 # never mutate symlink/device/unknown
        try:
            if kind == _S_IFDIR:
                os.rmdir(temp)          # deliberately never recursive
            else:
                os.remove(temp)
        except (OSError, ValueError, TypeError):
            return EIO
        if valid is not None and not valid():
            return None
        absent = self._path_absent(temp, valid=valid)
        if absent is None:
            return None
        return OK if absent else EIO

    def _resume_prefix(self, temp, total, valid=None):
        """Return ``(status, resume_offset, running_crc)`` for durable scratch.

        Every nonzero resume offset is backed by an exact-length CRC scan and
        an unchanged regular-file re-stat. Malformed state is removed only by
        the bounded non-recursive helper; failed cleanup is fail-closed.
        """
        if valid is not None and not valid():
            return (None, 0, 0)
        try:
            st = os.stat(temp)
        except OSError as exc:
            if errno_to_status(_oserrno(exc)) == ENOENT:
                return (OK, 0, 0)       # no temp → fresh upload
            return (EIO, 0, 0)
        if valid is not None and not valid():
            return (None, 0, 0)
        try:
            kind = st[0] & _S_IFMT
        except (IndexError, TypeError):
            return (EIO, 0, 0)
        if kind == _S_IFDIR:
            cleaned = self._remove_scratch(temp, st, valid=valid)
            return (cleaned, 0, 0)
        if kind != _S_IFREG:
            return (EIO, 0, 0)          # fail closed; leave special untouched
        length = st[6]
        if type(length) is not int or length < 0:
            cleaned = self._remove_scratch(temp, st, valid=valid)
            return (cleaned, 0, 0)
        if length == 0:
            return (OK, 0, 0)
        if length > total:
            cleaned = self._remove_scratch(temp, st, valid=valid)
            return (cleaned, 0, 0)
        if valid is not None and not valid():
            return (None, 0, 0)
        try:
            f = self._open(temp, "rb")
        except OSError:
            if valid is not None and not valid():
                return (None, 0, 0)
            cleaned = self._remove_scratch(temp, st, valid=valid)
            return (cleaned, 0, 0)
        if valid is not None and not valid():
            try:
                f.close()               # stale worker may close its local object
            except Exception:
                pass
            return (None, 0, 0)
        crc = 0
        scan_ok = True
        try:
            remaining = length
            while remaining > 0:
                if valid is not None and not valid():
                    scan_ok = False
                    break
                want = _READ_BLK if remaining > _READ_BLK else remaining
                block = f.read(want)
                if valid is not None and not valid():
                    scan_ok = False
                    break
                if type(block) is not bytes:
                    scan_ok = False
                    break
                if len(block) != want:
                    scan_ok = False     # premature EOF/short read is malformed
                    break
                crc = crc32_update(block, crc)
                remaining -= len(block)
        except Exception:
            scan_ok = False
        try:
            f.close()
        except Exception:
            scan_ok = False

        if valid is not None and not valid():
            return (None, 0, 0)

        try:
            current = os.stat(temp)
        except OSError:
            current = None
        if valid is not None and not valid():
            return (None, 0, 0)
        try:
            current_kind = current[0] & _S_IFMT
        except (IndexError, TypeError):
            current_kind = None
        unchanged = (current_kind == _S_IFREG and current[6] == length)
        if scan_ok and unchanged:
            return (OK, length, crc)

        if current is not None and current_kind not in (_S_IFREG, _S_IFDIR):
            return (EIO, 0, 0)          # changed-to-special remains untouched

        # Re-stat once more inside cleanup so a file→directory race is
        # normalized with the operation appropriate to its current type.
        cleaned = self._remove_scratch(temp, current, valid=valid)
        return (cleaned, 0, 0)

    def _space_status(self, remaining, valid=None):
        """Checked-u64 PUT capacity admission using frsize and bavail."""
        if valid is not None and not valid():
            return None
        if self._statvfs is None:
            return EIO
        try:
            values = self._statvfs(self._root)
            if len(values) <= 4:
                return EIO
            unit = values[1]
            available = values[4]
        except Exception:
            return EIO
        if valid is not None and not valid():
            return None
        if (type(unit) is not int or type(available) is not int
                or unit <= 0 or available < 0
                or unit > _UINT64_MAX or available > _UINT64_MAX):
            return EIO
        if available != 0 and unit > _UINT64_MAX // available:
            return EIO
        free_bytes = unit * available

        if remaining == 0:
            rounded = 0
        else:
            addend = unit - 1
            if remaining > _UINT64_MAX - addend:
                return EIO
            rounded = ((remaining + addend) // unit) * unit
            if rounded > _UINT64_MAX:
                return EIO
        if rounded > _UINT64_MAX - FS_SAFETY_RESERVE:
            return EIO
        required = rounded + FS_SAFETY_RESERVE
        return OK if free_bytes >= required else ENOSPC

    def handle_put_begin(self, payload):
        if not self._operation_valid():
            return None
        payload = bytes(payload)
        if len(payload) < 10:
            return bytes((EBADREQ,))
        total = _u32(payload, 0)
        crc_target = _u32(payload, 4)
        path, _ = self._parse_path(payload, 8)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))
        if _forbidden_artifact(jailed):
            return bytes((EACCES,))     # .mpy/.pyc never accepted (FR-FS-12)
        self._reconcile_stale_put()
        if self._busy():
            return bytes((EBUSY,))      # single active transfer (§5)
        # A disconnect cannot enter VFS from the synchronous BLE callback.
        # Close the prior object here, in the next PUT_BEGIN's worker context,
        # before the resume scan derives its durable prefix (F-10).
        close_status = self._close_put_file()
        if not self._operation_valid():
            return None
        if close_status != OK:
            self._reset_put()
            return bytes((close_status,))

        dest = self._host(jailed)
        temp = dest + TMP_SUFFIX        # same jailed dir; resolve() forbids the
        #                                 suffix on the wire by design
        st, resume, crc_run = self._resume_prefix(
            temp, total, valid=self._operation_valid)
        if st is None:
            return None
        if st != OK:
            self._reset_put()
            return bytes((st,))
        st = self._space_status(
            total - resume, valid=self._operation_valid)
        if st is None:
            return None
        if st != OK:
            self._reset_put()
            return bytes((st,))
        mode = "ab" if resume > 0 else "wb"   # wb truncates any stale temp
        try:
            opened = self._open(temp, mode)
        except OSError as exc:
            if not self._operation_valid():
                return None
            self._reset_put()           # temp (if any) persists on storage
            return bytes((errno_to_status(_oserrno(exc)),))
        if not self._operation_valid():
            try:
                opened.close()          # only the stale worker's local object
            except Exception:
                pass
            return None

        self._put_file = opened
        self._put_temp = temp
        self._put_dest = dest
        self._put_total = total
        self._put_crc_target = crc_target
        self._put_watermark = resume
        self._put_crc_run = crc_run
        self._put_latched = 0
        self._put_generation = self._owner_generation()
        self._put_session = self._operation_session
        # Publish active last. All fields above are inert until this cut.
        self._put_active = True
        return bytes((OK,)) + _p32(resume)

    # -- FILE_PUT_DATA (0x16): Go-Back-N; ACK-only, no RSP ---------------------
    def _ack(self):
        # ack_offset = next expected = highest contiguous (cumulative ACK)
        if self._put_owned():
            self._emit_owned(
                _OP_PUT_ACK, _p32(self._put_watermark), self._put_session)

    def handle_put_data(self, payload):
        if not self._put_owned():
            return None                 # no transfer → nothing to ack
        payload = bytes(payload)
        if len(payload) < 4:
            self._ack()                 # malformed → re-ack (idempotent)
            return None
        offset = _u32(payload, 0)
        data = payload[4:]
        if self._put_latched:
            self._ack()                 # latched error → keep acking; END reports
            return None
        if offset == self._put_watermark and data:
            if (self._put_watermark > self._put_total
                    or len(data) > self._put_total - self._put_watermark):
                self._put_latched = ERANGE
                self._ack()
                return None
            try:
                written = self._put_file.write(data)
            except OSError as exc:
                if not self._put_owned():
                    return None
                self._put_latched = errno_to_status(_oserrno(exc))
            else:
                if not self._put_owned():
                    return None
                if type(written) is not int or written != len(data):
                    self._put_latched = EIO
                    self._ack()
                    return None
                # Advance + extend the streaming whole-file CRC together, only
                # on a full contiguous write, so the running CRC stays in
                # lockstep with the watermark (a dup/gap never double-counts).
                self._put_crc_run = crc32_update(data, self._put_crc_run)
                self._put_watermark += len(data)
        # offset < watermark (duplicate) and offset > watermark (gap) both
        # re-ACK the watermark so the app retransmits from there (Go-Back-N).
        self._ack()
        return None

    # -- FILE_PUT_END (0x17): verify + atomic rename ---------------------------
    def handle_put_end(self, payload):
        if not self._put_owned():
            return bytes((EBADREQ,))    # END without an active BEGIN
        payload = bytes(payload)
        if len(payload) < 4:
            status = self._abort_put(EBADREQ)
            return None if status is None else bytes((status,))
        declared = _u32(payload, 0)
        if self._put_latched:
            st = self._put_latched      # ENOSPC / EIO latched during DATA
            status = self._abort_put(st)
            return None if status is None else bytes((status,))
        if self._put_watermark != self._put_total:
            status = self._abort_put(ERANGE)
            return None if status is None else bytes((status,))
        close_status = self._close_put_file()  # durability cut before rename
        if not self._put_owned():
            return None
        if close_status != OK:
            status = self._abort_put(close_status)
            return None if status is None else bytes((status,))
        # The streaming whole-file CRC (re-seeded over any resumed prefix) is
        # the ONLY correctness gate — a foreign prefix fails HERE (FR-FS-14).
        crc = self._put_crc_run
        if crc != self._put_crc_target or crc != declared:
            status = self._abort_put(ECRC)
            return None if status is None else bytes((status,))
        temp = self._put_temp
        dest = self._put_dest
        try:
            os.rename(temp, dest)       # atomic replace (LittleFS / POSIX)
        except OSError as exc:
            if not self._put_owned():
                return None
            st = errno_to_status(_oserrno(exc))
            status = self._abort_put(st)
            return None if status is None else bytes((status,))
        if not self._put_owned():
            return None
        self._reset_put()               # temp is gone (renamed) — clear only
        return bytes((OK,))

    # -- FILE_DELETE (0x18) ----------------------------------------------------
    def handle_delete(self, payload):
        payload = bytes(payload)
        path, _ = self._parse_path(payload, 0)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))
        if self._put_active:
            return bytes((EBUSY,))
        hpath = self._host(jailed)
        st, _size, isdir = self._stat(hpath)
        if st != OK:
            return bytes((st,))         # missing → ENOENT
        try:
            if isdir:
                os.rmdir(hpath)         # non-empty → ENOTEMPTY → EACCES
            else:
                os.remove(hpath)
        except OSError as exc:
            return bytes((errno_to_status(_oserrno(exc)),))
        return bytes((OK,))

    # -- MKDIR (0x19) ----------------------------------------------------------
    def handle_mkdir(self, payload):
        payload = bytes(payload)
        path, _ = self._parse_path(payload, 0)
        if path is None:
            return bytes((EBADREQ,))
        st, jailed = resolve(path)
        if st != OK:
            return bytes((st,))
        if self._put_active:
            return bytes((EBUSY,))
        hpath = self._host(jailed)
        st, _size, isdir = self._stat(hpath)
        if st == OK:
            # already-a-dir → idempotent OK; an existing file → EBADREQ
            return bytes((OK,)) if isdir else bytes((EBADREQ,))
        try:
            os.mkdir(hpath)             # missing parent → ENOENT
        except OSError as exc:
            return bytes((errno_to_status(_oserrno(exc)),))
        return bytes((OK,))

    # -- FILE_RENAME (0x1A): [slen:u16][src][dlen:u16][dst] — both jailed ------
    def handle_rename(self, payload):
        payload = bytes(payload)
        src, off = self._parse_path(payload, 0)
        if src is None:
            return bytes((EBADREQ,))
        dst, _ = self._parse_path(payload, off)
        if dst is None:
            return bytes((EBADREQ,))
        st, sjail = resolve(src)
        if st != OK:
            return bytes((st,))
        st, djail = resolve(dst)
        if st != OK:
            return bytes((st,))
        if self._put_active:
            return bytes((EBUSY,))
        spath = self._host(sjail)
        dpath = self._host(djail)
        st, _size, _isdir = self._stat(spath)
        if st != OK:
            return bytes((st,))         # src missing → ENOENT
        try:
            os.rename(spath, dpath)     # dst non-empty dir → EACCES (via map)
        except OSError as exc:
            return bytes((errno_to_status(_oserrno(exc)),))
        return bytes((OK,))

    # -- F-10 link-drop hook ---------------------------------------------------
    def on_disconnect(self):
        """Reset RAM only; defer VFS close and preserve resumable scratch."""
        self._transfer_generation += 1
        self._get = None
        self._reset_put()
