import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from shokz_refill.audiobook_models import (
    Audiobook,
    AudiobookshelfCredentials,
    BookPage,
    Library,
)
from shokz_refill.audiobookshelf import AudiobookshelfClient, Connection
from shokz_refill.config import ConfigStore
from shokz_refill.device import manual_device
from shokz_refill.ui import MainWindow


def until(app: QApplication, predicate) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def test_tab_order_connection_multiselect_and_one_folder_per_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application: QApplication
) -> None:
    root = tmp_path / "device"
    root.mkdir()
    first, second = (
        Audiobook("one", "First book", "Author"),
        Audiobook("two", "Second book", "Other"),
    )

    class Client(AudiobookshelfClient):
        def libraries(self) -> tuple[Library, ...]:
            return (Library("lib", "Books"),)

        def books(self, library_id, **kwargs):  # type: ignore[no-untyped-def]
            return BookPage((first, second), 2)

        def book(self, item_id):  # type: ignore[no-untyped-def]
            return first if item_id == "one" else second

    client = Client(Connection("https://server", "user", "token"))
    monkeypatch.setattr(AudiobookshelfClient, "login", classmethod(lambda cls, credentials: client))
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "YouTube Music",
        "Audiobookshelf",
        "Shokz device / files",
        "Transfers",
        "Settings",
    ]
    panel = window.audiobookshelf_panel
    assert panel.password.echoMode() == QLineEdit.EchoMode.Password
    panel.server.setText("https://server")
    panel.username.setText("user")
    panel.password.setText("private-password")
    window.audiobookshelf.connect_server()
    until(qt_application, lambda: panel.books.rowCount() == 2)
    assert not panel.download.isEnabled()
    window._update_devices([manual_device(root)])
    panel.books.selectAll()
    assert panel.download.isEnabled()
    queued: list[Audiobook] = []

    def enqueue(books, device_root, connected, **kwargs):  # type: ignore[no-untyped-def]
        assert device_root == root and connected is client
        queued.extend(books)
        return []

    monkeypatch.setattr(window.audiobook_queue, "enqueue", enqueue)

    window.audiobookshelf.download_selected()
    assert queued == [first, second]
    assert first.folder_name(client.connection.server) != second.folder_name(
        client.connection.server
    )
    saved_path = tmp_path / "config" / "audiobookshelf.json"
    assert "private-password" in saved_path.read_text()  # Always remembered, in a private file.
    window.audiobookshelf.disconnect_server()
    until(qt_application, lambda: not window.audiobookshelf.tasks.active("forget"))
    assert not panel.password.text() and not panel.download.isEnabled()


def test_book_search_pagination_and_late_result_are_independent_of_youtube(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application: QApplication
) -> None:
    import threading

    entered, release = threading.Event(), threading.Event()

    class Client(AudiobookshelfClient):
        def books(self, library_id, *, page=0, query=""):  # type: ignore[no-untyped-def]
            if query == "old":
                entered.set()
                assert release.wait(2)
            return BookPage((Audiobook(query or str(page), query or f"Page {page}"),), 100, page)

    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    controller, panel = window.audiobookshelf, window.audiobookshelf_panel
    controller.client = Client(Connection("https://server", "user", "token"))
    panel.libraries.addItem("Books", "lib")
    try:
        panel.query.setText("old")
        controller.load_books()
        assert entered.wait(2)
        panel.query.setText("new")
        controller.load_books()
        until(
            qt_application,
            lambda: panel.books.rowCount() == 1 and panel.books.item(0, 0).text() == "new",
        )
        release.set()
        until(qt_application, lambda: controller.tasks.idle)
        assert panel.books.item(0, 0).text() == "new"
        assert not window.result_objects
        panel.query.clear()
        controller.load_books(1)
        until(qt_application, lambda: panel.page_label.text() == "Page 2")
        assert panel.previous.isEnabled() and not panel.next.isEnabled()
    finally:
        release.set()


def test_app_speech_settings_validate_preview_and_persist(
    tmp_path: Path, qt_application: QApplication
) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    window = MainWindow(store)
    panel = window.speech_settings
    panel.template.setPlainText("$unsupported")
    assert not panel.save.isEnabled()
    assert "Unknown variable" in panel.status.text()
    panel.template.setPlainText("Voici $book_name. Auteur : $author_name.")
    assert panel.save.isEnabled() and "Victor Hugo" in panel.preview.text()
    panel.rate.setValue(95)
    panel.save.click()
    until(qt_application, lambda: panel.status.text() == "Settings saved")
    saved = store.load()
    assert saved.book_tts_template == "Voici $book_name. Auteur : $author_name."
    assert saved.book_tts_rate == 95
    assert window.audiobookshelf.get_options().template == saved.book_tts_template


def test_book_context_menu_selects_the_row_and_offers_actions(
    qt_application: QApplication,
) -> None:
    from shokz_refill.audiobook_panel import AudiobookshelfPanel

    panel = AudiobookshelfPanel(AudiobookshelfCredentials("", "", ""))
    panel.set_browsing_enabled(True)
    books = (Audiobook("one", "First", "Ann", 60), Audiobook("two", "Second", "Bob", 60))
    panel.show_page(BookPage(books, 2))
    panel.download.setEnabled(True)
    panel.show()
    point = panel.books.visualItemRect(panel.books.item(1, 0)).center()
    menu = panel.build_context_menu(point)
    actions = {action.text(): action for action in menu.actions() if action.text()}
    assert [book.title for book in panel.selected_books()] == ["Second"]
    assert actions["Send to Shokz…"].isEnabled()
    assert actions["Copy title and author"].isEnabled()
    actions["Copy title and author"].trigger()
    assert QApplication.clipboard().text() == "Second — Bob"
    actions["Select all"].trigger()
    assert len(panel.selected_books()) == 2
    actions["Clear selection"].trigger()
    assert not panel.selected_books()


def test_announcement_can_be_switched_off_in_settings_and_persists(
    tmp_path: Path, qt_application: QApplication
) -> None:
    store = ConfigStore(tmp_path / "config", tmp_path / "cache")
    window = MainWindow(store)
    panel = window.speech_settings
    assert panel.announce.isChecked() and panel.preview_button.isEnabled()
    panel.announce.setChecked(False)
    assert not panel.template.isEnabled() and panel.chapter_template.isEnabled()
    assert panel.preview_button.isEnabled()  # Other chapters are still spoken.
    panel.announce_chapters.setChecked(False)
    assert not panel.chapter_template.isEnabled() and not panel.preview_button.isEnabled()
    assert "starts directly" in panel.preview.text()
    panel.save.click()
    until(qt_application, lambda: not store.load().book_tts_announce)
    assert not window.audiobookshelf.get_options().announce
