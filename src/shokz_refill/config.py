from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _platform_dir(kind: str) -> Path:
    if sys.platform == "win32":
        key = "LOCALAPPDATA" if kind == "cache" else "APPDATA"
        base = Path(os.environ.get(key, Path.home() / "AppData" / "Local"))
    else:
        env = "XDG_CACHE_HOME" if kind == "cache" else "XDG_CONFIG_HOME"
        default = Path.home() / (".cache" if kind == "cache" else ".config")
        base = Path(os.environ.get(env, default))
    return base / "shokz-refill"


@dataclass(slots=True)
class AppConfig:
    version: int = 1
    manual_device: str = ""
    destination_relative: str = "."
    window_width: int = 1100
    window_height: int = 760


class ConfigStore:
    def __init__(self, config_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.config_dir = config_dir or _platform_dir("config")
        self.cache_dir = cache_dir or _platform_dir("cache")
        self.path = self.config_dir / "config.json"
        self.auth_path = self.config_dir / "browser.json"

    def ensure_dirs(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        self.ensure_dirs()
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            valid = {key: raw[key] for key in asdict(AppConfig()) if key in raw}
            return AppConfig(**valid)
        except (OSError, ValueError, TypeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.ensure_dirs()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def remove_auth(self) -> None:
        self.auth_path.unlink(missing_ok=True)
