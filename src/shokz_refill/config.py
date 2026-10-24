from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .book_export import DEFAULT_ANNOUNCEMENT, DEFAULT_CHAPTER_ANNOUNCEMENT, BookExportOptions
from .cancellation import check_cancelled


def _platform_dir(kind: str) -> Path:
    if sys.platform == "win32":
        key = "LOCALAPPDATA" if kind == "cache" else "APPDATA"
        base = Path(os.environ.get(key, Path.home() / "AppData" / "Local"))
    else:
        env = "XDG_CACHE_HOME" if kind == "cache" else "XDG_CONFIG_HOME"
        default = Path.home() / (".cache" if kind == "cache" else ".config")
        base = Path(os.environ.get(env, default))
    return base / "shokz-refill"


_LEGACY_ANNOUNCEMENT = "$book_name, de $author_name."


@dataclass(slots=True)
class AppConfig:
    version: int = 1
    manual_device: str = ""
    destination_relative: str = "."
    window_width: int = 1100
    window_height: int = 760
    book_tts_template: str = DEFAULT_ANNOUNCEMENT
    book_tts_voice: str = "fr"
    book_tts_rate: int = 100
    book_tts_engine: str = "piper-v1"
    book_tts_announce: bool = True
    book_announce_chapters: bool = True
    book_chapter_template: str = DEFAULT_CHAPTER_ANNOUNCEMENT

    def book_export_options(self) -> BookExportOptions:
        return BookExportOptions(
            self.book_tts_announce,
            self.book_tts_template,
            self.book_tts_voice,
            self.book_tts_rate,
            self.book_announce_chapters,
            self.book_chapter_template,
        )


class ConfigStore:
    def __init__(self, config_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.config_dir = config_dir or _platform_dir("config")
        self.cache_dir = cache_dir or _platform_dir("cache")
        self.path = self.config_dir / "config.json"
        self.auth_path = self.config_dir / "browser.json"
        self._lock = threading.RLock()

    def ensure_dirs(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        self.ensure_dirs()
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return AppConfig()
            defaults = asdict(AppConfig())
            valid = {
                key: raw[key]
                for key, default in defaults.items()
                if key in raw and type(raw[key]) is type(default)
            }
            for dimension in ("window_width", "window_height"):
                if dimension in valid and not 640 <= valid[dimension] <= 7680:
                    del valid[dimension]
            if raw.get("book_tts_engine") != "piper-v1":
                valid["book_tts_rate"] = 100
                valid["book_tts_engine"] = "piper-v1"
            if valid.get("book_tts_template") == _LEGACY_ANNOUNCEMENT:
                # The old default had no chapter; chapter 1 used to get it appended automatically.
                valid["book_tts_template"] = DEFAULT_ANNOUNCEMENT
            config = AppConfig(**valid)
            try:
                config.book_export_options().validate()
            except ValueError:
                config.book_tts_template = DEFAULT_ANNOUNCEMENT
                config.book_chapter_template = DEFAULT_CHAPTER_ANNOUNCEMENT
                config.book_tts_voice = "fr"
                config.book_tts_rate = 100
            return config
        except (OSError, ValueError, TypeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        with self._lock:
            check_cancelled()
            self.ensure_dirs()
            temporary = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(config), indent=2) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                check_cancelled()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
