#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python_bin="$project_dir/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required on the macOS build runner." >&2
  exit 1
fi

brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list deno >/dev/null 2>&1 || brew install deno

binary_dir="$project_dir/src/shokz_refill/bin"
mkdir -p "$binary_dir"
install -m 0755 "$(brew --prefix ffmpeg)/bin/ffmpeg" "$binary_dir/ffmpeg"
install -m 0755 "$(brew --prefix ffmpeg)/bin/ffprobe" "$binary_dir/ffprobe"
install -m 0755 "$(brew --prefix deno)/bin/deno" "$binary_dir/deno"
curl --fail --location --retry 3 \
  https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/COPYING.GPLv3 \
  --output "$binary_dir/FFMPEG-GPLv3.txt"
curl --fail --location --retry 3 \
  https://raw.githubusercontent.com/denoland/deno/main/LICENSE.md \
  --output "$binary_dir/DENO-LICENSE.md"

"$python_bin" -m PyInstaller --noconfirm --clean shokz-refill.spec
architecture="$(uname -m)"
artifact="$project_dir/dist/Shokz-Refill-macos-${architecture}"
mv -f "$project_dir/dist/Shokz-Refill" "$artifact"
chmod 0755 "$artifact"
QT_QPA_PLATFORM=offscreen "$artifact" --smoke-test
(cd "$(dirname "$artifact")" && shasum -a 256 "$(basename "$artifact")" > "$(basename "$artifact").sha256")
echo "Portable macOS binary: $artifact"
