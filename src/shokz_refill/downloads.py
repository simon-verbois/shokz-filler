from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .device import is_within
from .filesystem import device_operation
from .media import AudioConverter, DownloadCancelled, MediaDownloader
from .metadata import read_identity
from .models import DownloadJob, JobStatus, Track
from .naming import track_filename
from .playback_order import OrderGate, next_position, ordered_name

MAX_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_CONVERSIONS = 2
MAX_CONCURRENT_TRANSFERS = 1
JobCallback = Callable[[DownloadJob], None]
_TERMINAL = {JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.COMPLETE, JobStatus.SKIPPED}


class Downloader(Protocol):
    def download(
        self,
        track: Track,
        work_dir: Path,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool],
    ) -> Path: ...


class Converter(Protocol):
    def convert(
        self,
        source: Path,
        output: Path,
        track: Track,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool],
    ) -> Path: ...


class Transfer(Protocol):
    def transfer(
        self,
        source: Path,
        destination: Path,
        device_root: Path,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool],
    ) -> Path: ...


def cleanup_stale_cache(cache_dir: Path, state_path: Path, *, max_age_days: int = 14) -> None:
    jobs_dir = cache_dir / "jobs"
    if not jobs_dir.is_dir():
        return
    protected: set[Path] = set()
    try:
        import json

        states = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(states, dict) or any(
            not isinstance(state, dict) for state in states.values()
        ):
            return  # An unreadable journal cannot authorize deletion of cached sources.
        if isinstance(states, dict):
            protected = {
                Path(str(state["source"])).resolve()
                for state in states.values()
                if isinstance(state, dict) and "source" in state
            }
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        return
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
        transfer: Transfer,
        downloader: Downloader | None = None,
        converter: Converter | None = None,
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
        self._lock = threading.RLock()
        self._closed = False
        self._gates: dict[str, OrderGate] = {}

    def enqueue(
        self,
        tracks: list[Track],
        destination: Path,
        device_root: Path,
        *,
        ordered: bool = True,
        start: int | None = None,
    ) -> list[DownloadJob]:
        """Queue tracks; `ordered` numbers the files and publishes them in the given order.

        `start` is the first playback position; callers on the UI thread compute it in a worker
        (`next_position` lists the device folder) and pass it in.
        """
        if self._closed:
            raise RuntimeError("The download queue is shutting down")
        created: list[DownloadJob] = []
        first = (start if start is not None else next_position(destination)) if ordered else 0
        gate = OrderGate(first) if ordered else None
        for offset, track in enumerate(tracks):
            job = DownloadJob(uuid.uuid4().hex, track, destination, device_root=device_root)
            if gate is not None:
                job.position = first + offset
                self._gates[job.job_id] = gate
            duplicate = any(
                item.track.video_id == track.video_id
                and item.destination == destination
                and item.status
                not in {
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                    JobStatus.COMPLETE,
                    JobStatus.SKIPPED,
                }
                for item in self.jobs.values()
            )
            self.jobs[job.job_id] = job
            created.append(job)
            if duplicate:
                job.error = "This track is already queued for this folder"
                self._update(job, JobStatus.SKIPPED, 100)
            else:
                self.callback(replace(job))
                self._submit_download(job, device_root)
        return created

    def _update(
        self, job: DownloadJob, status: JobStatus | None = None, progress: int | None = None
    ) -> None:
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if job.status in _TERMINAL and job.position is not None:
            gate = self._gates.get(job.job_id)
            if gate is not None:
                gate.skip(job.position)
        self.callback(replace(job))

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

    def _submit(
        self,
        executor: ThreadPoolExecutor,
        function: Callable[..., None],
        job: DownloadJob,
        *args: object,
    ) -> None:
        with self._lock:
            if self._closed:
                raise DownloadCancelled("Application is closing")
            future = executor.submit(function, job, *args)
            self._track_future(job, future)

    def _submit_download(self, job: DownloadJob, device_root: Path) -> None:
        self._submit(self._download_executor, self._download_stage, job, device_root)

    def _submit_conversion(
        self, job: DownloadJob, device_root: Path, work: Path, source: Path
    ) -> None:
        self._submit(self._convert_executor, self._conversion_stage, job, device_root, work, source)

    def _submit_transfer(
        self, job: DownloadJob, device_root: Path, work: Path, cached: Path
    ) -> None:
        gate = self._gates.get(job.job_id)
        if gate is None or job.position is None or gate.passed(job.position):
            self._release_transfer(job, device_root, work, cached)
            return

        def release() -> None:
            try:
                self._release_transfer(job, device_root, work, cached)
            except Exception as exc:
                self._handle_failure(job, exc)

        gate.ready(job.position, release)

    def _release_transfer(
        self, job: DownloadJob, device_root: Path, work: Path, cached: Path
    ) -> None:
        self._submit(self._transfer_executor, self._transfer_stage, job, device_root, work, cached)

    @staticmethod
    def _cached_name(job: DownloadJob) -> str:
        title = f"{job.track.artist} - {job.track.title}"
        if job.position is None:
            return track_filename(job.track.artist, job.track.title)
        # Three digits keep names sortable for any realistic playlist size.
        return ordered_name(job.position, 999, title)

    @property
    def idle(self) -> bool:
        with self._lock:
            return not any(
                not future.done() for group in self._futures.values() for future in group
            )

    @staticmethod
    def _already_present(job: DownloadJob) -> bool:
        # IDs are authoritative; filenames and artist/title guesses are deliberately not.
        return any(
            not path.is_symlink()
            and path.suffix.casefold() == ".mp3"
            and read_identity(path).source_id == job.track.video_id
            for path in job.destination.iterdir()
            if path.is_file()
        )

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
        try:
            work.mkdir(parents=True, exist_ok=True)
            self._raise_if_cancelled(job)
            if not is_within(device_root, job.destination):
                raise ValueError("Invalid download destination")
            with device_operation(lambda: job.cancel_requested):
                if self._already_present(job):
                    self._update(job, JobStatus.SKIPPED, 100)
                    shutil.rmtree(work, ignore_errors=True)
                    return
            if job.cached_mp3 is not None and job.cached_mp3.is_file():
                self._submit_transfer(job, device_root, work, job.cached_mp3)
                return
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
            cached = work / self._cached_name(job)
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
            with device_operation(lambda: job.cancel_requested):
                if self._already_present(job):
                    self._update(job, JobStatus.SKIPPED, 100)
                    shutil.rmtree(work, ignore_errors=True)
                    return
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
            if (job := self.jobs.get(job_id)) and job.status not in {
                JobStatus.COMPLETE,
                JobStatus.SKIPPED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
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
                with self._lock:
                    if any(not future.done() for future in self._futures.get(job_id, set())):
                        continue
                if any(
                    other.job_id != job.job_id
                    and other.track.video_id == job.track.video_id
                    and other.destination == job.destination
                    and other.status
                    not in {
                        JobStatus.COMPLETE,
                        JobStatus.FAILED,
                        JobStatus.CANCELLED,
                        JobStatus.SKIPPED,
                    }
                    for other in self.jobs.values()
                ):
                    job.error = "This track is already queued for this folder"
                    self._update(job)
                    continue
                if job.device_root != device_root:
                    job.error = "Select the original device before retrying this track"
                    self._update(job)
                    continue
                job.cancel_requested = False
                job.error = ""
                self._gates.pop(job.job_id, None)  # Its slot has passed; keep the numbered name.
                self._update(job, JobStatus.QUEUED, 0)
                self._submit_download(job, device_root)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        for job in self.jobs.values():
            if job.status not in {
                JobStatus.COMPLETE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.SKIPPED,
            }:
                job.cancel_requested = True
        self._download_executor.shutdown(wait=False, cancel_futures=True)
        self._convert_executor.shutdown(wait=False, cancel_futures=True)
        self._transfer_executor.shutdown(wait=False, cancel_futures=True)
