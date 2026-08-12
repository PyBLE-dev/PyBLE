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
# Execution model (ports/rpi-pico2-w.md P2): the fast ops (LIST/STAT/DELETE/
# MKDIR/RENAME + every PUT step) answer inline in scheduled context; the GET
# stream is MAILBOXED — handle_get_begin() only validates + reserves and
# returns RSP{OK}[total]; the supervisor later calls pump() to emit the
# DATA*/END events on the main thread. pyble_agent owns RSP-before-EVT wire
# ordering (it sends the returned RSP, then calls pump()).
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

_READ_BLK = 256            # streaming read block (CRC/resume scans)

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

_S_IFDIR = 0x4000          # stat st_mode directory bit (POSIX + MicroPython)


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
    try:
        text = path.decode("utf-8")
    except Exception:
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

    def __init__(self, root, emit, chunk_size=229, open_fn=None):
        root = root or "/"
        if root != "/" and root.endswith("/"):
            root = root[:-1]
        self._root = root
        self._emit = emit
        self._chunk = chunk_size
        self._open = open_fn if open_fn is not None else open
        # Active-GET mailbox slot (P2): (host_path, offset) or None.
        self._get = None
        # PUT state machine (worker-local twin of pble_fs.c g_put_*). The open
        # temp file object is kept SEPARATE from the resettable state (the
        # rooted-pointer twin): on_disconnect resets flags but the orphan file
        # is flushed + closed only by the next PUT_BEGIN.
        self._put_file = None
        self._reset_put()

    # -- state helpers ---------------------------------------------------------
    def _reset_put(self):
        self._put_active = False
        self._put_temp = None       # host path of "<dest>.pbltmp"
        self._put_dest = None       # host path of the final destination
        self._put_total = 0
        self._put_crc_target = 0
        self._put_watermark = 0     # highest contiguous byte written
        self._put_crc_run = 0       # streaming whole-file CRC (finalized form)
        self._put_latched = 0       # 0, or a latched §8 write status

    def _close_put_file(self):
        f = self._put_file
        if f is not None:
            self._put_file = None
            try:
                f.close()           # flush to storage (fsync on LittleFS close)
            except Exception:
                pass

    def _abort_put(self):
        """Abort: close + DELETE the temp, KEEP the old target (FR-FS-14)."""
        self._close_put_file()
        temp = self._put_temp
        if temp:
            try:
                os.remove(temp)
            except OSError:
                pass
        self._reset_put()

    def _busy(self):
        return self._put_active or self._get is not None

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

    def _crc_file(self, hpath):
        """(status, whole-file CRC-32) streamed in _READ_BLK blocks."""
        try:
            f = self._open(hpath, "rb")
        except OSError as exc:
            return (errno_to_status(_oserrno(exc)), 0)
        crc = 0
        try:
            while True:
                block = f.read(_READ_BLK)
                if not block:
                    break
                crc = crc32_update(block, crc)
        except OSError as exc:
            return (errno_to_status(_oserrno(exc)), 0)
        finally:
            try:
                f.close()
            except Exception:
                pass
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
            st, crc = self._crc_file(hpath)  # whole-file CRC-32
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
        self._get = (hpath, offset)     # mailboxed: supervisor calls pump()
        return bytes((OK,)) + _p32(total)

    def pump(self):
        """Drain the active GET on the supervisor: emit FILE_GET_DATA chunks
        (bytes ≥ offset only) then FILE_GET_END [crc32] over the WHOLE file
        (a skipped prefix is CRC'd too), then free the transfer slot. No-op
        when idle. RSP{OK} already went out — a mid-stream fault cannot
        retract it, so END still goes out with the partial CRC (C twin)."""
        if self._get is None:
            return
        hpath, offset = self._get
        try:
            crc = 0
            pos = 0
            try:
                f = self._open(hpath, "rb")
            except OSError:
                f = None
            if f is not None:
                try:
                    while True:
                        block = f.read(self._chunk)
                        if not block:
                            break
                        crc = crc32_update(block, crc)  # whole-file (from 0)
                        end = pos + len(block)
                        if end > offset:                # emit only bytes ≥ offset
                            start = offset if pos < offset else pos
                            self._emit(_OP_GET_DATA,
                                       _p32(start) + block[start - pos:])
                        pos = end
                except OSError:
                    pass                # partial CRC → app detects the mismatch
                try:
                    f.close()
                except Exception:
                    pass
            self._emit(_OP_GET_END, _p32(crc))
        finally:
            self._get = None            # the transfer slot is free again

    # -- FILE_PUT_BEGIN (0x15): [st](+[resume_offset:u32]) ---------------------
    def _resume_prefix(self, temp, total):
        """F-10 resume: re-derive the verified prefix from storage. Returns
        (resume_offset, running_crc). No/empty/over-size/unreadable temp →
        (0, 0) and the caller's "wb" open truncates (the over-size guard)."""
        try:
            st = os.stat(temp)
        except OSError:
            return (0, 0)               # no temp → fresh upload
        if (st[0] & _S_IFDIR) != 0:
            return (0, 0)
        length = st[6]
        if length == 0 or length > total:
            return (0, 0)               # nothing to resume / over-size guard
        try:
            f = self._open(temp, "rb")
        except OSError:
            return (0, 0)
        crc = 0
        try:
            remaining = length
            while remaining > 0:
                want = _READ_BLK if remaining > _READ_BLK else remaining
                block = f.read(want)
                if not block:
                    break               # temp shorter than stat → CRC what exists
                crc = crc32_update(block, crc)
                remaining -= len(block)
        except OSError:
            return (0, 0)               # unreadable prefix → fresh (wb truncates)
        finally:
            try:
                f.close()
            except Exception:
                pass
        return (length, crc)            # durable prefix re-derived from flash

    def handle_put_begin(self, payload):
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
        if self._busy():
            return bytes((EBUSY,))      # single active transfer (§5)
        # Flush + close any file orphaned by a link-dropped transfer
        # (on_disconnect resets flags only) so the resume scan below sees the
        # full verified prefix length on storage (F-10).
        self._close_put_file()

        dest = self._host(jailed)
        temp = dest + TMP_SUFFIX        # same jailed dir; resolve() forbids the
        #                                 suffix on the wire by design
        resume, crc_run = self._resume_prefix(temp, total)
        mode = "ab" if resume > 0 else "wb"   # wb truncates any stale temp
        try:
            self._put_file = self._open(temp, mode)
        except OSError as exc:
            self._reset_put()           # temp (if any) persists on storage
            return bytes((errno_to_status(_oserrno(exc)),))

        self._put_active = True
        self._put_temp = temp
        self._put_dest = dest
        self._put_total = total
        self._put_crc_target = crc_target
        self._put_watermark = resume
        self._put_crc_run = crc_run
        self._put_latched = 0
        return bytes((OK,)) + _p32(resume)

    # -- FILE_PUT_DATA (0x16): Go-Back-N; ACK-only, no RSP ---------------------
    def _ack(self):
        # ack_offset = next expected = highest contiguous (cumulative ACK)
        self._emit(_OP_PUT_ACK, _p32(self._put_watermark))

    def handle_put_data(self, payload):
        if not self._put_active:
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
            try:
                self._put_file.write(data)
            except OSError as exc:
                self._put_latched = errno_to_status(_oserrno(exc))
            else:
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
        if not self._put_active:
            return bytes((EBADREQ,))    # END without an active BEGIN
        payload = bytes(payload)
        if len(payload) < 4:
            self._abort_put()
            return bytes((EBADREQ,))
        declared = _u32(payload, 0)
        if self._put_latched:
            st = self._put_latched      # ENOSPC / EIO latched during DATA
            self._abort_put()
            return bytes((st,))
        if self._put_watermark != self._put_total:
            self._abort_put()
            return bytes((ERANGE,))     # short/over transfer
        self._close_put_file()          # flush the temp to storage
        # The streaming whole-file CRC (re-seeded over any resumed prefix) is
        # the ONLY correctness gate — a foreign prefix fails HERE (FR-FS-14).
        crc = self._put_crc_run
        if crc != self._put_crc_target or crc != declared:
            self._abort_put()
            return bytes((ECRC,))       # mismatch → target untouched
        temp = self._put_temp
        dest = self._put_dest
        try:
            os.rename(temp, dest)       # atomic replace (LittleFS / POSIX)
        except OSError as exc:
            st = errno_to_status(_oserrno(exc))
            self._abort_put()
            return bytes((st,))
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
        """Reset in-RAM transfer state; KEEP <dest>.pbltmp on disk (its
        on-flash length is the durable watermark a resuming PUT_BEGIN
        re-derives). The orphan file object is flushed + closed later, by the
        next PUT_BEGIN — never here. Idempotent."""
        self._get = None
        self._reset_put()
