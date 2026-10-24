import threading
import time
from pathlib import Path

from mutagen.id3 import ID3

from shokz_refill.audiobook_models import Audiobook, AudioSource, Chapter
from shokz_refill.audiobook_normalizer import AudiobookNormalizer
from shokz_refill.audiobook_queue import AudiobookQueue
from shokz_refill.audiobookshelf import AudiobookshelfClient, Connection
from shokz_refill.book_export import BookExportOptions
from shokz_refill.metadata import read_identity
from shokz_refill.models import JobStatus
from shokz_refill.transfer import TransferManager


class Client(AudiobookshelfClient):
    def __init__(self) -> None:
        super().__init__(Connection("https://server", "user", "token"))
        self.downloads: list[int] = []
        self.detail_requests = 0

    def book(self, item_id: str) -> Audiobook:
        self.detail_requests += 1
        return Audiobook(
            item_id,
            "Book",
            "Author",
            sources=(AudioSource(1, "Z.m4b", "/1", 10, 5), AudioSource(2, "A.mp3", "/2", 10, 5)),
            chapters=(Chapter("First", 0, 15), Chapter("Second", 15, 20)),
        )

    def download(self, source, output, progress, cancelled):  # type: ignore[no-untyped-def]
        self.downloads.append(source.index)
        output.write_bytes(b"audio")
        progress(100)
        return output


