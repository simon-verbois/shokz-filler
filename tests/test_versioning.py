import re
import tomllib
from pathlib import Path

import pytest

import shokz_filler

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", release)
    assert project["project"]["version"] == release
    assert shokz_filler.__version__ == release


def test_changelog_is_bundled_and_current(monkeypatch: pytest.MonkeyPatch) -> None:
    from shokz_filler import about

    # The package may be installed non-editably (CI), where only PyInstaller bundles
    # the changelog; resolve it as if running from the sources.
    monkeypatch.setattr(about, "__file__", str(ROOT / "src" / "shokz_filler" / "about.py"))
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    text = about.changelog_text()
    assert text.startswith("# Changelog")
    assert f"## {release} " in text
    assert "CHANGELOG.md" in (ROOT / "shokz-filler.spec").read_text(encoding="utf-8")
