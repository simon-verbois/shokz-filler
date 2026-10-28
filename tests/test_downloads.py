import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shokz_filler.device import device_identity
from shokz_filler.downloads import DownloadQueue
from shokz_filler.metadata import write_metadata
from shokz_filler.models import JobStatus, Track


def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("The expected queue state was not reached")
        time.sleep(0.001)


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


class ControlledConverter(FakeConverter):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def convert(self, source, output, track, progress, cancelled):  # type: ignore[no-untyped-def]
        if track.video_id == "first":
            self.entered.set()
            assert self.release.wait(3)
        return super().convert(source, output, track, progress, cancelled)


def test_batches_share_positions_and_publication_order(tmp_path: Path) -> None:
    converted_second = threading.Event()
    converter = ControlledConverter()
    copied: list[str] = []

    class RecordingTransfer(FakeTransfer):
        def transfer(self, source, destination, *args):  # type: ignore[no-untyped-def]
            copied.append(destination.name)
            return super().transfer(source, destination, *args)

    def updated(job):  # type: ignore[no-untyped-def]
        if job.track.video_id == "second" and job.status == JobStatus.WAITING:
            converted_second.set()

    queue = DownloadQueue(
        tmp_path / "cache", RecordingTransfer(), FakeDownloader(), converter, updated
    )
    try:
        first = queue.enqueue([Track("first", "First")], tmp_path, tmp_path, start=1)[0]
        assert converter.entered.wait(2)
        second = queue.enqueue([Track("second", "Second")], tmp_path, tmp_path, start=1)[0]
        assert converted_second.wait(2)
        assert [first.position, second.position] == [1, 2]
        assert copied == []
        converter.release.set()
        wait_until(lambda: queue.idle)
        assert [first.status, second.status] == [JobStatus.COMPLETE] * 2
        assert copied == ["001 - Unknown Artist - First.mp3", "002 - Unknown Artist - Second.mp3"]
    finally:
        converter.release.set()
        queue.shutdown()
        wait_until(lambda: queue.idle)


def test_cancelling_a_gated_job_finishes_it_and_allows_retry(tmp_path: Path) -> None:
    converter = ControlledConverter()
    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), FakeDownloader(), converter)
    try:
        first, second, third = queue.enqueue(
            [Track("first", "First"), Track("second", "Second"), Track("third", "Third")],
            tmp_path,
            tmp_path,
        )
        assert converter.entered.wait(2)
        wait_until(
            lambda: second.status == JobStatus.WAITING and second.job_id not in queue._futures
        )
        queue.cancel([second.job_id])
        assert second.status == JobStatus.CANCELLED
        assert not queue.idle
        converter.release.set()
        wait_until(lambda: queue.idle)
        assert [first.status, third.status] == [JobStatus.COMPLETE] * 2
        assert not list(tmp_path.glob("002*.mp3"))
        queue.retry([second.job_id], tmp_path)
        wait_until(lambda: queue.idle)
        assert second.status == JobStatus.COMPLETE
    finally:
        converter.release.set()
        queue.shutdown()
        wait_until(lambda: queue.idle)


def test_replaced_device_during_download_never_receives_music(tmp_path: Path) -> None:
    root = tmp_path / "device"
    folder = root / "Music"
    folder.mkdir(parents=True)

    class SwappingDownloader(FakeDownloader):
        def download(self, *args):  # type: ignore[no-untyped-def]
            root.rename(tmp_path / "detached")
            (root / "Music").mkdir(parents=True)
            return super().download(*args)

    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), SwappingDownloader(), FakeConverter())
    try:
        job = queue.enqueue([Track("id", "Song")], folder, root)[0]
        wait_until(lambda: queue.idle)
        assert job.status == JobStatus.FAILED
        assert "device changed" in job.error.lower()
        assert not list(root.rglob("*.mp3"))
        queue.retry([job.job_id], root)
        wait_until(lambda: queue.idle)
        assert job.status == JobStatus.FAILED
        assert not list(root.rglob("*.mp3"))
    finally:
        queue.shutdown()
        wait_until(lambda: queue.idle)


def test_selected_identity_is_checked_before_the_download_starts(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    original = device_identity(root)
    root.rename(tmp_path / "detached")
    root.mkdir()

    class UnexpectedDownloader(FakeDownloader):
        def download(self, *args):  # type: ignore[no-untyped-def]
            raise AssertionError("A changed device must fail before downloading")

    queue = DownloadQueue(
        tmp_path / "cache", FakeTransfer(), UnexpectedDownloader(), FakeConverter()
    )
    try:
        job = queue.enqueue([Track("id", "Song")], root, root, expected_device=original)[0]
        wait_until(lambda: queue.idle)
        assert job.status == JobStatus.FAILED
        assert "device changed" in job.error.lower()
    finally:
        queue.shutdown()


def test_simultaneous_enqueues_reserve_unique_positions(tmp_path: Path) -> None:
    entered = threading.Barrier(3)
    release = threading.Event()

    class BlockingDownloader(FakeDownloader):
        def download(self, *args):  # type: ignore[no-untyped-def]
            assert release.wait(3)
            return super().download(*args)

    queue = DownloadQueue(tmp_path / "cache", FakeTransfer(), BlockingDownloader(), FakeConverter())

    def enqueue(number: int):  # type: ignore[no-untyped-def]
        entered.wait(timeout=2)
        return queue.enqueue([Track(str(number), str(number))], tmp_path, tmp_path, start=1)[0]

    try:
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(enqueue, number) for number in (1, 2)]
            entered.wait(timeout=2)
            jobs = [future.result(timeout=2) for future in futures]
        assert sorted(job.position for job in jobs) == [1, 2]
        release.set()
        wait_until(lambda: queue.idle)
        assert all(job.status == JobStatus.COMPLETE for job in jobs)
    finally:
        release.set()
        queue.shutdown()
        wait_until(lambda: queue.idle)
