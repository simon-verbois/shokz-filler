import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from shokz_refill.audiobook_models import Audiobook, BookPage, Library
from shokz_refill.audiobookshelf import AudiobookshelfClient, Connection
from shokz_refill.book_export import BookExportOptions
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

    class OptionsDialog:
        def __init__(self, book, defaults, parent):  # type: ignore[no-untyped-def]
            assert defaults.announce
            self.options = BookExportOptions(announce=False)

        def exec(self):  # type: ignore[no-untyped-def]
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("shokz_refill.audiobook_panel.BookExportDialog", OptionsDialog)
    window.audiobookshelf.download_selected()
    assert queued == [first, second]
    assert first.folder_name(client.connection.server) != second.folder_name(
        client.connection.server
    )
    saved = (tmp_path / "config" / "audiobookshelf.json").read_text()
    assert "private-password" not in saved
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


def test_book_popup_starts_with_announcement_enabled_and_can_disable_it(
    qt_application: QApplication,
) -> None:
    from shokz_refill.book_dialogs import BookExportDialog

    book = Audiobook("id", "Les Misérables", "Victor Hugo")
    dialog = BookExportDialog(book, BookExportOptions(template="$author_name présente $book_name."))
    assert dialog.announcement.isChecked()
    assert "Victor Hugo présente Les Misérables." in dialog.preview.text()
    assert "3 seconds" in dialog.preview.text()
    dialog.announcement.setChecked(False)
    assert not dialog.options.announce
    assert "starts directly" in dialog.preview.text()
    dialog.close()


def test_skipping_book_popup_does_not_enqueue_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application: QApplication
) -> None:
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    root = tmp_path / "device"
    root.mkdir()
    window._update_devices([manual_device(root)])
    window.audiobookshelf.client = AudiobookshelfClient(Connection("https://server", "u", "token"))
    monkeypatch.setattr(window.audiobookshelf.client, "book", lambda _item: Audiobook("id", "Book"))
    window.audiobookshelf_panel.show_page(BookPage((Audiobook("id", "Book"),), 1))
    window.audiobookshelf_panel.books.selectRow(0)

    class Skip:
        def __init__(self, *args):  # type: ignore[no-untyped-def]
            pass

        def exec(self):  # type: ignore[no-untyped-def]
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("shokz_refill.audiobook_panel.BookExportDialog", Skip)
    window.audiobookshelf.download_selected()
    assert not window.audiobook_queue.jobs


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
