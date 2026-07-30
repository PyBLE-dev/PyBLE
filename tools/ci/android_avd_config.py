#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Apply deterministic, duplicate-free Android AVD configuration overrides."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

VALID_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _parse_overrides(assignments: Sequence[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if (
            not separator
            or not VALID_KEY.fullmatch(key)
            or not value
            or "\n" in value
            or "\r" in value
        ):
            raise ValueError(
                f"override must be a single-line KEY=VALUE assignment: {assignment!r}"
            )
        if key in seen:
            raise ValueError(f"duplicate requested override: {key}")
        seen.add(key)
        parsed.append((key, value))
    return parsed


def apply_overrides(config: Path, assignments: Sequence[str]) -> None:
    """Replace all existing copies of each requested key with one canonical value."""
    overrides = _parse_overrides(assignments)
    controlled_keys = {key for key, _ in overrides}
    retained: list[str] = []
    for line in config.read_text(encoding="utf-8").splitlines():
        candidate, separator, _ = line.partition("=")
        if separator and candidate.strip() in controlled_keys:
            continue
        retained.append(line)

    retained.extend(f"{key}={value}" for key, value in overrides)
    config.write_text("\n".join(retained) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply duplicate-free KEY=VALUE overrides to an AVD config.ini."
    )
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--set",
        action="append",
        dest="overrides",
        required=True,
        metavar="KEY=VALUE",
    )
    args = parser.parse_args()
    try:
        apply_overrides(args.config, args.overrides)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
