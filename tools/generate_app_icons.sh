#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
app_dir="$repo_dir/app"
source_svg="$app_dir/assets/branding/pyble-prompt-chip.svg"
master_png="$app_dir/assets/branding/pyble-prompt-chip-master.png"
ios_dir="$app_dir/ios/Runner/Assets.xcassets/AppIcon.appiconset"
android_res_dir="$app_dir/android/app/src/main/res"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/pyble-app-icons.XXXXXX")"

cleanup() {
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

for tool in inkscape magick; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required icon-generation tool is missing: %s\n' "$tool" >&2
    exit 1
  fi
done

render_svg() {
  local svg_path="$1"
  local png_path="$2"
  inkscape "$svg_path" \
    --export-filename="$png_path" \
    --export-width=1024 \
    --export-height=1024 >/dev/null
}

normalize_rgb() {
  local source_path="$1"
  local output_path="$2"
  magick "$source_path" \
    -alpha off \
    -colorspace sRGB \
    -strip \
    -define png:color-type=2 \
    "$output_path"
}

sed \
  -e 's/#081B35/#030B18/g' \
  -e 's/#2F8CFF/#68A9FF/g' \
  -e 's/#F4F7FF/#E9F0FF/g' \
  "$source_svg" >"$work_dir/dark.svg"
sed \
  -e 's/#081B35/#202020/g' \
  -e 's/#2F8CFF/#F2F2F2/g' \
  -e 's/#F4F7FF/#F2F2F2/g' \
  "$source_svg" >"$work_dir/tinted.svg"

render_svg "$source_svg" "$work_dir/default-render.png"
render_svg "$work_dir/dark.svg" "$work_dir/dark-render.png"
render_svg "$work_dir/tinted.svg" "$work_dir/tinted-render.png"

normalize_rgb "$work_dir/default-render.png" "$master_png"
normalize_rgb \
  "$work_dir/dark-render.png" \
  "$ios_dir/Icon-App-1024x1024-dark@1x.png"
magick "$work_dir/tinted-render.png" \
  -alpha off \
  -colorspace Gray \
  -depth 8 \
  -strip \
  -define png:color-type=0 \
  "$ios_dir/Icon-App-1024x1024-tinted@1x.png"
cp "$master_png" "$ios_dir/Icon-App-1024x1024@1x.png"

while read -r filename size; do
  magick "$master_png" \
    -filter Lanczos \
    -resize "${size}x${size}!" \
    -alpha off \
    -colorspace sRGB \
    -strip \
    -define png:color-type=2 \
    "$ios_dir/$filename"
done <<'SIZES'
Icon-App-20x20@1x.png 20
Icon-App-20x20@2x.png 40
Icon-App-20x20@3x.png 60
Icon-App-29x29@1x.png 29
Icon-App-29x29@2x.png 58
Icon-App-29x29@3x.png 87
Icon-App-40x40@1x.png 40
Icon-App-40x40@2x.png 80
Icon-App-40x40@3x.png 120
Icon-App-60x60@2x.png 120
Icon-App-60x60@3x.png 180
Icon-App-76x76@1x.png 76
Icon-App-76x76@2x.png 152
Icon-App-83.5x83.5@2x.png 167
SIZES

while read -r density size; do
  magick "$master_png" \
    -filter Lanczos \
    -resize "${size}x${size}!" \
    -alpha off \
    -colorspace sRGB \
    -strip \
    -define png:color-type=2 \
    "$android_res_dir/mipmap-$density/ic_launcher.png"
done <<'DENSITIES'
mdpi 48
hdpi 72
xhdpi 96
xxhdpi 144
xxxhdpi 192
DENSITIES

magick "$master_png" \
  -filter Lanczos \
  -resize 512x512! \
  -alpha on \
  -channel A \
  -evaluate set 100% \
  +channel \
  -colorspace sRGB \
  -strip \
  -define png:color-type=6 \
  "$app_dir/assets/branding/pyble-google-play-512.png"

printf 'Generated PyBLE launcher assets from %s\n' "$source_svg"
