"""Exercise the redesigned navigation and actions with real Qt events and fake services."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QPushButton, QWidget

from shokz_refill.config import ConfigStore
from shokz_refill.models import Device, DownloadJob, JobStatus, Playlist, Track
from shokz_refill.ui import MainWindow


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    # These tests exercise presentation; no real filesystem scan or cleanup is needed.
    monkeypatch.setattr(MainWindow, "_run", lambda *args, **kwargs: None)
    result = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    result.resize(1280, 800)
    result.show()
    return result


def test_sidebar_navigation_keeps_selection_and_tracks_programmatic_navigation(
    window: MainWindow, qt_application: QApplication
) -> None:
    track = Track("one", "Selected song", ("Artist",))
    window._show_results([track])
    window.results.selectRow(0)
    for page in (1, 2, 3, 4, 0):
        QTest.mouseClick(window.sidebar.buttons[page], Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        assert window.tabs.currentIndex() == page
        assert window.sidebar.buttons[page].isChecked()
        assert sum(button.isChecked() for button in window.sidebar.buttons) == 1
    assert window._selected_result_objects() == [track]
    window.tabs.setCurrentIndex(2)
    assert window.sidebar.buttons[2].isChecked()
    window.activateWindow()
    qt_application.processEvents()
    QTest.keyClick(window, Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(150)  # Native button shortcuts activate through Qt's animateClick timer.
    assert window.tabs.currentIndex() == 4


def test_sidebar_device_summary_refresh_and_disconnect(window: MainWindow, tmp_path: Path) -> None:
    gib = 1024**3
    device = Device("Test Shokz", tmp_path, 32 * gib, 5 * gib, 27 * gib)
    window._update_devices([device])
    assert window.sidebar.device_name.text() == "Test Shokz"
    assert "27.0 GiB free" in window.sidebar.device_status.text()
    assert window.sidebar.storage.value() == 16
    # Discovery itself is covered with injected results here; the refresh signal remains public.
    requests: list[bool] = []
    window.sidebar.refreshRequested.connect(lambda: requests.append(True))
    window.sidebar.refresh.click()
    assert requests == [True]
    window._update_devices([])
    assert window.sidebar.device_name.text() == "No Shokz connected"
    assert window.sidebar.storage.value() == 0
    assert not window.download_button.isEnabled()


def test_card_download_uses_sorted_identity_and_excludes_hidden_selection(
    window: MainWindow,
    qt_application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = Track("z", "Zulu", ("Other",))
    second = Track("a", "Alpha", ("Chosen artist",))
    window.device = Device("Shokz", tmp_path, 1000, 0, 1000)
    window.destination = tmp_path / "Music"
    queued: list[Track] = []
    monkeypatch.setattr(window.queue, "enqueue", lambda tracks, *args, **_o: queued.extend(tracks))
    # The fixture disables background work; run this one inline.
    monkeypatch.setattr(
        MainWindow, "_run", lambda _self, work, done, *_a, **_k: done(work()), raising=True
    )
    window._show_results([first, second])
    # Trigger the same menu action a user uses, rather than calling the sort implementation.
    menu = window.browser.filter_button.menu()
    assert menu is not None
    menu.actions()[0].trigger()
    window.results.selectRow(1)
    window.browser.result_filters.set_filter(1, "Chosen artist")
    assert not window._selected_result_objects()
    action = window.results.visualRect(window.results.model().index(0, 3)).center()
    QTest.mouseClick(window.results.viewport(), Qt.MouseButton.LeftButton, pos=action)
    # "+" only adds to the send list; "Send to Shokz" triggers it.
    assert queued == [] and window.browser.pending == [second]
    assert window.download_button.text() == "Send to Shokz (1)"

    class AcceptingWizard:
        def __init__(self, tracks, device, parent=None, **_options):  # type: ignore[no-untyped-def]
            self.tracks, self.destination = list(tracks), device.root / "Music"

        def exec(self):  # type: ignore[no-untyped-def]
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("shokz_refill.ui.TransferWizard", AcceptingWizard)
    window.browser.downloadRequested.emit()
    assert queued == [second] and window.browser.pending == []
    assert window.download_button.text() == "Send to Shokz"
    assert window._selected_result_objects() == [second]
    assert not window.results.item(1, 0).isSelected()


def test_track_plus_never_downloads_and_playlist_plus_requests_the_whole_playlist(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[object] = []
    monkeypatch.setattr(window.queue, "enqueue", lambda *args, **_o: requests.append(args))
    window._show_results([Track("one", "Song")])
    window.browser._row_action(0, 3)
    assert requests == [] and [t.video_id for t in window.browser.pending] == ["one"]
    playlist = Playlist("playlist", "Open me")
    window._show_results([playlist])
    added: list[Playlist] = []
    activated: list[tuple[int, int]] = []
    window.browser.playlistAddRequested.connect(added.append)
    window.browser.activated.connect(lambda row, column: activated.append((row, column)))
    window.browser._row_action(0, 3)
    assert added == [playlist] and activated == []
    window.browser._activate_row(0, 3)
    assert activated == []
    window.browser._activate_row(0, 0)
    assert activated == [(0, 0)]


def test_transfers_page_and_sidebar_summary_track_progress_errors_and_actions(
    window: MainWindow, tmp_path: Path, qt_application: QApplication
) -> None:
    panel = window.queue_panel
    sidebar = window.sidebar
    assert not sidebar.transfer_indicator.isVisible()
    job = DownloadJob(
        "one", Track("source", "Book"), tmp_path, status=JobStatus.DOWNLOADING, progress=20
    )
    panel.update_job(job)
    assert sidebar.transfer_indicator.state == "active"
    assert sidebar.transfer_indicator.isVisible() and sidebar.transfer_indicator._timer.isActive()
    assert "1 active · 20%" in sidebar.buttons[3].toolTip()
    sidebar.buttons[3].click()
    qt_application.processEvents()
    assert panel.table.isVisible()
    panel.table.selectRow(0)
    assert panel.cancel.isEnabled()
    panel.update_job(replace(job, status=JobStatus.FAILED, progress=50, error="USB disconnected"))
    assert sidebar.transfer_indicator.state == "failed"
    assert not sidebar.transfer_indicator._timer.isActive()
    assert "1 failed" in sidebar.buttons[3].toolTip()
    assert panel.overall.value() == 50
    assert panel.table.item(0, 3).toolTip() == "USB disconnected"
    assert panel.selected_ids() == [job.job_id]
    assert panel.retry.isEnabled() and not panel.cancel.isEnabled()
    panel.filters.set_filter(1, "complete")
    assert not panel.selected_ids()
    assert not panel.retry.isEnabled()
    panel.filters.clear()
    panel.update_job(replace(job, status=JobStatus.COMPLETE, progress=100))
    assert sidebar.transfer_indicator.state == "done"
    assert "finished" in sidebar.buttons[3].toolTip()


def test_empty_states_and_audiobook_connection_controls(
    window: MainWindow, qt_application: QApplication
) -> None:
    window._show_results([])
    assert window.results.rowCount() == 0
    assert window.browser.empty_state.label.isVisible()
    assert "No results" in window.browser.empty_state.label.text()
    window._show_results([Track("one", "Song")])
    assert not window.browser.empty_state.label.isVisible()
    panel = window.audiobookshelf_panel
    window.sidebar.buttons[4].click()
    qt_application.processEvents()
    assert panel.connection_card.isVisible()
    assert window.settings_page.isAncestorOf(panel.connection_card)
    assert window.settings_page.isAncestorOf(window.connect_button)
    assert panel.password.echoMode() == QLineEdit.EchoMode.Password
    window.sidebar.buttons[1].click()
    panel.settings_button.click()
    qt_application.processEvents()
    assert window.tabs.currentIndex() == 4
    panel.set_status("Connection failed: try again")
    assert "try again" in panel.connection_status.text()
    assert "try again" in panel.status.text()


def test_device_actions_exclude_a_hidden_row_even_if_selected_again(
    window: MainWindow, tmp_path: Path
) -> None:
    window.device = Device("Shokz", tmp_path, 1000, 0, 1000)
    window._show_files(
        [(tmp_path / "Visible.mp3", False, 10), (tmp_path / "Hidden.mp3", False, 10)]
    )
    window.file_filters.set_filter(0, "Visible")
    window.files.selectionModel().select(
        window.files.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert window._selected_paths() == []
    window._update_actions()
    assert not window.file_buttons["Delete"].isEnabled()


def test_settings_save_floats_over_the_bottom_right_corner_while_scrolling(
    window: MainWindow, qt_application: QApplication
) -> None:
    window.sidebar.buttons[4].click()
    qt_application.processEvents()
    page = window.settings_page
    button = window.speech_settings.save
    assert button.parent() is page
    margin = 20
    assert button.geometry().right() == page.width() - margin - 1
    assert button.geometry().bottom() == page.height() - margin - 1
    before = button.pos()
    scrollbar = page.scroll_area.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    qt_application.processEvents()
    assert button.pos() == before and button.isVisible()


@pytest.mark.parametrize("size", [(1040, 720), (1280, 800)])
def test_compact_layout_keeps_navigation_and_actions_inside_the_window(
    window: MainWindow, qt_application: QApplication, size: tuple[int, int]
) -> None:
    window.resize(*size)
    for page in range(5):
        window.sidebar.buttons[page].click()
        qt_application.processEvents()
        assert window.size().toTuple() == size
        for control in window.findChildren(QWidget):
            if isinstance(control, (QPushButton, QLineEdit, QComboBox)) and control.isVisible():
                # Editors in the scrollable settings panel may sit below the viewport.
                if window.speech_settings.isAncestorOf(control):
                    continue
                position = control.mapTo(window, QPoint())
                assert position.x() + control.width() <= window.width()
                assert position.y() + control.height() <= window.height()


def test_saved_accounts_connect_at_launch_and_open_my_playlists(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[str] = []
    connects: list[bool] = []
    monkeypatch.setattr(
        window, "_run", lambda function, success, message="", *a, **k: runs.append(message)
    )
    monkeypatch.setattr(window.audiobookshelf, "connect_server", lambda: connects.append(True))
    window.connect_saved_accounts()
    assert runs == [] and connects == []  # nothing saved: stay disconnected

    window.youtube.auth_path.parent.mkdir(parents=True, exist_ok=True)
    window.youtube.auth_path.write_text("{}", encoding="utf-8")
    window.audiobookshelf_panel.server.setText("https://books.example")
    window.audiobookshelf_panel.username.setText("reader")
    window.audiobookshelf_panel.password.setText("secret")
    window.tabs.setCurrentIndex(2)
    window.connect_saved_accounts()
    assert runs == ["Loading your playlists…"]
    assert connects == [True]
    assert window.tabs.currentIndex() == 0


def test_voice_preview_synthesizes_plays_and_stops(
    window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qt_application: QApplication,
) -> None:
    import wave

    stopped: list[bool] = []

    class FakePlayback:
        def stop(self) -> None:
            stopped.append(True)

    class FakeSpeech:
        def __init__(self, cache_dir: Path) -> None:
            pass

        def synthesize(self, text, output, voice, rate, cancelled):  # type: ignore[no-untyped-def]
            assert "Les Misérables" in text and voice == "fr-siwis" and rate == 100
            with wave.open(str(output), "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\0" * 4 * 4410)
            return output

    played: list[Path] = []

    def fake_play(path: Path) -> FakePlayback:
        played.append(path)
        return FakePlayback()

    monkeypatch.setattr(window.voice_preview, "speech", lambda cache: FakeSpeech(cache))
    monkeypatch.setattr(window.voice_preview, "player", fake_play)
    panel = window.speech_settings
    panel.voice.setCurrentIndex(panel.voice.findData("fr-siwis"))
    panel.preview_button.click()
    assert panel.preview_button.text() == "Stop"
    deadline = time.monotonic() + 5
    while window.voice_preview.playback is None and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.01)
    assert len(played) == 1
    panel.preview_button.click()
    assert stopped == [True]
    assert panel.preview_button.text() == "Preview"


def test_row_hover_highlights_the_whole_row_not_a_single_cell(
    window: MainWindow, qt_application: QApplication
) -> None:
    from PySide6.QtGui import QCursor

    window._show_results([Track("one", "Song", ("Artist",)), Track("two", "Other", ("Artist",))])
    window.show()
    table = window.results
    viewport = table.viewport()
    qt_application.processEvents()
    QCursor.setPos(viewport.mapToGlobal(QPoint(40, table.rowViewportPosition(0) + 30)))
    QTest.mouseMove(viewport, QPoint(40, table.rowViewportPosition(0) + 30))
    qt_application.processEvents()
    image = viewport.grab().toImage()
    y = table.rowViewportPosition(0) + 10
    left = image.pixelColor(table.columnViewportPosition(0) + 200, y)
    right = image.pixelColor(table.columnViewportPosition(2) + 10, y)
    other_row = image.pixelColor(
        table.columnViewportPosition(0) + 200, table.rowViewportPosition(1) + 10
    )
    assert left == right
    assert left != other_row


def test_cursor_is_an_arrow_inside_the_window_and_a_hand_on_buttons(
    window: MainWindow, qt_application: QApplication
) -> None:
    from shokz_refill.theme import apply_theme

    apply_theme(qt_application)
    fresh = QPushButton("Action")
    fresh.ensurePolished()
    assert fresh.cursor().shape() == Qt.CursorShape.PointingHandCursor
    window.setCursor(Qt.CursorShape.SizeVerCursor)  # as left behind by the resize margin
    assert window.window_frame.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert window.results.viewport().cursor().shape() != Qt.CursorShape.SizeVerCursor


def test_rounded_combo_popup_lists_options_and_applies_the_choice(
    qt_application: QApplication,
) -> None:
    from shokz_refill.theme import RoundedComboBox

    combo = RoundedComboBox()
    combo.addItems(["Audiobooks", "Podcasts", "Radio"])
    combo.show()
    activated: list[int] = []
    combo.activated.connect(activated.append)
    combo.showPopup()
    popup = combo._popup
    assert popup.isVisible() and popup.options.count() == 3
    assert popup.options.currentRow() == 0
    popup.optionChosen.emit(2)
    assert combo.currentIndex() == 2 and activated == [2] and not popup.isVisible()


def test_every_page_places_title_subtitle_controls_and_content_identically(
    window: MainWindow, qt_application: QApplication
) -> None:
    from shokz_refill.page_layout import PageTemplate

    positions = []
    for index in range(window.tabs.count()):
        window.sidebar.buttons[index].click()
        qt_application.processEvents()
        page = window.tabs.widget(index)
        assert isinstance(page, PageTemplate)
        title = page.title_label.mapTo(window, QPoint()).y()
        subtitle = page.subtitle.mapTo(window, QPoint()).y() if page.subtitle.isVisible() else None
        controls = (
            page.controls_host.mapTo(window, QPoint()).y()
            if page.controls_host.isVisible()
            else None
        )
        left = page.title_label.mapTo(window, QPoint()).x()
        positions.append((title, subtitle, controls, left))
    assert len({(title, left) for title, _s, _c, left in positions}) == 1
    assert len({subtitle for _t, subtitle, _c, _l in positions if subtitle is not None}) == 1
    assert len({controls for _t, _s, controls, _l in positions if controls is not None}) == 1


def test_plus_toggles_tracks_in_order_and_survives_new_results(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = Track("one", "One"), Track("two", "Two")
    window.device = Device("Shokz", Path("/unused"), 1000, 0, 1000)
    window._show_results([first, second])
    window.browser._row_action(1, 3)
    window.browser._row_action(0, 3)
    assert window.browser.pending == [second, first]
    window.browser._row_action(1, 3)
    assert window.browser.pending == [first]
    window._show_results([second])
    assert window.browser.pending == [first]
    assert window.download_button.isEnabled()
    window.browser.clear_pending()
    assert window.browser.pending == []


def test_logo_asset_matches_embedded_logo_and_site_favicon() -> None:
    from shokz_refill.icons import LOGO_SVG

    root = Path(__file__).resolve().parents[1]
    assert (root / "assets" / "logo.svg").read_text() == LOGO_SVG
    assert (root / "docs" / "favicon.svg").read_text() == LOGO_SVG
