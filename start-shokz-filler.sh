#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
    printf '%s\n' \
        "Environnement Python introuvable : $python_bin" \
        "Depuis $project_dir, exécutez :" \
        "  python3 -m venv .venv" \
        "  .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

cd -- "$project_dir"
exec "$python_bin" "$project_dir/run_shokz_filler.py" "$@"
