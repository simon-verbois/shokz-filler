import re
import tomllib
from pathlib import Path

import shokz_filler

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", release)
    assert project["project"]["version"] == release
    assert shokz_filler.__version__ == release


def test_changelog_is_bundled_and_current() -> None:
    from shokz_filler.about import changelog_text

    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    text = changelog_text()
    assert text.startswith("# Changelog")
    assert f"## {release} " in text
    assert "CHANGELOG.md" in (ROOT / "shokz-filler.spec").read_text(encoding="utf-8")
