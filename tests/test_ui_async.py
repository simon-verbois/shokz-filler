import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shokz_refill.config import ConfigStore  # noqa: E402
from shokz_refill.device import manual_device  # noqa: E402
from shokz_refill.models import Playlist, Track  # noqa: E402
from shokz_refill.ui import MainWindow  # noqa: E402


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
