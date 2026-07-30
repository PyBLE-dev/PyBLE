# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# PyBLE agent — Layer 3 frozen-Python package (chip-agnostic).
#
# EMPTY PLACEHOLDER at S1. This package exists so the per-chip board overlays
# have a frozen manifest target and the build can freeze *something* for the
# empty-agent bring-up. The agent modules (pyble_agent, pyble_ble, pyble_proto,
# pyble_runner, pyble_fs, pyble_console, pyble_info) are authored per-story from
# S2 onward by their owning engineers — see TDD §10.5. Do NOT add agent logic
# here (that is out of scope for build-smith).

__version__ = "0.4.1"  # mirrors versions.lock [pyble] agent_version (SemVer, BLD-12)
