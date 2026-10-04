#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python_bin="$project_dir/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi
if [[ ! -x src/shokz_refill/bin/ffmpeg || ! -x src/shokz_refill/bin/deno ]]; then
  scripts/fetch_ffmpeg_linux.sh
fi
"$python_bin" -m PyInstaller --noconfirm --clean shokz-refill.spec
artifact="$project_dir/dist/Shokz-Refill-linux-x86_64"
mv -f "$project_dir/dist/Shokz-Refill" "$artifact"
chmod 0755 "$artifact"
QT_QPA_PLATFORM=offscreen "$artifact" --smoke-test
(cd "$(dirname "$artifact")" && sha256sum "$(basename "$artifact")" > "$(basename "$artifact").sha256")
echo "Portable Linux binary: $artifact"
