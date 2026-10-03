from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .duplicates import DuplicateIndex
from .media import AudioConverter, DownloadCancelled, MediaDownloader
from .models import DownloadJob, JobStatus, Track
from .naming import track_filename
from .transfer import TransferManager

MAX_CONCURRENT_DOWNLOADS = 3
JobCallback = Callable[[DownloadJob], None]


def cleanup_stale_cache(cache_dir: Path, state_path: Path, *, max_age_days: int = 14) -> None:
    jobs_dir = cache_dir / "jobs"
    if not jobs_dir.is_dir():
        return
    protected: set[Path] = set()
    try:
        import json

        states = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(states, dict):
            protected = {
                Path(str(state["source"])).resolve()
                for state in states.values()
                if isinstance(state, dict) and "source" in state
            }
    except (OSError, ValueError, TypeError):
        pass
    cutoff = time.time() - max_age_days * 86_400
    for folder in jobs_dir.iterdir():
        try:
            is_protected = any(folder.resolve() in source.parents for source in protected)
            if folder.is_dir() and folder.stat().st_mtime < cutoff and not is_protected:
                shutil.rmtree(folder)
        except OSError:
            continue


class DownloadQueue:
    def __init__(
        self,
        cache_dir: Path,
        transfer: TransferManager,
        downloader: MediaDownloader | None = None,
        converter: AudioConverter | None = None,
        callback: JobCallback = lambda _job: None,
    ) -> None:
        self.cache_dir = cache_dir
        self.transfer = transfer
        self.downloader = downloader or MediaDownloader()
        self.converter = converter or AudioConverter()
        self.callback = callback
        self.jobs: dict[str, DownloadJob] = {}
        self._executor = ThreadPoolExecutor(MAX_CONCURRENT_DOWNLOADS, "shokz-download")
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def enqueue(
        self, tracks: list[Track], destination: Path, device_root: Path, duplicates: DuplicateIndex
    ) -> list[DownloadJob]:
        created: list[DownloadJob] = []
        for track in tracks:
            job = DownloadJob(uuid.uuid4().hex, track, destination)
            self.jobs[job.job_id] = job
            created.append(job)
            already_queued = any(
                existing.track.video_id == track.video_id
                and existing.status not in {JobStatus.FAILED, JobStatus.CANCELLED}
                for existing in self.jobs.values()
                if existing.job_id != job.job_id
            )
            if already_queued or duplicates.match(
                source_id=track.video_id, artist=track.artist, title=track.title
            ):
                job.status = JobStatus.DUPLICATE
                job.error = "Already present on the selected device"
                self.callback(job)
                continue
            self.callback(job)
            self._futures[job.job_id] = self._executor.submit(self._run, job, device_root)
        return created

    def _update(
        self, job: DownloadJob, status: JobStatus | None = None, progress: int | None = None
    ) -> None:
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        self.callback(job)

    def _run(self, job: DownloadJob, device_root: Path) -> None:
        work = self.cache_dir / "jobs" / job.job_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            self._update(job, JobStatus.DOWNLOADING, 0)
            source = self.downloader.download(
                job.track,
                work,
                lambda p: self._update(job, progress=p // 2),
                lambda: job.cancel_requested,
            )
            self._update(job, JobStatus.CONVERTING, 50)
            cached = work / track_filename(job.track.artist, job.track.title)
            job.cached_mp3 = self.converter.convert(
                source,
                cached,
                job.track,
                lambda p: self._update(job, progress=50 + p // 4),
                lambda: job.cancel_requested,
            )
            self._update(job, JobStatus.WAITING, 75)
            target = job.destination / cached.name
            self._update(job, JobStatus.TRANSFERRING, 75)
            self.transfer.transfer(
                cached,
                target,
                device_root,
                lambda p: self._update(job, progress=75 + p // 4),
                lambda: job.cancel_requested,
            )
            self._update(job, JobStatus.COMPLETE, 100)
            shutil.rmtree(work, ignore_errors=True)
        except DownloadCancelled as exc:
            job.error = str(exc)
            self._update(job, JobStatus.CANCELLED)
        except InterruptedError as exc:
            job.error = str(exc)
            self._update(job, JobStatus.CANCELLED)
        except Exception as exc:
            job.error = str(exc)
            self._update(job, JobStatus.FAILED)

    def cancel(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            if job := self.jobs.get(job_id):
                job.cancel_requested = True
                future = self._futures.get(job_id)
                if future and future.cancel():
                    self._update(job, JobStatus.CANCELLED)

    def retry(self, job_ids: list[str], device_root: Path) -> None:
        for job_id in job_ids:
            job = self.jobs.get(job_id)
            if job and job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                job.cancel_requested = False
                job.error = ""
                self._update(job, JobStatus.QUEUED, 0)
                self._futures[job_id] = self._executor.submit(self._run, job, device_root)

    def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.status not in {
                JobStatus.COMPLETE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.DUPLICATE,
            }:
                job.cancel_requested = True
        self._executor.shutdown(wait=False, cancel_futures=True)
