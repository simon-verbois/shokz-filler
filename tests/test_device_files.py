import os
import subprocess
from pathlib import Path

import pytest

from shokz_filler.device import is_within, manual_device
from shokz_filler.files import DeviceFileService
from shokz_filler.transfer import TransferManager


def _create_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        # NTFS junctions need no administrator/symlink privilege. Exercise real
        # path redirection and deletion safety on the non-admin Windows runner.
        subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)
    assert link.resolve(strict=True) == target.resolve(strict=True)


def test_path_validation_blocks_escape_and_directory_link(tmp_path: Path) -> None:
    root = tmp_path / "device"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _create_directory_link(root / "escape", outside)
    assert is_within(root, root / "folder", allow_missing=True)
    assert not is_within(root, root / ".." / "outside")
    assert not is_within(root, root / "escape" / "file.mp3", allow_missing=True)
    with pytest.raises(ValueError):
        DeviceFileService(root).checked(root / "escape" / "file.mp3", missing=True)
    with pytest.raises(ValueError, match="symbolic link|leaves the selected device"):
        DeviceFileService(root).ensure_folder(root, "escape")


def test_file_operations_and_collision(tmp_path: Path) -> None:
    root = tmp_path / "SWIM PRO"
    root.mkdir()
    service = DeviceFileService(root)
    folder = service.create_folder(root, "Music")
    assert service.ensure_folder(root, "Music") == folder
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    transfer = TransferManager(tmp_path / "transfers.json")
    first = transfer.transfer(source, folder / "song.mp3", root)
    second = transfer.transfer(source, folder / "song.mp3", root)
    assert first.name == "song.mp3"
    assert second.name == "song 2.mp3"
    renamed = service.rename(first, "new:name")
    assert renamed.name == "newname.mp3"
    service.delete(renamed)
    service.delete(second)
    service.delete(folder)
    assert manual_device(root).automatic is False


@pytest.mark.parametrize("hidden_name", ["System Volume Information", "SYSTEM", "System", "system"])
def test_list_hides_system_folders(tmp_path: Path, hidden_name: str) -> None:
    root = tmp_path / "device"
    root.mkdir()
    hidden = root / hidden_name
    hidden.mkdir()
    (root / "Music").mkdir()
    (root / "Systems").mkdir()
    (root / "system.mp3").write_bytes(b"audio")

    assert [path.name for path in DeviceFileService(root).list_dir(root)] == [
        "Music",
        "Systems",
        "system.mp3",
    ]
    assert hidden.is_dir()


def test_move_selected_items_safely(tmp_path: Path) -> None:
    root = tmp_path / "device"
    source_folder = root / "source"
    destination = root / "destination"
    source_folder.mkdir(parents=True)
    destination.mkdir()
    first = source_folder / "song.mp3"
    second = source_folder / "other.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    (destination / "song.mp3").write_bytes(b"existing")
    service = DeviceFileService(root)

    moved = service.move([first, second], destination)

    assert [path.name for path in moved] == ["song 2.mp3", "other.mp3"]
    assert (destination / "song.mp3").read_bytes() == b"existing"
    assert (destination / "song 2.mp3").read_bytes() == b"first"
    assert not first.exists() and not second.exists()


def test_move_blocks_folder_into_itself_and_outside_device(tmp_path: Path) -> None:
    root = tmp_path / "device"
    child = root / "folder" / "child"
    outside = tmp_path / "outside"
    child.mkdir(parents=True)
    outside.mkdir()
    service = DeviceFileService(root)

    with pytest.raises(ValueError, match="inside itself"):
        service.move([root / "folder"], child)
    with pytest.raises(ValueError, match="leaves the selected device"):
        service.move([root / "folder"], outside)


def test_folder_hierarchy_is_kept_flat(tmp_path: Path) -> None:
    root = tmp_path / "device"
    first = root / "first"
    second = root / "second"
    first.mkdir(parents=True)
    second.mkdir()
    service = DeviceFileService(root)

    with pytest.raises(ValueError, match="only be created at the device root"):
        service.create_folder(first, "nested")
    with pytest.raises(ValueError, match="only be created at the device root"):
        service.ensure_folder(first, "nested")
    with pytest.raises(ValueError, match="cannot be placed inside another folder"):
        service.move([first], second)


def test_delete_nonempty_folder_without_following_directory_link(tmp_path: Path) -> None:
    root = tmp_path / "device"
    folder = root / "playlist" / "nested"
    outside = tmp_path / "outside"
    folder.mkdir(parents=True)
    outside.mkdir()
    (folder / "song.mp3").write_bytes(b"song")
    protected = outside / "keep.mp3"
    protected.write_bytes(b"keep")
    _create_directory_link(folder / "outside-link", outside)

    DeviceFileService(root).delete(root / "playlist")

    assert not (root / "playlist").exists()
    assert protected.read_bytes() == b"keep"


def test_device_mutations_wait_for_active_transfer(tmp_path: Path) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    root = tmp_path / "device"
    folder = root / "music"
    folder.mkdir(parents=True)
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    copying = threading.Event()
    release = threading.Event()
    rename_started = threading.Event()

    def progress(value: int) -> None:
        if value == 0:
            copying.set()
            assert release.wait(2)

    def rename() -> Path:
        rename_started.set()
        return DeviceFileService(root).rename(folder, "renamed")

    with ThreadPoolExecutor(2) as executor:
        transfer = executor.submit(
            TransferManager(tmp_path / "state.json").transfer,
            source,
            folder / "song.mp3",
            root,
            progress,
        )
        assert copying.wait(2)
        mutation = executor.submit(rename)
        try:
            assert rename_started.wait(2)
            assert not mutation.done()
            assert folder.exists()
        finally:
            release.set()
        transfer.result(timeout=2)
        target = mutation.result(timeout=2)
        assert (target / "song.mp3").read_bytes() == b"audio"
