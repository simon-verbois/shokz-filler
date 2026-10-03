from pathlib import Path

from shokz_refill.naming import collision_path, sanitize_component, track_filename


def test_sanitize_windows_and_length() -> None:
    assert sanitize_component(r' A<B>:"C/ \. ') == "A_B___C_ _"
    assert sanitize_component("CON") == "_CON"
    assert len(sanitize_component("é" * 200).encode()) <= 180
    assert track_filename("Artist", "Title") == "Artist - Title.mp3"


def test_collision_path(tmp_path: Path) -> None:
    original = tmp_path / "song.mp3"
    original.write_bytes(b"one")
    assert collision_path(original).name == "song (2).mp3"
