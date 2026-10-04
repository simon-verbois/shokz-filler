import shutil
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
