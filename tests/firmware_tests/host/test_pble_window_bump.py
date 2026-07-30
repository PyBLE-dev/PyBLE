# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host coverage for the reference-agent PUT sliding-window bump
# (W 4->8, receiver queue W+2 6->10). Frozen 2026-07-04 `[docs]`:
#   - FR-FS-4  (specs.md:157): "the reference agent advertises W=8 with
#              receiver queue depth W+2". No wire change (§5 offset/watermark
#              ACK is W-agnostic; W lives only in HELLO caps `window=`, §7).
#   - NFR-PERF-2 (specs.md:230): reference-agent default window W=8.
#   - FR-INFO-3 (specs.md:183): caps carry `put_window` (W); the HELLO reply
#              advertises what the receiver can actually honor.
#
# Sole [red] author: firmware-test-author. This is the only tag I author code
# under; the constant changes are PRODUCTION C and are HAND-OFFs (see below).
#
# WHY A SOURCE ASSERTION (not a runtime unit test): W and the receiver queue
# depth live in the native agent (pble_info.c caps text + pble_fs.c
# PBLE_FS_QDEPTH). There is no host C-compile/Unity harness yet (that arrives
# with F-20), and the FreeRTOS mailbox depth is not runnable off-device, so the
# honest host-observable check is a compile-time (static-source) assertion on
# the two constants and their W+2 relation — exactly the "compile-time check in
# the test harness" the task scopes when queue depth is not host-observable.
# The BYTE-EXACT caps/HELLO wire vector stays gated in conformance/s3_pending
# until §7 caps serialization is filled into the shared corpus; this file
# asserts only the FROZEN NUMERIC contract (W=8, queue W+2), never a draft byte.
#
# HAND-OFFs for [green] (I never edit firmware/**):
#   - pble_info.c caps `window=` 4->8 .......... identity-engineer
#   - pble_fs.c  PBLE_FS_QDEPTH  6->10 (W+2) .... storage-engineer

import importlib.util
import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402  (repo-root discovery; kept consistent with siblings)

REPO_ROOT = _support.REPO_ROOT
CMOD_DIR = os.path.join(REPO_ROOT, "firmware", "user_c_modules", "pyble")
INFO_C = os.path.join(CMOD_DIR, "pble_info.c")
FS_C = os.path.join(CMOD_DIR, "pble_fs.c")
HIL_DIR = os.path.join(REPO_ROOT, "tests", "firmware_tests", "hil")
F11_BENCH = os.path.join(HIL_DIR, "f11_reliability_bench.py")
ROUNDTRIP_BENCH = os.path.join(HIL_DIR, "file_roundtrip_bench.py")

