from pathlib import Path

from mutagen.id3 import ID3

from shokz_refill.metadata import read_identity, write_metadata


def test_metadata_identity_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "track.mp3"
    ID3().save(path)
    write_metadata(path, source_id="abc123", artist="An Artist", title="A Song", album="Album")
    identity = read_identity(path)
    assert identity.source_id == "abc123"
    assert identity.artist == "An Artist"
    assert identity.title == "A Song"
