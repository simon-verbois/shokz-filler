from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import ID3, TALB, TIT2, TPE1, TXXX
from mutagen.mp3 import MP3

SOURCE_DESC = "SHOKZ_REFILL_SOURCE_ID"


@dataclass(frozen=True, slots=True)
class Mp3Identity:
    source_id: str = ""
    artist: str = ""
    title: str = ""


def write_metadata(path: Path, *, source_id: str, artist: str, title: str, album: str = "") -> None:
    try:
        tags = ID3(path)
    except Exception:
        tags = ID3()
    tags.delall("TXXX:" + SOURCE_DESC)
    tags.add(TXXX(encoding=3, desc=SOURCE_DESC, text=[source_id]))
    tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
    if album:
        tags.setall("TALB", [TALB(encoding=3, text=[album])])
    tags.save(path, v2_version=3)


def read_identity(path: Path) -> Mp3Identity:
    try:
        tags = ID3(path)
    except Exception:
        return Mp3Identity()
    sources = tags.getall("TXXX:" + SOURCE_DESC)
    source = str(sources[0].text[0]) if sources and sources[0].text else ""
    artist = str(tags["TPE1"].text[0]) if "TPE1" in tags and tags["TPE1"].text else ""
    title = str(tags["TIT2"].text[0]) if "TIT2" in tags and tags["TIT2"].text else ""
    return Mp3Identity(source, artist, title)


def validate_mp3(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The converted MP3 is empty")
    audio = MP3(path)
    if audio.info is None:
        raise ValueError("The converted file has no MP3 audio stream")
    if audio.info.sample_rate != 44_100:
        raise ValueError("The converted MP3 is not 44.1 kHz")
    if audio.info.channels != 2:
        raise ValueError("The converted MP3 is not stereo")


def validate_source_mp3(path: Path) -> None:
    if path.suffix.casefold() != ".mp3" or not path.is_file():
        raise ValueError(f"{path.name} is not an MP3 file")
    try:
        audio = MP3(path)
        if audio.info is None or audio.info.length <= 0:
            raise ValueError
    except Exception:
        raise ValueError(f"{path.name} is corrupt or is not supported MP3 audio") from None
