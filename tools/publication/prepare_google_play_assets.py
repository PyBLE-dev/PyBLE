#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Export store artwork and verified, unretouched Android screenshot copies."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(*args: object) -> str:
    return subprocess.check_output([str(arg) for arg in args], text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def properties(path: Path) -> tuple[int, int]:
    frames, width, height, kind, depth = run(
        "magick", "identify", "-ping", "-format", "%n %w %h %m %z", path
    ).split()
    if frames != "1" or kind != "PNG" or depth != "8":
        raise ValueError(f"Expected one 8-bit PNG: {path}")
    return int(width), int(height)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--capture-manifest", type=Path,
        help="Local JSON: capture environment and screenshots with source, device_type, order, key, alt_text",
    )
    args = parser.parse_args()
    for tool in ("inkscape", "magick"):
        if shutil.which(tool) is None:
            parser.error(f"Required tool is missing: {tool}")
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "local" / "publication"):
        parser.error("Output must be below this repository's ignored local/publication/")
    if output.exists():
        parser.error("Output already exists; select a new directory to preserve prior assets")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "source_revision": run("git", "-C", ROOT, "rev-parse", "HEAD"),
        "artwork": [], "screenshots": [],
    }
    with tempfile.TemporaryDirectory(prefix=".play-assets-", dir=output.parent) as tmp:
        stage = Path(tmp)
        icon_source = ROOT / "app/assets/branding/pyble-google-play-512.png"
        if properties(icon_source) != (512, 512) or icon_source.stat().st_size > 1048576:
            raise ValueError("Canonical Play icon must be 512x512 and at most 1024 KB")
        icon = stage / "pyble-icon-512.png"
        shutil.copyfile(icon_source, icon)
        manifest["artwork"].append({
            "filename": icon.name, "source": str(icon_source.relative_to(ROOT)),
            "sha256": digest(icon), "width": 512, "height": 512,
            "alt_text": "PyBLE blue microcontroller with a white terminal prompt on a navy background.",
        })
        feature_source = ROOT / "tools/publication/pyble-google-play-feature.svg"
        rendered = stage / ".feature-render.png"
        run("inkscape", feature_source, f"--export-filename={rendered}",
            "--export-width=1024", "--export-height=500")
        feature = stage / "pyble-feature-1024x500.png"
        run("magick", rendered, "-alpha", "off", "-colorspace", "sRGB",
            "-strip", "-depth", "8", "-define", "png:color-type=2", feature)
        rendered.unlink()
        if properties(feature) != (1024, 500):
            raise ValueError("Feature graphic must be 1024x500")
        manifest["artwork"].append({
            "filename": feature.name, "source": str(feature_source.relative_to(ROOT)),
            "source_sha256": digest(feature_source), "sha256": digest(feature),
            "width": 1024, "height": 500,
            "alt_text": "PyBLE: MicroPython over Bluetooth, with a code prompt and wireless signal illustration.",
        })
        if args.capture_manifest:
            source_manifest = args.capture_manifest.resolve()
            captures = json.loads(source_manifest.read_text())
            manifest["capture_environment"] = captures["environment"]
            seen: set[str] = set()
            for capture in captures["screenshots"]:
                kind = capture["device_type"]
                if kind not in ("phone", "tablet-7-inch", "tablet-10-inch"):
                    raise ValueError(f"Unexpected device type: {kind}")
                key = capture["key"]
                if not key or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in key):
                    raise ValueError(f"Invalid capture key: {key}")
                order = int(capture["order"])
                if order < 1 or order > 8:
                    raise ValueError("Screenshot order must be between 1 and 8")
                destination = Path(kind) / f"{order:02d}-{key}.png"
                if str(destination) in seen:
                    raise ValueError(f"Duplicate capture: {destination}")
                seen.add(str(destination))
                source = (source_manifest.parent / capture["source"]).resolve()
                width, height = properties(source)
                conversion_source = source
                processing = "Metadata stripped; 24-bit PNG; unchanged RGB pixels; no crop or resize"
                if "crop" in capture:
                    crop = capture["crop"]
                    x, y, crop_width, crop_height = (
                        int(crop[name]) for name in ("x", "y", "width", "height")
                    )
                    if (x < 0 or y < 0 or crop_width <= 0 or crop_height <= 0
                            or x + crop_width > width or y + crop_height > height):
                        raise ValueError(f"Invalid system-bar crop: {source}")
                    conversion_source = stage / ".capture-crop.png"
                    geometry = f"{crop_width}x{crop_height}+{x}+{y}"
                    run("magick", source, "-crop", geometry, "+repage", conversion_source)
                    width, height = crop_width, crop_height
                    processing = (
                        f"Exact system-bar crop {geometry}; metadata stripped; "
                        "24-bit PNG; unchanged cropped RGB pixels; no resize"
                    )
                if min(width, height) < 320 or max(width, height) > 3840:
                    raise ValueError(f"Screenshot dimensions outside Play limits: {source}")
                if max(width, height) > min(width, height) * 2:
                    raise ValueError(f"Screenshot aspect ratio exceeds 2:1: {source}")
                image = stage / destination
                image.parent.mkdir(exist_ok=True)
                run("magick", conversion_source, "-alpha", "off", "-strip", "-depth", "8",
                    "-define", "png:color-type=2", image)
                # Screenshot content must survive conversion byte-for-pixel.
                run("magick", "compare", "-metric", "AE", conversion_source, image, "null:")
                if conversion_source != source:
                    conversion_source.unlink()
                if len(capture["alt_text"]) > 140:
                    raise ValueError("Alt text exceeds 140 characters")
                manifest["screenshots"].append({
                    **capture, "source": str(source.relative_to(ROOT)),
                    "filename": str(destination), "source_sha256": digest(source),
                    "sha256": digest(image), "width": width, "height": height,
                    "processing": processing,
                })
        (stage / "asset-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        assets = manifest["artwork"] + manifest["screenshots"]
        (stage / "SHA256SUMS").write_text("".join(
            f"{asset['sha256']}  {asset['filename']}\n" for asset in assets
        ))
        shutil.copytree(stage, output)
    print(f"Prepared {len(assets)} graphics in {output}")


if __name__ == "__main__":
    main()
