#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Reject broken repository-local links in public Markdown files."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK = re.compile(r"!?\[[^\]]*]\(([^)\n]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+]:\s*(\S+)", re.MULTILINE)
EXTERNAL_SCHEMES = {"data", "http", "https", "mailto", "tel"}
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
EXPLICIT_ID = re.compile(r"<a\s+(?:name|id)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def markdown_files(root: Path) -> list[Path]:
    """Return authored Markdown paths, preferring the Git index."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "*.md"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return [
            root / relative
            for relative in result.stdout.decode("utf-8").split("\0")
            if relative
        ]

    excluded = {".git", ".next", "build", "node_modules", "out", "upstream"}
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in excluded for part in path.relative_to(root).parts)
    )


def _link_destination(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def _markdown_anchors(markdown: Path) -> set[str]:
    text = markdown.read_text(encoding="utf-8")
    anchors = set(EXPLICIT_ID.findall(text))
    duplicates: dict[str, int] = {}
    for raw_heading in HEADING.findall(text):
        heading = re.sub(r"<[^>]+>", "", raw_heading)
        heading = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = duplicates.get(slug, 0)
        duplicates[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def find_broken_links(root: Path) -> list[str]:
    """Return human-readable errors for missing repository-local targets."""
    errors: list[str] = []
    for markdown in markdown_files(root):
        text = markdown.read_text(encoding="utf-8")
        destinations = [
            *INLINE_LINK.findall(text),
            *REFERENCE_LINK.findall(text),
        ]
        for raw in destinations:
            destination = _link_destination(raw)
            if not destination:
                continue

            parsed = urlsplit(destination)
            if parsed.scheme.lower() in EXTERNAL_SCHEMES or parsed.netloc:
                continue
            if parsed.scheme:
                errors.append(
                    f"{markdown.relative_to(root)}: unsupported link scheme: "
                    f"{destination}"
                )
                continue

            relative = unquote(parsed.path)
            if not relative:
                target = markdown.resolve()
            else:
                target = (
                    root / relative.lstrip("/")
                    if relative.startswith("/")
                    else markdown.parent / relative
                ).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                errors.append(
                    f"{markdown.relative_to(root)}: link escapes repository: "
                    f"{destination}"
                )
                continue
            if not target.exists():
                errors.append(
                    f"{markdown.relative_to(root)}: missing target: {destination}"
                )
                continue
            if (
                parsed.fragment
                and target.is_file()
                and target.suffix.lower() in {".md", ".markdown"}
                and unquote(parsed.fragment) not in _markdown_anchors(target)
            ):
                errors.append(
                    f"{markdown.relative_to(root)}: missing anchor: "
                    f"{destination}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    root = args.root.resolve()
    errors = find_broken_links(root)
    if errors:
        for error in errors:
            print(f"docs_links: {error}")
        print(f"docs_links: {len(errors)} broken local link(s)")
        return 1
    print("docs_links: all repository-local Markdown targets exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
