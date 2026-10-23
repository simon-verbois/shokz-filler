from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from .device import is_within
from .filesystem import device_operation, flush_directory, rename_no_replace
from .naming import collision_path

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]


def _check_cancelled(cancelled: Cancelled) -> None:
    if cancelled():
        raise InterruptedError("Transfer cancelled; partial copy retained for explicit resume")


def _fingerprint(path: Path, cancelled: Cancelled) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            _check_cancelled(cancelled)
            digest.update(chunk)
    return {"size": path.stat().st_size, "sha256": digest.hexdigest()}


def _open_partial(path: Path, *, existing: bool) -> BinaryIO:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("A transfer partial cannot be a link")
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not existing:
        flags |= os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.fstat(descriptor).st_nlink != 1:
        os.close(descriptor)
        raise ValueError("A transfer partial must be a private regular file")
    return os.fdopen(descriptor, "r+b")


class TransferManager:
    """Serialized copies with verified resumptions and exclusive final publication."""

    def __init__(self, state_path: Path, *, chunk_size: int = 1024 * 1024) -> None:
        self.state_path = state_path
        if chunk_size <= 0:
            raise ValueError("Copy chunk size must be positive")
        self.chunk_size = chunk_size

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            raise ValueError(
                "Transfer state is corrupt; partial files have been preserved"
            ) from None
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(state, dict) for key, state in value.items()
        ):
            raise ValueError("Invalid transfer state; partial files have been preserved")
        return value

    def _save(self, states: dict[str, dict[str, object]]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(states, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.state_path)
            flush_directory(self.state_path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def transfer(
        self,
        source: Path,
        destination: Path,
        device_root: Path,
        progress: Progress = lambda _value: None,
        cancelled: Cancelled = lambda: False,
    ) -> Path:
        with device_operation(cancelled):
            return self._transfer(source, destination, device_root, progress, cancelled)

    def resume_for_device(
        self,
        device_root: Path,
        cancelled: Cancelled = lambda: False,
        progress: Progress = lambda _value: None,
    ) -> tuple[list[Path], list[str]]:
        """Resume only when explicitly requested by the user."""
        with device_operation(cancelled):
            root = device_root.resolve(strict=True)
            completed: list[Path] = []
            errors: list[str] = []
            for state in list(self._load().values()):
                _check_cancelled(cancelled)
                try:
                    source = Path(str(state["source"]))
                    destination = Path(str(state["destination"]))
                    if not is_within(root, destination, allow_missing=True):
                        continue
                    completed.append(self.transfer(source, destination, root, progress, cancelled))
                except InterruptedError:
                    raise
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
        if not is_within(root, destination, allow_missing=True) or destination == root:
            raise ValueError("Invalid destination path")
        root_identity = (root.stat().st_dev, root.stat().st_ino)
        parent_identity = (destination.parent.stat().st_dev, destination.parent.stat().st_ino)

        def check_device() -> None:
            _check_cancelled(cancelled)
            if (
                (root.stat().st_dev, root.stat().st_ino) != root_identity
                or (destination.parent.stat().st_dev, destination.parent.stat().st_ino)
                != parent_identity
                or not is_within(root, destination, allow_missing=True)
            ):
                raise OSError("Device or destination changed during transfer")

        fingerprint = _fingerprint(source, cancelled)
        needed = source.stat().st_size
        states = self._load()
        key = ""
        partial: Path | None = None
        for state_key, state in states.items():
            if state.get("source") == str(source) and state.get("destination") == str(destination):
                key = state_key
                raw_partial = state.get("partial")
                if not isinstance(raw_partial, str):
                    raise ValueError("Invalid transfer partial path")
                partial = Path(raw_partial)
                if (
                    not partial.is_absolute()
                    or partial.parent != destination.parent
                    or not partial.name.startswith(destination.name + ".")
                    or not partial.name.endswith(".shokz-refill.part")
                    or not is_within(root, partial, allow_missing=True)
                ):
                    raise ValueError("Unsafe transfer partial path; file preserved")
                if state.get("fingerprint") != fingerprint:
                    raise ValueError("Cached source changed; existing partial preserved")
                break
        existing = partial is not None
        if partial is None:
            key = uuid.uuid4().hex
            partial = destination.with_name(destination.name + f".{key}.shokz-refill.part")
        check_device()
        if not existing and shutil.disk_usage(destination.parent).free < needed:
            raise OSError("The device does not have enough free space")
        with _open_partial(partial, existing=existing) as writer, source.open("rb") as reader:
            partial_stat = os.fstat(writer.fileno())
            partial_identity = (partial_stat.st_dev, partial_stat.st_ino)
            offset = partial_stat.st_size
            if offset > needed:
                raise ValueError("Partial copy is larger than its source; file preserved")
            remaining = offset
            while remaining:
                check_device()
                size = min(remaining, self.chunk_size)
                if writer.read(size) != reader.read(size):
                    raise ValueError("Partial content does not match its source; file preserved")
                remaining -= size
            if shutil.disk_usage(destination.parent).free < needed - offset:
                raise OSError("The device does not have enough free space")
            states[key] = {
                "source": str(source),
                "destination": str(destination),
                "partial": str(partial),
                "fingerprint": fingerprint,
            }
            self._save(states)
            progress(int(offset * 100 / max(needed, 1)))
            while chunk := reader.read(self.chunk_size):
                check_device()
                writer.write(chunk)
                offset += len(chunk)
                progress(int(offset * 100 / max(needed, 1)))
            writer.flush()
            os.fsync(writer.fileno())
        check_device()
        if _fingerprint(partial, cancelled) != fingerprint:
            raise OSError("Transfer integrity verification failed; partial preserved")
        while True:
            check_device()
            current = partial.lstat()
            if (current.st_dev, current.st_ino) != partial_identity or not stat.S_ISREG(
                current.st_mode
            ):
                raise ValueError("Partial file changed before publication")
            try:
                rename_no_replace(partial, destination)
                break
            except FileExistsError:
                destination = collision_path(destination)
        flush_directory(destination.parent)
        del states[key]
        self._save(states)
        progress(100)
        return destination
