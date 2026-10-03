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
tar -C dist -czf dist/Shokz-Refill-linux-x86_64.tar.gz Shokz-Refill
