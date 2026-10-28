"""Per-user connection persistence in a private (0600) file."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from .audiobook_models import AudiobookshelfCredentials
from .cancellation import check_cancelled


class AudiobookshelfSettings:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AudiobookshelfCredentials:
        data: dict[str, str] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {
                    key: value
                    for key, value in raw.items()
                    if key in {"server", "username", "password"} and isinstance(value, str)
                }
        except (OSError, ValueError):
            pass
        return AudiobookshelfCredentials(
            os.environ.get("AUDIOBOOKSHELF_SERVER", data.get("server", "")),
            os.environ.get("AUDIOBOOKSHELF_USERNAME", data.get("username", "")),
            os.environ.get("AUDIOBOOKSHELF_PASSWORD", data.get("password", "")),
        )

    def save(self, credentials: AudiobookshelfCredentials) -> None:
        """Always remembers the connection, in a file readable by this user only."""
        check_cancelled()
        data = asdict(credentials)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            check_cancelled()
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)
