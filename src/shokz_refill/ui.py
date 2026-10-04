from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import ConfigStore
from .device import DeviceDetector, is_within, manual_device
from .downloads import DownloadQueue, cleanup_stale_cache
from .files import DeviceFileService
from .media import MediaDownloader
from .metadata import validate_source_mp3
from .models import Device, DownloadJob, JobStatus, Playlist, Track
from .naming import playlist_folder_name, sanitize_component
from .transfer import TransferManager
from .youtube import YouTubeMusicService

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class BrowserPage:
    title: str
    items: list[Track | Playlist]
    playlist: Playlist | None = None


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:
            LOG.exception("Background operation failed")
            self.signals.error.emit(str(exc))


class AuthDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect YouTube Music")
        self.resize(650, 470)
        layout = QVBoxLayout(self)
        instructions = QLabel(
            "1. Sign in at music.youtube.com.\n"
            "2. Open Developer Tools → Network, filter for /browse, and select a POST request.\n"
            "3. Firefox: Copy → Copy Request Headers. Chrome/Edge: copy the Request Headers "
            "section (or paste the header JSON from Copy as fetch).\n"
            "4. Paste below. The credentials stay only on this computer."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.headers = QTextEdit()
        self.headers.setPlaceholderText("Paste request headers here…")
        layout.addWidget(self.headers)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self.config = store.load()
        self.youtube = YouTubeMusicService(store.auth_path)
        self.detector = DeviceDetector()
        self.pool = QThreadPool.globalInstance()
        self._workers: set[Worker] = set()
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
        self.queue_rows: dict[str, int] = {}
        transfer_state = store.cache_dir / "transfers.json"
        cleanup_stale_cache(store.cache_dir, transfer_state)
        self.transfer = TransferManager(transfer_state)
        self.resumed_roots: set[Path] = set()
        self.queue = DownloadQueue(
            store.cache_dir,
            self.transfer,
            downloader=MediaDownloader(store.auth_path),
            callback=self._queue_callback,
        )
        self._build_ui()
        self.resize(self.config.window_width, self.config.window_height)
        self._refresh_auth_label()
        if self.config.manual_device:
            try:
                self.device = manual_device(Path(self.config.manual_device))
                self.current_folder = self.device.root
                self._reset_folder_history(self.device.root)
                saved = self.device.root / self.config.destination_relative
                self.destination = (
                    saved.resolve()
                    if saved.is_dir() and is_within(self.device.root, saved)
                    else self.device.root
                )
            except (OSError, ValueError):
                self.device = None
        if self.device is not None:
            self._refresh_files()
            self._render_device()
        self._poll_devices()
        self.device_timer = QTimer(self)
        self.device_timer.timeout.connect(self._poll_devices)
        self.device_timer.start(5000)

    def _build_ui(self) -> None:
        self.setWindowTitle("Shokz Refill")
        central = QWidget()
        outer = QVBoxLayout(central)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._youtube_tab(), "YouTube Music")
        self.tabs.addTab(self._device_tab(), "Shokz device / files")
        queue_box = QWidget()
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Download and transfer queue"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setFormat("Overall %p%")
        self.overall_progress.setMaximumWidth(220)
        queue_header.addWidget(self.overall_progress)
        queue_header.addStretch()
        retry = QPushButton("Retry failed")
        retry.clicked.connect(self._retry_jobs)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self._cancel_jobs)
        queue_header.addWidget(retry)
        queue_header.addWidget(cancel)
        queue_layout.addLayout(queue_header)
        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["Track", "Status", "Progress", "Details"])
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self._queue_context_menu)
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        queue_layout.addWidget(self.queue_table)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(queue_box)
        splitter.setSizes([500, 220])
        outer.addWidget(splitter)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

    def _youtube_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        auth = QHBoxLayout()
        self.auth_label = QLabel()
        connect = QPushButton("Connect YouTube Music")
        connect.clicked.connect(self._connect_youtube)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(self._disconnect_youtube)
        library = QPushButton("My playlists")
        library.clicked.connect(self._load_library)
        auth.addWidget(self.auth_label)
        auth.addStretch()
        auth.addWidget(connect)
        auth.addWidget(disconnect)
        auth.addWidget(library)
        layout.addLayout(auth)
        search = QHBoxLayout()
        self.browser_back = QPushButton("<")
        self.browser_back.setFixedWidth(34)
        self.browser_back.setToolTip("Go back to the previous YouTube Music page")
        self.browser_back.setEnabled(False)
        self.browser_back.clicked.connect(self._browser_go_back)
        self.browser_forward = QPushButton(">")
        self.browser_forward.setFixedWidth(34)
        self.browser_forward.setToolTip("Go forward to the next YouTube Music page")
        self.browser_forward.setEnabled(False)
        self.browser_forward.clicked.connect(self._browser_go_forward)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search YouTube Music")
        self.search_edit.returnPressed.connect(self._search)
        self.search_type = QComboBox()
        self.search_type.addItems(["Songs", "Playlists"])
        search_button = QPushButton("Search")
        search_button.clicked.connect(self._search)
        search.addWidget(self.browser_back)
        search.addWidget(self.browser_forward)
        search.addWidget(self.search_edit)
        search.addWidget(self.search_type)
        search.addWidget(search_button)
        layout.addLayout(search)
        result_actions = QHBoxLayout()
        open_playlist = QPushButton("Open playlist")
        open_playlist.clicked.connect(self._open_selected_playlist)
        select_all = QPushButton("Select all")
        self.download_playlist_button = QPushButton("Download whole playlist")
        self.download_playlist_button.setEnabled(False)
        self.download_playlist_button.clicked.connect(self._download_current_playlist)
        result_actions.addWidget(open_playlist)
        result_actions.addWidget(select_all)
        result_actions.addStretch()
        result_actions.addWidget(self.download_playlist_button)
        layout.addLayout(result_actions)
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(["Title", "Artist / count", "Duration"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self._results_context_menu)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.cellDoubleClicked.connect(self._result_double_clicked)
        select_all.clicked.connect(self.results.selectAll)
        layout.addWidget(self.results)
        row = QHBoxLayout()
        self.destination_label = QLabel("Destination: select a Shokz folder")
        download = QPushButton("Download / transfer selected")
        download.clicked.connect(self._download_selected)
        row.addWidget(self.destination_label)
        row.addStretch()
        row.addWidget(download)
        layout.addLayout(row)
        return widget

    def _device_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_selected)
        manual = QPushButton("Select device folder")
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
        self.folder_back.setToolTip("Go back to the previously visited folder")
        self.folder_back.setEnabled(False)
        self.folder_back.clicked.connect(self._folder_go_back)
        self.folder_forward = QPushButton(">")
        self.folder_forward.setFixedWidth(34)
        self.folder_forward.setToolTip("Go forward to the next visited folder")
        self.folder_forward.setEnabled(False)
        self.folder_forward.clicked.connect(self._folder_go_forward)
        location.addWidget(self.folder_back)
        location.addWidget(self.folder_forward)
        location.addStretch()
        layout.addLayout(location)
        self.files = QTableWidget(0, 3)
        self.files.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        self.files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._files_context_menu)
        self.files.horizontalHeader().setStretchLastSection(True)
        self.files.doubleClicked.connect(self._open_folder)
        layout.addWidget(self.files)
        actions = QHBoxLayout()
        for label, handler in (
            ("New folder", self._new_folder),
            ("Rename", self._rename),
            ("Move selected…", self._move_selected),
            ("Delete", self._delete),
            ("Add local MP3", self._add_local),
            ("Select destination folder", self._select_destination),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        return widget

    def _run(
        self, function: Callable[[], Any], success: Callable[[Any], None], message: str = "Working…"
    ) -> None:
        self.statusBar().showMessage(message)
        worker = Worker(function)
        self._workers.add(worker)

        def completed(value: object) -> None:
            self._workers.discard(worker)
            self.statusBar().showMessage("Ready")
            success(value)

        def failed(message: str) -> None:
            self._workers.discard(worker)
            self._show_error(message)

        worker.signals.result.connect(completed)
        worker.signals.error.connect(failed)
        self.pool.start(worker)

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage("Operation failed")
        QMessageBox.warning(self, "Shokz Refill", message or "The operation failed")

    def _refresh_auth_label(self) -> None:
        self.auth_label.setText(
            "YouTube Music: connected"
            if self.youtube.authenticated
            else "YouTube Music: not connected"
        )

    def _connect_youtube(self) -> None:
        dialog = AuthDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        raw = dialog.headers.toPlainText()
        self._run(lambda: self.youtube.connect_headers(raw), self._connected, "Validating account…")

    def _connected(self, name: object) -> None:
        self._refresh_auth_label()
        self.statusBar().showMessage(f"YouTube Music connected: {name}")

    def _disconnect_youtube(self) -> None:
        self.youtube.disconnect()
        self._refresh_auth_label()
        self.statusBar().showMessage("Local YouTube Music credentials removed")

    def _search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
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
        )

    def _load_library(self) -> None:
        self._run(
            self.youtube.library_playlists,
            lambda objects: self._set_browser_root("My playlists", objects),
            "Loading your playlists…",
        )

    def _set_browser_root(self, title: str, objects: object) -> None:
        items = list(objects) if isinstance(objects, list) else []
        page = BrowserPage(title, items)
        self.browser_history = [page]
        self.browser_history_index = 0
        self._set_browser_page(page)

    def _set_browser_page(self, page: BrowserPage) -> None:
        self.browser_page = page
        self.browser_back.setEnabled(self.browser_history_index > 0)
        self.browser_forward.setEnabled(
            0 <= self.browser_history_index < len(self.browser_history) - 1
        )
        self.download_playlist_button.setEnabled(page.playlist is not None)
        self._show_results(page.items)

    def _browser_go_back(self) -> None:
        if self.browser_history_index > 0:
            self.browser_history_index -= 1
            self._set_browser_page(self.browser_history[self.browser_history_index])

    def _browser_go_forward(self) -> None:
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
        if not self.result_objects:
            self.results.setRowCount(1)
            self.results.setItem(0, 0, QTableWidgetItem("No results found"))
            self.results.setItem(0, 1, QTableWidgetItem("Try a different search"))
            return
        self.results.setRowCount(len(self.result_objects))
        for row, item in enumerate(self.result_objects):
            if isinstance(item, Track):
                duration = (
                    ""
                    if item.duration_seconds is None
                    else f"{item.duration_seconds // 60}:{item.duration_seconds % 60:02d}"
                )
                values = (item.title, item.artist, duration)
            else:
                values = (item.title, f"{item.count} tracks" if item.count else "Playlist", "")
            for column, value in enumerate(values):
                self.results.setItem(row, column, QTableWidgetItem(value))
        self.results.resizeColumnsToContents()

    def _selected_result_objects(self) -> list[Track | Playlist]:
        return [
            self.result_objects[index.row()]
            for index in self.results.selectionModel().selectedRows()
            if index.row() < len(self.result_objects)
        ]

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
        )

    def _result_double_clicked(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self.result_objects):
            return
        item = self.result_objects[row]
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
        if not self.device or not self.destination or not self.device.root.exists():
            self._show_error("No connected Shokz destination is selected")
            return
        device, destination = self.device, self.destination
        self._enqueue_tracks(tracks, destination, device)

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
        if not self.device or not self.destination or not self.device.root.exists():
            self._show_error("No connected Shokz destination is selected")
            return
        device, base = self.device, self.destination
        folder_name = playlist_folder_name(playlist.title)

        def prepare() -> Path:
            return DeviceFileService(device.root).ensure_folder(base, folder_name)

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
        worker = Worker(self.detector.scan)
        self._workers.add(worker)

        def completed(value: object) -> None:
            self._workers.discard(worker)
            self._update_devices(value)

        def failed(_message: str) -> None:
            self._workers.discard(worker)

        worker.signals.result.connect(completed)
        worker.signals.error.connect(failed)
        self.pool.start(worker)

    def _update_devices(self, value: object) -> None:
        devices = list(value) if isinstance(value, list) else []
        current_root = self.device.root if self.device else None
        roots = {candidate.root for candidate in devices if isinstance(candidate, Device)}
        if (
            self.device
            and not self.device.automatic
            and self.device.root.exists()
            and self.device.root not in roots
        ):
            devices.insert(0, manual_device(self.device.root))
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
        if current_root and selected_index == 0:
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
        value = self.device_combo.itemData(index)
        self.device = value if isinstance(value, Device) else None
        if self.device:
            self.current_folder = self.device.root
            self._reset_folder_history(self.device.root)
            self.destination = self.device.root
            if not self.device.automatic:
                self.config.manual_device = str(self.device.root)
            self._refresh_files()
            if self.device.root not in self.resumed_roots:
                self.resumed_roots.add(self.device.root)
                root = self.device.root
                self._run(
                    lambda: self.transfer.resume_for_device(root),
                    self._resumed_transfers,
                    "Checking interrupted transfers…",
                )
        else:
            self.current_folder = None
            self.folder_history = []
            self.folder_history_index = -1
            self.destination = None
        self._render_device()

    def _resumed_transfers(self, result: object) -> None:
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
        try:
            device = manual_device(Path(chosen))
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.device = device
        self.current_folder = device.root
        self._reset_folder_history(device.root)
        self.destination = device.root
        self.config.manual_device = str(device.root)
        self._update_devices([device])
        self.device_combo.setCurrentIndex(1)
        self._refresh_files()
        self._render_device()

    def _render_device(self) -> None:
        if not self.device:
            self.folder_back.setEnabled(False)
            self.folder_forward.setEnabled(False)
            self.storage_label.setText("No Shokz connected")
            self.destination_label.setText("Destination: select a Shokz folder")
            self.files.setRowCount(0)
            return
        try:
            usage = shutil.disk_usage(self.device.root)
            gib = 1024**3
            self.storage_label.setText(
                f"{usage.free / gib:.1f} GiB free / {usage.total / gib:.1f} GiB"
            )
        except OSError:
            self.storage_label.setText("Device disconnected")
        self.folder_back.setEnabled(self.folder_history_index > 0)
        self.folder_forward.setEnabled(
            0 <= self.folder_history_index < len(self.folder_history) - 1
        )
        self.destination_label.setText(f"Destination: {self.destination or self.device.root}")

    def _refresh_files(self) -> None:
        if not self.device or not self.current_folder:
            return
        root, folder = self.device.root, self.current_folder
        self._run(
            lambda: DeviceFileService(root).list_dir(folder), self._show_files, "Reading device…"
        )

    def _show_files(self, value: object) -> None:
        self.file_objects = list(value) if isinstance(value, list) else []
        self.files.setRowCount(len(self.file_objects))
        for row, path in enumerate(self.file_objects):
            try:
                size = "" if path.is_dir() else f"{path.stat().st_size / (1024 * 1024):.1f} MB"
                values = (path.name, "Folder" if path.is_dir() else "MP3", size)
            except OSError:
                values = (path.name, "Unavailable", "")
            for column, text in enumerate(values):
                self.files.setItem(row, column, QTableWidgetItem(text))
        self.files.resizeColumnsToContents()
        self._render_device()

    def _selected_paths(self) -> list[Path]:
        return [
            self.file_objects[index.row()]
            for index in self.files.selectionModel().selectedRows()
            if index.row() < len(self.file_objects)
        ]

    def _files_context_menu(self, position: Any) -> None:
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
        single_folder = selected[0] if len(selected) == 1 and selected[0].is_dir() else None
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
        new_folder_action = menu.addAction("New folder here")
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
        if selected and selected[0].is_dir():
            self._navigate_folder(selected[0])

    def _reset_folder_history(self, folder: Path) -> None:
        self.folder_history = [folder]
        self.folder_history_index = 0

    def _navigate_folder(self, folder: Path) -> None:
        if not self.device or not folder.is_dir() or not is_within(self.device.root, folder):
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
            service = DeviceFileService(self.device.root)
            parent = self.current_folder
            self._run(
                lambda: service.create_folder(parent, name),
                lambda _v: self._refresh_files(),
            )

    def _rename(self) -> None:
        selected = self._selected_paths()
        if not self.device or len(selected) != 1:
            self._show_error("Select exactly one file or folder")
            return
        name, accepted = QInputDialog.getText(self, "Rename", "New name:", text=selected[0].stem)
        if accepted and name:
            service = DeviceFileService(self.device.root)
            self._run(lambda: service.rename(selected[0], name), lambda _v: self._refresh_files())

    def _delete(self) -> None:
        selected = self._selected_paths()
        if not self.device or not selected:
            self._show_error("Select one or more files or empty folders")
            return
        if (
            QMessageBox.question(
                self, "Delete", f"Permanently delete {len(selected)} selected item(s)?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        service = DeviceFileService(self.device.root)

        def delete_selected() -> None:
            for path in selected:
                service.delete(path)

        self._run(
            delete_selected,
            lambda _v: self._refresh_files(),
            "Deleting…",
        )

    def _move_selected(self) -> None:
        selected = self._selected_paths()
        if not self.device or not self.current_folder or not selected:
            self._show_error("Select one or more files or folders to move")
            return
        chosen = QFileDialog.getExistingDirectory(
            self,
            f"Move {len(selected)} selected item(s) to",
            str(self.current_folder),
        )
        if not chosen:
            return
        service = DeviceFileService(self.device.root)
        destination = Path(chosen)

        def completed(value: object) -> None:
            count = len(value) if isinstance(value, list) else 0
            self.statusBar().showMessage(f"Moved {count} item(s)")
            self._refresh_files()

        self._run(
            lambda: service.move(selected, destination),
            completed,
            "Moving selected items…",
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

        def copy_files() -> int:
            copied = 0
            for source in sources:
                validate_source_mp3(source)
                safe_name = sanitize_component(source.stem, max_bytes=220) + ".mp3"
                self.transfer.transfer(source, folder / safe_name, root)
                copied += 1
            return copied

        self._run(copy_files, self._local_added, "Copying MP3 files…")

    def _local_added(self, result: object) -> None:
        copied = result if isinstance(result, int) else 0
        self.statusBar().showMessage(f"Copied {copied} MP3 file(s)")
        self._refresh_files()

    def _select_destination(self) -> None:
        if self.device and self.current_folder:
            self._set_destination(self.current_folder)

    def _set_destination(self, folder: Path | None) -> None:
        if self.device and folder and folder.is_dir() and is_within(self.device.root, folder):
            self.destination = folder.resolve()
            self.config.destination_relative = str(folder.relative_to(self.device.root))
            self._render_device()
            self.tabs.setCurrentIndex(0)

    def _queue_callback(self, job: DownloadJob) -> None:
        # Python callbacks arrive on worker threads; a zero-shot signal marshals safely to Qt.
        QTimer.singleShot(0, self, lambda: self._update_queue_row(job))

    def _update_queue_row(self, job: DownloadJob) -> None:
        row = self.queue_rows.get(job.job_id)
        if row is None:
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_rows[job.job_id] = row
            first = QTableWidgetItem(f"{job.track.artist} — {job.track.title}")
            first.setData(Qt.ItemDataRole.UserRole, job.job_id)
            self.queue_table.setItem(row, 0, first)
            self.queue_table.setItem(row, 1, QTableWidgetItem())
            bar = QProgressBar()
            self.queue_table.setCellWidget(row, 2, bar)
            self.queue_table.setItem(row, 3, QTableWidgetItem())
        status_item = self.queue_table.item(row, 1)
        detail_item = self.queue_table.item(row, 3)
        if status_item is not None:
            status_item.setText(job.status.value)
        progress_widget = self.queue_table.cellWidget(row, 2)
        if isinstance(progress_widget, QProgressBar):
            progress_widget.setValue(job.progress)
        if detail_item is not None:
            detail_item.setText(job.error)
        all_jobs = list(self.queue.jobs.values())
        self.overall_progress.setValue(
            int(sum(item.progress for item in all_jobs) / len(all_jobs)) if all_jobs else 0
        )
        if job.status == JobStatus.COMPLETE:
            self._refresh_files()

    def _selected_job_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.queue_table.selectionModel().selectedRows():
            item = self.queue_table.item(index.row(), 0)
            value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if isinstance(value, str):
                ids.append(value)
        return ids

    def _queue_context_menu(self, position: Any) -> None:
        row = self.queue_table.rowAt(position.y())
        clicked_item = self.queue_table.item(row, 0) if row >= 0 else None
        if row >= 0 and clicked_item is not None and not clicked_item.isSelected():
            self.queue_table.clearSelection()
            self.queue_table.selectRow(row)
        if not self._selected_job_ids():
            return
        menu = QMenu(self)
        retry_action = menu.addAction("Retry failed/cancelled")
        cancel_action = menu.addAction("Cancel selected")
        chosen = menu.exec(self.queue_table.viewport().mapToGlobal(position))
        if chosen == retry_action:
            self._retry_jobs()
        elif chosen == cancel_action:
            self._cancel_jobs()

    def _retry_jobs(self) -> None:
        if self.device:
            self.queue.retry(self._selected_job_ids(), self.device.root)

    def _cancel_jobs(self) -> None:
        self.queue.cancel(self._selected_job_ids())

    def closeEvent(self, event: Any) -> None:
        self.queue.shutdown()
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.store.save(self.config)
        super().closeEvent(event)
