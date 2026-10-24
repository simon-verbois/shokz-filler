"""Bounded audiobook workflow; each book's parts are published strictly in playback order."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .audiobook_models import Audiobook, AudioSource, export_plan
from .audiobook_normalizer import AudiobookNormalizer
from .audiobookshelf import AudiobookshelfClient
from .book_export import BookExportOptions
from .cancellation import current_cancellation
from .downloads import JobCallback
from .files import DeviceFileService
from .filesystem import device_operation
from .media import Cancelled, Progress
from .metadata import read_identity
from .models import DownloadJob, JobStatus, Track
from .naming import collision_path
from .transfer import TransferManager

MAX_CONCURRENT_BOOKS = 1

TERMINAL = {JobStatus.COMPLETE, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}


class BookClient(Protocol):
    def book(self, item_id: str) -> Audiobook: ...
    def download(
        self, source: AudioSource, output: Path, progress: Progress, cancelled: Cancelled
    ) -> Path: ...


@dataclass
class BookWork:
    client: BookClient
    server: str
    item_id: str
    options: BookExportOptions
    export_identity: str = ""


class AudiobookQueue:
    def __init__(
        self,
        cache_dir: Path,
        transfer: TransferManager,
        callback: JobCallback = lambda _job: None,
        normalizer: AudiobookNormalizer | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.transfer = transfer
        self.callback = callback
        self.normalizer = normalizer or AudiobookNormalizer()
        self.jobs: dict[str, DownloadJob] = {}
        self.work: dict[str, BookWork] = {}
        self._executor = ThreadPoolExecutor(MAX_CONCURRENT_BOOKS, "shokz-audiobook")
        self._futures: dict[str, Future[None]] = {}
        self._events: dict[str, threading.Event] = {}
        self._closed = False
        self._lock = threading.RLock()

    def enqueue(
        self,
        books: list[Audiobook],
        device_root: Path,
        client: AudiobookshelfClient,
        *,
        options: BookExportOptions | None = None,
    ) -> list[DownloadJob]:
        if not client.connection.can_download:
            raise PermissionError("This Audiobookshelf account cannot download audio")
        options = options or BookExportOptions()
        options.validate()
        created: list[DownloadJob] = []
        server = client.connection.server
        with self._lock:
            if self._closed:
                raise RuntimeError("Audiobook queue is closing")
            for book in books:
                destination = device_root / book.folder_name(server)
                identity = (
                    "audiobookshelf:"
                    + hashlib.sha256(f"{server}:{book.item_id}".encode()).hexdigest()
                )
                job = DownloadJob(
                    uuid.uuid4().hex,
                    Track(identity, book.title, (book.author,), album="Audiobookshelf"),
                    destination,
                    device_root=device_root,
                )
                duplicate = any(
                    other.track.video_id == identity
                    and other.device_root == device_root
                    and other.status not in TERMINAL
                    for other in self.jobs.values()
                )
                self.jobs[job.job_id] = job
                self._events[job.job_id] = threading.Event()
                self.work[job.job_id] = BookWork(client, server, book.item_id, options)
                created.append(job)
                if duplicate:
                    self._update(job, JobStatus.SKIPPED, 100, "This book is already queued")
                else:
                    self._update(job, JobStatus.QUEUED, 0)
                    self._submit(job)
        return created

    def _update(self, job: DownloadJob, status: JobStatus, progress: int, detail: str = "") -> None:
        job.status, job.progress, job.error = status, progress, detail
        self.callback(replace(job))

    def _submit(self, job: DownloadJob) -> None:
        self._futures[job.job_id] = self._executor.submit(self._run, job)

    @staticmethod
    def _cancelled(job: DownloadJob) -> bool:
        return job.cancel_requested

    @staticmethod
    def _check(job: DownloadJob) -> None:
        if job.cancel_requested:
            raise InterruptedError(
                "Audiobook cancelled; cached audio and partial transfers were kept for retry"
            )

    def _prepare_destination(self, root: Path, preferred: Path, identities: set[str]) -> Path:
        service = DeviceFileService(root)
        pattern = re.compile(re.escape(preferred.name) + r"(?: [0-9]+)?$")
        for candidate in service.list_dir(root):
            if candidate.is_dir() and pattern.fullmatch(candidate.name):
                files = [path for path in candidate.iterdir() if path.suffix.lower() == ".mp3"]
                # A shared first chapter alone cannot prove that the other files match this export.
                if files and len(self._present(candidate, identities)) == len(files):
                    return candidate
        if preferred.is_dir() and not preferred.is_symlink():
            safe = service.checked(preferred)
            if not any(path.suffix.lower() == ".mp3" for path in safe.iterdir()):
                return safe
        while True:
            destination = collision_path(preferred)
            try:
                return service.create_folder(root, destination.name)
            except FileExistsError:
                continue

    def _run(self, job: DownloadJob) -> None:
        token = current_cancellation.set(self._events[job.job_id])
        work = self.work[job.job_id]
        cache = self.cache_dir / "jobs" / job.job_id

        def cancelled() -> bool:
            return self._cancelled(job)

        try:
            self._check(job)
            root = job.device_root
            if root is None:
                raise ValueError("Missing destination device")
            stat = root.stat()
            device_identity = (stat.st_dev, stat.st_ino)

            def check_device() -> None:
                self._check(job)
                current = root.stat()
                if (current.st_dev, current.st_ino) != device_identity:
                    raise OSError(
                        "Selected device changed or disconnected; select it again and retry"
                    )

            self._update(job, JobStatus.DOWNLOADING, 0, "Reading audiobook chapter order")
            book = work.client.book(work.item_id)
            parts = export_plan(book)
            work.options.text(book.title, book.author)
            identities = [
                part.source_id(
                    work.server,
                    book,
                    work.options.fingerprint(book.title, book.author, part.number, part.title),
                )
                for part in parts
            ]
            # Track the complete revision, including other chapters' announcements, across retries.
            export_identity = hashlib.sha256(json.dumps(identities).encode()).hexdigest()
            # Old revisions can still back resumable partials; never overwrite their cached sources.
            cache = cache / export_identity
            for part in parts:
                self.normalizer.check_size(sum(segment.duration for segment in part.segments))
            with device_operation(cancelled):
                check_device()
                if work.export_identity != export_identity:
                    job.destination = self._prepare_destination(
                        root, root / book.folder_name(work.server), set(identities)
                    )
                    work.export_identity = export_identity
                present = self._present(job.destination, set(identities))
            pending = [
                (part, identity)
                for part, identity in zip(parts, identities, strict=True)
                if identity not in present
            ]
            if not pending:
                self._update(
                    job, JobStatus.SKIPPED, 100, "This complete audiobook is already present"
                )
                return
            cache.mkdir(parents=True, exist_ok=True)
            needed = sorted({s.source_index for part, _ in pending for s in part.segments})
            sources: dict[int, Path] = {}
            for ordinal, index in enumerate(needed):
                source = next(source for source in book.sources if source.index == index)
                sources[index] = self._source(job, work, source, cache, ordinal, len(needed))
            for position, (part, identity) in enumerate(pending):
                self._check(job)
                base = 45 + position * 55 // len(pending)
                span = 55 // len(pending)
                label = f"Chapter {part.number}/{len(parts)}: {part.title}"
                output = cache / part.filename
                if not self._valid_cache(output, identity):
                    self._update(job, JobStatus.CONVERTING, base, f"Converting {label}")
                    self.normalizer.convert(
                        part,
                        book,
                        sources,
                        output,
                        identity,
                        len(parts),
                        cancelled,
                        self._converting(job, base, span, label),
                        options=work.options,
                    )
                self._check(job)
                # Strictly one file at a time, in playback order: Shokz players follow the
                # transmission order, and the zero-padded names keep name sorting identical.
                with device_operation(cancelled):
                    check_device()
                    if identity not in self._present(job.destination, {identity}):
                        self._update(
                            job,
                            JobStatus.TRANSFERRING,
                            base + int(span * 0.7),
                            f"Copying {label}",
                        )
                        self.transfer.transfer(
                            output,
                            job.destination / part.filename,
                            root,
                            self._copying(job, base, span),
                            cancelled,
                        )
                output.unlink(missing_ok=True)
            self._update(
                job,
                JobStatus.COMPLETE,
                100,
                f"{len(parts)} ordered MP3 files in {job.destination.name}",
            )
            shutil.rmtree(cache, ignore_errors=True)
        except Exception as exc:
            self._update(
                job,
                JobStatus.CANCELLED
                if job.cancel_requested or isinstance(exc, InterruptedError)
                else JobStatus.FAILED,
                job.progress,
                str(exc),
            )
        finally:
            current_cancellation.reset(token)

    def _converting(self, job: DownloadJob, base: int, span: int, label: str) -> Progress:
        def report(percent: int) -> None:
            self._update(
                job,
                JobStatus.CONVERTING,
                base + int(percent * span * 0.7 / 100),
                f"Converting {label}",
            )

        return report

    def _copying(self, job: DownloadJob, base: int, span: int) -> Progress:
        def report(percent: int) -> None:
            self._update(
                job,
                JobStatus.TRANSFERRING,
                base + int(span * (0.7 + percent * 0.3 / 100)),
                job.error,
            )

        return report

    @staticmethod
    def _present(destination: Path, identities: set[str]) -> set[str]:
        return {
            found
            for path in destination.iterdir()
            if not path.is_symlink()
            and path.suffix.lower() == ".mp3"
            and (found := read_identity(path).source_id) in identities
        }

    def _valid_cache(self, output: Path, identity: str) -> bool:
        if not output.is_file() or read_identity(output).source_id != identity:
            return False
        try:
            self.normalizer.validator(output)
            return True
        except (ValueError, OSError):
            return False

    def _source(
        self,
        job: DownloadJob,
        work: BookWork,
        source: AudioSource,
        cache: Path,
        part: int,
        total: int,
    ) -> Path:
        identity = hashlib.sha256(
            json.dumps((source.download_path, source.size, source.modified)).encode()
        ).hexdigest()
        output = cache / f"source-{source.index}.audio"
        manifest = output.with_suffix(".json")
        try:
            saved = json.loads(manifest.read_text())
            if (
                isinstance(saved, dict)
                and saved.get("identity") == identity
                and output.is_file()
                and output.stat().st_size == saved.get("size")
                and self._digest(output, job) == saved.get("sha256")
            ):
                return output
        except (ValueError, OSError):
            pass
        self._check(job)
        result = work.client.download(
            source,
            output,
            lambda progress: self._update(
                job,
                JobStatus.DOWNLOADING,
                int((part + progress / 100) * 45 / total),
                f"Downloading source {source.index}: {source.filename}",
            ),
            lambda: self._cancelled(job),
        )
        manifest.write_text(
            json.dumps(
                {
                    "identity": identity,
                    "size": result.stat().st_size,
                    "sha256": self._digest(result, job),
                }
            )
        )
        return result

    @staticmethod
    def _digest(path: Path, job: DownloadJob) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                AudiobookQueue._check(job)
                digest.update(chunk)
        return digest.hexdigest()

    def cancel(self, ids: list[str]) -> None:
        with self._lock:
            for key in ids:
                job = self.jobs.get(key)
                if job is not None and job.status not in TERMINAL:
                    job.cancel_requested = True
                    self._events[key].set()
                    future = self._futures.get(key)
                    if future is not None and future.cancel():
                        self._update(job, JobStatus.CANCELLED, job.progress, "Book cancelled")

    def retry(self, ids: list[str], root: Path, client: AudiobookshelfClient | None) -> None:
        with self._lock:
            if self._closed:
                return
            for key in ids:
                job = self.jobs.get(key)
                if job is None or job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    continue
                if not self._futures[key].done():
                    continue
                work = self.work[key]
                if any(
                    other.job_id != job.job_id
                    and other.track.video_id == job.track.video_id
                    and other.device_root == job.device_root
                    and other.status not in TERMINAL
                    for other in self.jobs.values()
                ):
                    self._update(job, job.status, job.progress, "This book is already queued")
                    continue
                if (
                    client is None
                    or not client.connection.can_download
                    or client.connection.server != work.server
                    or root != job.device_root
                ):
                    self._update(
                        job,
                        job.status,
                        job.progress,
                        "Reconnect the original server and device to retry",
                    )
                    continue
                work.client = client
                job.cancel_requested = False
                self._events[key].clear()
                self._update(job, JobStatus.QUEUED, 0)
                self._submit(job)

    @property
    def idle(self) -> bool:
        with self._lock:
            return all(future.done() for future in self._futures.values())

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self.cancel(list(self.jobs))
            self._executor.shutdown(wait=False, cancel_futures=True)
