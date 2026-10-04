import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView  # noqa: E402

from shokz_refill.config import ConfigStore  # noqa: E402
from shokz_refill.device import manual_device  # noqa: E402
from shokz_refill.models import Playlist, Track  # noqa: E402
from shokz_refill.ui import MainWindow, MoveDestinationDialog  # noqa: E402


def test_background_result_reaches_ui(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    received: list[str] = []
    window._run(lambda: "result", lambda value: received.append(str(value)))
    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window.pool.waitForDone(3_000)
    window.close()
    assert received == ["result"]


def test_table_columns_have_readable_default_layout(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))

    assert window.files.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert (
        window.files.horizontalHeader().sectionResizeMode(1)
        == QHeaderView.ResizeMode.ResizeToContents
    )
    assert (
        window.files.horizontalHeader().sectionResizeMode(2)
        == QHeaderView.ResizeMode.ResizeToContents
    )
    assert window.results.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert (
        window.queue_table.horizontalHeader().sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch
    )
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def test_playlist_navigation_has_back_history(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    playlist = Playlist("playlist-id", "My Playlist")
    window._set_browser_root("Playlist search", [playlist])
    window._enter_playlist(playlist, [Track("video-id", "Song", ("Artist",))])
    assert window.browser_page.playlist == playlist
    assert window.browser_back.isEnabled()
    assert window.download_playlist_button.isEnabled()
    window._browser_go_back()
    assert window.browser_page.items == [playlist]
    assert not window.browser_back.isEnabled()
    assert window.browser_forward.isEnabled()
    window._browser_go_forward()
    assert window.browser_page.playlist == playlist
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def test_whole_playlist_creates_automatic_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    root.mkdir()
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.destination = root
    queued: list[Path] = []

    def enqueue(_tracks: object, destination: Path, _root: Path) -> list[object]:
        queued.append(destination)
        return []

    monkeypatch.setattr(window.queue, "enqueue", enqueue)
    window._prepare_playlist_download(
        Playlist("playlist-id", "Ma Playlist ÉTÉ / 2026"),
        [Track("video-id", "Song", ("Artist",))],
    )
    deadline = time.monotonic() + 3
    while not queued and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window.pool.waitForDone(3_000)
    window.close()
    assert queued == [root / "ma_playlist_été_2026"]
    assert queued[0].is_dir()


def test_double_click_track_in_playlist_uses_playlist_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    root.mkdir()
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.destination = root
    playlist = Playlist("playlist-id", "Road Trip")
    track = Track("video-id", "Song", ("Artist",))
    window._set_browser_page(window.browser_page.__class__(playlist.title, [track], playlist))
    queued: list[Path] = []

    def enqueue(_tracks: object, destination: Path, _root: Path) -> list[object]:
        queued.append(destination)
        return []

    monkeypatch.setattr(window.queue, "enqueue", enqueue)
    window._result_double_clicked(0, 0)
    deadline = time.monotonic() + 3
    while not queued and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window.pool.waitForDone(3_000)
    window.close()
    assert queued == [root / "road_trip"]


def test_device_folder_back_and_forward_history(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    first = root / "first"
    second = first / "second"
    second.mkdir(parents=True)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.current_folder = root
    window._reset_folder_history(root)

    window._navigate_folder(first)
    window._navigate_folder(second)
    window._folder_go_back()
    assert window.current_folder == first
    assert window.folder_forward.isEnabled()
    window._folder_go_back()
    assert window.current_folder == root
    window._folder_go_forward()
    assert window.current_folder == first

    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def test_move_dialog_loads_internal_folder_tree(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    (root / "Music" / "Running").mkdir(parents=True)
    (root / "System Volume Information").mkdir()
    dialog = MoveDestinationDialog(manual_device(root), [])
    deadline = time.monotonic() + 3
    root_item = dialog.tree.topLevelItem(0)
    while root_item.childCount() == 1 and root_item.child(0).text(0) == "Loading…":
        if time.monotonic() >= deadline:
            break
        app.processEvents()
        time.sleep(0.01)

    assert [root_item.child(index).text(0) for index in range(root_item.childCount())] == ["Music"]
    dialog.tree.setCurrentItem(root_item)
    dialog._accept_selection()
    assert dialog.destination == root
    dialog.close()


def test_drag_drop_rows_move_to_visible_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    destination = root / "Music"
    destination.mkdir(parents=True)
    song = root / "song.mp3"
    song.write_bytes(b"song")
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.file_objects = [destination, song]
    requested: list[tuple[list[Path], Path]] = []
    monkeypatch.setattr(
        window,
        "_move_paths",
        lambda paths, folder: requested.append((paths, folder)),
    )

    window._move_rows_to_folder([1], 0)

    assert requested == [([song], destination)]
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()
