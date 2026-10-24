import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shokz_refill.downloads import DownloadQueue
from shokz_refill.models import JobStatus, Track
from shokz_refill.playback_order import (
    OrderGate,
    next_position,
    ordered_name,
    plan_names,
    position_of,
)
from shokz_refill.transfer import TransferManager


def test_names_are_zero_padded_so_name_sort_equals_playback_order() -> None:
    names = plan_names([f"Track {i}" for i in range(1, 121)])
    assert names[0] == "001 - Track 1.mp3" and names[-1] == "120 - Track 120.mp3"
    assert names == sorted(names)
    assert ordered_name(3, 9, "A/B:C") == "03 - ABC.mp3"
    with pytest.raises(ValueError):
        ordered_name(0, 5, "x")


def test_next_position_continues_after_existing_numbered_files(tmp_path: Path) -> None:
    assert next_position(tmp_path) == 1
    (tmp_path / "07 - Old.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "99 - not audio.txt").write_text("x")
    assert next_position(tmp_path) == 8
    assert position_of("12 - Song.mp3") == 12 and position_of("Song.mp3") is None
    assert next_position(tmp_path / "missing") == 1


def test_gate_releases_strictly_in_order_and_skips_failed_items() -> None:
    gate = OrderGate(1)
    released: list[int] = []
    gate.ready(3, lambda: released.append(3))
    gate.ready(2, lambda: released.append(2))
    assert released == []
    gate.skip(1)
    assert released == [2, 3]
    gate.skip(4)
    gate.ready(5, lambda: released.append(5))
    assert released == [2, 3, 5] and gate.passed(5)


def test_concurrent_gate_callbacks_are_submitted_in_order() -> None:
    gate = OrderGate(1)
    entered, proceed = threading.Event(), threading.Event()
    released: list[int] = []

    def first() -> None:
        entered.set()
        assert proceed.wait(3)
        released.append(1)

    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(gate.ready, 1, first)
        try:
            assert entered.wait(2)
            gate.ready(2, lambda: released.append(2))
            assert released == []
        finally:
            proceed.set()
        future.result(timeout=2)
    assert released == [1, 2]


def test_gate_allows_reentrant_readiness_and_ignores_cancelled_slots() -> None:
    gate = OrderGate(1)
    released: list[int] = []
    gate.skip(2)
    gate.ready(2, lambda: released.append(2))

    def first() -> None:
        released.append(1)
        gate.ready(3, lambda: released.append(3))

    gate.ready(1, first)
    assert released == [1, 3]


class SlowFirstConverter:
    def __init__(self) -> None:
        import threading

        self.first_done = threading.Event()

    def convert(self, source, output, track, progress, cancelled):  # type: ignore[no-untyped-def]
        if track.video_id == "a":
            assert self.first_done.wait(0.3) is False  # A converts last...
        output.write_bytes(b"mp3")
        return output


class Downloader:
    def download(self, track, work_dir, progress, cancelled):  # type: ignore[no-untyped-def]
        path = work_dir / "src"
        path.write_bytes(b"x")
        return path


def test_music_files_are_numbered_and_copied_in_playlist_order(tmp_path: Path) -> None:
    import time

    root = tmp_path / "device"
    folder = root / "List"
    folder.mkdir(parents=True)
    copied: list[str] = []

    class Recording(TransferManager):
        def transfer(self, source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
            copied.append(destination.name)
            return super().transfer(source, destination, *args, **kwargs)

    queue = DownloadQueue(
        tmp_path / "cache",
        Recording(tmp_path / "state.json"),
        Downloader(),
        SlowFirstConverter(),
    )
    try:
        jobs = queue.enqueue([Track("a", "One", ("X",)), Track("b", "Two", ("X",))], folder, root)
        deadline = time.monotonic() + 5
        while not queue.idle and time.monotonic() < deadline:
            time.sleep(0.01)
        assert [job.status for job in jobs] == [JobStatus.COMPLETE] * 2
        assert copied == ["001 - X - One.mp3", "002 - X - Two.mp3"]
    finally:
        queue.shutdown()
