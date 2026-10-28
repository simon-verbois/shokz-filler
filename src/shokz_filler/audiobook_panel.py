"""Audiobookshelf view and controller, separate from the application's main window."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .audiobook_models import Audiobook, AudiobookshelfCredentials, BookPage, Library, export_plan
from .audiobook_queue import AudiobookQueue
from .audiobook_settings import AudiobookshelfSettings
from .audiobookshelf import AudiobookshelfClient
from .background import TaskRunner
from .book_export import BookExportOptions
from .icons import icon
from .library_view import library_rows
from .models import Device
from .page_layout import NO_DEVICE_MESSAGE, PageTemplate
from .table_state import TableEmptyState
from .theme import ON_ACCENT, RoundedComboBox, role


class _OptionalLabel(QLabel):
    """Takes no room while empty, so the footer's other line stays on the vertical centre."""

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        super().setText(text)
        self.setVisible(bool(text))


class AudiobookshelfPanel(PageTemplate):
    settingsRequested = Signal()

    def __init__(self, credentials: AudiobookshelfCredentials) -> None:
        super().__init__("Audiobookshelf")
        self.settings_button = QPushButton("Connection settings")
        self.settings_button.setIcon(icon("settings"))
        role(self.settings_button, "quiet")
        self.settings_button.clicked.connect(self.settingsRequested)
        self.header.addWidget(self.settings_button)
        # The connection form is built here but hosted by the Settings page.
        card = QFrame()
        self.connection_card = card
        role(card, "card")
        connection_layout = QVBoxLayout(card)
        connection_layout.setContentsMargins(16, 12, 16, 12)
        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(4)
        self.server = QLineEdit(credentials.server)
        self.server.setPlaceholderText("https://audiobooks.example.com")
        self.username = QLineEdit(credentials.username)
        self.password = QLineEdit(credentials.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for row, column, span, title, widget in (
            (0, 0, 2, "Server", self.server),
            (2, 0, 1, "Username", self.username),
            (2, 1, 1, "Password", self.password),
        ):
            label = QLabel(title)
            label.setBuddy(widget)
            fields.addWidget(label, row, column, 1, span)
            fields.addWidget(widget, row + 1, column, 1, span)
        connection_layout.addLayout(fields)
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect / forget")
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.disconnect_button)
        connection_layout.addSpacing(6)
        connection_layout.addLayout(actions)
        self.status = self.subtitle
        self.status.clear()  # The empty state below already says it.
        self.connection_status = QLabel()
        self.connection_status.setWordWrap(True)
        self.connection_status.setTextFormat(Qt.TextFormat.PlainText)
        role(self.connection_status, "muted")
        connection_layout.addWidget(self.connection_status)
        self.libraries = RoundedComboBox()
        self.libraries.setAccessibleName("Audiobookshelf library")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search books or authors")
        self.query.setAccessibleName("Search Audiobookshelf")
        self.query.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.query.setClearButtonEnabled(True)
        self.search = QPushButton()
        self.search.setIcon(icon("refresh"))
        self.search.setToolTip("Search / refresh")
        self.search.setAccessibleName("Search or refresh books")
        self.previous = QPushButton()
        self.previous.setIcon(icon("back"))
        self.previous.setToolTip("Previous page")
        self.previous.setAccessibleName("Previous page of books")
        self.next = QPushButton()
        self.next.setIcon(icon("forward"))
        self.next.setToolTip("Next page")
        self.next.setAccessibleName("Next page of books")
        for button in (self.search, self.previous, self.next):
            button.setFixedWidth(36)
        self.page_label = QLabel()
        for control in (
            self.libraries,
            self.query,
            self.search,
            self.previous,
            self.page_label,
            self.next,
        ):
            self.controls.addWidget(control)
        self.controls.setStretch(1, 1)
        self.books = QTableWidget(0, 4)
        library_rows(self.books, book=True)
        self.books.setHorizontalHeaderLabels(["Title", "Author", "Duration", "Availability"])
        self.books.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.books.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.books.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.books.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.books.customContextMenuRequested.connect(self._context_menu)
        header = self.books.horizontalHeader()
        header.hide()
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.books.setColumnWidth(1, 230)
        self.books.setColumnHidden(3, True)  # Availability is shown with the duration.
        self.empty_state = TableEmptyState(
            self.books, "Your audiobook library\nConnect to your server to choose books."
        )
        self.content.addWidget(self.books)
        self.details = _OptionalLabel()
        self.details.hide()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        role(self.details, "muted")
        self.device_label = QLabel(NO_DEVICE_MESSAGE)
        self.device_label.setWordWrap(True)
        role(self.device_label, "muted")
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(self.details)
        info.addWidget(self.device_label)
        self.footer.addLayout(info, 1)
        self.download = QPushButton("Send to Shokz")
        role(self.download, "primary")
        self.download.setIcon(icon("download", ON_ACCENT))
        self.download.setToolTip(
            "One book → one folder → one numbered MP3 per chapter (01 - Title.mp3…), copied in "
            "playback order. MP3 CBR 192 kbps · 44.1 kHz · stereo (mono in Settings). "
            "Existing files are skipped; "
            "conflicts keep both files."
        )
        self.footer.addWidget(self.download)
        self.download.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.set_browsing_enabled(False)

    def _context_menu(self, point: QPoint) -> None:
        self.build_context_menu(point).exec(self.books.viewport().mapToGlobal(point))

    def build_context_menu(self, point: QPoint) -> QMenu:
        """Menu for the book under the pointer; actions run through their own handlers."""
        row = self.books.rowAt(point.y())
        if row >= 0 and not self.books.selectionModel().isRowSelected(row):
            self.books.clearSelection()
            self.books.selectRow(row)
        selected = self.selected_books()
        menu = QMenu(self)

        def add(text: str, enabled: bool, handler: Callable[[], object], glyph: str = "") -> None:
            action = menu.addAction(icon(glyph), text) if glyph else menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False: handler())

        add("Send to Shokz…", self.download.isEnabled(), self.download.click, "download")
        add("Copy title and author", bool(selected), lambda: self._copy_titles(selected))
        menu.addSeparator()
        add("Select all", self.books.rowCount() > 0, self.books.selectAll)
        add(
            "Clear selection",
            self.books.selectionModel().hasSelection(),
            self.books.clearSelection,
        )
        add("Refresh list", self.search.isEnabled(), self.search.click, "refresh")
        return menu

    @staticmethod
    def _copy_titles(books: list[Audiobook]) -> None:
        QApplication.clipboard().setText("\n".join(f"{b.title} — {b.author}" for b in books))

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.connection_status.setText(text)

    def credentials(self) -> AudiobookshelfCredentials:
        return AudiobookshelfCredentials(
            self.server.text().strip(), self.username.text(), self.password.text()
        )

    def selected_books(self) -> list[Audiobook]:
        result: list[Audiobook] = []
        for index in self.books.selectionModel().selectedRows():
            item = self.books.item(index.row(), 0)
            book = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(book, Audiobook) and book.available:
                result.append(book)
        return result

    def set_browsing_enabled(self, enabled: bool) -> None:
        for control in (
            self.libraries,
            self.query,
            self.search,
            self.books,
            self.previous,
            self.next,
        ):
            control.setEnabled(enabled)

    def show_page(self, page: BookPage, *, search: bool = False) -> None:
        self.empty_state.set_text("No books found\nTry another search or choose another library.")
        self.books.setRowCount(0)
        self.books.setRowCount(len(page.books))
        for row, book in enumerate(page.books):
            duration = f"{int(book.duration) // 3600}h {int(book.duration) // 60 % 60:02d}m"
            for column, text in enumerate(
                (
                    book.title,
                    book.author,
                    duration if book.available else f"{duration} · Unavailable",
                    "",
                )
            ):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, book)
                self.books.setItem(row, column, item)
        self.previous.setEnabled(not search and page.page > 0)
        self.next.setEnabled(not search and (page.page + 1) * page.limit < page.total)
        self.page_label.setText(f"{page.total} result(s)" if search else f"Page {page.page + 1}")
        self.details.clear()


