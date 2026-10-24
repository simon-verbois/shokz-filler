from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Track:
    video_id: str
    title: str
    artists: tuple[str, ...] = ()
    album: str = ""
    duration_seconds: int | None = None

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) or "Unknown Artist"

    @property
    def url(self) -> str:
        return f"https://music.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class Playlist:
    playlist_id: str
    title: str
    count: str = ""


@dataclass(frozen=True, slots=True)
class Device:
    name: str
    root: Path
    total: int
    used: int
    free: int
    automatic: bool = True
    identity: tuple[int, int] | None = None


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    WAITING = "waiting for transfer"
    TRANSFERRING = "transferring"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "already present"


@dataclass(slots=True)
class DownloadJob:
    job_id: str
    track: Track
    destination: Path
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    error: str = ""
    cached_mp3: Path | None = None
    cancel_requested: bool = False
    device_root: Path | None = None
    position: int | None = None  # 1-based playback position; None leaves the name unnumbered
    device_identity: tuple[int, int] | None = None
