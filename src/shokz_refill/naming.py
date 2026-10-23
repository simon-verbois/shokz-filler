from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_SPECIAL = re.compile(r"[^\w\s-]+", re.UNICODE)
_SPACE = re.compile(r"\s+")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component(value: str, *, max_bytes: int = 180) -> str:
    value = unicodedata.normalize("NFC", value)
    value = _SPACE.sub(" ", _SPECIAL.sub("", value)).strip()
    if not value or not any(character.isalnum() for character in value):
        value = "Untitled"
    if value.upper() in _RESERVED:
        value = f"_{value}"
    while len(value.encode("utf-8")) > max_bytes:
        value = value[:-1].rstrip(" .")
    return value or "Untitled"


def track_filename(artist: str, title: str) -> str:
    return sanitize_component(f"{artist} - {title}", max_bytes=220) + ".mp3"


def playlist_folder_name(title: str) -> str:
    return sanitize_component(title, max_bytes=180)


def collision_path(path: Path) -> Path:
    if (
        not path.exists()
        and not path.is_symlink()
        and not path.with_name(path.name + ".shokz-refill.part").exists()
    ):
        return path
    for number in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} {number}{path.suffix}")
        if (
            not candidate.exists()
            and not candidate.is_symlink()
            and not candidate.with_name(candidate.name + ".shokz-refill.part").exists()
        ):
            return candidate
    raise FileExistsError(f"Could not find a free name for {path.name}")
