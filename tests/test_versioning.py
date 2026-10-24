import re
import tomllib
from pathlib import Path

import shokz_refill

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", release)
    assert project["project"]["version"] == release
    assert shokz_refill.__version__ == release
