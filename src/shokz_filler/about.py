"""Version and changelog shown in Settings; both ship inside the package."""

from __future__ import annotations

from pathlib import Path

from . import __version__

_NAME = "CHANGELOG.md"


def changelog_text() -> str:
    """The bundled changelog; the repository copy is used when running from sources."""
    here = Path(__file__).resolve().parent
    for candidate in (here / _NAME, here.parents[1] / _NAME):
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return "The changelog is not available in this build."


def version_label() -> str:
    return __version__
