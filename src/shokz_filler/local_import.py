"""Validate and normalize local MP3s before safely publishing them to a device."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Protocol

from .device import device_identity, verify_device
from .downloads import Transfer
from .filesystem import device_operation
from .media import AudioConverter, Cancelled, Progress
from .metadata import validate_mp3, validate_source_mp3
from .naming import sanitize_component


class LocalConverter(Protocol):
    def normalize(
        self, source: Path, output: Path, progress: Progress, cancelled: Cancelled
    ) -> Path: ...


class LocalMp3Importer:
    def __init__(
        self, cache_dir: Path, transfer: Transfer, converter: LocalConverter | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.transfer = transfer
        self.converter = converter or AudioConverter()

    def import_files(
        self,
        sources: list[Path],
        folder: Path,
        root: Path,
        progress: Progress = lambda _value: None,
        cancelled: Cancelled = lambda: False,
        *,
        expected_device: tuple[int, int] | None = None,
    ) -> int:
        """Keep normalized sources after failure so explicit partial-transfer resume stays valid."""
        expected = expected_device if expected_device is not None else device_identity(root)
        work = self.cache_dir / "jobs" / f"local-{uuid.uuid4().hex}"
        for index, source in enumerate(sources):
            if cancelled():
                raise InterruptedError("Local import cancelled")
            verify_device(root, expected)
            validate_source_mp3(source)
            prepared = source

            def report(value: int, completed: int = index) -> None:
                progress(int((completed + value / 100) * 100 / len(sources)))

            channels = getattr(self.converter, "channels", 2)
            try:
                validate_mp3(source, channels)
            except ValueError:
                work.mkdir(parents=True, exist_ok=True)
                prepared = self.converter.normalize(
                    source, work / f"{index + 1}.mp3", lambda p: report(p // 2), cancelled
                )
                validate_mp3(prepared, channels)

            def copying(value: int, normalized: bool = prepared != source) -> None:
                report(50 + value // 2 if normalized else value)

            with device_operation(cancelled):
                verify_device(root, expected)
                self.transfer.transfer(
                    prepared,
                    folder / (sanitize_component(source.stem, max_bytes=220) + ".mp3"),
                    root,
                    copying,
                    cancelled,
                )
        if work.exists():
            shutil.rmtree(work)
        return len(sources)
