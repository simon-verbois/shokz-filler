"""Audiobookshelf data and ordered export plans, independent of Qt and HTTP."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from .naming import sanitize_component
from .playback_order import ordered_name


@dataclass(frozen=True)
class AudiobookshelfCredentials:
    server: str = ""
    username: str = ""
    password: str = field(default="", repr=False)


def server_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Enter a full http:// or https:// server address without credentials or query"
        )
    if any(part in {".", ".."} for part in parsed.path.split("/")):
        raise ValueError("Invalid server path")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class Library:
    library_id: str
    name: str


@dataclass(frozen=True)
class AudioSource:
    index: int
    filename: str
    download_path: str
    duration: float
    size: int = 0
    modified: str = ""


@dataclass(frozen=True)
class Chapter:
    title: str
    start: float
    end: float


@dataclass(frozen=True)
class Audiobook:
    item_id: str
    title: str
    author: str = ""
    duration: float = 0
    sources: tuple[AudioSource, ...] = ()
    chapters: tuple[Chapter, ...] = ()
    available: bool = True

    def folder_name(self, server: str) -> str:
        identity = hashlib.sha256(f"{server}:{self.item_id}".encode()).hexdigest()[:8]
        return sanitize_component(f"{self.author} - {self.title}", max_bytes=80) + f" {identity}"


@dataclass(frozen=True)
class BookPage:
    books: tuple[Audiobook, ...]
    total: int
    page: int = 0
    limit: int = 50


@dataclass(frozen=True)
class Segment:
    source_index: int
    offset: float
    duration: float


@dataclass(frozen=True)
class ExportPart:
    number: int
    title: str
    segments: tuple[Segment, ...]
    total: int = 1

    @property
    def filename(self) -> str:
        """Zero-padded position prefix, so name order, copy order and TRCK all agree."""
        return ordered_name(self.number, self.total, self.title)

    def source_id(self, server: str, book: Audiobook, export_options: str = "") -> str:
        value = {
            "layout": "ordered-mp3-v1",
            "export_options": export_options,
            "server": server,
            "item": book.item_id,
            "number": self.number,
            "total": self.total,
            "segments": [(s.source_index, s.offset, s.duration) for s in self.segments],
            "sources": [(s.index, s.download_path, s.size, s.modified) for s in book.sources],
        }
        return (
            "audiobookshelf:"
            + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        )


def _number(value: object, default: float = 0) -> float:
    try:
        result = float(str(value))
        return result if math.isfinite(result) and result >= 0 else default
    except (TypeError, ValueError):
        return default


def map_book(data: dict[str, Any], *, expanded: bool = False) -> Audiobook:
    media = data.get("media") or {}
    metadata = media.get("metadata") or {}
    authors = metadata.get("authorName") or ", ".join(
        str(author.get("name", "")) for author in metadata.get("authors") or []
    )
    sources: list[AudioSource] = []
    if expanded:
        files = {
            str(entry.get("metadata", {}).get("relPath")): entry
            for entry in data.get("libraryFiles") or []
        }
        audio_files = media.get("audioFiles") or []
        raw_tracks = media.get("tracks")
        if raw_tracks is None:
            raw_tracks = [
                entry
                for entry in audio_files
                if not entry.get("exclude") and int(entry.get("index", 0)) >= 0
            ]
        for ordinal, entry in enumerate(raw_tracks, 1):
            meta = entry.get("metadata") or {}
            relpath = str(meta.get("relPath") or meta.get("filename") or "")
            file = files.get(relpath, {})
            ino = file.get("ino") or entry.get("ino")
            if not ino:
                match: dict[str, Any] = next(
                    (f for f in audio_files if f.get("metadata", {}).get("relPath") == relpath), {}
                )
                ino = match.get("ino")
            path = (
                f"/api/items/{quote(str(data['id']), safe='')}/file/"
                f"{quote(str(ino), safe='')}/download"
                if ino
                else str(entry.get("contentUrl") or "")
            )
            index = int(entry.get("index", ordinal))
            if index < 0 or entry.get("exclude"):
                continue
            duration = _number(entry.get("duration"))
            if not path or duration <= 0:
                raise ValueError(
                    "Audiobook has a missing audio URL or duration; rescan it on the server"
                )
            sources.append(
                AudioSource(
                    index,
                    str(meta.get("filename") or entry.get("title") or f"Track {ordinal}"),
                    path,
                    duration,
                    int(_number(meta.get("size"))),
                    str(meta.get("mtimeMs") or ""),
                )
            )
        sources.sort(key=lambda track: track.index)
        if len({track.index for track in sources}) != len(sources):
            raise ValueError("Audiobook has ambiguous track indices; fix its order on the server")
    chapters = tuple(
        Chapter(
            str(chapter.get("title") or f"Chapter {index}"),
            _number(chapter.get("start"), -1),
            _number(chapter.get("end"), -1),
        )
        for index, chapter in enumerate(media.get("chapters") or [], 1)
    )
    return Audiobook(
        str(data["id"]),
        str(metadata.get("title") or "Untitled audiobook"),
        str(authors),
        sum(s.duration for s in sources) or _number(media.get("duration")),
        tuple(sources),
        chapters,
        not data.get("isMissing", False)
        and not data.get("isInvalid", False)
        and (not expanded or bool(sources))
        and media.get("numTracks", media.get("numAudioFiles", 1)) != 0,
    )


def _chapter_parts(book: Audiobook, sources: list[AudioSource]) -> list[ExportPart] | None:
    """One part per chapter when chapters tile the book cleanly; None means use the files."""
    total = sum(source.duration for source in sources)
    chapters = book.chapters
    if len(chapters) < 2:
        return None
    previous_end = 0.0
    for chapter in chapters:
        if (
            chapter.start < 0
            or chapter.end <= chapter.start
            or chapter.start < previous_end - 0.05
            or chapter.end > total + 1
        ):
            return None
        previous_end = chapter.end
    starts: list[tuple[AudioSource, float]] = []
    cursor = 0.0
    for source in sources:
        starts.append((source, cursor))
        cursor += source.duration
    parts: list[ExportPart] = []
    for number, chapter in enumerate(chapters, 1):
        segments: list[Segment] = []
        for source, begin in starts:
            low, high = max(chapter.start, begin), min(chapter.end, begin + source.duration)
            if high - low > 0.01:
                segments.append(Segment(source.index, low - begin, high - low))
        if not segments:
            return None
        parts.append(ExportPart(number, chapter.title, tuple(segments), len(chapters)))
    return parts


def export_plan(book: Audiobook) -> tuple[ExportPart, ...]:
    """Ordered parts: one per chapter if they tile the book, else one per Audiobookshelf track."""
    if not book.available or not book.sources:
        raise ValueError("This book has no available audio tracks")
    sources = sorted(book.sources, key=lambda source: source.index)
    if len({source.index for source in sources}) != len(sources):
        raise ValueError("Audiobook has ambiguous track indices")
    if any(
        source.index < 0 or not math.isfinite(source.duration) or source.duration <= 0
        for source in sources
    ):
        raise ValueError("Audiobook has invalid track durations or indices")
    chapters = _chapter_parts(book, sources)
    if chapters is not None:
        return tuple(chapters)
    return tuple(
        ExportPart(
            number,
            source.filename.rsplit(".", 1)[0] if "." in source.filename else source.filename,
            (Segment(source.index, 0, source.duration),),
            len(sources),
        )
        for number, source in enumerate(sources, 1)
    )
