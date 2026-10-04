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
    queue._futures[job.job_id].result(timeout=3)
    assert job.status == JobStatus.COMPLETE
    assert (tmp_path / "Artist - Song.mp3").read_bytes() == b"mp3"
    repeated_job = queue.enqueue([track], tmp_path, tmp_path)[0]
    queue._futures[repeated_job.job_id].result(timeout=3)
    assert repeated_job.status == JobStatus.COMPLETE
    assert JobStatus.DOWNLOADING in statuses and JobStatus.TRANSFERRING in statuses
    queue.shutdown()
