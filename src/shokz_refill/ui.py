from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audiobook_panel import AudiobookshelfController, AudiobookshelfPanel
from .audiobook_queue import AudiobookQueue
from .audiobook_settings import AudiobookshelfSettings
from .background import TaskRunner
from .book_dialogs import SpeechSettingsPanel
from .book_export import BookExportOptions
from .browser_panel import BrowserPanel
from .config import ConfigStore
from .device import DeviceDetector, manual_device
from .dialogs import AuthDialog, DeviceFolderDialog
from .downloads import DownloadQueue, cleanup_stale_cache
from .files import DeviceFileService
from .filesystem import device_operation
from .media import MediaDownloader
from .metadata import validate_source_mp3
from .models import Device, DownloadJob, JobStatus, Playlist, Track
from .naming import playlist_folder_name, sanitize_component
from .queue_panel import QueuePanel
from .table_filters import ColumnFilters
from .transfer import TransferManager
from .youtube import YouTubeMusicService


@dataclass(slots=True)
class BrowserPage:
    title: str
    items: list[Track | Playlist]
    playlist: Playlist | None = None


class DeviceFileTable(QTableWidget):
    moveRequested = Signal(object, int)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        target_row = self.rowAt(event.position().toPoint().y())
        self.moveRequested.emit(rows, target_row)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