class AudiobookshelfController(QObject):
    jobsQueued = Signal()

    def __init__(
        self,
        panel: AudiobookshelfPanel,
        settings: AudiobookshelfSettings,
        queue: AudiobookQueue,
        get_device: Callable[[], Device | None],
        get_options: Callable[[], BookExportOptions] = BookExportOptions,
    ) -> None:
        super().__init__(panel)
        self.panel, self.settings, self.queue = panel, settings, queue
        self.get_device = get_device
        self.get_options = get_options
        self.tasks = TaskRunner(self)
        self.client: AudiobookshelfClient | None = None
        self.page = 0
        self._query = ""
        self._library = ""
        panel.connect_button.clicked.connect(self.connect_server)
        panel.password.returnPressed.connect(self.connect_server)
        panel.disconnect_button.clicked.connect(self.disconnect_server)
        panel.libraries.currentIndexChanged.connect(lambda _index: self.load_books())
        panel.search.clicked.connect(self.load_books)
        panel.query.returnPressed.connect(self.load_books)
        panel.previous.clicked.connect(lambda: self.load_books(self.page - 1))
        panel.next.clicked.connect(lambda: self.load_books(self.page + 1))
        panel.books.itemSelectionChanged.connect(self.selection_changed)
        panel.download.clicked.connect(self.download_selected)

    def _failed(self, message: str) -> None:
        self.panel.set_status(message or "Audiobookshelf operation failed")

    def connect_server(self) -> None:
        if self.tasks.active("login") or self.tasks.active("forget"):
            return
        for key in ("libraries", "books", "detail"):
            self.tasks.cancel(key)
        self.client = None
        self.panel.set_browsing_enabled(False)
        self.panel.download.setEnabled(False)
        self.panel.disconnect_button.setEnabled(False)
        credentials = self.panel.credentials()
        self.panel.connect_button.setEnabled(False)
        for field in (
            self.panel.server,
            self.panel.username,
            self.panel.password,
        ):
            field.setEnabled(False)
        self.panel.set_status("Connecting to Audiobookshelf…")

        def login() -> AudiobookshelfClient:
            client = AudiobookshelfClient.login(credentials)
            self.settings.save(credentials)
            return client

        def connected(client: AudiobookshelfClient) -> None:
            self.client = client
            self.panel.connect_button.setEnabled(True)
            for field in (
                self.panel.server,
                self.panel.username,
                self.panel.password,
            ):
                field.setEnabled(True)
            self.panel.disconnect_button.setEnabled(True)
            self.panel.set_status(
                "Connected"
                if client.connection.can_download
                else "Connected — this account has no download permission"
            )
            self.panel.set_browsing_enabled(True)
            self.tasks.start(
                client.libraries, self._libraries_loaded, self._failed, key="libraries"
            )

        def failed(message: str) -> None:
            self.panel.connect_button.setEnabled(True)
            for field in (
                self.panel.server,
                self.panel.username,
                self.panel.password,
            ):
                field.setEnabled(True)
            self._failed(message)

        self.tasks.start(login, connected, failed, key="login")

    def _libraries_loaded(self, libraries: tuple[Library, ...]) -> None:
        self.panel.libraries.blockSignals(True)
        self.panel.libraries.clear()
        for library in libraries:
            self.panel.libraries.addItem(library.name, library.library_id)
        self.panel.libraries.blockSignals(False)
        if self.panel.libraries.count():
            self.load_books()
        else:
            self.panel.set_status("This account has no audiobook libraries")

    def load_books(self, page: int = 0) -> None:
        client = self.client
        library = self.panel.libraries.currentData()
        if client is None or not isinstance(library, str):
            return
        self.tasks.cancel("detail")
        self._query = self.panel.query.text().strip()
        self._library = library
        self.page = max(0, int(page))
        query, selected_page = self._query, self.page
        self.panel.set_status("Loading books…")
        self.panel.books.setRowCount(0)
        self.panel.download.setEnabled(False)

        def show(result: BookPage) -> None:
            self.panel.show_page(result, search=bool(query))
            self.panel.set_status(f"{result.total} book(s) — select the ones to transfer")

        self.tasks.start(
            lambda: client.books(library, page=selected_page, query=query),
            show,
            self._failed,
            key="books",
        )

    def selection_changed(self) -> None:
        selected = self.panel.selected_books()
        self.update_device()
        self.tasks.cancel("detail")
        if len(selected) != 1 or self.client is None:
            self.panel.details.setText(f"{len(selected)} book(s) selected — one folder per book")
            return
        client, book = self.client, selected[0]
        self.panel.details.setText("Reading audio formats and source order…")

        def describe(detail: Audiobook) -> None:
            try:
                plan = export_plan(detail)
                formats = ", ".join(
                    sorted(
                        {
                            Path(source.filename).suffix.upper().lstrip(".")
                            for source in detail.sources
                        }
                    )
                )
                self.panel.details.setText(
                    f"{detail.title} · {formats} · {len(detail.sources)} source(s) "
                    f"→ {len(plan)} complete MP3. Folder: "
                    f"{detail.folder_name(client.connection.server)}"
                )
            except ValueError as exc:
                self.panel.details.setText(str(exc))

        self.tasks.start(
            lambda: client.book(book.item_id),
            describe,
            lambda message: self.panel.details.setText(message),
            key="detail",
        )

    def update_device(self) -> None:
        device = self.get_device()
        self.panel.device_label.setText("" if device is not None else NO_DEVICE_MESSAGE)
        self.panel.download.setEnabled(
            self.client is not None
            and self.client.connection.can_download
            and self.get_device() is not None
            and bool(self.panel.selected_books())
        )

    def download_selected(self) -> None:
        device, client = self.get_device(), self.client
        selected = self.panel.selected_books()
        if device is None or client is None or not selected:
            self._failed("Select a device and one or more books first")
            return
        try:
            options = self.get_options()
            queued = len(self.queue.enqueue(selected, device.root, client, options=options))
            self.panel.set_status(f"Queued {queued} book(s) — one MP3 per book")
            self.jobsQueued.emit()
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            self._failed(str(exc))

    def disconnect_server(self) -> None:
        self.panel.empty_state.set_text(
            "Your audiobook library\nConnect to your server to choose books."
        )
        for key in ("login", "libraries", "books", "detail"):
            self.tasks.cancel(key)
        self.queue.cancel(list(self.queue.jobs))
        self.client = None
        self.panel.password.clear()
        self.panel.books.setRowCount(0)
        self.panel.libraries.clear()
        self.panel.set_browsing_enabled(False)
        self.panel.download.setEnabled(False)
        self.panel.disconnect_button.setEnabled(False)
        self.panel.connect_button.setEnabled(False)
        self.panel.set_status("Disconnected; forgetting the saved connection…")

        def forgotten(_value: object) -> None:
            self.panel.connect_button.setEnabled(True)
            self.panel.set_status("Disconnected; saved connection removed")

        def failed(message: str) -> None:
            self.panel.connect_button.setEnabled(True)
            self._failed(message)

        self.tasks.start(self.settings.forget, forgotten, failed, key="forget")
