from pathlib import Path

from mutagen.id3 import ID3

from shokz_refill.duplicates import DuplicateIndex
from shokz_refill.metadata import read_identity, write_metadata


def id3_file(path: Path) -> None:
    ID3().save(path)


def test_metadata_identity_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "track.mp3"
    id3_file(path)
    write_metadata(path, source_id="abc123", artist="An Artist", title="A Song", album="Album")
    identity = read_identity(path)
    assert identity.source_id == "abc123"
    assert identity.artist == "An Artist"
    assert identity.title == "A Song"


def test_duplicate_priority_and_fallbacks(tmp_path: Path) -> None:
    path = tmp_path / "Artist - Song.mp3"
    id3_file(path)
    write_metadata(path, source_id="video", artist="Artist", title="Song")
    plain = tmp_path / "Other Song.mp3"
    plain.write_bytes(b"not really mp3")
    index = DuplicateIndex.scan(tmp_path)
    assert index.match(source_id="video")
    assert index.match(artist="artist", title="SONG")
    assert index.match(filename="other_song.mp3")
    assert not index.match(source_id="different", artist="Nobody", title="Else")
