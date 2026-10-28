from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen import MutagenError
from mutagen.id3 import ID3, TALB, TCON, TIT2, TPE1, TPOS, TRCK, TXXX
from mutagen.mp3 import MP3, BitrateMode

SOURCE_DESC = "SHOKZ_FILLER_SOURCE_ID"
# Files written before the rename to Shokz Filler carry this tag; it is still read.
LEGACY_SOURCE_DESC = "SHOKZ_REFILL_SOURCE_ID"


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
    tags.delall("TXXX:" + LEGACY_SOURCE_DESC)
    tags.add(TXXX(encoding=3, desc=SOURCE_DESC, text=[source_id]))
    tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
    if album:
        tags.setall("TALB", [TALB(encoding=3, text=[album])])
    tags.save(path, v2_version=3)


def write_audiobook_metadata(
    path: Path, *, source_id: str, author: str, title: str, book_title: str, number: int, total: int
) -> None:
    write_metadata(path, source_id=source_id, artist=author, title=title, album=book_title)
    tags = ID3(path)
    tags.setall("TRCK", [TRCK(encoding=3, text=[f"{number}/{total}"])])
    tags.setall("TPOS", [TPOS(encoding=3, text=["1/1"])])
    tags.setall("TCON", [TCON(encoding=3, text=["Audiobook"])])
    tags.save(path, v2_version=3)


def read_identity(path: Path) -> Mp3Identity:
    try:
        tags = ID3(path)
    except Exception:
        return Mp3Identity()
    sources = tags.getall("TXXX:" + SOURCE_DESC) or tags.getall("TXXX:" + LEGACY_SOURCE_DESC)
    source = str(sources[0].text[0]) if sources and sources[0].text else ""
    artist = str(tags["TPE1"].text[0]) if "TPE1" in tags and tags["TPE1"].text else ""
    title = str(tags["TIT2"].text[0]) if "TIT2" in tags and tags["TIT2"].text else ""
    return Mp3Identity(source, artist, title)


def validate_mp3(path: Path, channels: int = 2) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The converted MP3 is empty")
    try:
        audio = MP3(path)
    except MutagenError:
        raise ValueError("The converted file is not valid MP3 audio") from None
    if audio.info is None:
        raise ValueError("The converted file has no MP3 audio stream")
    if audio.info.bitrate_mode != BitrateMode.CBR or not 190_000 <= audio.info.bitrate <= 194_000:
        raise ValueError("The converted MP3 is not CBR 192 kbps")
    if audio.info.sample_rate != 44_100:
        raise ValueError("The converted MP3 is not 44.1 kHz")
    if audio.info.channels != channels:
        raise ValueError(f"The converted MP3 is not {'mono' if channels == 1 else 'stereo'}")


def validate_source_mp3(path: Path) -> None:
    if path.suffix.casefold() != ".mp3" or not path.is_file():
        raise ValueError(f"{path.name} is not an MP3 file")
    try:
        audio = MP3(path)
        if audio.info is None or audio.info.length <= 0:
            raise ValueError
    except Exception:
        raise ValueError(f"{path.name} is corrupt or is not supported MP3 audio") from None
