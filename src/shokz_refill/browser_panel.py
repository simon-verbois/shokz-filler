"""YouTube search controls and result presentation, without service access."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from .models import Playlist, Track
from .table_filters import ColumnFilters

_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: str | int) -> None:
        super().__init__(text)
        self.setData(_SORT_ROLE, sort_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        own_value = self.data(_SORT_ROLE)
        other_value = other.data(_SORT_ROLE)
        if isinstance(own_value, int) and isinstance(other_value, int):
            return own_value < other_value
        if isinstance(own_value, str) and isinstance(other_value, str):
            return own_value.casefold() < other_value.casefold()
        return super().__lt__(other)


class BrowserPanel(QWidget):
    authRequested = Signal()
    disconnectRequested = Signal()
    libraryRequested = Signal()
    backRequested = Signal()
    forwardRequested = Signal()
    searchRequested = Signal()
    downloadRequested = Signal()
    playlistDownloadRequested = Signal()
    contextRequested = Signal(QPoint)
    activated = Signal(int, int)
    selectionChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.results_sort_column: int | None = None
        self.results_sort_order = Qt.SortOrder.AscendingOrder
        layout = QVBoxLayout(self)
        auth = QHBoxLayout()
        self.auth_label = QLabel()
        connect = QPushButton("Connect YouTube Music")
        self.connect_button = connect
        connect.clicked.connect(self.authRequested.emit)
        disconnect = QPushButton("Disconnect")
        self.disconnect_button = disconnect
        disconnect.clicked.connect(self.disconnectRequested.emit)
        library = QPushButton("My playlists")
        self.library_button = library
        library.clicked.connect(self.libraryRequested.emit)
        auth.addWidget(self.auth_label)
        auth.addStretch()
        auth.addWidget(connect)
        auth.addWidget(disconnect)
        auth.addWidget(library)
        layout.addLayout(auth)
        search = QHBoxLayout()
        self.browser_back = QPushButton("<")
        self.browser_back.setFixedWidth(34)
        self.browser_back.setAccessibleName("Previous YouTube Music page")
        self.browser_back.setToolTip("Go back to the previous YouTube Music page")
        self.browser_back.setEnabled(False)
        self.browser_back.clicked.connect(self.backRequested.emit)
        self.browser_forward = QPushButton(">")
        self.browser_forward.setFixedWidth(34)
        self.browser_forward.setAccessibleName("Next YouTube Music page")
        self.browser_forward.setToolTip("Go forward to the next YouTube Music page")
        self.browser_forward.setEnabled(False)
        self.browser_forward.clicked.connect(self.forwardRequested.emit)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search YouTube Music")
        self.search_edit.returnPressed.connect(self.searchRequested.emit)
        self.search_type = QComboBox()
        self.search_type.addItems(["Songs", "Playlists"])
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.searchRequested.emit)
        search.addWidget(self.browser_back)
        search.addWidget(self.browser_forward)
        search.addWidget(self.search_edit)
        search.addWidget(self.search_type)
        search.addWidget(search_button)
        layout.addLayout(search)
        self.browser_title = QLabel("Search for songs or playlists to get started")
        layout.addWidget(self.browser_title)
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(["Title", "Artist / count", "Duration"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.contextRequested.emit)
        results_header = self.results.horizontalHeader()
        results_header.setStretchLastSection(False)
        results_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        results_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        results_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        results_header.setSortIndicatorShown(False)
        results_header.sectionClicked.connect(self._sort_results)
        self.results.setColumnWidth(1, 280)
        self.result_filters = ColumnFilters(self.results, (0, 1))
        self.results.cellDoubleClicked.connect(self.activated.emit)
        self.results.itemSelectionChanged.connect(self.selectionChanged.emit)
        self.results.setToolTip(
            "Double-click a playlist to open it; double-click a song to download it"
        )
        layout.addWidget(self.results)
        row = QHBoxLayout()
        self.destination_label = QLabel("Destination: select a Shokz folder")
        download = QPushButton("Download / transfer selected")
        self.download_button = download
        download.clicked.connect(self.downloadRequested.emit)
        self.download_playlist_button = QPushButton("Download whole playlist")
        self.download_playlist_button.setEnabled(False)
        self.download_playlist_button.clicked.connect(self.playlistDownloadRequested.emit)
        row.addWidget(self.destination_label)
        row.addStretch()
        row.addWidget(download)
        row.addWidget(self.download_playlist_button)
        layout.addLayout(row)
        policy = QLabel(
            "Existing YouTube tracks in this folder are skipped. "
            "Filename conflicts keep both files with numbered names."
        )
        policy.setWordWrap(True)
        layout.addWidget(policy)

    def _show_results(self, objects: object) -> None:
        result_objects = list(objects) if isinstance(objects, list) else []
        self.results.setSortingEnabled(False)
        self.results.clearContents()
        if not result_objects:
            self.results.setRowCount(1)
            self.results.setItem(0, 0, QTableWidgetItem("No results found"))
            self.results.setItem(0, 1, QTableWidgetItem("Try a different search"))
            return
        self.results.setRowCount(len(result_objects))
        for row, item in enumerate(result_objects):
            if isinstance(item, Track):
                duration_seconds = (
                    item.duration_seconds if item.duration_seconds is not None else -1
                )
                duration = (
                    ""
                    if item.duration_seconds is None
                    else f"{item.duration_seconds // 60}:{item.duration_seconds % 60:02d}"
                )
                values: tuple[tuple[str, str | int], ...] = (
                    (item.title, item.title),
                    (item.artist, item.artist),
                    (duration, duration_seconds),
                )
            else:
                values = (
                    (item.title, item.title),
                    (f"{item.count} tracks" if item.count else "Playlist", item.count or 0),
                    ("", -1),
                )
            for column, (text, sort_value) in enumerate(values):
                table_item = SortableTableItem(text, sort_value)
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, item)
                self.results.setItem(row, column, table_item)
        if self.results_sort_column is not None:
            self.results.sortItems(self.results_sort_column, self.results_sort_order)

    def _sort_results(self, column: int) -> None:
        if self.results_sort_column == column:
            self.results_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self.results_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self.results_sort_column = column
            self.results_sort_order = Qt.SortOrder.AscendingOrder
        header = self.results.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, self.results_sort_order)
        self.results.sortItems(column, self.results_sort_order)

    def _selected_result_objects(self) -> list[Track | Playlist]:
        selected: list[Track | Playlist] = []
        for index in self.results.selectionModel().selectedRows():
            table_item = self.results.item(index.row(), 0)
            value = table_item.data(Qt.ItemDataRole.UserRole) if table_item else None
            if isinstance(value, (Track, Playlist)):
                selected.append(value)
        return selected
