import os
from pathlib import Path

from shokz_refill.config import AppConfig, ConfigStore


def test_config_round_trip_and_bad_input(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    config = AppConfig(manual_device="/media/test", window_width=900)
    store.save(config)
    assert store.load() == config
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o077 == 0
    store.path.write_text("not json", encoding="utf-8")
    assert store.load() == AppConfig()
