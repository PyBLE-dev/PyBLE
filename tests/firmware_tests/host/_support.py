# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-test support for the S2 (M1/G1) firmware unit + conformance tests.
#
# Responsibilities:
#   1. Put firmware/pyble/ on sys.path so the frozen top-level modules
#      `pyble_proto` / `pyble_ble` import by the same names they carry on device.
#   2. Inject the MicroPython `bluetooth` / `machine` GUARDS (host/_fakes/) into
#      sys.modules BEFORE pyble_ble is imported, so a host import of pyble_ble's
#      PURE helpers does not require the real NimBLE module (S2 env-reality rule).
#   3. Load the SHARED PBLE/1 conformance corpus (host/conformance/corpus.json).
#   4. Provide `require(...)`: a red-with-a-reason helper so a missing module /
#      attribute fails the specific acceptance criterion (not a bare ImportError
#      "masquerading as red").
#
# These tests are authored [red] by firmware-test-author. The production modules
# do not exist yet, so importing them returns None here and every behavioural
# test FAILS naming the FR-* criterion it captures. When the owning engineer
# lands [green], `require(...)` returns the real module and the asserts run.

import json
import os
import sys

HOST_DIR = os.path.dirname(os.path.abspath(__file__))
FT_DIR = os.path.dirname(HOST_DIR)                       # tests/firmware_tests
REPO_ROOT = os.path.dirname(os.path.dirname(FT_DIR))     # repo root
PYBLE_DIR = os.path.join(REPO_ROOT, "firmware", "pyble")
FAKES_DIR = os.path.join(HOST_DIR, "_fakes")
CORPUS_PATH = os.path.join(HOST_DIR, "conformance", "corpus.json")

# --- 1. frozen agent modules import by their on-device top-level names --------
if PYBLE_DIR not in sys.path:
    sys.path.insert(0, PYBLE_DIR)

# --- 2. inject the MicroPython module guards before importing pyble_ble -------
if FAKES_DIR not in sys.path:
    sys.path.insert(0, FAKES_DIR)


def _inject_micropython_guards():
    """Make `import bluetooth` / `import machine` resolve to the host guards, so
    a top-level `import bluetooth` in pyble_ble does not crash a host import of
    its pure helpers. NimBLE behaviour itself is HIL-only and never faked."""
    import importlib

    for name in ("bluetooth", "machine"):
        if name not in sys.modules:
            sys.modules[name] = importlib.import_module(name)


# --- 3. shared conformance corpus --------------------------------------------
def load_corpus():
    with open(CORPUS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def frames():
    return load_corpus()["frames"]


def crc_reject_frames():
    return load_corpus()["crc_reject"]


# --- 4. red-with-a-reason ----------------------------------------------------
def try_import(module_name):
    """Import a frozen agent module, or return (None, reason) if it is not yet
    implemented / not importable. Never raises — the caller turns the absence
    into a behavioural FAIL tagged with its acceptance criterion."""
    if module_name == "pyble_ble":
        _inject_micropython_guards()
    try:
        import importlib

        return importlib.import_module(module_name), None
    except Exception as exc:  # noqa: BLE001 - report any import failure as red
        return None, "{}: {}".format(type(exc).__name__, exc)


class RedReason:
    """Wraps a (module, reason) so tests can assert a criterion and, on absence,
    fail with the FR-* text + the owning-engineer hand-off."""

    def __init__(self, module_name, owner):
        self.module_name = module_name
        self.owner = owner
        self.mod, self.reason = try_import(module_name)

    def obj(self, testcase, criterion):
        """Return the imported module or FAIL `testcase` naming `criterion`."""
        if self.mod is None:
            testcase.fail(
                "[{crit}] unmet: `{mod}` not importable on host "
                "({why}). HAND-OFF: {owner} authors {mod}.py [green].".format(
                    crit=criterion, mod=self.module_name, why=self.reason, owner=self.owner
                )
            )
        return self.mod

    def attr(self, testcase, name, criterion):
        """Return `mod.name` or FAIL `testcase` naming `criterion`."""
        mod = self.obj(testcase, criterion)
        if not hasattr(mod, name):
            testcase.fail(
                "[{crit}] unmet: `{mod}.{attr}` missing — interface pinned by "
                "this [red] test. HAND-OFF: {owner}.".format(
                    crit=criterion, mod=self.module_name, attr=name, owner=self.owner
                )
            )
        return getattr(mod, name)


def hx(hexstr):
    return bytes.fromhex(hexstr)
