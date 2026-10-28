"""Offline onboarding, persistence, keyboard controls and real-widget layout checks."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from shokz_filler.config import AppConfig, ConfigStore
from shokz_filler.models import Track
from shokz_filler.ui import MainWindow


def test_first_open_is_saved_even_when_skipped_and_can_be_replayed(
    tmp_path: Path, qt_application: QApplication
) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.ensure_dirs()
    store.path.write_text('{"manual_device": "/example/shokz"}', encoding="utf-8")
    window = MainWindow(store)
    window.show()
    window.show_guided_tour_if_needed()
    qt_application.processEvents()
    tour = window.guided_tour
    assert tour is not None and tour.isVisible()
    window.show_guided_tour()
    assert window.guided_tour is tour
    tour.skip.click()
    assert window.guided_tour is None

    deadline = time.monotonic() + 3
    while not store.load().guided_tour_seen and time.monotonic() < deadline:
        QTest.qWait(10)
    assert store.load().guided_tour_seen
    assert store.load().manual_device == "/example/shokz"

    reopened = MainWindow(store)
    reopened.show()
    reopened.show_guided_tour_if_needed()
    assert reopened.guided_tour is None
    reopened.sidebar.tour_button.click()
    assert reopened.guided_tour is not None
    assert reopened.guided_tour.index == 0
    dividers = reopened.sidebar.findChildren(QFrame, "sidebarDivider")
    assert len(dividers) == 1
    assert dividers[0].y() < reopened.sidebar.tour_button.y()
    assert reopened.sidebar.tour_button.y() < reopened.sidebar.buttons[4].y()


@pytest.mark.parametrize("size", [(1040, 720), (1280, 800)])
def test_every_step_tracks_visible_controls_and_finishing_restores_the_page(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
) -> None:
    monkeypatch.setattr(MainWindow, "_run", lambda *_args, **_kwargs: None)
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    store.save(AppConfig(guided_tour_seen=True))
    window = MainWindow(store)
    window.resize(*size)
    track = Track("example", "Keep this song")
    window._show_results([track])
    window.browser.pending.append(track)
    window.tabs.setCurrentIndex(2)
    window.show()
    window.sidebar.tour_button.click()
    tour = window.guided_tour
    assert tour is not None
    assert not tour.back.isEnabled()
    assert tour.windowModality() == Qt.WindowModality.WindowModal

    for index, step in enumerate(tour.steps):
        qt_application.processEvents()
        assert tour.index == index
        assert window.tabs.currentIndex() == step.page
        assert step.target.isVisible()
        assert tour.rect().contains(tour.card.geometry())
        assert tour.rect().contains(tour.spotlight)
        target_center = step.target.mapTo(window, step.target.rect().center())
        assert tour.spotlight.contains(target_center)
        assert not tour.description.text().endswith("…")
        assert tour.card.height() >= tour.card.minimumSizeHint().height()
        tour.next.click()

    assert window.guided_tour is None
    assert window.tabs.currentIndex() == 2
    assert window.sidebar.buttons[2].isChecked()
    assert window.browser.pending == [track]
    assert not window.queue.jobs and not window.audiobook_queue.jobs


def test_keyboard_back_escape_and_resize_preserve_user_context(
    tmp_path: Path, qt_application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MainWindow, "_run", lambda *_args, **_kwargs: None)
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    window.show()
    window.activateWindow()
    qt_application.processEvents()
    window.browser.search_edit.setText("My search")
    window.browser.search_edit.setFocus()
    window.show_guided_tour()
    tour = window.guided_tour
    assert tour is not None
    qt_application.processEvents()
    QTest.keyClick(tour.next, Qt.Key.Key_Return)
    assert tour.index == 1
    QTest.keyClick(tour.next, Qt.Key.Key_Backtab)
    assert tour.back.hasFocus()
    QTest.keyClick(tour.back, Qt.Key.Key_Space)
    assert tour.index == 0
    window.resize(1280, 800)
    window.move(40, 40)
    qt_application.processEvents()
    assert tour.size() == window.size()
    assert tour.pos() == window.mapToGlobal(QPoint())
    assert tour.rect().contains(tour.card.geometry())
    QTest.keyClick(tour, Qt.Key.Key_Escape)
    qt_application.processEvents()
    assert window.guided_tour is None
    assert window.tabs.currentIndex() == 0
    assert window.browser.search_edit.text() == "My search"
    assert window.browser.search_edit.hasFocus()
