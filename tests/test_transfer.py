import os
import shutil
import stat
from pathlib import Path

import pytest

from shokz_refill.transfer import TransferManager


def test_transfer_success_and_collision(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"abcdef" * 100)
    manager = TransferManager(tmp_path / "state.json", chunk_size=23)
    target = manager.transfer(source, root / "song.mp3", root)
    assert target.read_bytes() == source.read_bytes()
    second = manager.transfer(source, root / "song.mp3", root)
    assert second.name == "song 2.mp3"


def test_interrupted_transfer_resumes(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(bytes(range(256)) * 100)
    state = tmp_path / "state.json"
    manager = TransferManager(state, chunk_size=100)
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 5

    with pytest.raises(InterruptedError):
        manager.transfer(source, root / "song.mp3", root, cancelled=cancel)
    partial = next(root.glob("*.part"))
    previous_size = partial.stat().st_size
    assert previous_size > 0
    restarted = TransferManager(state, chunk_size=100)
    resumed, errors = restarted.resume_for_device(root)
    assert errors == []
    result = resumed[0]
    assert result.read_bytes() == source.read_bytes()
    assert not list(root.glob("*.part"))
    assert state.read_text(encoding="utf-8").strip() == "{}"


def test_transfer_blocks_outside_destination(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source"
    source.write_bytes(b"data")
    with pytest.raises(ValueError):
        TransferManager(tmp_path / "state.json").transfer(source, tmp_path / "bad.mp3", root)


def test_transfer_reports_low_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source"
    source.write_bytes(b"too large")
    usage = shutil.disk_usage(root)
    monkeypatch.setattr(
        "shokz_refill.transfer.shutil.disk_usage",
        lambda _path: usage._replace(free=1),
    )
    with pytest.raises(OSError, match="enough free space"):
        TransferManager(tmp_path / "state.json").transfer(source, root / "song.mp3", root)


def interrupted_copy(tmp_path: Path) -> tuple[TransferManager, Path, Path, Path]:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"abcdefghij")
    manager = TransferManager(tmp_path / "state.json", chunk_size=2)
    stop = False

    def progress(value: int) -> None:
        nonlocal stop
        stop = value >= 40

    with pytest.raises(InterruptedError):
        manager.transfer(source, root / "song.mp3", root, progress, lambda: stop)
    return manager, source, root, next(root.glob("*.part"))


def test_resume_rejects_corrupt_prefix_without_touching_partial(tmp_path: Path) -> None:
    manager, source, root, partial = interrupted_copy(tmp_path)
    partial.write_bytes(b"XXXX")
    with pytest.raises(ValueError, match="content does not match"):
        manager.transfer(source, root / "song.mp3", root)
    assert partial.read_bytes() == b"XXXX"
    assert not (root / "song.mp3").exists()


@pytest.mark.parametrize("kind", ["outside", "unrelated", "symlink", "hardlink"])
def test_resume_rejects_unsafe_partials(tmp_path: Path, kind: str) -> None:
    import json
    import os

    manager, source, root, partial = interrupted_copy(tmp_path)
    protected = tmp_path / "protected.mp3"
    protected.write_bytes(b"KEEP")
    states = json.loads(manager.state_path.read_text())
    state = next(iter(states.values()))
    if kind == "outside":
        state["partial"] = str(protected)
    elif kind == "unrelated":
        unrelated = root / "user.mp3"
        unrelated.write_bytes(b"KEEP")
        state["partial"] = str(unrelated)
    else:
        partial.unlink()
        try:
            if kind == "symlink":
                partial.symlink_to(protected)
            else:
                os.link(protected, partial)
        except OSError:
            pytest.skip("Host does not permit this link type")
    manager.state_path.write_text(json.dumps(states))
    with pytest.raises(ValueError, match="partial|regular file|link"):
        manager.transfer(source, root / "song.mp3", root)
    assert protected.read_bytes() == b"KEEP"
    assert not (root / "song.mp3").exists()


def test_resume_rejects_changed_source_and_preserves_partial(tmp_path: Path) -> None:
    manager, source, root, partial = interrupted_copy(tmp_path)
    previous = partial.read_bytes()
    source.write_bytes(b"changed!!!")
    with pytest.raises(ValueError, match="source changed"):
        manager.transfer(source, root / "song.mp3", root)
    assert partial.read_bytes() == previous


def test_resume_requires_only_remaining_free_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, source, root, _partial = interrupted_copy(tmp_path)
    usage = shutil.disk_usage(root)
    monkeypatch.setattr(
        "shokz_refill.transfer.shutil.disk_usage", lambda _p: usage._replace(free=6)
    )
    result = manager.transfer(source, root / "song.mp3", root)
    assert result.read_bytes() == source.read_bytes()


def test_finalization_preserves_late_conflict(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"new audio")
    destination = root / "song.mp3"

    def progress(value: int) -> None:
        if value == 100 and not destination.exists():
            destination.write_bytes(b"user audio")

    result = TransferManager(tmp_path / "state.json").transfer(source, destination, root, progress)
    assert destination.read_bytes() == b"user audio"
    assert result.name == "song 2.mp3"
    assert result.read_bytes() == source.read_bytes()


@pytest.mark.skipif(os.name == "nt", reason="Windows locks the directory while the partial is open")
def test_destination_replaced_during_copy_fails_without_complete_file(tmp_path: Path) -> None:
    root = tmp_path / "device"
    folder = root / "music"
    folder.mkdir(parents=True)
    source = tmp_path / "source.mp3"
    source.write_bytes(b"abcdefghij")
    detached = root / "detached"

    def progress(value: int) -> None:
        if value >= 20 and not detached.exists():
            folder.rename(detached)
            folder.mkdir()

    with pytest.raises(OSError, match="changed"):
        TransferManager(tmp_path / "state.json", chunk_size=2).transfer(
            source, folder / "song.mp3", root, progress
        )
    assert not (folder / "song.mp3").exists()
    assert list(detached.glob("*.part"))


def test_changed_destination_identity_preserves_partial_on_all_platforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    folder = root / "music"
    folder.mkdir(parents=True)
    source = tmp_path / "source.mp3"
    source.write_bytes(b"abcdefghij")
    changed = False
    original_stat = Path.stat

    def device_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        info = original_stat(path, follow_symlinks=follow_symlinks)
        if path == folder and changed:
            values = list(info)
            values[stat.ST_INO] += 1
            return os.stat_result(values)
        return info

    def progress(value: int) -> None:
        nonlocal changed
        if value >= 20:
            changed = True

    monkeypatch.setattr(Path, "stat", device_stat)
    with pytest.raises(OSError, match="changed"):
        TransferManager(tmp_path / "state.json", chunk_size=2).transfer(
            source, folder / "song.mp3", root, progress
        )
    assert not (folder / "song.mp3").exists()
    assert list(folder.glob("*.part"))


def test_cancellation_at_end_keeps_partial_for_explicit_resume(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    stop = False

    def progress(value: int) -> None:
        nonlocal stop
        stop = value == 100

    manager = TransferManager(tmp_path / "state.json")
    with pytest.raises(InterruptedError):
        manager.transfer(source, root / "song.mp3", root, progress, lambda: stop)
    assert not (root / "song.mp3").exists()
    completed, errors = manager.resume_for_device(root)
    assert not errors and completed[0].read_bytes() == b"audio"


def test_corrupt_journal_fails_closed(tmp_path: Path) -> None:
    manager, source, root, partial = interrupted_copy(tmp_path)
    manager.state_path.write_text('{"broken": 42}')
    with pytest.raises(ValueError, match="Invalid transfer state"):
        manager.transfer(source, root / "song.mp3", root)
    assert partial.exists()


def test_final_hash_rejects_content_modified_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shokz_refill import transfer

    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"abcdefghij")
    fingerprint = transfer._fingerprint

    def corrupt_before_verification(path, cancelled):  # type: ignore[no-untyped-def]
        if path.name.endswith(".part"):
            path.write_bytes(b"XXXXXXXXXX")
        return fingerprint(path, cancelled)

    monkeypatch.setattr(transfer, "_fingerprint", corrupt_before_verification)
    with pytest.raises(OSError, match="integrity"):
        TransferManager(tmp_path / "state.json").transfer(source, root / "song.mp3", root)
    assert not (root / "song.mp3").exists()
    assert next(root.glob("*.part")).read_bytes() == b"XXXXXXXXXX"


def test_readonly_copy_fails_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")

    def readonly(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("Read-only device")

    monkeypatch.setattr("shokz_refill.transfer._open_partial", readonly)
    with pytest.raises(PermissionError, match="Read-only"):
        TransferManager(tmp_path / "state.json").transfer(source, root / "song.mp3", root)
    assert not list(root.iterdir())


def test_waiting_device_operation_can_be_cancelled() -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from shokz_refill.filesystem import device_operation

    started = threading.Event()
    cancelled = threading.Event()

    def waiting() -> None:
        started.set()
        with device_operation(cancelled.is_set):
            raise AssertionError("Cancelled work must not enter the device lock")

    with ThreadPoolExecutor(1) as executor, device_operation():
        future = executor.submit(waiting)
        assert started.wait(2)
        cancelled.set()
        with pytest.raises(InterruptedError):
            future.result(timeout=2)
