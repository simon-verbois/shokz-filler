"""YouTube search controls and result presentation, without service access."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from .icons import icon
from .library_view import LibraryDelegate, library_rows
from .models import Playlist, Track
from .page_layout import NO_DEVICE_MESSAGE, PageTemplate
from .table_filters import ColumnFilters
from .table_state import TableEmptyState
from .theme import ACCENT, ON_ACCENT, RoundedComboBox, role

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


class BrowserPanel(PageTemplate):
    libraryRequested = Signal()
    backRequested = Signal()
    forwardRequested = Signal()
    searchRequested = Signal()
    downloadRequested = Signal()
    contextRequested = Signal(QPoint)
    activated = Signal(int, int)
    selectionChanged = Signal()
    pendingChanged = Signal()
    playlistAddRequested = Signal(object)
    settingsRequested = Signal()

    def __init__(self) -> None:
        super().__init__("YouTube Music")
        self.pending: list[Track] = []  # the send list, in playback order
        self.pending_origin: dict[str, Playlist | None] = {}  # playlist a song was added from
        self.current_playlist: Playlist | None = None
        self.results_sort_column: int | None = None
        self.results_sort_order = Qt.SortOrder.AscendingOrder
        library = QPushButton("My playlists")
        library.setToolTip("Your YouTube Music playlists (connect your account in Settings)")
        self.library_button = library
        library.clicked.connect(self.libraryRequested.emit)
        self.browser_back = QPushButton()
        self.browser_back.setIcon(icon("back"))
        self.browser_back.setFixedWidth(36)
        self.browser_back.setAccessibleName("Previous YouTube Music page")
        self.browser_back.setToolTip("Go back to the previous YouTube Music page")
        self.browser_back.setEnabled(False)
        self.browser_back.clicked.connect(self.backRequested.emit)
        self.browser_forward = QPushButton()
        self.browser_forward.setIcon(icon("forward"))
        self.browser_forward.setFixedWidth(36)
        self.browser_forward.setAccessibleName("Next YouTube Music page")
        self.browser_forward.setToolTip("Go forward to the next YouTube Music page")
        self.browser_forward.setEnabled(False)
        self.browser_forward.clicked.connect(self.forwardRequested.emit)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search songs, artists or playlists…")
        self.search_edit.setAccessibleName("Search YouTube Music")
        self.search_edit.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.searchRequested.emit)
        self.search_type = RoundedComboBox()
        self.search_type.addItems(["Songs", "Playlists"])
        self.search_type.setAccessibleName("YouTube Music search type")
        search_button = QPushButton()
        search_button.setIcon(icon("search"))
        search_button.setAccessibleName("Search")
        search_button.setToolTip("Search (Enter)")
        search_button.setFixedWidth(36)
        search_button.clicked.connect(self.searchRequested.emit)
        self.filter_button = QPushButton()
        self.filter_button.setIcon(icon("filter"))
        self.filter_button.setFixedWidth(36)
        self.filter_button.setAccessibleName("Sort and filter music")
        self.filter_button.setToolTip("Sort and filter music")
        role(library, "quiet")
        library.setIcon(icon("music"))
        self.header.addWidget(library)
        self.settings_button = QPushButton("Connection settings")
        self.settings_button.setIcon(icon("settings"))
        role(self.settings_button, "quiet")
        self.settings_button.clicked.connect(self.settingsRequested)
        self.header.addWidget(self.settings_button)
        self.browser_title = self.subtitle
        self.browser_title.clear()  # The empty state below already says it.
        for widget in (self.search_type, self.search_edit, search_button):
            self.controls.addWidget(widget)
        self.controls.setStretch(1, 1)
        for widget in (self.browser_back, self.browser_forward, self.filter_button):
            self.controls.addWidget(widget)
        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels(
            ["Title", "Artist / count", "Duration", "Add", "More"]
        )
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
        results_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        results_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.results.setColumnWidth(3, 68)
        self.results.setColumnHidden(4, True)
        results_header.sectionClicked.connect(self._sort_results)
        self.results.setColumnWidth(1, 280)
        self.result_filters = ColumnFilters(self.results, (0, 1))
        library_rows(self.results)
        results_header.hide()
        self.filter_button.setMenu(self._filter_menu())
        self.results.cellClicked.connect(self._row_action)
        self.results.cellDoubleClicked.connect(self._activate_row)
        self.results.itemSelectionChanged.connect(self.selectionChanged.emit)
        self.results.setToolTip(
            "Double-click a playlist to open it; double-click a song to download it"
        )
        self.empty_state = TableEmptyState(
            self.results, "Find your next swim soundtrack\nSearch for songs or open My playlists."
        )
        self.content.addWidget(self.results)
        download = QPushButton("Send to Shokz")
        role(download, "primary")
        download.setIcon(icon("download", ON_ACCENT))
        download.setToolTip(
            "Opens the transfer assistant for the songs you added with +. "
            "Existing YouTube tracks in the chosen folder are skipped. "
            "Filename conflicts keep both files with numbered names."
        )
        self.download_button = download
        download.clicked.connect(self.downloadRequested.emit)
        self.clear_pending_button = QPushButton("Clear list")
        role(self.clear_pending_button, "quiet")
        self.clear_pending_button.setToolTip("Empty the send list")
        self.clear_pending_button.clicked.connect(self.clear_pending)
        self.clear_pending_button.hide()
        self.device_label = QLabel(NO_DEVICE_MESSAGE)
        role(self.device_label, "muted")
        self.footer.addWidget(self.device_label)
        self.footer.addStretch(1)
        self.footer.addWidget(self.clear_pending_button)
        self.footer.addWidget(download)

    def _filter_menu(self) -> QMenu:
        menu = QMenu(self)
        for column, title in ((0, "Title"), (1, "Artist / count"), (2, "Duration")):
            action = menu.addAction(f"Sort by {title.lower()}")
            action.triggered.connect(partial(self._sort_results, column))
            if column < 2:
                action = menu.addAction(f"Filter {title.lower()}…")
                action.triggered.connect(partial(self.result_filters.edit, column))
        menu.addSeparator()
        menu.addAction("Clear filters", self.result_filters.clear)
        return menu

    def _row_button(self, column: int, is_playlist: bool) -> QWidget:
        """A real button per row; its row is resolved at click time, so sorting stays safe."""
        cell = QWidget()
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton()
        button.setFixedSize(38, 38)
        role(button, "rowbutton")
        button.setIcon(icon("plus"))
        label = "Add the whole playlist to the send list" if is_playlist else "Add to the send list"
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(partial(self._row_button_clicked, cell, column))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
        delegate = self.results.itemDelegate()
        if isinstance(delegate, LibraryDelegate):
            delegate.track(cell)
        return cell

    def _row_button_clicked(self, cell: QWidget, column: int) -> None:
        row = self.results.indexAt(cell.pos()).row()
        if row >= 0:
            self._row_action(row, column)

    def _row_action(self, row: int, column: int) -> None:
        if column != 3:
            return
        first = self.results.item(row, 0)
        if first is None:
            return
        item = first.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item, (Track, Playlist)) or self.results.isRowHidden(row):
            return
        self.results.clearSelection()
        self.results.selectRow(row)
        if isinstance(item, Playlist):
            self.playlistAddRequested.emit(item)
        elif isinstance(item, Track):
            self.toggle_pending(item)

    def in_pending(self, track: Track) -> bool:
        return any(item.video_id == track.video_id for item in self.pending)

    def toggle_pending(self, track: Track) -> None:
        if self.in_pending(track):
            self.remove_pending([track])
        else:
            self.add_pending([track])

    def add_pending(self, tracks: list[Track], origin: Playlist | None = None) -> None:
        source = origin or self.current_playlist
        for track in tracks:
            if not self.in_pending(track):
                self.pending.append(track)
                self.pending_origin[track.video_id] = source
        self._pending_updated()

    def remove_pending(self, tracks: list[Track]) -> None:
        removed = {track.video_id for track in tracks}
        self.pending = [item for item in self.pending if item.video_id not in removed]
        self._pending_updated()

    def discard_pending(self, tracks: list[Track]) -> None:
        self.remove_pending(tracks)

    def clear_pending(self) -> None:
        self.pending = []
        self._pending_updated()

    def pending_groups(self) -> list[tuple[Playlist | None, list[Track]]]:
        """The send list split by origin: each opened playlist, then loose songs, in order."""
        groups: dict[str, tuple[Playlist | None, list[Track]]] = {}
        for track in self.pending:
            origin = self.pending_origin.get(track.video_id)
            key = origin.playlist_id if origin else ""
            groups.setdefault(key, (origin, []))[1].append(track)
        return list(groups.values())

    def _pending_updated(self) -> None:
        count = len(self.pending)
        self.pending_origin = {
            key: value
            for key, value in self.pending_origin.items()
            if any(item.video_id == key for item in self.pending)
        }
        self.download_button.setText(f"Send to Shokz ({count})" if count else "Send to Shokz")
        self.clear_pending_button.setVisible(bool(count))
        self._refresh_row_buttons()
        self.pendingChanged.emit()

    def _refresh_row_buttons(self) -> None:
        queued = {track.video_id for track in self.pending}
        for row in range(self.results.rowCount()):
            first = self.results.item(row, 0)
            item = first.data(Qt.ItemDataRole.UserRole) if first else None
            cell = self.results.cellWidget(row, 3)
            button = cell.findChild(QPushButton) if cell else None
            if button is None or not isinstance(item, Track):
                continue
            selected = item.video_id in queued
            button.setIcon(icon("check", ACCENT) if selected else icon("plus"))
            label = "Remove from the send list" if selected else "Add to the send list"
            button.setToolTip(label)
            button.setAccessibleName(label)

    def _activate_row(self, row: int, column: int) -> None:
        if column < 3:
            self.activated.emit(row, column)

    def _show_results(self, objects: object) -> None:
        result_objects = list(objects) if isinstance(objects, list) else []
        self.results.setSortingEnabled(False)
        self.results.setRowCount(0)
        if not result_objects:
            self.results.setRowCount(0)
            self.empty_state.set_text("No results found\nTry a different song, artist or playlist.")
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
                    table_item.setToolTip(f"{item.title}\n{values[1][0]}")
                    table_item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, values[1][0])
                self.results.setItem(row, column, table_item)
            is_playlist = isinstance(item, Playlist)
            self.results.setItem(
                row, 3, QTableWidgetItem("Open playlist" if is_playlist else "Download")
            )
            self.results.setCellWidget(row, 3, self._row_button(3, is_playlist))
        if self.results_sort_column is not None:
            self.results.sortItems(self.results_sort_column, self.results_sort_order)
        self._refresh_row_buttons()

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
        self.results.sortItems(column, self.results_sort_order)

    def _selected_result_objects(self) -> list[Track | Playlist]:
        selected: list[Track | Playlist] = []
        for index in self.results.selectionModel().selectedRows():
            if self.results.isRowHidden(index.row()):
                continue
            table_item = self.results.item(index.row(), 0)
            value = table_item.data(Qt.ItemDataRole.UserRole) if table_item else None
            if isinstance(value, (Track, Playlist)):
                selected.append(value)
        return selected
