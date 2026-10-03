from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .metadata import Mp3Identity, read_identity
from .naming import normalized


@dataclass(slots=True)
class DuplicateIndex:
    source_ids: set[str] = field(default_factory=set)
    artist_titles: set[tuple[str, str]] = field(default_factory=set)
    filenames: set[str] = field(default_factory=set)

    @classmethod
    def scan(cls, root: Path) -> DuplicateIndex:
        index = cls()
        for path in root.rglob("*"):
            try:
                if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".mp3":
                    continue
                index.add(path, read_identity(path))
            except OSError:
                continue
        return index

    def add(self, path: Path, identity: Mp3Identity) -> None:
        if identity.source_id:
            self.source_ids.add(identity.source_id)
        if identity.artist and identity.title:
            self.artist_titles.add((normalized(identity.artist), normalized(identity.title)))
        self.filenames.add(normalized(path.stem))

    def match(
        self, *, source_id: str = "", artist: str = "", title: str = "", filename: str = ""
    ) -> bool:
        if source_id and source_id in self.source_ids:
            return True
        if artist and title and (normalized(artist), normalized(title)) in self.artist_titles:
            return True
        return bool(filename and normalized(Path(filename).stem) in self.filenames)
