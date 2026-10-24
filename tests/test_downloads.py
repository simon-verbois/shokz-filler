import threading
import time
from pathlib import Path

from shokz_refill.downloads import DownloadQueue
from shokz_refill.metadata import write_metadata
from shokz_refill.models import JobStatus, Track


class FakeDownloader:
    def download(self, track: Track, work_dir: Path, progress, cancelled) -> Path:  # type: ignore[no-untyped-def]
        path = work_dir / "source.bin"
        path.write_bytes(b"source")
        progress(100)
        return path


class FakeConverter:
    def convert(self, source: Path, output: Path, track: Track, progress, cancelled) -> Path:  # type: ignore[no-untyped-def]
        output.write_bytes(b"mp3")
        write_metadata(output, source_id=track.video_id, artist=track.artist, title=track.title)
        progress(100)
        return output


class FakeTransfer:
    def transfer(
        self, source: Path, destination: Path, device_root: Path, progress, cancelled
    ) -> Path:  # type: ignore[no-untyped-def]
        destination.write_bytes(source.read_bytes())
        progress(100)
        return destination


def wait_for_terminal(job, timeout: float = 3) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while job.status not in {
        JobStatus.COMPLETE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.SKIPPED,
    }:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Job remained {job.status}")
        time.sleep(0.01)


def test_queue_completes_repeated_tracks(tmp_path: Path) -> None:
    statuses: list[JobStatus] = []
    queue = DownloadQueue(
        tmp_path / "cache",
        FakeTransfer(),
        FakeDownloader(),
        FakeConverter(),  # type: ignore[arg-type]
        lambda job: statuses.append(job.status),
    )
    track = Track("id", "Song", ("Artist",))
    job = queue.enqueue([track], tmp_path, tmp_path)[0]
    wait_for_terminal(job)
    assert job.status == JobStatus.COMPLETE
    assert (tmp_path / "001 - Artist - Song.mp3").is_file()
    repeated_job = queue.enqueue([track], tmp_path, tmp_path)[0]
    wait_for_terminal(repeated_job)
    assert repeated_job.status == JobStatus.SKIPPED
    assert JobStatus.DOWNLOADING in statuses and JobStatus.TRANSFERRING in statuses
    queue.shutdown()


def test_downloads_continue_while_conversions_are_busy(tmp_path: Path) -> None:
    conversion_release = threading.Event()
    four_downloads_started = threading.Event()
    download_count = 0
    lock = threading.Lock()

    class TrackingDownloader(FakeDownloader):
        def download(self, track, work_dir, progress, cancelled):  # type: ignore[no-untyped-def]
            nonlocal download_count
            with lock:
                download_count += 1
                if download_count == 4:
                    four_downloads_started.set()
            return super().download(track, work_dir, progress, cancelled)

    class BlockingConverter(FakeConverter):
        def convert(self, source, output, track, progress, cancelled):  # type: ignore[no-untyped-def]
            if not conversion_release.wait(timeout=3):
                raise TimeoutError("test conversion was not released")
            return super().convert(source, output, track, progress, cancelled)

    queue = DownloadQueue(
        tmp_path / "cache",
        FakeTransfer(),
        TrackingDownloader(),
        BlockingConverter(),  # type: ignore[arg-type]
    )
    tracks = [Track(str(index), f"Song {index}", ("Artist",)) for index in range(4)]
    jobs = queue.enqueue(tracks, tmp_path, tmp_path)

    assert four_downloads_started.wait(timeout=2)
    conversion_release.set()
    for job in jobs:
        wait_for_terminal(job)
        assert job.status == JobStatus.COMPLETE
    queue.shutdown()


