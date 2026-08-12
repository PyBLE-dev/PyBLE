# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# PyBLE agent — Layer 3 frozen-Python package (chip-agnostic).
#
# Package identity is generated from versions.lock into the frozen top-level
# _version module by every ESP and RP2 build. Source-only/dev imports retain an
# explicit non-release fallback; no maintained board carries a release override.

try:
    import _version

    __version__ = _version.AGENT_VERSION
except (ImportError, AttributeError):
    __version__ = "0.0.0-dev"
