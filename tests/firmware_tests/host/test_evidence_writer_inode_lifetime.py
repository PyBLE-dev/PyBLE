#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only regressions for exclusive evidence-file inode ownership.

Descriptor-lifetime assertions are deterministic on both macOS and Linux;
replacement checks must not depend on how quickly a filesystem reuses inodes.
Synthetic files do not constitute physical qualification evidence.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]


def load_gate(name):
    path = ROOT / "firmware" / "qualification" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_inode_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load evidence writer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WRITERS = (
    (load_gate("v060_profile_release_gate"), "_write_exclusive_result", "_remove_created_result"),
    (load_gate("v061_hardening_release_gate"), "_write_exclusive", "_remove_created"),
)


@contextmanager
def observe_writer_descriptor(gate):
    """Observe the real descriptor without extending its lifetime for the test."""
    state = {"descriptor": None, "closed": False}
    real_open, real_close = os.open, os.close

    def open_file(path, flags, *args, **kwargs):
        descriptor = real_open(path, flags, *args, **kwargs)
        if flags & os.O_CREAT:
            if state["descriptor"] is not None:
                raise AssertionError("writer created more than one output")
            state["descriptor"] = descriptor
        return descriptor

    def close_file(descriptor):
        if descriptor == state["descriptor"]:
            state["closed"] = True
        return real_close(descriptor)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(gate.os, "open", side_effect=open_file))
        stack.enter_context(mock.patch.object(gate.os, "close", side_effect=close_file))
        yield state


class EvidenceWriterInodeLifetimeTests(unittest.TestCase):
    def assert_writer_pinned(self, state):
        self.assertIsNotNone(state["descriptor"])
        self.assertFalse(
            state["closed"],
            "original inode must remain pinned until publication or cleanup finishes",
        )
        return os.fstat(state["descriptor"])

    def test_writer_is_pinned_until_successful_publication(self):
        for gate, writer_name, _cleanup_name in WRITERS:
            with self.subTest(writer=writer_name), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp).resolve() / "result.json"
                raw = b"writer-owned evidence\n"
                with observe_writer_descriptor(gate) as state:
                    getattr(gate, writer_name)(
                        output,
                        raw,
                        post_write_check=lambda: self.assert_writer_pinned(state),
                    )
                self.assertTrue(state["closed"], "successful writer must close its descriptor")
                self.assertEqual(output.read_bytes(), raw)

    def test_writer_is_pinned_through_failed_publication_cleanup(self):
        for gate, writer_name, cleanup_name in WRITERS:
            with self.subTest(writer=writer_name), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp).resolve() / "result.json"
                original_cleanup = getattr(gate, cleanup_name)

                def fail_validation():
                    raise gate.QualificationError("synthetic validation failure")

                with observe_writer_descriptor(gate) as state:
                    def cleanup(*args):
                        self.assert_writer_pinned(state)
                        return original_cleanup(*args)

                    with mock.patch.object(gate, cleanup_name, side_effect=cleanup) as observed:
                        with self.assertRaises(gate.QualificationError):
                            getattr(gate, writer_name)(
                                output,
                                b"writer-owned evidence\n",
                                post_write_check=fail_validation,
                            )
                    observed.assert_called_once()
                self.assertTrue(state["closed"], "failed writer must close its descriptor")
                self.assertFalse(output.exists())

    def test_replacements_are_rejected_and_preserved_even_with_identical_bytes(self):
        raw = b"writer-owned evidence\n"
        for gate, writer_name, _cleanup_name in WRITERS:
            for replacement in (raw, b"replacement-owned evidence\n"):
                with self.subTest(writer=writer_name, identical=replacement == raw):
                    with tempfile.TemporaryDirectory() as tmp:
                        output = Path(tmp).resolve() / "result.json"

                        def replace_output():
                            output.unlink()
                            output.write_bytes(replacement)
                            output.chmod(0o600)

                        with self.assertRaises(gate.QualificationError):
                            getattr(gate, writer_name)(
                                output,
                                raw,
                                post_write_check=replace_output,
                            )
                        self.assertEqual(output.read_bytes(), replacement)


if __name__ == "__main__":
    unittest.main()
