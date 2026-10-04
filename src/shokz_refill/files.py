from __future__ import annotations

import os
import shutil
from pathlib import Path

from .device import is_within
from .naming import collision_path, sanitize_component


class DeviceFileService:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def checked(self, path: Path, *, missing: bool = False) -> Path:
        candidate = path if path.is_absolute() else self.root / path
        if not is_within(self.root, candidate, allow_missing=missing):
            raise ValueError("Invalid destination path: it leaves the selected device")
        return (
            candidate.parent.resolve(strict=True) / candidate.name
            if missing
            else candidate.resolve()
        )

    def list_dir(self, path: Path) -> list[Path]:
        folder = self.checked(path)
        if not folder.is_dir():
            raise ValueError("The selected location is not a folder")
        return sorted(
            (
                item
                for item in folder.iterdir()
                if not item.is_symlink() and (item.is_dir() or item.suffix.casefold() == ".mp3")
            ),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        )

    def create_folder(self, parent: Path, name: str) -> Path:
        target = self.checked(parent) / sanitize_component(name)
        self.checked(target, missing=True).mkdir()
        return target

    def ensure_folder(self, parent: Path, name: str) -> Path:
        folder = self.checked(parent)
        target = folder / sanitize_component(name)
        if target.is_symlink():
            raise ValueError(f"{target.name} is a symbolic link, not a safe folder")
        checked = self.checked(target, missing=not target.exists())
        if checked.exists():
            if checked.is_symlink() or not checked.is_dir():
                raise ValueError(f"{checked.name} exists but is not a safe folder")
            return checked
        checked.mkdir()
        return checked

    def rename(self, path: Path, new_name: str) -> Path:
        source = self.checked(path)
        suffix = source.suffix if source.is_file() else ""
        clean = sanitize_component(new_name.removesuffix(suffix)) + suffix
        target = self.checked(source.with_name(clean), missing=True)
        if target.exists():
            raise FileExistsError(f"{target.name} already exists")
        source.rename(target)
        return target

    def delete(self, path: Path) -> None:
        target = self.checked(path)
        if target == self.root:
            raise ValueError("The device root cannot be deleted")
        if target.is_dir():
            target.rmdir()  # Deliberately only empty folders.
        else:
            target.unlink()

    def import_mp3(self, source: Path, destination: Path) -> Path:
        if source.suffix.casefold() != ".mp3" or not source.is_file():
            raise ValueError(f"{source.name} is not an MP3 file")
        folder = self.checked(destination)
        target = collision_path(
            self.checked(folder / sanitize_component(source.stem), missing=True).with_suffix(".mp3")
        )
        partial = target.with_name(target.name + ".shokz-refill.part")
        with source.open("rb") as reader, partial.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        partial.replace(target)
        return target