# The architect-frozen values (specs.md FR-FS-4 / NFR-PERF-2, 2026-07-04).
REF_WINDOW = 8          # reference-agent advertised W
REF_QDEPTH = REF_WINDOW + 2   # receiver queue depth = W + 2 = 10


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _load_f11_bench():
    if HIL_DIR not in sys.path:
        sys.path.insert(0, HIL_DIR)
    spec = importlib.util.spec_from_file_location("pyble_f11_hil", F11_BENCH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load F-11 HIL bench")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _advertised_window(info_src):
    """The `window=N` the caps template (pble_info_device_info snprintf) emits.
    Caps are newline `key=value`; the app parses this verbatim — so the literal
    in the template IS what HELLO/DEVICE_INFO/INFO advertise. Returns int or
    None if no literal `window=<int>` is present (e.g. it became a %-format)."""
    m = re.search(r"window=(\d+)", info_src)
    return int(m.group(1)) if m else None


def _fs_qdepth(fs_src):
    """The PBLE_FS_QDEPTH #define value (receiver mailbox depth). Returns int or
    None if the macro is absent/renamed."""
    m = re.search(r"#define\s+PBLE_FS_QDEPTH\s+(\d+)", fs_src)
    return int(m.group(1)) if m else None


class CapsAdvertiseWindow8Test(unittest.TestCase):
    """FR-INFO-3 / FR-FS-4 / NFR-PERF-2: HELLO/DEVICE_INFO caps MUST advertise
    the reference-agent window W=8. HAND-OFF: identity-engineer (pble_info.c)."""

    def setUp(self):
        self.assertTrue(os.path.isfile(INFO_C),
                        "pble_info.c not found at %s" % INFO_C)
        self.info_src = _read(INFO_C)

    def test_caps_advertise_window_8(self):
        w = _advertised_window(self.info_src)
        self.assertIsNotNone(
            w, "caps template has no `window=<int>` literal in pble_info.c — "
               "FR-INFO-3 caps must advertise put_window (W). HAND-OFF: identity-engineer.")
        self.assertEqual(
            w, REF_WINDOW,
            "caps advertise window=%s; FR-FS-4/NFR-PERF-2 (frozen 2026-07-04) "
            "require the reference agent to advertise window=%d. "
            "HAND-OFF: identity-engineer -> pble_info.c caps `window=`." % (w, REF_WINDOW))


class ReceiverQueueDepthTest(unittest.TestCase):
    """FR-FS-4: receiver queue depth MUST be W+2 so the agent can hold a full
    window of unacknowledged PUT_DATA (plus control) without dropping. With
    W=8 that is a 10-deep mailbox. HAND-OFF: storage-engineer (pble_fs.c)."""

    def setUp(self):
        self.assertTrue(os.path.isfile(FS_C),
                        "pble_fs.c not found at %s" % FS_C)
        self.fs_src = _read(FS_C)

    def test_qdepth_holds_full_window_plus_two(self):
        q = _fs_qdepth(self.fs_src)
        self.assertIsNotNone(
            q, "PBLE_FS_QDEPTH #define not found in pble_fs.c. HAND-OFF: storage-engineer.")
        self.assertEqual(
            q, REF_QDEPTH,
            "PBLE_FS_QDEPTH=%d; FR-FS-4 (frozen 2026-07-04) requires receiver "
            "queue depth W+2 = %d so a full W=%d window of unacked PUT_DATA is "
            "accepted without refusing/dropping. HAND-OFF: storage-engineer "
            "-> pble_fs.c PBLE_FS_QDEPTH." % (q, REF_QDEPTH, REF_WINDOW))


class WindowQueueRelationTest(unittest.TestCase):
    """FR-FS-4 cross-check: the advertised window and the receiver queue depth
    MUST stay in the W+2 relation, so what caps promise (window=W) is what the
    receiver can actually buffer. Guards a future half-edit (bump one, not the
    other) that would re-introduce queue-full PUT_DATA drops under a full
    window. Spans both modules -> identity-engineer + storage-engineer."""

    def test_qdepth_equals_advertised_window_plus_two(self):
        w = _advertised_window(_read(INFO_C))
        q = _fs_qdepth(_read(FS_C))
        self.assertIsNotNone(w, "no advertised `window=` literal in pble_info.c")
        self.assertIsNotNone(q, "no PBLE_FS_QDEPTH #define in pble_fs.c")
        self.assertEqual(
            q, w + 2,
            "receiver queue depth (PBLE_FS_QDEPTH=%d) MUST equal advertised "
            "window (%d) + 2 = %d (FR-FS-4 'receiver queue depth W+2'). A "
            "mismatch means caps promise a window the receiver cannot buffer, "
            "re-opening the queue-full drop that Go-Back-N has to recover from. "
            "HAND-OFF: identity-engineer (caps) + storage-engineer (QDEPTH)."
            % (q, w, w + 2))


class HilWindowContractTest(unittest.TestCase):
    """The real-board benches must exercise the current reference-agent W=8
    by default; a stale W=4 harness can pass while under-driving the queue."""

    def test_f11_uses_the_central_requested_mtu_contract(self):
        bench = _load_f11_bench()
        self.assertEqual(
            getattr(bench, "REQUESTED_MTU", None),
            247,
            "F-11 must use the BLE central's canonical requested ATT MTU",
        )
        self.assertNotIn(
            "wire.REQUESTED_MTU",
            inspect.getsource(bench.run_bench),
            "REQUESTED_MTU belongs to _pble_central, not the wire codec",
        )

    def test_f11_sends_the_apps_canonical_hello_offer(self):
        bench = _load_f11_bench()
        self.assertEqual(
            getattr(bench, "HELLO_PAYLOAD", None),
            b"proto_versions=1\napp_name=hil-f11\napp_version=0",
            "F-11 must offer PBLE/1 with the §7 field names used by the app",
        )
        self.assertIn(
            "HELLO_PAYLOAD",
            inspect.getsource(bench.run_bench),
            "the byte-exact HIL HELLO constant must be sent by run_bench",
        )

    def test_f11_requires_an_exact_expected_chip_for_every_bench_run(self):
        bench = _load_f11_bench()
        parse_args = getattr(bench, "_parse_args", None)
        self.assertTrue(
            callable(parse_args),
            "F-11 must expose one host-testable argument validator",
        )
        with self.assertRaises(SystemExit):
            parse_args(["--address", "test-board"])
        args = parse_args(
            [
                "--address",
                "test-board",
                "--expect-chip",
                "esp32-s3",
            ]
        )
        self.assertEqual(args.address, "test-board")
        self.assertEqual(args.expect_chip, "esp32-s3")
        self.assertTrue(parse_args(["--scan"]).scan)

    def test_f11_uses_advertised_transfer_caps_by_default(self):
        bench = _load_f11_bench()
        select = getattr(bench, "_select_transfer_settings", None)
        self.assertTrue(
            callable(select),
            "F-11 must expose one host-testable HELLO-cap selection helper",
        )
        self.assertEqual(
            select(
                {"chip": "esp32-s3", "window": "8", "chunk": "229"},
                mtu=247,
            ),
            ("esp32-s3", 8, 229),
        )

    def test_f11_bounds_explicit_diagnostic_overrides_to_advertised_caps(self):
        bench = _load_f11_bench()
        select = getattr(bench, "_select_transfer_settings", None)
        self.assertTrue(callable(select))
        self.assertEqual(
            select(
                {"chip": "esp32-s3", "window": "8", "chunk": "229"},
                mtu=247,
                expected_chip="esp32-s3",
                window_override=4,
                chunk_override=120,
            ),
            ("esp32-s3", 4, 120),
        )
        for overrides in (
            {"window_override": 9},
            {"chunk_override": 230},
            {"expected_chip": "esp32"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    select(
                        {"chip": "esp32-s3", "window": "8", "chunk": "229"},
                        mtu=247,
                        **overrides,
                    )

    def test_f11_rejects_missing_or_invalid_required_caps(self):
        bench = _load_f11_bench()
        select = getattr(bench, "_select_transfer_settings", None)
        self.assertTrue(callable(select))
        for caps in (
            {"chip": "esp32-s3", "chunk": "229"},
            {"chip": "esp32-s3", "window": "0", "chunk": "229"},
            {"chip": "esp32-s3", "window": "eight", "chunk": "229"},
            {"chip": "esp32-s3", "window": "8", "chunk": "230"},
        ):
            with self.subTest(caps=caps):
                with self.assertRaises(ValueError):
                    select(caps, mtu=247)

    def test_roundtrip_retains_only_the_missing_cap_legacy_fallback(self):
        source = _read(ROUNDTRIP_BENCH)
        match = re.search(r"(?m)^DEFAULT_WINDOW\s*=\s*(\d+)\b", source)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 4)
        self.assertRegex(
            source,
            r"(?i)legacy|missing-cap|caps omit",
            "W=4 in the round-trip bench must be labelled only as fallback",
        )

    def test_f11_help_does_not_advertise_the_retired_window(self):
        source = _read(F11_BENCH)
        self.assertNotRegex(
            source,
            r"(?i)(?:default\s+4|W\s*=\s*4)",
            "the HIL runner must not direct operators to retired W=4",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