class FakeSpeech:
    def synthesize(self, text, output, voice, rate, cancelled):  # type: ignore[no-untyped-def]
        import wave

        with wave.open(str(output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"\0\0" * 2205)
        return output


def normalizer(commands: list[list[str]]) -> AudiobookNormalizer:
    def run(command, cancelled):  # type: ignore[no-untyped-def]
        commands.append(command)
        ID3().save(command[-1])

    return AudiobookNormalizer(
        run, lambda _p: None, lambda _name: Path("fake-ffmpeg"), FakeSpeech()
    )


def wait(queue: AudiobookQueue) -> None:
    deadline = time.monotonic() + 3
    while not queue.idle and time.monotonic() < deadline:
        time.sleep(0.001)
    assert queue.idle


def test_books_get_separate_folders_and_parts_are_transferred_in_order(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    client = Client()
    commands: list[list[str]] = []

    class RecordingTransfer(TransferManager):
        names: list[str] = []

        def transfer(self, source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.names.append(destination.name)
            return super().transfer(source, destination, *args, **kwargs)

    transfer = RecordingTransfer(tmp_path / "state.json")
    queue = AudiobookQueue(tmp_path / "cache", transfer, normalizer=normalizer(commands))
    try:
        first, second = queue.enqueue(
            [Audiobook("one", "Book", "Author"), Audiobook("two", "Book", "Author")], root, client
        )
        wait(queue)
        assert first.status == second.status == JobStatus.COMPLETE
        assert first.destination != second.destination
        assert transfer.names == ["01 - First.mp3", "02 - Second.mp3"] * 2
        assert client.downloads == [
            1,
            2,
            1,
            2,
        ]  # Each source downloaded once per book, not once per chapter.
        assert sorted(path.name for path in first.destination.glob("*.mp3")) == [
            "01 - First.mp3",
            "02 - Second.mp3",
        ]
        assert all(
            read_identity(path).source_id.startswith("audiobookshelf:")
            for path in first.destination.glob("*.mp3")
        )
        repeated = queue.enqueue([Audiobook("one", "Book", "Author")], root, client)[0]
        wait(queue)
        assert repeated.status == JobStatus.SKIPPED
        assert len(client.downloads) == 4
    finally:
        queue.shutdown()


def test_cancelled_transfer_retries_from_cache_and_skips_completed_parts(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    client = Client()
    commands: list[list[str]] = []
    stop = True
    queue: AudiobookQueue

    def update(job):  # type: ignore[no-untyped-def]
        nonlocal stop
        if stop and job.status == JobStatus.TRANSFERRING and "Chapter 2" in job.error:
            stop = False
            queue.cancel([job.job_id])

    queue = AudiobookQueue(
        tmp_path / "cache",
        TransferManager(tmp_path / "state.json", chunk_size=50),
        update,
        normalizer(commands),
    )
    try:
        job = queue.enqueue([Audiobook("one", "Book", "Author")], root, client)[0]
        wait(queue)
        assert job.status == JobStatus.CANCELLED
        assert [path.name for path in job.destination.glob("*.mp3")] == ["01 - First.mp3"]
        queue.retry([job.job_id], root, client)
        wait(queue)
        assert job.status == JobStatus.COMPLETE
        assert client.downloads == [1, 2]
        assert len(commands) == 7
        assert len(list(job.destination.glob("*.mp3"))) == 2
        assert not list(job.destination.glob("*.part"))
    finally:
        queue.shutdown()


def test_duplicate_active_book_is_skipped_and_shutdown_cancels_remaining(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    entered, release = threading.Event(), threading.Event()

    class BlockingClient(Client):
        def book(self, item_id):  # type: ignore[no-untyped-def]
            entered.set()
            assert release.wait(2)
            return super().book(item_id)

    client = BlockingClient()
    queue = AudiobookQueue(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer=normalizer([])
    )
    try:
        first, repeated = queue.enqueue(
            [Audiobook("one", "Book"), Audiobook("one", "Book")], root, client
        )
        assert repeated.status == JobStatus.SKIPPED
        assert entered.wait(2)
        queue.shutdown()
        release.set()
        wait(queue)
        assert first.status == JobStatus.CANCELLED
        assert not list(root.rglob("*.mp3"))
    finally:
        release.set()
        queue.shutdown()


def test_device_changed_during_download_never_receives_complete_mp3(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()

    class DisconnectingClient(Client):
        def download(self, source, output, progress, cancelled):  # type: ignore[no-untyped-def]
            result = super().download(source, output, progress, cancelled)
            if not (tmp_path / "detached").exists():
                root.rename(tmp_path / "detached")
                root.mkdir()
            return result

    queue = AudiobookQueue(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer=normalizer([])
    )
    try:
        job = queue.enqueue([Audiobook("one", "Book")], root, DisconnectingClient())[0]
        wait(queue)
        assert job.status == JobStatus.FAILED
        assert "device changed" in job.error.lower()
        assert not list(root.rglob("*.mp3"))
    finally:
        queue.shutdown()


def test_changed_announcement_preserves_old_export_in_separate_folder(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    client = Client()
    queue = AudiobookQueue(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer=normalizer([])
    )
    try:
        book = Audiobook("one", "Book", "Author")
        first = queue.enqueue(
            [book], root, client, options=BookExportOptions(announce=False, announce_chapters=False)
        )[0]
        wait(queue)
        original = (first.destination / "01 - First.mp3").read_bytes()
        second = queue.enqueue([book], root, client, options=BookExportOptions())[0]
        wait(queue)
        assert first.status == second.status == JobStatus.COMPLETE
        assert second.destination != first.destination
        assert (first.destination / "01 - First.mp3").read_bytes() == original
        assert len(list(second.destination.glob("*.mp3"))) == 2
        repeated = queue.enqueue([book], root, client)[0]
        wait(queue)
        assert repeated.status == JobStatus.SKIPPED
        assert repeated.destination == second.destination
    finally:
        queue.shutdown()


def test_legacy_chapter_files_are_preserved_when_creating_ordered_export(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    client = Client()
    book = Audiobook("one", "Book", "Author")
    old = root / book.folder_name(client.connection.server)
    old.mkdir()
    (old / "00001 chapter.mp3").write_bytes(b"legacy audio")
    queue = AudiobookQueue(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer=normalizer([])
    )
    try:
        job = queue.enqueue([book], root, client)[0]
        wait(queue)
        assert job.status == JobStatus.COMPLETE
        assert job.destination != old
        assert (old / "00001 chapter.mp3").read_bytes() == b"legacy audio"
        assert len(list(job.destination.glob("*.mp3"))) == 2
    finally:
        queue.shutdown()
