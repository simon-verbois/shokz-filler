import shutil
from pathlib import Path

from mutagen.id3 import ID3

from shokz_filler.metadata import read_identity, write_metadata


def test_metadata_identity_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "track.mp3"
    ID3().save(path)
    write_metadata(path, source_id="abc123", artist="An Artist", title="A Song", album="Album")
    identity = read_identity(path)
    assert identity.source_id == "abc123"
    assert identity.artist == "An Artist"
    assert identity.title == "A Song"


def test_source_id_written_before_the_rename_is_still_read(tmp_path: Path) -> None:
    from mutagen.id3 import ID3, TXXX

    from shokz_filler.metadata import LEGACY_SOURCE_DESC, read_identity

    path = tmp_path / "old.mp3"
    shutil.copyfile(Path(__file__).parent / "fixtures" / "target-stereo.mp3", path)
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc=LEGACY_SOURCE_DESC, text=["video-123"]))
    tags.save(path, v2_version=3)
    assert read_identity(path).source_id == "video-123"
