#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python_bin="$project_dir/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi
if [[ ! -x src/shokz_filler/bin/ffmpeg || ! -x src/shokz_filler/bin/deno ]]; then
  scripts/fetch_ffmpeg_linux.sh
fi
"$python_bin" scripts/fetch_tts_voices.py
"$python_bin" -m PyInstaller --noconfirm --clean shokz-filler.spec
artifact="$project_dir/dist/Shokz-Filler-linux-x86_64"
mv -f "$project_dir/dist/Shokz-Filler" "$artifact"
chmod 0755 "$artifact"
QT_QPA_PLATFORM=offscreen "$artifact" --smoke-test
"$artifact" --tts-smoke-test
(cd "$(dirname "$artifact")" && sha256sum "$(basename "$artifact")" > "$(basename "$artifact").sha256")
echo "Portable Linux binary: $artifact"
