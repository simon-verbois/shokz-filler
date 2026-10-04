from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import cast

from .device import is_within
from .naming import collision_path

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]


def _flush_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError:
        # Some Windows and removable filesystems do not support directory fsync.
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fingerprint(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    stat = path.stat()
    return {"size": stat.st_size, "sha256": digest.hexdigest()}


class TransferManager:
    """Sequential, resumable copies to removable storage."""

    def __init__(self, state_path: Path, *, chunk_size: int = 1024 * 1024) -> None:
        self.state_path = state_path
        self.chunk_size = chunk_size
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return {}
            return cast(dict[str, dict[str, object]], value)
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self, states: dict[str, dict[str, object]]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(states, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def transfer(
        self,
        source: Path,
        destination: Path,
        device_root: Path,
        progress: Progress = lambda _value: None,
        cancelled: Cancelled = lambda: False,
    ) -> Path:
        with self._lock:
            return self._transfer(source, destination, device_root, progress, cancelled)

    def resume_for_device(self, device_root: Path) -> tuple[list[Path], list[str]]:
        root = device_root.resolve(strict=True)
        completed: list[Path] = []
        errors: list[str] = []
        for state in list(self._load().values()):
            try:
                source = Path(str(state["source"]))
                destination = Path(str(state["destination"]))
                if not is_within(root, destination, allow_missing=True):
                    continue
                if not source.is_file():
                    errors.append(f"Cannot resume {destination.name}: cached source is missing")
                    continue
                completed.append(self.transfer(source, destination, root))
            except (KeyError, OSError, ValueError) as exc:
                errors.append(f"Could not resume a transfer: {exc}")
        return completed, errors

    def _transfer(
        self,
        source: Path,
        destination: Path,
        device_root: Path,
        progress: Progress,
        cancelled: Cancelled,
    ) -> Path:
        source = source.resolve(strict=True)
        root = device_root.resolve(strict=True)
        destination = destination.parent.resolve(strict=True) / destination.name
        if not is_within(root, destination, allow_missing=True):
            raise ValueError("Invalid destination path")
        if destination.exists():
            destination = collision_path(destination)
        needed = source.stat().st_size
        if shutil.disk_usage(destination.parent).free < needed:
            raise OSError("The device does not have enough free space")

        fingerprint = _fingerprint(source)
        states = self._load()
        matching_key = ""
        partial: Path | None = None
        for key, state in states.items():
            if state.get("source") == str(source) and state.get("destination") == str(destination):
                matching_key = key
                partial = Path(str(state["partial"]))
                if state.get("fingerprint") != fingerprint or not partial.is_file():
                    if partial.exists() and is_within(root, partial):
                        partial.unlink()
                    del states[key]
                    matching_key = ""
                    partial = None
                break
        if partial is None:
            matching_key = uuid.uuid4().hex
            partial = destination.with_name(destination.name + ".shokz-refill.part")
            if partial.exists():
                partial = destination.with_name(
                    destination.name + f".{matching_key[:8]}.shokz-refill.part"
                )
            states[matching_key] = {
                "source": str(source),
                "destination": str(destination),
                "partial": str(partial),
                "fingerprint": fingerprint,
            }
            self._save(states)

        offset = partial.stat().st_size if partial.exists() else 0
        if offset > needed:
            partial.unlink()
            offset = 0
        try:
            with source.open("rb") as reader, partial.open("ab") as writer:
                reader.seek(offset)
                copied = offset
                progress(int(copied * 100 / max(needed, 1)))
                while chunk := reader.read(self.chunk_size):
                    if cancelled():
                        raise InterruptedError(
                            "Transfer cancelled; partial copy retained for resume"
                        )
                    writer.write(chunk)
                    copied += len(chunk)
                    progress(int(copied * 100 / max(needed, 1)))
                writer.flush()
                os.fsync(writer.fileno())
            if partial.stat().st_size != needed:
                raise OSError("Transfer verification failed: sizes do not match")
            partial.replace(destination)
            _flush_directory(destination.parent)
            del states[matching_key]
            self._save(states)
            return destination
        except Exception:
            self._save(states)
            raise
