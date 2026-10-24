import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QHeaderView  # noqa: E402

from shokz_refill.config import ConfigStore  # noqa: E402
from shokz_refill.device import manual_device  # noqa: E402
from shokz_refill.models import Playlist, Track  # noqa: E402
from shokz_refill.themed_dialog import InputDialog  # noqa: E402
from shokz_refill.ui import DeviceFolderDialog, MainWindow  # noqa: E402


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


def test_expired_library_error_runs_on_ui_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.ensure_dirs()
    store.auth_path.write_text("{}", encoding="utf-8")
    window = MainWindow(store)
    window.show()
    assert "not yet verified" in window.auth_label.text()
    calls: list[tuple[str, QThread]] = []
    request_threads: list[QThread] = []

    class ExpiredClient:
        def get_account_info(self) -> object:
            request_threads.append(QThread.currentThread())
            raise KeyError("expired session")

    monkeypatch.setattr(window.youtube, "_auth_client", ExpiredClient())
    monkeypatch.setattr(
        window, "_show_error", lambda message: calls.append((message, QThread.currentThread()))
    )
    window._load_library()
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert calls and calls[0][1] == app.thread()
    assert request_threads and request_threads[0] != app.thread()
    assert "paste fresh request headers" in calls[0][0]
    assert window.auth_label.text() == "Not connected"
    assert window.isVisible()
    assert store.auth_path.is_file()
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


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
    assert window.browser_title.text().startswith("My Playlist")
    window._browser_go_back()
    assert window.browser_page.items == [playlist]
    assert not window.browser_back.isEnabled()
    assert window.browser_forward.isEnabled()
    window._browser_go_forward()
    assert window.browser_page.playlist == playlist
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


class FakeWizard:
    """Stands in for the modal assistant: accepts with a chosen folder."""

    instances: list["FakeWizard"] = []

    def __init__(self, tracks, device, parent=None, *, suggested="", last=None):  # type: ignore[no-untyped-def]
        self.tracks = list(tracks)
        self.suggested = suggested
        self.last = last
        self.destination: Path | None = device.root / (suggested or "Singles")
        FakeWizard.instances.append(self)

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted


def _window_with_wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    root = tmp_path / "device"
    root.mkdir()
    FakeWizard.instances.clear()
    monkeypatch.setattr("shokz_refill.ui.TransferWizard", FakeWizard)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    queued: list[tuple[list[Track], Path, int | None]] = []

    def enqueue(tracks: list[Track], destination: Path, _root: Path, **options: object):  # type: ignore[no-untyped-def]
        start = options.get("start")
        queued.append((tracks, destination, start if isinstance(start, int) else None))
        return []

    monkeypatch.setattr(window.queue, "enqueue", enqueue)
    return window, root, queued


def test_send_opens_assistant_and_playlist_songs_suggest_their_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    window, root, queued = _window_with_wizard(tmp_path, monkeypatch)
    playlist = Playlist("playlist-id", "Road Trip")
    track = Track("video-id", "Song", ("Artist",))
    window._set_browser_page(window.browser_page.__class__(playlist.title, [track], playlist))
    window._result_double_clicked(0, 0)
    assert window.browser.pending == [track] and queued == []
    window._download_selected()
    pump_until(app, lambda: bool(queued))
    assert FakeWizard.instances[0].suggested == "Road Trip"
    assert queued[0][:2] == ([track], root / "Road Trip")
    assert queued[0][2] == 1
    assert (root / "Road Trip").is_dir()  # A suggested folder is created when missing.
    assert window.browser.pending == []
    assert window.destination == root / "Road Trip"
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def test_loose_songs_reuse_last_folder_as_suggestion_without_auto_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    window, root, queued = _window_with_wizard(tmp_path, monkeypatch)
    (root / "Singles").mkdir()
    (root / "Singles" / "07 - Old.mp3").write_bytes(b"x")
    window.browser.add_pending([Track("a", "A"), Track("b", "B")])
    window._download_selected()
    pump_until(app, lambda: bool(queued))
    assert FakeWizard.instances[0].suggested == ""
    assert queued[0][1] == root / "Singles"
    assert queued[0][2] == 8  # Numbering continues after the highest existing position.
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def test_send_without_list_or_device_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    window, _root, queued = _window_with_wizard(tmp_path, monkeypatch)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    window._download_selected()
    window.browser.add_pending([Track("a", "A")])
    window.device = None
    window._download_selected()
    assert len(errors) == 2 and queued == [] and not FakeWizard.instances
    window.close()
    app.processEvents()


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
    assert window.path_edit.text() == str(first)
    window._navigate_folder(second)
    assert window.path_edit.text() == str(second)
    window._folder_go_back()
    assert window.current_folder == first
    assert window.path_edit.text() == str(first)
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
    (root / "SYSTEM").mkdir()
    dialog = DeviceFolderDialog(manual_device(root), [])
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


def test_download_folder_dialog_blocks_root_and_creates_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    (root / "Existing").mkdir(parents=True)
    dialog = DeviceFolderDialog(manual_device(root), [], allow_root=False, allow_create=True)
    deadline = time.monotonic() + 3
    while (
        dialog.tree.topLevelItemCount() == 0 or dialog.tree.topLevelItem(0).text(0) == "Loading…"
    ) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert [
        dialog.tree.topLevelItem(index).text(0) for index in range(dialog.tree.topLevelItemCount())
    ] == ["Existing"]
    assert all(
        dialog.tree.topLevelItem(index).text(0) != dialog.device.name
        for index in range(dialog.tree.topLevelItemCount())
    )
    assert not dialog.ok_button.isEnabled()
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    assert dialog.ok_button.isEnabled()
    dialog.tree.setCurrentItem(None)
    monkeypatch.setattr(
        InputDialog,
        "getText",
        staticmethod(lambda *_args, **_kwargs: ("My New Folder!", True)),
    )

    dialog._create_folder()
    deadline = time.monotonic() + 3
    while dialog.result() != QDialog.DialogCode.Accepted and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert dialog.destination == root / "My New Folder"
    assert dialog.destination.is_dir()
    dialog.close()