def test_duplicate_in_same_batch_is_skipped(tmp_path: Path) -> None:
    release = threading.Event()

    class BlockingDownloader(FakeDownloader):
        def download(self, track, work_dir, progress, cancelled):  # type: ignore[no-untyped-def]
            assert release.wait(2)
            return super().download(track, work_dir, progress, cancelled)

    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), BlockingDownloader(), FakeConverter())  # type: ignore[arg-type]
    try:
        track = Track("id", "Song")
        first, second = queue.enqueue([track, track], tmp_path, tmp_path)
        assert second.status == JobStatus.SKIPPED
        release.set()
        wait_for_terminal(first)
        assert first.status == JobStatus.COMPLETE
    finally:
        release.set()
        queue.shutdown()


def test_existing_source_id_skips_network_across_queue_instances(tmp_path: Path) -> None:
    target = tmp_path / "renamed.mp3"
    target.write_bytes(b"audio")
    write_metadata(target, source_id="id", artist="Other spelling", title="Renamed")

    class NeverDownloader(FakeDownloader):
        def download(self, *args):  # type: ignore[no-untyped-def]
            raise AssertionError("Existing track must not be downloaded")

    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), NeverDownloader(), FakeConverter())  # type: ignore[arg-type]
    try:
        job = queue.enqueue([Track("id", "Song")], tmp_path, tmp_path)[0]
        wait_for_terminal(job)
        assert job.status == JobStatus.SKIPPED
    finally:
        queue.shutdown()


def test_same_title_with_different_source_id_is_downloaded(tmp_path: Path) -> None:
    existing = tmp_path / "existing.mp3"
    existing.write_bytes(b"audio")
    write_metadata(existing, source_id="other", artist="Artist", title="Song")
    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), FakeDownloader(), FakeConverter())  # type: ignore[arg-type]
    try:
        job = queue.enqueue([Track("id", "Song", ("Artist",))], tmp_path, tmp_path)[0]
        wait_for_terminal(job)
        assert job.status == JobStatus.COMPLETE
        assert existing.exists()
    finally:
        queue.shutdown()


def test_retry_reuses_converted_cache(tmp_path: Path) -> None:
    class FailingTransfer(FakeTransfer):
        attempts = 0

        def transfer(self, *args):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("Disconnected")
            return super().transfer(*args)

    downloader = FakeDownloader()
    queue = DownloadQueue(tmp_path / "cache", FailingTransfer(), downloader, FakeConverter())  # type: ignore[arg-type]
    try:
        job = queue.enqueue([Track("id", "Song")], tmp_path, tmp_path)[0]
        wait_for_terminal(job)
        assert job.status == JobStatus.FAILED and job.cached_mp3 is not None
        deadline = time.monotonic() + 2
        while not queue.idle and time.monotonic() < deadline:
            time.sleep(0.001)

        def unexpected(*args):  # type: ignore[no-untyped-def]
            raise AssertionError("Retry must reuse cache")

        downloader.download = unexpected  # type: ignore[method-assign]
        queue.retry([job.job_id], tmp_path)
        wait_for_terminal(job)
        assert job.status == JobStatus.COMPLETE
    finally:
        queue.shutdown()


def test_shutdown_cancels_stages_and_rejects_new_jobs(tmp_path: Path) -> None:
    import pytest

    entered = threading.Event()
    released = threading.Event()

    class CancellableDownloader(FakeDownloader):
        def download(self, track, work_dir, progress, cancelled):  # type: ignore[no-untyped-def]
            entered.set()
            assert released.wait(2)
            assert cancelled()
            return super().download(track, work_dir, progress, cancelled)

    queue = DownloadQueue(
        tmp_path / "cache", FakeTransfer(), CancellableDownloader(), FakeConverter()
    )  # type: ignore[arg-type]
    try:
        job = queue.enqueue([Track("id", "Song")], tmp_path, tmp_path)[0]
        assert entered.wait(2)
        queue.shutdown()
        released.set()
        wait_for_terminal(job)
        assert job.status == JobStatus.CANCELLED
        with pytest.raises(RuntimeError, match="shutting down"):
            queue.enqueue([Track("new", "Song")], tmp_path, tmp_path)
    finally:
        released.set()
        queue.shutdown()
