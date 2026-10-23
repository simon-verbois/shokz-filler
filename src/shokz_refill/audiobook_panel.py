"""Audiobookshelf view and controller, separate from the application's main window."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .audiobook_models import Audiobook, AudiobookshelfCredentials, BookPage, Library, export_plan
from .audiobook_queue import AudiobookQueue
from .audiobook_settings import AudiobookshelfSettings
from .audiobookshelf import AudiobookshelfClient
from .background import TaskRunner
from .book_dialogs import BookExportDialog
from .book_export import BookExportOptions
from .models import Device


class AudiobookshelfPanel(QWidget):
    def __init__(self, credentials: AudiobookshelfCredentials) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        fields = QGridLayout()
        self.server = QLineEdit(credentials.server)
        self.server.setPlaceholderText("https://audiobooks.example.com")
        self.username = QLineEdit(credentials.username)
        self.password = QLineEdit(credentials.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for column, (title, widget) in enumerate(
            (("Server", self.server), ("Username", self.username), ("Password", self.password))
        ):
            label = QLabel(title)
            label.setBuddy(widget)
            fields.addWidget(label, 0, column)
            fields.addWidget(widget, 1, column)
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect / forget")
        fields.addWidget(self.connect_button, 1, 3)
        fields.addWidget(self.disconnect_button, 1, 4)
        layout.addLayout(fields)
        connection = QHBoxLayout()
        self.remember = QCheckBox("Remember password on this computer")
        self.remember.setToolTip("Stores the password in your private per-user configuration file")
        self.status = QLabel("Connect to your Audiobookshelf server to browse books")
        self.status.setWordWrap(True)
        connection.addWidget(self.remember)
        connection.addWidget(self.status, 1)
        layout.addLayout(connection)
        browse = QHBoxLayout()
        self.libraries = QComboBox()
        self.libraries.setAccessibleName("Audiobookshelf library")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search books or authors")
        self.query.setAccessibleName("Search Audiobookshelf")
        self.search = QPushButton("Search / refresh")
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        self.page_label = QLabel()
        for control in (
            self.libraries,
            self.query,
            self.search,
            self.previous,
            self.page_label,
            self.next,
        ):
            browse.addWidget(control)
        layout.addLayout(browse)
        self.books = QTableWidget(0, 4)
        self.books.setHorizontalHeaderLabels(["Title", "Author", "Duration", "Availability"])
        self.books.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.books.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.books.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.books.horizontalHeader()
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.books.setColumnWidth(1, 230)
        layout.addWidget(self.books)
        self.details = QLabel(
            "Select one or more books. Each book gets its own folder on the device."
        )
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.device_label = QLabel("No Shokz selected — choose a device in Shokz device / files")
        self.device_label.setWordWrap(True)
        layout.addWidget(self.device_label)
        actions = QHBoxLayout()
        self.download = QPushButton("Download / transfer selected books")
        actions.addWidget(QLabel("One book → one folder → one MP3"))
        actions.addStretch()
        actions.addWidget(self.download)
        layout.addLayout(actions)
        policy = QLabel(
            "MP3 CBR 192 kbps · 44.1 kHz · stereo · sources merged in Audiobookshelf order. "
            "Existing parts are skipped; conflicts keep both files."
        )
        policy.setWordWrap(True)
        layout.addWidget(policy)
        self.download.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.set_browsing_enabled(False)

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
        self.books.setRowCount(0)
        self.books.setRowCount(len(page.books))
        for row, book in enumerate(page.books):
            duration = f"{int(book.duration) // 3600}:{int(book.duration) // 60 % 60:02d}"
            for column, text in enumerate(
                (
                    book.title,
                    book.author,
                    duration,
                    "Available" if book.available else "Unavailable",
                )
            ):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, book)
                self.books.setItem(row, column, item)
        self.previous.setEnabled(not search and page.page > 0)
        self.next.setEnabled(not search and (page.page + 1) * page.limit < page.total)
        self.page_label.setText(f"{page.total} result(s)" if search else f"Page {page.page + 1}")
        self.details.setText(
            "Select one or more books. Each book gets its own folder on the device."
        )


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
        panel.remember.setChecked(settings.has_saved_password())

    def _failed(self, message: str) -> None:
        self.panel.status.setText(message or "Audiobookshelf operation failed")

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
        remember = self.panel.remember.isChecked()
        self.panel.connect_button.setEnabled(False)
        for field in (
            self.panel.server,
            self.panel.username,
            self.panel.password,
            self.panel.remember,
        ):
            field.setEnabled(False)
        self.panel.status.setText("Connecting to Audiobookshelf…")

        def login() -> AudiobookshelfClient:
            client = AudiobookshelfClient.login(credentials)
            self.settings.save(credentials, remember_password=remember)
            return client

        def connected(client: AudiobookshelfClient) -> None:
            self.client = client
            self.panel.connect_button.setEnabled(True)
            for field in (
                self.panel.server,
                self.panel.username,
                self.panel.password,
                self.panel.remember,
            ):
                field.setEnabled(True)
            self.panel.disconnect_button.setEnabled(True)
            self.panel.status.setText(
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
                self.panel.remember,
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
            self.panel.status.setText("This account has no audiobook libraries")

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
        self.panel.status.setText("Loading books…")
        self.panel.books.setRowCount(0)
        self.panel.download.setEnabled(False)

        def show(result: BookPage) -> None:
            self.panel.show_page(result, search=bool(query))
            self.panel.status.setText(f"{result.total} book(s) — select the ones to transfer")

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
        self.panel.device_label.setText(
            f"Device: {device.name} — {device.root}"
            if device is not None
            else "No Shokz selected — choose a device in Shokz device / files"
        )
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
            queued = 0
            for book in selected:
                dialog = BookExportDialog(book, self.get_options(), self.panel)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    continue
                # A modal dialog processes device events; recheck the selected destination.
                current = self.get_device()
                if current is None or current.root != device.root or self.client is not client:
                    raise ValueError(
                        "The selected device or server changed; select the books again"
                    )
                jobs = self.queue.enqueue([book], device.root, client, options=dialog.options)
                queued += len(jobs)
            self.panel.status.setText(f"Queued {queued} book(s) — one MP3 per book")
            self.jobsQueued.emit()
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            self._failed(str(exc))

    def disconnect_server(self) -> None:
        for key in ("login", "libraries", "books", "detail"):
            self.tasks.cancel(key)
        self.queue.cancel(list(self.queue.jobs))
        self.client = None
        self.panel.password.clear()
        self.panel.remember.setChecked(False)
        self.panel.books.setRowCount(0)
        self.panel.libraries.clear()
        self.panel.set_browsing_enabled(False)
        self.panel.download.setEnabled(False)
        self.panel.disconnect_button.setEnabled(False)
        self.panel.connect_button.setEnabled(False)
        self.panel.status.setText("Disconnected; forgetting the saved connection…")

        def forgotten(_value: object) -> None:
            self.panel.connect_button.setEnabled(True)
            self.panel.status.setText("Disconnected; saved connection removed")

        def failed(message: str) -> None:
            self.panel.connect_button.setEnabled(True)
            self._failed(message)

        self.tasks.start(self.settings.forget, forgotten, failed, key="forget")