def test_result_headers_sort_and_keep_track_mapping(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    slow = Track("slow-id", "Zulu", ("Beta",), duration_seconds=600)
    fast = Track("fast-id", "Alpha", ("Gamma",), duration_seconds=90)
    window._show_results([slow, fast])

    assert window.results.item(0, 0).text() == "Zulu"
    window._sort_results(0)
    assert window.results.item(0, 0).text() == "Alpha"
    window.results.selectRow(0)
    assert window._selected_result_objects() == [fast]

    window._sort_results(2)
    assert window.results.item(0, 0).text() == "Alpha"
    window._sort_results(2)
    assert window.results.item(0, 0).text() == "Zulu"

    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


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
    window._file_kinds = {destination: True, song: False}
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


def test_move_operation_stays_visible_until_completion(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    destination = root / "Music"
    destination.mkdir(parents=True)
    song = root / "song.mp3"
    song.write_bytes(b"song")
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.current_folder = root

    window._move_paths([song], destination)
    assert "keep the Shokz connected" in window.device_operation_label.text()
    assert window.device_operation_progress.maximum() == 0

    deadline = time.monotonic() + 3
    while song.exists() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    while (
        "complete" not in window.device_operation_label.text().casefold()
        and time.monotonic() < deadline
    ):
        app.processEvents()
        time.sleep(0.01)

    assert (destination / "song.mp3").is_file()
    assert "Move complete" in window.device_operation_label.text()
    assert window.device_operation_progress.value() == 100
    window.pool.waitForDone(3_000)
    window.close()
    app.processEvents()


def pump_until(app, predicate, timeout: float = 3) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def test_late_search_response_cannot_replace_newer_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    entered = threading.Event()
    release = threading.Event()

    def search(query: str) -> list[Track]:
        if query == "old":
            entered.set()
            assert release.wait(2)
        return [Track(query, query)]

    monkeypatch.setattr(window.youtube, "search_songs", search)
    try:
        window.search_edit.setText("old")
        window._search()
        assert entered.wait(2)
        window.search_edit.setText("new")
        window._search()
        pump_until(app, lambda: window.result_objects == [Track("new", "new")])
        release.set()
        pump_until(app, lambda: window.tasks.idle)
        assert window.result_objects == [Track("new", "new")]
    finally:
        release.set()
        window.close()
        pump_until(app, lambda: not window.isVisible() and window.tasks.idle)


def test_stale_folder_listing_cannot_replace_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from shokz_refill.files import DeviceFileService

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    root = tmp_path / "device"
    first = root / "first"
    second = root / "second"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "old.mp3").write_bytes(b"old")
    (second / "new.mp3").write_bytes(b"new")
    entered = threading.Event()
    release = threading.Event()
    original = DeviceFileService.list_dir

    def list_dir(service, path):  # type: ignore[no-untyped-def]
        if path == first:
            entered.set()
            assert release.wait(2)
        return original(service, path)

    monkeypatch.setattr(DeviceFileService, "list_dir", list_dir)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    try:
        window._navigate_folder(first)
        assert entered.wait(2)
        window._navigate_folder(second)
        pump_until(app, lambda: window.file_objects == [second / "new.mp3"])
        release.set()
        pump_until(app, lambda: window.tasks.idle)
        assert window.file_objects == [second / "new.mp3"]
    finally:
        release.set()
        window.close()
        pump_until(app, lambda: window.tasks.idle)


def test_close_cancels_work_and_waits_without_blocking_qt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from shokz_refill.cancellation import check_cancelled

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.show()
    entered = threading.Event()
    release = threading.Event()
    callbacks: list[object] = []

    def work() -> str:
        entered.set()
        assert release.wait(2)
        check_cancelled()
        return "outdated"

    window._run(work, callbacks.append)
    assert entered.wait(2)
    window.close()
    assert window._closing and window.isVisible()
    app.processEvents()
    release.set()
    pump_until(app, lambda: not window.isVisible())
    assert window.tasks.idle and window.queue.idle
    assert not callbacks


def test_selecting_device_does_not_resume_cancelled_copies_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    root = tmp_path / "device"
    root.mkdir()
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    resumed: list[object] = []
    monkeypatch.setattr(window.transfer, "resume_for_device", lambda *args: resumed.append(args))
    window._update_devices([manual_device(root)])
    pump_until(app, lambda: window.tasks.idle)
    assert not resumed
    assert window.resume_button.isEnabled()
    window.close()
    app.processEvents()


def test_pending_download_reserves_destination_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shokz_refill.models import DownloadJob, JobStatus

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    root = tmp_path / "device"
    folder = root / "Music"
    folder.mkdir(parents=True)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.device = manual_device(root)
    window.current_folder = root
    window._show_files([(folder, True, 0)])
    window.files.selectRow(0)
    job = DownloadJob("job", Track("id", "Song"), folder, device_root=root)
    window.queue.jobs[job.job_id] = job
    window._update_actions()
    for label in ("Rename", "Move selected…", "Delete"):
        assert not window.file_buttons[label].isEnabled()
    job.status = JobStatus.COMPLETE
    window._update_actions()
    assert window.file_buttons["Rename"].isEnabled()
    window.close()
    pump_until(app, lambda: window.tasks.idle)
