#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Verify the ESP release ELF contains PyBLE's two VM lifecycle seams."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


TARGET_NM = {
    "esp32": "xtensa-esp32-elf-nm",
    "esp32-s3": "xtensa-esp32s3-elf-nm",
    "esp32-c3": "riscv32-esp-elf-nm",
    "waveshare-esp32-s3-lcd-147b": "xtensa-esp32s3-elf-nm",
}
REQUIRED_SYMBOLS = {
    "__wrap_mp_thread_deinit",
    "mp_thread_deinit",
    "pble_vm_epoch_begin",
}


class VerificationError(RuntimeError):
    """The built image does not prove the frozen lifecycle linkage."""


def regular_file(raw: str, label: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        raise VerificationError(f"{label} is missing or not a regular file: {path}")
    return path


def defined_symbols(nm: Path, elf: Path) -> set[str]:
    try:
        completed = subprocess.run(
            [str(nm), "--defined-only", "--extern-only", str(elf)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"nm could not inspect {elf}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "no diagnostic"
        raise VerificationError(f"nm rejected {elf}: {detail}")

    symbols: set[str] = set()
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            symbols.add(fields[-1])
    return symbols


def verify(args: argparse.Namespace) -> None:
    elf = regular_file(args.elf, "micropython ELF")
    link_map = regular_file(args.map_path, "micropython.map")
    nm = regular_file(args.nm, "target nm")

    expected_nm = TARGET_NM[args.target]
    if nm.name != expected_nm:
        raise VerificationError(
            f"{args.target} requires {expected_nm}, not {nm.name}"
        )

    symbols = defined_symbols(nm, elf)
    missing_symbols = sorted(REQUIRED_SYMBOLS - symbols)
    if missing_symbols:
        raise VerificationError(
            "ELF lacks defined lifecycle symbol(s): " + ", ".join(missing_symbols)
        )

    map_text = link_map.read_text(encoding="utf-8", errors="replace")
    required_map_tokens = REQUIRED_SYMBOLS | {"pble_vm_lifecycle.c"}
    missing_map_tokens = sorted(
        token for token in required_map_tokens if token not in map_text
    )
    if missing_map_tokens:
        raise VerificationError(
            "micropython.map lacks lifecycle evidence: "
            + ", ".join(missing_map_tokens)
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=tuple(TARGET_NM))
    parser.add_argument("--elf", required=True)
    parser.add_argument("--map", required=True, dest="map_path")
    parser.add_argument("--nm", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        verify(args)
    except (OSError, VerificationError) as exc:
        print(f"verify_vm_lifecycle_linkage.py: {exc}", file=sys.stderr)
        return 1
    print(f"verify_vm_lifecycle_linkage.py: OK — {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
