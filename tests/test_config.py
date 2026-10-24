import os
from pathlib import Path

from shokz_refill.config import AppConfig, ConfigStore


def test_config_round_trip_and_bad_input(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    config = AppConfig(manual_device="/media/test", window_width=900, guided_tour_seen=True)
    store.save(config)
    assert store.load() == config
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o077 == 0
    store.path.write_text("not json", encoding="utf-8")
    assert store.load() == AppConfig()


def test_wrong_json_types_fall_back_to_valid_defaults(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.ensure_dirs()
    store.path.write_text(
        '{"window_width": "invalid", "window_height": -1, "manual_device": 42, '
        '"guided_tour_seen": "false"}'
    )
    assert store.load() == AppConfig()


def test_old_espeak_speed_migrates_without_losing_template(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.ensure_dirs()
    store.path.write_text(
        '{"book_tts_rate": 175, "book_tts_voice": "en-us", '
        '"book_tts_template": "Listen to $book_name."}'
    )
    config = store.load()
    assert config.book_tts_rate == 100
    assert config.book_tts_engine == "piper-v1"
    assert config.book_tts_voice == "en-us"
    assert config.book_tts_template == "Listen to $book_name."
    store.save(config)
    assert store.load() == config


def test_untouched_old_default_announcement_gains_the_chapter_number(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.ensure_dirs()
    store.path.write_text(
        '{"book_tts_engine": "piper-v1", "book_tts_template": "$book_name, de $author_name."}'
    )
    assert (
        store.load().book_tts_template == "$book_name, de $author_name. Chapitre $chapter_number."
    )
    store.path.write_text(
        '{"book_tts_engine": "piper-v1", "book_tts_template": "Listen to $book_name."}'
    )
    assert store.load().book_tts_template == "Listen to $book_name."
