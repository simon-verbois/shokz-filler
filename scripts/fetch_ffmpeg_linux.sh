#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
binary_dir="$project_dir/src/shokz_refill/bin"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

mkdir -p "$binary_dir"
if [[ ! -x "$binary_dir/ffmpeg" || ! -x "$binary_dir/ffprobe" ]]; then
  curl --fail --location --retry 3 \
    https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
    --output "$temporary_dir/ffmpeg.tar.xz"
  tar -xJf "$temporary_dir/ffmpeg.tar.xz" -C "$temporary_dir"
  release_dir="$(find "$temporary_dir" -maxdepth 1 -type d -name 'ffmpeg-*-amd64-static' -print -quit)"
  install -m 0755 "$release_dir/ffmpeg" "$binary_dir/ffmpeg"
  install -m 0755 "$release_dir/ffprobe" "$binary_dir/ffprobe"
  if [[ -f "$release_dir/GPLv3.txt" ]]; then
    install -m 0644 "$release_dir/GPLv3.txt" "$binary_dir/FFMPEG-GPLv3.txt"
  fi
fi
if [[ ! -x "$binary_dir/deno" ]]; then
  curl --fail --location --retry 3 \
    https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    --output "$temporary_dir/deno.zip"
  unzip -q "$temporary_dir/deno.zip" -d "$temporary_dir/deno"
  install -m 0755 "$temporary_dir/deno/deno" "$binary_dir/deno"
fi
if [[ ! -f "$binary_dir/DENO-LICENSE.md" ]]; then
  curl --fail --location --retry 3 \
    https://raw.githubusercontent.com/denoland/deno/main/LICENSE.md \
    --output "$binary_dir/DENO-LICENSE.md"
fi
"$binary_dir/ffmpeg" -version | head -n 1
"$binary_dir/deno" --version | head -n 1
