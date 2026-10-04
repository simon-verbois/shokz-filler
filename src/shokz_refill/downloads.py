from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .media import AudioConverter, DownloadCancelled, MediaDownloader
from .models import DownloadJob, JobStatus, Track
from .naming import track_filename
from .transfer import TransferManager

MAX_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_CONVERSIONS = 2
MAX_CONCURRENT_TRANSFERS = 1
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
        self._download_executor = ThreadPoolExecutor(MAX_CONCURRENT_DOWNLOADS, "shokz-download")
        self._convert_executor = ThreadPoolExecutor(MAX_CONCURRENT_CONVERSIONS, "shokz-convert")
        self._transfer_executor = ThreadPoolExecutor(MAX_CONCURRENT_TRANSFERS, "shokz-transfer")
        self._futures: dict[str, set[Future[None]]] = {}
        self._lock = threading.Lock()

    def enqueue(
        self, tracks: list[Track], destination: Path, device_root: Path
    ) -> list[DownloadJob]:
        created: list[DownloadJob] = []
        for track in tracks:
            job = DownloadJob(uuid.uuid4().hex, track, destination)
            self.jobs[job.job_id] = job
            created.append(job)
            self.callback(job)
            self._submit_download(job, device_root)
        return created

    def _update(
        self, job: DownloadJob, status: JobStatus | None = None, progress: int | None = None
    ) -> None:
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        self.callback(job)

    def _track_future(self, job: DownloadJob, future: Future[None]) -> None:
        with self._lock:
            self._futures.setdefault(job.job_id, set()).add(future)

        def finished(completed: Future[None]) -> None:
            with self._lock:
                futures = self._futures.get(job.job_id)
                if futures is not None:
                    futures.discard(completed)
                    if not futures:
                        self._futures.pop(job.job_id, None)

        future.add_done_callback(finished)

    def _submit_download(self, job: DownloadJob, device_root: Path) -> None:
        future = self._download_executor.submit(self._download_stage, job, device_root)
        self._track_future(job, future)

    def _submit_conversion(
        self, job: DownloadJob, device_root: Path, work: Path, source: Path
    ) -> None:
        future = self._convert_executor.submit(
            self._conversion_stage, job, device_root, work, source
        )
        self._track_future(job, future)

    def _submit_transfer(
        self, job: DownloadJob, device_root: Path, work: Path, cached: Path
    ) -> None:
        future = self._transfer_executor.submit(
            self._transfer_stage, job, device_root, work, cached
        )
        self._track_future(job, future)

    @staticmethod
    def _raise_if_cancelled(job: DownloadJob) -> None:
        if job.cancel_requested:
            raise DownloadCancelled("Operation cancelled")

    def _handle_failure(self, job: DownloadJob, exc: Exception) -> None:
        job.error = str(exc)
        if job.cancel_requested or isinstance(exc, (DownloadCancelled, InterruptedError)):
            self._update(job, JobStatus.CANCELLED)
        else:
            self._update(job, JobStatus.FAILED)

    def _download_stage(self, job: DownloadJob, device_root: Path) -> None:
        work = self.cache_dir / "jobs" / job.job_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            self._raise_if_cancelled(job)
            self._update(job, JobStatus.DOWNLOADING, 0)
            source = self.downloader.download(
                job.track,
                work,
                lambda p: self._update(job, progress=p // 2),
                lambda: job.cancel_requested,
            )
            self._raise_if_cancelled(job)
            self._update(job, JobStatus.CONVERTING, 50)
            self._submit_conversion(job, device_root, work, source)
        except Exception as exc:
            self._handle_failure(job, exc)

    def _conversion_stage(
        self, job: DownloadJob, device_root: Path, work: Path, source: Path
    ) -> None:
        try:
            self._raise_if_cancelled(job)
            cached = work / track_filename(job.track.artist, job.track.title)
            job.cached_mp3 = self.converter.convert(
                source,
                cached,
                job.track,
                lambda p: self._update(job, progress=50 + p // 4),
                lambda: job.cancel_requested,
            )
            self._raise_if_cancelled(job)
            self._update(job, JobStatus.WAITING, 75)
            self._submit_transfer(job, device_root, work, job.cached_mp3)
        except Exception as exc:
            self._handle_failure(job, exc)

    def _transfer_stage(
        self, job: DownloadJob, device_root: Path, work: Path, cached: Path
    ) -> None:
        try:
            self._raise_if_cancelled(job)
            self._update(job, JobStatus.TRANSFERRING, 75)
            target = job.destination / cached.name
            self.transfer.transfer(
                cached,
                target,
                device_root,
                lambda p: self._update(job, progress=75 + p // 4),
                lambda: job.cancel_requested,
            )
            self._update(job, JobStatus.COMPLETE, 100)
            shutil.rmtree(work, ignore_errors=True)
        except Exception as exc:
            self._handle_failure(job, exc)

    def cancel(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            if job := self.jobs.get(job_id):
                job.cancel_requested = True
                with self._lock:
                    futures = list(self._futures.get(job_id, set()))
                cancelled = [future.cancel() for future in futures]
                if any(cancelled):
                    self._update(job, JobStatus.CANCELLED)

    def retry(self, job_ids: list[str], device_root: Path) -> None:
        for job_id in job_ids:
            job = self.jobs.get(job_id)
            if job and job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                job.cancel_requested = False
                job.error = ""
                self._update(job, JobStatus.QUEUED, 0)
                self._submit_download(job, device_root)

    def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.status not in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED}:
                job.cancel_requested = True
        self._download_executor.shutdown(wait=False, cancel_futures=True)
        self._convert_executor.shutdown(wait=False, cancel_futures=True)
        self._transfer_executor.shutdown(wait=False, cancel_futures=True)