class MainWindow(QMainWindow):
    queueUpdated = Signal(object)
    deviceProgress = Signal(int)

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self.config = store.load()
        self.youtube = YouTubeMusicService(store.auth_path)
        self.detector = DeviceDetector()
        self.tasks = TaskRunner(self)
        self.pool = self.tasks.pool
        self._closing = False
        self._close_timer = QTimer(self)
        self._close_timer.timeout.connect(self._finish_close)
        self._device_cancel = threading.Event()
        self._device_busy = False
        self.device: Device | None = None
        self.current_folder: Path | None = None
        self.folder_history: list[Path] = []
        self.folder_history_index = -1
        self.destination: Path | None = None
        self.result_objects: list[Track | Playlist] = []
        self.browser_page = BrowserPage("YouTube Music", [])
        self.browser_history: list[BrowserPage] = []
        self.browser_history_index = -1
        self.file_objects: list[Path] = []
        self._file_kinds: dict[Path, bool] = {}
        transfer_state = store.cache_dir / "transfers.json"
        self.transfer = TransferManager(transfer_state)
        self.queue = DownloadQueue(
            store.cache_dir,
            self.transfer,
            downloader=MediaDownloader(store.auth_path),
            callback=self._queue_callback,
        )
        self.audiobook_queue = AudiobookQueue(store.cache_dir, self.transfer, self._queue_callback)
        self._queues = (self.queue, self.audiobook_queue)
        self._build_ui()
        self._run(lambda: cleanup_stale_cache(store.cache_dir, transfer_state), lambda _v: None)
        self.resize(self.config.window_width, self.config.window_height)
        self._refresh_auth_label()
        self._update_actions()
        self._poll_devices()
        self.device_timer = QTimer(self)
        self.device_timer.timeout.connect(self._poll_devices)
        self.device_timer.start(5000)
        self.deviceProgress.connect(
            self.device_operation_progress.setValue, Qt.ConnectionType.QueuedConnection
        )

    def _build_ui(self) -> None:
        self.setWindowTitle("Shokz Refill")
        central = QWidget()
        outer = QVBoxLayout(central)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._youtube_tab(), "YouTube Music")
        settings = AudiobookshelfSettings(self.store.config_dir / "audiobookshelf.json")
        self.audiobookshelf_panel = AudiobookshelfPanel(settings.load())
        self.audiobookshelf = AudiobookshelfController(
            self.audiobookshelf_panel,
            settings,
            self.audiobook_queue,
            lambda: self.device,
            lambda: self.config.book_export_options(),
        )
        self.audiobookshelf.jobsQueued.connect(self._update_actions)
        self.tabs.addTab(self.audiobookshelf_panel, "Audiobookshelf")
        self.tabs.addTab(self._device_tab(), "Shokz device / files")
        self.speech_settings = SpeechSettingsPanel(self.config.book_export_options())
        self.speech_settings.saveRequested.connect(self._save_speech_settings)
        self.tabs.addTab(self.speech_settings, "Settings")
        self.queue_panel = QueuePanel()
        self.queue_panel.retryRequested.connect(self._retry_jobs)
        self.queue_panel.cancelRequested.connect(self._cancel_jobs)
        self.queue_table = self.queue_panel.table
        self.overall_progress = self.queue_panel.overall
        self.queueUpdated.connect(self._update_queue_row, Qt.ConnectionType.QueuedConnection)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.queue_panel)
        splitter.setSizes([500, 220])
        outer.addWidget(splitter)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

    def _save_speech_settings(self, options: BookExportOptions) -> None:
        options.validate()
        self.config.book_tts_template = options.template
        self.config.book_tts_voice = options.voice
        self.config.book_tts_rate = options.rate
        snapshot = replace(self.config)

        def saved(_value: object) -> None:
            self.speech_settings.status.setText(
                "Settings saved"
                if self.speech_settings.options == options
                else "Settings saved; newer changes remain unsaved"
            )

        self._run(
            lambda: self.store.save(snapshot),
            saved,
            "Saving speech settings…",
            lambda message: self.speech_settings.status.setText(message),
            key="settings",
        )

    def _youtube_tab(self) -> QWidget:
        self.browser = BrowserPanel()
        self.browser.authRequested.connect(self._connect_youtube)
        self.browser.disconnectRequested.connect(self._disconnect_youtube)
        self.browser.libraryRequested.connect(self._load_library)
        self.browser.backRequested.connect(self._browser_go_back)
        self.browser.forwardRequested.connect(self._browser_go_forward)
        self.browser.searchRequested.connect(self._search)
        self.browser.downloadRequested.connect(self._download_selected)
        self.browser.playlistDownloadRequested.connect(self._download_current_playlist)
        self.browser.contextRequested.connect(self._results_context_menu)
        self.browser.activated.connect(self._result_double_clicked)
        self.browser.selectionChanged.connect(self._update_actions)
        self.results = self.browser.results
        self.browser_title = self.browser.browser_title
        self.browser_back = self.browser.browser_back
        self.browser_forward = self.browser.browser_forward
        self.search_edit = self.browser.search_edit
        self.search_type = self.browser.search_type
        self.auth_label = self.browser.auth_label
        self.connect_button = self.browser.connect_button
        self.disconnect_button = self.browser.disconnect_button
        self.library_button = self.browser.library_button
        self.download_button = self.browser.download_button
        self.download_playlist_button = self.browser.download_playlist_button
        self.destination_label = self.browser.destination_label
        return self.browser

    def _device_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_selected)
        manual = QPushButton("Select device folder")
        self.manual_device_button = manual
        manual.clicked.connect(self._select_manual_device)
        self.storage_label = QLabel("No Shokz connected")
        top.addWidget(QLabel("Device:"))
        top.addWidget(self.device_combo, 1)
        top.addWidget(manual)
        top.addWidget(self.storage_label)
        layout.addLayout(top)
        location = QHBoxLayout()
        self.folder_back = QPushButton("<")
        self.folder_back.setFixedWidth(34)
        self.folder_back.setAccessibleName("Previous device folder")
        self.folder_back.setToolTip("Go back to the previously visited folder")
        self.folder_back.setEnabled(False)
        self.folder_back.clicked.connect(self._folder_go_back)
        self.folder_forward = QPushButton(">")
        self.folder_forward.setFixedWidth(34)
        self.folder_forward.setAccessibleName("Next device folder")
        self.folder_forward.setToolTip("Go forward to the next visited folder")
        self.folder_forward.setEnabled(False)
        self.folder_forward.clicked.connect(self._folder_go_forward)
        location.addWidget(self.folder_back)
        location.addWidget(self.folder_forward)
        self.device_root_button = QPushButton("Device root")
        self.device_root_button.clicked.connect(self._go_device_root)
        location.addWidget(self.device_root_button)
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        location.addWidget(self.folder_label, 1)
        layout.addLayout(location)
        self.files = DeviceFileTable(0, 3)
        self.files.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        self.files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setDragEnabled(True)
        self.files.setAcceptDrops(True)
        self.files.setDropIndicatorShown(True)
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.files.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.files.moveRequested.connect(self._move_rows_to_folder)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._files_context_menu)
        files_header = self.files.horizontalHeader()
        files_header.setStretchLastSection(False)
        files_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        files_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        files_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.file_filters = ColumnFilters(self.files, (0, 1))
        self.files.doubleClicked.connect(self._open_folder)
        self.files.itemSelectionChanged.connect(self._update_actions)
        layout.addWidget(self.files)
        actions = QHBoxLayout()
        self.file_buttons: dict[str, QPushButton] = {}
        for label, handler in (
            ("New folder", self._new_folder),
            ("Rename", self._rename),
            ("Move selected…", self._move_selected),
            ("Delete", self._delete),
            ("Add local MP3", self._add_local),
            ("Change download folder…", self._select_destination),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            self.file_buttons[label] = button
            actions.addWidget(button)
        self.resume_button = QPushButton("Resume interrupted copies")
        self.resume_button.clicked.connect(self._resume_transfers)
        self.stop_device_button = QPushButton("Cancel operation")
        self.stop_device_button.clicked.connect(self._device_cancel.set)
        controls = QHBoxLayout()
        controls.addWidget(self.resume_button)
        controls.addWidget(self.stop_device_button)
        controls.addStretch()
        actions.addStretch()
        layout.addLayout(actions)
        layout.addLayout(controls)
        device_activity = QHBoxLayout()
        self.device_operation_label = QLabel("Device operation: idle")
        self.device_operation_label.setWordWrap(True)
        self.device_operation_progress = QProgressBar()
        self.device_operation_progress.setMaximumWidth(220)
        self.device_operation_progress.setRange(0, 100)
        self.device_operation_progress.setValue(0)
        self.device_operation_progress.setVisible(False)
        device_activity.addWidget(self.device_operation_label)
        device_activity.addWidget(self.device_operation_progress)
        device_activity.addStretch()
        layout.addLayout(device_activity)
        return widget

    def _run(
        self,
        function: Callable[[], Any],
        success: Callable[[Any], None],
        message: str = "Working…",
        failure: Callable[[str], None] | None = None,
        *,
        key: str | None = None,
    ) -> None:
        if self._closing:
            return
        self.statusBar().showMessage(message)

        def completed(value: object) -> None:
            self.statusBar().showMessage("Ready")
            success(value)

        self.tasks.start(function, completed, failure or self._show_error, key=key)

    def _reserved_paths(self, paths: list[Path]) -> bool:
        return any(
            job.status
            not in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.SKIPPED}
            and any(path == job.destination or path in job.destination.parents for path in paths)
            for queue in self._queues
            for job in queue.jobs.values()
        )

    def _update_actions(self) -> None:
        if not hasattr(self, "file_buttons"):
            return
        ready = self.device is not None and not self._closing
        writable = ready and not self._device_busy
        paths = self._selected_paths()
        editable = writable and not self._reserved_paths(paths)
        self.download_button.setEnabled(
            ready and any(isinstance(item, Track) for item in self._selected_result_objects())
        )
        self.download_playlist_button.setEnabled(ready and self.browser_page.playlist is not None)
        for label, button in self.file_buttons.items():
            enabled = writable
            if label == "Rename":
                enabled = editable and len(paths) == 1
            elif label in {"Move selected…", "Delete"}:
                enabled = editable and bool(paths)
            button.setEnabled(enabled)
        self.resume_button.setEnabled(writable)
        self.stop_device_button.setEnabled(self._device_busy and not self._closing)
        self.device_combo.setEnabled(not self._device_busy)
        self.manual_device_button.setEnabled(not self._device_busy)
        self.device_root_button.setEnabled(ready)

    def _run_device(
        self, function: Callable[[], Any], success: Callable[[Any], None], message: str
    ) -> None:
        if self._device_busy or self._closing:
            return
        self._device_busy = True
        self._device_cancel.clear()
        self._set_device_operation(message, busy=True)
        self._update_actions()

        def run() -> Any:
            with device_operation(self._device_cancel.is_set):
                return function()

        def completed(value: object) -> None:
            self._device_busy = False
            self._update_actions()
            success(value)

        def failed(error: str) -> None:
            self._device_busy = False
            self._update_actions()
            self._refresh_files()
            if self._device_cancel.is_set():
                self._set_device_operation("Cancelled; completed items were kept")
            else:
                self._device_operation_failed(error)

        self._run(run, completed, message, failed, key="device-operation")

    def _resume_transfers(self) -> None:
        if self.device is None:
            return
        root = self.device.root
        self._run_device(
            lambda: self.transfer.resume_for_device(
                root, self._device_cancel.is_set, self.deviceProgress.emit
            ),
            self._resumed_transfers,
            "Resuming interrupted copies — keep the Shokz connected",
        )

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage("Operation failed")
        QMessageBox.warning(self, "Shokz Refill", message or "The operation failed")

    def _refresh_auth_label(self) -> None:
        if self.youtube.connection_verified:
            label = "YouTube Music: connected"
        elif self.youtube.authenticated:
            label = "YouTube Music: saved session (not yet verified)"
        else:
            label = "YouTube Music: not connected"
        self.auth_label.setText(label)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(self.youtube.authenticated)
        self.library_button.setEnabled(self.youtube.authenticated)

    def _connect_youtube(self) -> None:
        if self.tasks.active("auth"):
            return
        dialog = AuthDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        raw = dialog.headers.toPlainText()
        self.tasks.cancel("browser")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)

        def failed(message: str) -> None:
            self._refresh_auth_label()
            self._show_error(message)

        self._run(
            lambda: self.youtube.connect_headers(raw),
            self._connected,
            "Validating account…",
            failed,
            key="auth",
        )

    def _connected(self, name: object) -> None:
        self._refresh_auth_label()
        self.statusBar().showMessage(f"YouTube Music connected: {name}")

    def _disconnect_youtube(self) -> None:
        if self.tasks.active("auth"):
            return
        self.tasks.cancel("browser")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self._run(
            self.youtube.disconnect,
            lambda _v: self._refresh_auth_label(),
            "Removing local YouTube Music credentials…",
            key="auth",
        )

    def _search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self.tasks.cancel("browser")
        self.result_objects = []
        self.results.clearContents()
        self.results.setRowCount(1)
        self.results.setItem(0, 0, QTableWidgetItem("Searching…"))
        self.results.setItem(0, 1, QTableWidgetItem("Please wait"))
        function = (
            self.youtube.search_songs
            if self.search_type.currentText() == "Songs"
            else self.youtube.search_playlists
        )
        title = f"Search: {query}"
        self._run(
            lambda: function(query),
            lambda objects: self._set_browser_root(title, objects),
            "Searching YouTube Music…",
            key="browser",
        )

    def _load_library(self) -> None:
        self._run(
            self.youtube.library_playlists,
            self._library_loaded,
            "Loading your playlists…",
            failure=self._library_failed,
            key="browser",
        )

    def _library_failed(self, message: str) -> None:
        self._refresh_auth_label()
        self._show_error(message)

    def _library_loaded(self, objects: object) -> None:
        self._refresh_auth_label()
        self._set_browser_root("My playlists", objects)

    def _set_browser_root(self, title: str, objects: object) -> None:
        items = list(objects) if isinstance(objects, list) else []
        page = BrowserPage(title, items)
        self.browser_history = [page]
        self.browser_history_index = 0
        self._set_browser_page(page)

    def _set_browser_page(self, page: BrowserPage) -> None:
        self.browser_page = page
        self.browser_title.setText(f"{page.title} — {len(page.items)} item(s)")
        self.browser_back.setEnabled(self.browser_history_index > 0)
        self.browser_forward.setEnabled(
            0 <= self.browser_history_index < len(self.browser_history) - 1
        )
        self.download_playlist_button.setEnabled(
            page.playlist is not None and self.device is not None
        )
        self._show_results(page.items)
        self._render_device()

    def _browser_go_back(self) -> None:
        self.tasks.cancel("browser")
        if self.browser_history_index > 0:
            self.browser_history_index -= 1
            self._set_browser_page(self.browser_history[self.browser_history_index])

    def _browser_go_forward(self) -> None:
        self.tasks.cancel("browser")
        if self.browser_history_index < len(self.browser_history) - 1:
            self.browser_history_index += 1
            self._set_browser_page(self.browser_history[self.browser_history_index])

    def _enter_playlist(self, playlist: Playlist, objects: object) -> None:
        tracks: list[Track | Playlist] = (
            [item for item in objects if isinstance(item, Track)]
            if isinstance(objects, list)
            else []
        )
        page = BrowserPage(playlist.title, tracks, playlist)
        self.browser_history = self.browser_history[: self.browser_history_index + 1]
        self.browser_history.append(page)
        self.browser_history_index += 1
        self._set_browser_page(page)

    def _show_results(self, objects: object) -> None:
        self.result_objects = list(objects) if isinstance(objects, list) else []
        self.browser._show_results(objects)

    def _sort_results(self, column: int) -> None:
        self.browser._sort_results(column)

    def _selected_result_objects(self) -> list[Track | Playlist]:
        return self.browser._selected_result_objects()

    def _open_selected_playlist(self) -> None:
        selected = self._selected_result_objects()
        playlist = next((item for item in selected if isinstance(item, Playlist)), None)
        if playlist:
            self._open_playlist(playlist)

    def _open_playlist(self, playlist: Playlist) -> None:
        self._run(
            lambda: self.youtube.playlist_tracks(playlist.playlist_id),
            lambda objects: self._enter_playlist(playlist, objects),
            "Loading playlist…",
            key="browser",
        )

    def _result_double_clicked(self, row: int, _column: int) -> None:
        table_item = self.results.item(row, 0)
        item = table_item.data(Qt.ItemDataRole.UserRole) if table_item else None
        if not isinstance(item, (Track, Playlist)):
            return
        if isinstance(item, Playlist):
            self._open_playlist(item)
        elif self.browser_page.playlist is not None:
            self._prepare_playlist_download(self.browser_page.playlist, [item])
        else:
            self._download_tracks([item])

    def _download_selected(self) -> None:
        tracks = [item for item in self._selected_result_objects() if isinstance(item, Track)]
        if not tracks:
            self._show_error("Select one or more songs first")
            return
        if self.browser_page.playlist is not None:
            self._prepare_playlist_download(self.browser_page.playlist, tracks)
            return
        self._download_tracks(tracks)

    def _download_tracks(self, tracks: list[Track]) -> None:
        if not self.device:
            self._show_error("No connected Shokz device is selected")
            return
        device = self.device
        if self.destination is not None and self.destination != device.root:
            self._enqueue_tracks(tracks, self.destination, device)
            return
        dialog = DeviceFolderDialog(
            device,
            [],
            self,
            title="Choose download folder",
            allow_root=False,
            allow_create=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.destination is None:
            return
        self.destination = dialog.destination
        self.config.destination_relative = str(dialog.destination.relative_to(device.root))
        self._render_device()
        self._refresh_files()
        self._enqueue_tracks(tracks, dialog.destination, device)

    def _enqueue_tracks(self, tracks: list[Track], destination: Path, device: Device) -> None:
        self.queue.enqueue(tracks, destination, device.root)

    def _download_current_playlist(self) -> None:
        playlist = self.browser_page.playlist
        if playlist is not None:
            tracks = [item for item in self.browser_page.items if isinstance(item, Track)]
            self._prepare_playlist_download(playlist, tracks)

    def _download_playlist(self, playlist: Playlist) -> None:
        self._run(
            lambda: self.youtube.playlist_tracks(playlist.playlist_id),
            lambda objects: self._prepare_playlist_download(
                playlist,
                [item for item in objects if isinstance(item, Track)]
                if isinstance(objects, list)
                else [],
            ),
            f"Loading {playlist.title}…",
        )

    def _prepare_playlist_download(self, playlist: Playlist, tracks: list[Track]) -> None:
        if not tracks:
            self._show_error("This playlist has no downloadable tracks")
            return
        if not self.device:
            self._show_error("No connected Shokz device is selected")
            return
        device = self.device
        folder_name = playlist_folder_name(playlist.title)

        def prepare() -> Path:
            return DeviceFileService(device.root).ensure_folder(device.root, folder_name)

        def enqueue(value: object) -> None:
            if isinstance(value, Path):
                self.queue.enqueue(tracks, value, device.root)
                self.statusBar().showMessage(f"Queued {len(tracks)} track(s) in {value.name}")
                self._refresh_files()

        self._run(prepare, enqueue, f"Preparing folder {folder_name}…")

    def _results_context_menu(self, position: Any) -> None:
        row = self.results.rowAt(position.y())
        clicked_item = self.results.item(row, 0) if row >= 0 else None
        if (
            0 <= row < len(self.result_objects)
            and clicked_item is not None
            and not clicked_item.isSelected()
        ):
            self.results.clearSelection()
            self.results.selectRow(row)
        selected = self._selected_result_objects()
        playlist = next((item for item in selected if isinstance(item, Playlist)), None)
        tracks = [item for item in selected if isinstance(item, Track)]
        menu = QMenu(self)
        open_action = menu.addAction("Open playlist") if playlist else None
        playlist_action = (
            menu.addAction("Download playlist to automatic folder")
            if playlist or self.browser_page.playlist
            else None
        )
        tracks_action = menu.addAction("Download selected track(s)") if tracks else None
        if playlist_action is not None:
            playlist_action.setEnabled(self.device is not None)
        if tracks_action is not None:
            tracks_action.setEnabled(self.device is not None)
        select_all_action = menu.addAction("Select all")
        back_action = menu.addAction("Back") if self.browser_history_index > 0 else None
        forward_action = (
            menu.addAction("Forward")
            if self.browser_history_index < len(self.browser_history) - 1
            else None
        )
        chosen = menu.exec(self.results.viewport().mapToGlobal(position))
        if open_action is not None and chosen == open_action:
            self._open_selected_playlist()
        elif playlist_action is not None and chosen == playlist_action:
            if playlist:
                self._download_playlist(playlist)
            else:
                self._download_current_playlist()
        elif tracks_action is not None and chosen == tracks_action:
            self._download_selected()
        elif chosen == select_all_action:
            self.results.selectAll()
        elif back_action is not None and chosen == back_action:
            self._browser_go_back()
        elif forward_action is not None and chosen == forward_action:
            self._browser_go_forward()

    def _poll_devices(self) -> None:
        if self._closing or self.tasks.active("scan"):
            return
        manual = self.config.manual_device

        def scan() -> list[Device]:
            devices = self.detector.scan()
            if manual and all(str(device.root) != manual for device in devices):
                with suppress(OSError, ValueError):
                    devices.append(manual_device(Path(manual)))
            return devices

        self.tasks.start(scan, self._update_devices, lambda _message: None, key="scan")

    def _update_devices(self, value: object) -> None:
        devices = list(value) if isinstance(value, list) else []
        current_root = self.device.root if self.device else None
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("No device selected", None)
        selected_index = 0
        for device in devices:
            self.device_combo.addItem(f"{device.name} — {device.root}", device)
            if current_root == device.root:
                selected_index = self.device_combo.count() - 1
        self.device_combo.setCurrentIndex(selected_index)
        self.device_combo.blockSignals(False)
        if selected_index > 0:
            self.device = devices[selected_index - 1]
            self._render_device()
        if current_root and selected_index == 0:
            self._device_cancel.set()
            for queue in self._queues:
                queue.cancel(
                    [key for key, job in queue.jobs.items() if job.device_root == current_root]
                )
            self.tasks.cancel("files")
            self.device = None
            self.current_folder = None
            self.folder_history = []
            self.folder_history_index = -1
            self.destination = None
            self._render_device()
            self.statusBar().showMessage("Shokz device disconnected")
        elif not current_root and len(devices) == 1:
            self.device_combo.setCurrentIndex(1)

    def _device_selected(self, index: int) -> None:
        self.tasks.cancel("files")
        value = self.device_combo.itemData(index)
        self.device = value if isinstance(value, Device) else None
        if self.device:
            self.current_folder = self.device.root
            self._reset_folder_history(self.device.root)
            relative = self.config.destination_relative
            self.destination = self.device.root / relative if relative != "." else None
            if not self.device.automatic:
                self.config.manual_device = str(self.device.root)
            self._refresh_files()
        else:
            self.current_folder = None
            self.folder_history = []
            self.folder_history_index = -1
            self.destination = None
        self._render_device()

    def _resumed_transfers(self, result: object) -> None:
        self._set_device_operation("Resume check complete", complete=True)
        completed, errors = result if isinstance(result, tuple) else ([], [])
        if completed:
            self.statusBar().showMessage(f"Resumed {len(completed)} interrupted transfer(s)")
            self._refresh_files()
        if errors:
            self._show_error("\n".join(errors))

    def _select_manual_device(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Select mounted Shokz device folder", self.config.manual_device
        )
        if not chosen:
            return
        self._run(
            lambda: manual_device(Path(chosen)),
            self._manual_device_selected,
            "Reading selected device…",
            key="manual-device",
        )

    def _manual_device_selected(self, device: Device) -> None:
        self.tasks.cancel("scan")
        self.config.manual_device = str(device.root)
        self.device = None
        self._update_devices([device])

    def _render_device(self) -> None:
        self._update_actions()
        self.audiobookshelf.update_device()
        self.folder_label.setText(
            str(self.current_folder) if self.current_folder else "No folder selected"
        )
        if not self.device:
            self.folder_back.setEnabled(False)
            self.folder_forward.setEnabled(False)
            self.storage_label.setText("No Shokz connected")
            self.destination_label.setText("Destination: select a Shokz folder")
            self.files.setRowCount(0)
            return
        gib = 1024**3
        self.storage_label.setText(
            f"{self.device.free / gib:.1f} GiB free / {self.device.total / gib:.1f} GiB"
        )
        self.folder_back.setEnabled(self.folder_history_index > 0)
        self.folder_forward.setEnabled(
            0 <= self.folder_history_index < len(self.folder_history) - 1
        )
        if self.browser_page.playlist is not None:
            target = playlist_folder_name(self.browser_page.playlist.title)
            self.destination_label.setText(f"Playlist folder: {target} (automatic)")
        else:
            self.destination_label.setText(
                f"Download folder: {self.destination}"
                if self.destination
                else "Download folder: choose a folder when downloading"
            )

    def _refresh_files(self) -> None:
        if not self.device or not self.current_folder or self._closing:
            return
        root, folder = self.device.root, self.current_folder

        def read() -> list[tuple[Path, bool, int]]:
            return [
                (path, path.is_dir(), path.stat().st_size)
                for path in DeviceFileService(root).list_dir(folder)
            ]

        def show(entries: list[tuple[Path, bool, int]]) -> None:
            if (
                self.device is not None
                and self.device.root == root
                and self.current_folder == folder
            ):
                self._show_files(entries)

        self._run(read, show, "Reading device…", key="files")

    def _show_files(self, entries: list[tuple[Path, bool, int]]) -> None:
        self.file_objects = [path for path, _directory, _size in entries]
        self._file_kinds = {path: directory for path, directory, _size in entries}
        self.files.clearContents()
        self.files.setRowCount(len(entries))
        for row, (path, directory, size) in enumerate(entries):
            values = (
                path.name,
                "Folder" if directory else "MP3",
                "" if directory else f"{size / (1024 * 1024):.1f} MB",
            )
            for column, text in enumerate(values):
                self.files.setItem(row, column, QTableWidgetItem(text))
        self._render_device()

    def _selected_paths(self) -> list[Path]:
        return [
            self.file_objects[index.row()]
            for index in self.files.selectionModel().selectedRows()
            if index.row() < len(self.file_objects)
        ]

    def _files_context_menu(self, position: Any) -> None:
        if self._device_busy:
            return
        row = self.files.rowAt(position.y())
        clicked_item = self.files.item(row, 0) if row >= 0 else None
        if (
            0 <= row < len(self.file_objects)
            and clicked_item is not None
            and not clicked_item.isSelected()
        ):
            self.files.clearSelection()
            self.files.selectRow(row)
        selected = self._selected_paths()
        single_folder = (
            selected[0] if len(selected) == 1 and self._file_kinds.get(selected[0], False) else None
        )
        menu = QMenu(self)
        open_action = menu.addAction("Open folder") if single_folder else None
        destination_action = (
            menu.addAction("Use as download destination") if single_folder else None
        )
        rename_action = menu.addAction("Rename") if len(selected) == 1 else None
        move_action = menu.addAction("Move selected…") if selected else None
        delete_action = menu.addAction("Delete") if selected else None
        if selected:
            menu.addSeparator()
        new_folder_action = menu.addAction("New folder at device root")
        new_folder_action.setEnabled(self.device is not None and not self._device_busy)
        add_mp3_action = menu.addAction("Add local MP3 here")
        chosen = menu.exec(self.files.viewport().mapToGlobal(position))
        if open_action is not None and chosen == open_action:
            self._open_folder()
        elif destination_action is not None and chosen == destination_action:
            self._set_destination(single_folder)
        elif rename_action is not None and chosen == rename_action:
            self._rename()
        elif move_action is not None and chosen == move_action:
            self._move_selected()
        elif delete_action is not None and chosen == delete_action:
            self._delete()
        elif chosen == new_folder_action:
            self._new_folder()
        elif chosen == add_mp3_action:
            self._add_local()

    def _open_folder(self) -> None:
        selected = self._selected_paths()
        if selected and self._file_kinds.get(selected[0], False):
            self._navigate_folder(selected[0])

    def _go_device_root(self) -> None:
        if self.device is not None:
            self._navigate_folder(self.device.root)

    def _reset_folder_history(self, folder: Path) -> None:
        self.folder_history = [folder]
        self.folder_history_index = 0

    def _navigate_folder(self, folder: Path) -> None:
        if not self.device:
            self._show_error("Invalid destination path")
            return
        self.folder_history = self.folder_history[: self.folder_history_index + 1]
        self.folder_history.append(folder)
        self.folder_history_index += 1
        self.current_folder = folder
        self._render_device()
        self._refresh_files()

    def _folder_go_back(self) -> None:
        if self.folder_history_index > 0:
            self.folder_history_index -= 1
            self.current_folder = self.folder_history[self.folder_history_index]
            self._render_device()
            self._refresh_files()

    def _folder_go_forward(self) -> None:
        if self.folder_history_index < len(self.folder_history) - 1:
            self.folder_history_index += 1
            self.current_folder = self.folder_history[self.folder_history_index]
            self._render_device()
            self._refresh_files()

    def _new_folder(self) -> None:
        if not self.device or not self.current_folder:
            self._show_error("No Shokz device selected")
            return
        name, accepted = QInputDialog.getText(self, "New folder", "Folder name:")
        if accepted and name:
            parent = self.device.root
            self._run_device(
                lambda: DeviceFileService(parent).create_folder(parent, name),
                lambda _v: self._file_operation_complete("Folder created"),
                "Creating folder at device root…",
            )

    def _rename(self) -> None:
        selected = self._selected_paths()
        if self._reserved_paths(selected):
            self._show_error(
                "Wait for downloads to finish before changing their destination folder"
            )
            return
        if not self.device or len(selected) != 1:
            self._show_error("Select exactly one file or folder")
            return
        name, accepted = QInputDialog.getText(self, "Rename", "New name:", text=selected[0].stem)
        if accepted and name:
            root = self.device.root
            self._run_device(
                lambda: DeviceFileService(root).rename(selected[0], name),
                lambda _v: self._file_operation_complete("Rename complete"),
                "Renaming selected item…",
            )

    def _delete(self) -> None:
        selected = self._selected_paths()
        if self._reserved_paths(selected):
            self._show_error(
                "Wait for downloads to finish before deleting their destination folder"
            )
            return
        if not self.device or not selected:
            self._show_error("Select one or more files or folders")
            return
        includes_folders = any(self._file_kinds.get(path, False) for path in selected)
        detail = (
            " Selected folders and everything inside them will be permanently deleted."
            if includes_folders
            else ""
        )
        if (
            QMessageBox.question(
                self,
                "Delete",
                f"Permanently delete {len(selected)} selected item(s)?{detail}",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        root = self.device.root

        def delete_selected() -> None:
            service = DeviceFileService(root)
            for path in selected:
                if self._device_cancel.is_set():
                    raise InterruptedError("Deletion cancelled")
                service.delete(path)

        self._run_device(
            delete_selected,
            lambda _v: self._file_operation_complete("Deletion complete"),
            "Deleting…",
        )

    def _move_selected(self) -> None:
        selected = self._selected_paths()
        if not self.device or not self.current_folder or not selected:
            self._show_error("Select one or more files or folders to move")
            return
        dialog = DeviceFolderDialog(
            self.device,
            selected,
            self,
            title="Move selected items",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.destination is None:
            return
        self._move_paths(selected, dialog.destination)

    def _move_rows_to_folder(self, rows: object, target_row: int) -> None:
        if not isinstance(rows, list) or not 0 <= target_row < len(self.file_objects):
            self._show_error("Drop the selected items onto a folder")
            return
        destination = self.file_objects[target_row]
        if not self._file_kinds.get(destination, False):
            self._show_error("Drop the selected items onto a folder")
            return
        selected = [
            self.file_objects[row]
            for row in rows
            if isinstance(row, int) and 0 <= row < len(self.file_objects)
        ]
        self._move_paths(selected, destination)

    def _move_paths(self, selected: list[Path], destination: Path) -> None:
        if not self.device or not selected or self._device_busy:
            return
        if self._reserved_paths(selected):
            self._show_error("Wait for downloads to finish before moving their destination folder")
            return
        root = self.device.root
        count = len(selected)
        self._set_device_operation(f"Moving {count} item(s) — keep the Shokz connected", busy=True)

        def completed(value: object) -> None:
            moved_count = len(value) if isinstance(value, list) else 0
            self._set_device_operation(f"Move complete: {moved_count} item(s)", complete=True)
            self.statusBar().showMessage(f"Moved {moved_count} item(s)")
            self._refresh_files()

        self._run_device(
            lambda: DeviceFileService(root).move(
                selected, destination, cancelled=self._device_cancel.is_set
            ),
            completed,
            f"Moving {count} item(s) — keep the Shokz connected",
        )

    def _add_local(self) -> None:
        if not self.device or not self.current_folder:
            self._show_error("No Shokz device folder selected")
            return
        names, _ = QFileDialog.getOpenFileNames(self, "Add MP3 files", "", "MP3 audio (*.mp3)")
        if not names:
            return
        sources = [Path(name) for name in names]
        root, folder = self.device.root, self.current_folder
        self._set_device_operation(
            f"Copying {len(sources)} MP3 file(s) — keep the Shokz connected", busy=True
        )

        def copy_files() -> int:
            copied = 0
            for source in sources:
                validate_source_mp3(source)
                safe_name = sanitize_component(source.stem, max_bytes=220) + ".mp3"

                def report(value: int, completed: int = copied) -> None:
                    self.deviceProgress.emit(int((completed + value / 100) * 100 / len(sources)))

                self.transfer.transfer(
                    source,
                    folder / safe_name,
                    root,
                    report,
                    self._device_cancel.is_set,
                )
                copied += 1
            return copied

        self._run_device(
            copy_files,
            self._local_added,
            f"Copying {len(sources)} MP3 file(s) — keep the Shokz connected",
        )
        self.device_operation_progress.setRange(0, 100)

    def _file_operation_complete(self, message: str) -> None:
        self._set_device_operation(message, complete=True)
        self._refresh_files()

    def _local_added(self, result: object) -> None:
        copied = result if isinstance(result, int) else 0
        self._set_device_operation(f"Copy complete: {copied} MP3 file(s)", complete=True)
        self.statusBar().showMessage(f"Copied {copied} MP3 file(s)")
        self._refresh_files()

    def _device_operation_failed(self, message: str) -> None:
        self._set_device_operation(f"Device operation failed: {message}")
        self._show_error(message)

    def _set_device_operation(
        self, message: str, *, busy: bool = False, complete: bool = False
    ) -> None:
        self.device_operation_label.setText(f"Device operation: {message}")
        self.device_operation_progress.setVisible(busy or complete)
        if busy:
            self.device_operation_progress.setRange(0, 0)
        else:
            self.device_operation_progress.setRange(0, 100)
            self.device_operation_progress.setValue(100 if complete else 0)

    def _select_destination(self) -> None:
        if self.device is None:
            return
        dialog = DeviceFolderDialog(self.device, [], self, allow_root=False, allow_create=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_destination(dialog.destination)

    def _set_destination(self, folder: Path | None) -> None:
        if self.device and folder is not None and folder != self.device.root:
            self.destination = folder
            self.config.destination_relative = str(folder.relative_to(self.device.root))
            self._render_device()
            self.tabs.setCurrentIndex(0)

    def _queue_callback(self, job: DownloadJob) -> None:
        self.queueUpdated.emit(job)

    @Slot(object)
    def _update_queue_row(self, job: DownloadJob) -> None:
        if self._closing:
            return
        if self.queue_panel.update_job(job):
            self._refresh_files()
        self._update_actions()

    def _selected_job_ids(self) -> list[str]:
        return self.queue_panel.selected_ids()

    def _retry_jobs(self) -> None:
        if self.device:
            self.queue.retry(self._selected_job_ids(), self.device.root)
            self.audiobook_queue.retry(
                self._selected_job_ids(), self.device.root, self.audiobookshelf.client
            )

    def _cancel_jobs(self) -> None:
        for queue in self._queues:
            queue.cancel(self._selected_job_ids())

    def closeEvent(self, event: Any) -> None:
        if not self._closing:
            self._closing = True
            self.device_timer.stop()
            self._device_cancel.set()
            for queue in self._queues:
                queue.shutdown()
            for runner in self.findChildren(TaskRunner):
                runner.shutdown()
            self.setEnabled(False)
            self.statusBar().showMessage("Stopping operations safely…")
        if not all(queue.idle for queue in self._queues) or any(
            not runner.idle for runner in self.findChildren(TaskRunner)
        ):
            self._close_timer.start(25)
            event.ignore()
            return
        self._close_timer.stop()
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.store.save(self.config)
        super().closeEvent(event)

    @Slot()
    def _finish_close(self) -> None:
        if all(queue.idle for queue in self._queues) and all(
            runner.idle for runner in self.findChildren(TaskRunner)
        ):
            self._close_timer.stop()
            self.close()
