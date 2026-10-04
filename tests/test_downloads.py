import threading
import time
from pathlib import Path

from shokz_refill.downloads import DownloadQueue
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
    while job.status not in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED}:
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
    assert (tmp_path / "Artist - Song.mp3").read_bytes() == b"mp3"
    repeated_job = queue.enqueue([track], tmp_path, tmp_path)[0]
    wait_for_terminal(repeated_job)
    assert repeated_job.status == JobStatus.COMPLETE
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
