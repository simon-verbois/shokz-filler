from pathlib import Path

import pytest

from shokz_refill.device import is_within, manual_device
from shokz_refill.files import DeviceFileService


def test_path_validation_blocks_escape_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "device"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    assert is_within(root, root / "folder", allow_missing=True)
    assert not is_within(root, root / ".." / "outside")
    assert not is_within(root, root / "escape" / "file.mp3", allow_missing=True)
    with pytest.raises(ValueError):
        DeviceFileService(root).checked(root / "escape" / "file.mp3", missing=True)
    with pytest.raises(ValueError, match="symbolic link"):
        DeviceFileService(root).ensure_folder(root, "escape")


def test_file_operations_and_collision(tmp_path: Path) -> None:
    root = tmp_path / "SWIM PRO"
    root.mkdir()
    service = DeviceFileService(root)
    folder = service.create_folder(root, "Music")
    assert service.ensure_folder(root, "Music") == folder
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    first = service.import_mp3(source, folder)
    second = service.import_mp3(source, folder)
    assert first.name == "song.mp3"
    assert second.name == "song (2).mp3"
    renamed = service.rename(first, "new:name")
    assert renamed.name == "new_name.mp3"
    service.delete(renamed)
    service.delete(second)
    service.delete(folder)
    assert manual_device(root).automatic is False
