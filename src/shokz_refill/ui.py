from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
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
from .device import DeviceDetector, manual_device, verify_device
from .dialogs import DeviceFolderDialog
from .downloads import DownloadQueue, cleanup_stale_cache
from .files import DeviceFileService
from .filesystem import device_operation
from .guided_tour import GuidedTour, application_tour_steps
from .icons import icon
from .library_view import LibraryEntry, library_rows
from .local_import import LocalMp3Importer
from .media import MediaDownloader
from .models import Device, DownloadJob, JobStatus, Playlist, Track
from .naming import playlist_folder_name
from .navigation import SETTINGS_PAGE, Sidebar
from .page_layout import PageTemplate
from .playback_order import next_position
from .queue_panel import QueuePanel
from .settings_page import SettingsPage
from .table_filters import ColumnFilters
from .table_state import TableEmptyState
from .theme import ON_ACCENT, RoundedComboBox, role
from .themed_dialog import InputDialog, MessageDialog
from .transfer import TransferManager
from .transfer_wizard import TransferWizard
from .voice_preview import VoicePreview
from .window_frame import EDGE_MARGIN, TitleBar, cursor_for, edges_at
from .youtube import YouTubeMusicService
from .youtube_dialog import AuthDialog


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
        rows = sorted(
            index.row()
            for index in self.selectionModel().selectedRows()
            if not self.isRowHidden(index.row())
        )
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
        self.local_import = LocalMp3Importer(store.cache_dir, self.transfer)
        self.queue = DownloadQueue(
            store.cache_dir,
            self.transfer,
            downloader=MediaDownloader(store.auth_path),
            callback=self._queue_callback,
        )
        self.audiobook_queue = AudiobookQueue(store.cache_dir, self.transfer, self._queue_callback)
        self._queues = (self.queue, self.audiobook_queue)
        self._initial_focus_cleared = False
        self.guided_tour: GuidedTour | None = None
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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_focus_cleared:
            # The first tab stop (device refresh) would otherwise open with a focus ring.
            self._initial_focus_cleared = True
            QTimer.singleShot(0, self._clear_initial_focus)

    def _clear_initial_focus(self) -> None:
        if self.guided_tour is not None:
            return
        # Hand focus to the page container (click focus only), so no control shows a focus ring.
        host = self.centralWidget()
        if host is not None:
            host.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            host.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_ui(self) -> None:
        self.setWindowTitle("Shokz Refill")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        central = QWidget()
        central.setObjectName("windowShell")
        central.setMouseTracking(True)
        self._shell_layout = QVBoxLayout(central)
        self._shell_layout.setContentsMargins(*([EDGE_MARGIN] * 4))
        self.window_frame = QFrame()
        self.window_frame.setObjectName("windowFrame")
        # Resize cursors belong to the transparent margin only; never inherit them inside.
        self.window_frame.setCursor(Qt.CursorShape.ArrowCursor)
        self._shell_layout.addWidget(self.window_frame)
        outer = QHBoxLayout(self.window_frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = Sidebar()
        outer.addWidget(self.sidebar)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        column = QVBoxLayout(workspace)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.title_bar = TitleBar(self)
        column.addWidget(self.title_bar)
        body = QWidget()
        column.addWidget(body, 1)
        content = QVBoxLayout(body)
        content.setContentsMargins(24, 4, 20, 16)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.sidebar.pageRequested.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.sidebar.set_page)
        self.sidebar.refreshRequested.connect(self._poll_devices)
        self.sidebar.tourRequested.connect(self.show_guided_tour)
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
        self.queue_panel = QueuePanel()
        self.queue_panel.retryRequested.connect(self._retry_jobs)
        self.queue_panel.cancelRequested.connect(self._cancel_jobs)
        self.queue_panel.summaryChanged.connect(self.sidebar.set_transfers)
        self.queue_table = self.queue_panel.table
        self.queueUpdated.connect(self._update_queue_row, Qt.ConnectionType.QueuedConnection)
        self.tabs.addTab(self.queue_panel, "Transfers")
        self.speech_settings = SpeechSettingsPanel(self.config.book_export_options())
        self.speech_settings.saveRequested.connect(self._save_speech_settings)
        self.voice_preview = VoicePreview(self.tasks, self.store.cache_dir, self.speech_settings)
        self.settings_page = SettingsPage(
            self.audiobookshelf_panel.connection_card,
            self.speech_settings,
            self.speech_settings.save,
        )
        self.settings_page.authRequested.connect(self._connect_youtube)
        self.settings_page.disconnectRequested.connect(self._disconnect_youtube)
        self.auth_label = self.settings_page.auth_label
        self.connect_button = self.settings_page.connect_button
        self.disconnect_button = self.settings_page.disconnect_button
        self.audiobookshelf_panel.settingsRequested.connect(
            lambda: self.tabs.setCurrentIndex(SETTINGS_PAGE)
        )
        self.tabs.addTab(self.settings_page, "Settings")
        content.addWidget(self.tabs)
        outer.addWidget(workspace, 1)
        self.setMinimumSize(1040, 720)
        self.setCentralWidget(central)
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.hide()
        status_bar.messageChanged.connect(lambda text: status_bar.setVisible(bool(text)))

    def show_guided_tour_if_needed(self) -> None:
        """Offer onboarding at startup until the tour has been opened once."""
        if not self.config.guided_tour_seen:
            self.show_guided_tour()

    def show_guided_tour(self) -> None:
        """Open a single, nonblocking tour without triggering application actions."""
        if self._closing or not self.isVisible():
            return
        if self.guided_tour is not None:
            self.guided_tour.raise_()
            self.guided_tour.activateWindow()
            return
        tour = GuidedTour(self, self.tabs, application_tour_steps(self))
        self.guided_tour = tour
        tour.finished.connect(lambda _result: setattr(self, "guided_tour", None))
        tour.open()
        if not self.config.guided_tour_seen:
            self.config.guided_tour_seen = True
            snapshot = replace(self.config)
            self._run(
                lambda: self.store.save(snapshot),
                lambda _value: None,
                "",
                lambda error: self.statusBar().showMessage(
                    f"Could not save guided tour preference: {error}"
                ),
            )

    def _is_maximized(self) -> bool:
        return self.isMaximized() or self.isFullScreen()

    def _set_chrome_maximized(self) -> None:
        maximized = self._is_maximized()
        self.title_bar.sync()
        if self.window_frame.property("maximized") == maximized:
            return
        margin = 0 if maximized else EDGE_MARGIN
        self._shell_layout.setContentsMargins(margin, margin, margin, margin)
        for widget in (self.window_frame, self.sidebar):
            widget.setProperty("maximized", maximized)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self._set_chrome_maximized()

    def _resize_edges(self, position: QPoint) -> Qt.Edge:
        if self._is_maximized():
            return Qt.Edge(0)
        return edges_at(position, self.size())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        shape = cursor_for(self._resize_edges(event.position().toPoint()))
        if shape != self.cursor().shape():
            self.setCursor(shape)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        edges = self._resize_edges(event.position().toPoint())
        handle = self.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and edges and handle is not None:
            handle.startSystemResize(edges)
            event.accept()
            return
        super().mousePressEvent(event)

    def _save_speech_settings(self, options: BookExportOptions) -> None:
        options.validate()
        self.config.book_tts_announce = options.announce
        self.config.book_announce_chapters = options.announce_chapters
        self.config.book_chapter_template = options.chapter_template
        self.config.book_tts_template = options.template
        self.config.book_tts_voice = options.voice
        self.config.book_tts_rate = options.rate
        snapshot = replace(self.config)

        def saved(_value: object) -> None:
            self.speech_settings.set_status(
                "Settings saved"
                if self.speech_settings.options == options
                else "Settings saved; newer changes remain unsaved"
            )

        self._run(
            lambda: self.store.save(snapshot),
            saved,
            "Saving speech settings…",
            self.speech_settings.set_status,
            key="settings",
        )

    def _youtube_tab(self) -> QWidget:
        self.browser = BrowserPanel()
        self.browser.libraryRequested.connect(self._load_library)
        self.browser.backRequested.connect(self._browser_go_back)
        self.browser.forwardRequested.connect(self._browser_go_forward)
        self.browser.searchRequested.connect(self._search)
        self.browser.downloadRequested.connect(self._download_selected)
        self.browser.pendingChanged.connect(self._update_actions)
        self.browser.playlistAddRequested.connect(self._add_playlist_to_send_list)
        self.browser.settingsRequested.connect(lambda: self.tabs.setCurrentIndex(SETTINGS_PAGE))
        self.browser.contextRequested.connect(self._results_context_menu)
        self.browser.activated.connect(self._result_double_clicked)
        self.browser.selectionChanged.connect(self._update_actions)
        self.results = self.browser.results
        self.browser_title = self.browser.browser_title
        self.browser_back = self.browser.browser_back
        self.browser_forward = self.browser.browser_forward
        self.search_edit = self.browser.search_edit
        self.search_type = self.browser.search_type
        self.library_button = self.browser.library_button
        self.download_button = self.browser.download_button
        return self.browser

    def _device_tab(self) -> QWidget:
        page = PageTemplate("Shokz files")
        self.device_combo = RoundedComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_selected)
        manual = QPushButton("Browse…")
        manual.setIcon(icon("folder"))
        role(manual, "quiet")
        manual.setToolTip("Select the mounted device folder manually")
        self.manual_device_button = manual
        manual.clicked.connect(self._select_manual_device)
        self.device_combo.setAccessibleName("Shokz device")
        self.device_combo.setMinimumWidth(180)
        page.header.addWidget(manual)
        self.folder_label = page.subtitle
        self.folder_label.clear()
        # The device selector right below already shows the path, so this line counts items.
        location = page.controls
        location.addWidget(self.device_combo)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setAccessibleName("Current device folder")
        self.path_edit.setPlaceholderText("No folder selected")
        location.addWidget(self.path_edit, 1)
        self.folder_back = QPushButton()
        self.folder_back.setIcon(icon("back"))
        self.folder_back.setFixedWidth(36)
        self.folder_back.setAccessibleName("Previous device folder")
        self.folder_back.setToolTip("Go back to the previously visited folder")
        self.folder_back.setEnabled(False)
        self.folder_back.clicked.connect(self._folder_go_back)
        self.folder_forward = QPushButton()
        self.folder_forward.setIcon(icon("forward"))
        self.folder_forward.setFixedWidth(36)
        self.folder_forward.setAccessibleName("Next device folder")
        self.folder_forward.setToolTip("Go forward to the next visited folder")
        self.folder_forward.setEnabled(False)
        self.folder_forward.clicked.connect(self._folder_go_forward)
        location.addWidget(self.folder_back)
        location.addWidget(self.folder_forward)
        self.device_root_button = QPushButton("Device root")
        self.device_root_button.setToolTip("Go back to the device's top-level folders")
        self.device_root_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.device_root_button.clicked.connect(self._go_device_root)
        location.addWidget(self.device_root_button)
        self.files_filter_button = QPushButton()
        self.files_filter_button.setIcon(icon("filter"))
        self.files_filter_button.setFixedWidth(36)
        self.files_filter_button.setToolTip("Filter files")
        self.files_filter_button.setAccessibleName("Filter files")
        location.addWidget(self.files_filter_button)
        self.files = DeviceFileTable(0, 3)
        self.files_empty_state = TableEmptyState(
            self.files,
            "Connect your Shokz\nChoose a mounted device folder to manage its MP3 files.",
        )
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
        library_rows(self.files, book=True)
        files_header.hide()
        filter_menu = QMenu(self.files_filter_button)
        filter_menu.addAction("Filter name…", lambda: self.file_filters.edit(0))
        filter_menu.addAction("Filter type…", lambda: self.file_filters.edit(1))
        filter_menu.addAction("Clear filters", self.file_filters.clear)
        self.files_filter_button.setMenu(filter_menu)
        self.files.doubleClicked.connect(self._open_folder)
        self.files.itemSelectionChanged.connect(self._update_actions)
        page.content.addWidget(self.files)
        device_activity = QHBoxLayout()
        self.device_operation_label = QLabel("Device operation: idle")
        self.device_operation_label.setWordWrap(True)
        self.device_operation_progress = QProgressBar()
        self.device_operation_progress.setMaximumWidth(220)
        self.device_operation_progress.setRange(0, 100)
        self.device_operation_progress.setValue(0)
        self.device_operation_progress.setVisible(False)
        role(self.device_operation_label, "muted")
        self.device_operation_label.setVisible(False)
        device_activity.addWidget(self.device_operation_label)
        device_activity.addWidget(self.device_operation_progress)
        device_activity.addStretch()
        page.footer.addLayout(device_activity, 1)
        page.footer.addLayout(self._file_toolbar())
        return page

    def _file_toolbar(self) -> QHBoxLayout:
        """Compact file actions; rarely used device tools live in the overflow menu."""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.file_buttons: dict[str, QPushButton] = {}
        for label, glyph, handler in (
            ("New folder", "plus", self._new_folder),
            ("Rename", None, self._rename),
            ("Move selected…", None, self._move_selected),
            ("Delete", None, self._delete),
        ):
            button = QPushButton(label.replace(" selected", ""))
            if glyph:
                button.setIcon(icon(glyph))
            button.setToolTip(label.removesuffix("…"))
            button.clicked.connect(handler)
            role(button, "danger" if label == "Delete" else "quiet")
            self.file_buttons[label] = button
            toolbar.addWidget(button)
        add = QPushButton("Add MP3")
        add.setToolTip("Import MP3 files; normalize to 192 kbps, 44.1 kHz stereo when needed")
        role(add, "primary")
        add.setIcon(icon("plus", ON_ACCENT))
        add.clicked.connect(self._add_local)
        self.file_buttons["Add local MP3"] = add
        toolbar.addWidget(add)
        more = QPushButton()
        more.setIcon(icon("more"))
        more.setFixedWidth(36)
        more.setToolTip("More device actions")
        more.setAccessibleName("More device actions")
        role(more, "quiet")
        menu = QMenu(more)
        self.resume_button = QAction("Resume interrupted copies", menu)
        self.resume_button.triggered.connect(self._resume_transfers)
        self.stop_device_button = QAction("Cancel operation", menu)
        self.stop_device_button.triggered.connect(self._device_cancel.set)
        menu.addAction(self.resume_button)
        menu.addAction(self.stop_device_button)
        more.setMenu(menu)
        toolbar.addWidget(more)
        return toolbar

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
            self.statusBar().clearMessage()
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

    def _at_device_root(self) -> bool:
        return (
            self.device is not None
            and self.current_folder is not None
            and self.current_folder == self.device.root
        )

    def _update_actions(self) -> None:
        if not hasattr(self, "file_buttons"):
            return
        ready = self.device is not None and not self._closing
        writable = ready and not self._device_busy
        paths = self._selected_paths()
        editable = writable and not self._reserved_paths(paths)
        self.download_button.setEnabled(ready and bool(self.browser.pending))
        for label, button in self.file_buttons.items():
            enabled = writable
            if label == "Rename":
                enabled = editable and len(paths) == 1
            elif label in {"Move selected…", "Delete"}:
                enabled = editable and bool(paths)
            button.setEnabled(enabled)
            if label == "New folder":
                button.setVisible(self._at_device_root())
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
        MessageDialog.warning(self, "Shokz Refill", message or "The operation failed")

    def _refresh_auth_label(self) -> None:
        if self.youtube.connection_verified:
            label = "Connected"
        elif self.youtube.authenticated:
            label = "Saved session (not yet verified)"
        else:
            label = "Not connected"
        self.auth_label.setText(label)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(self.youtube.authenticated)
        self.library_button.setEnabled(self.youtube.authenticated)

    def _connect_youtube(self) -> None:
        if any(runner.active("auth") for runner in self.findChildren(TaskRunner)):
            return
        self.tasks.cancel("browser")
        dialog = AuthDialog(self.youtube, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._connected(dialog.account_name)
        else:
            self._refresh_auth_label()

    def _connected(self, name: object) -> None:
        self._refresh_auth_label()
        self.statusBar().showMessage(f"YouTube Music connected: {name}")

    def _disconnect_youtube(self) -> None:
        if any(runner.active("auth") for runner in self.findChildren(TaskRunner)):
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

    def connect_saved_accounts(self) -> None:
        """Sign in to remembered accounts at launch; failures stay quiet and reach the status."""
        if self.youtube.authenticated:
            self.tabs.setCurrentIndex(0)
            self._run(
                self.youtube.library_playlists,
                self._library_loaded,
                "Loading your playlists…",
                failure=self._startup_library_failed,
                key="browser",
            )
        credentials = self.audiobookshelf_panel.credentials()
        if credentials.server and credentials.username and credentials.password:
            self.audiobookshelf.connect_server()

    def _startup_library_failed(self, message: str) -> None:
        self._refresh_auth_label()
        self.statusBar().showMessage(message or "Could not load your YouTube Music playlists")

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
        self.browser.current_playlist = page.playlist
        self.browser_title.setText(f"{page.title} — {len(page.items)} item(s)")
        self.browser_back.setEnabled(self.browser_history_index > 0)
        self.browser_forward.setEnabled(
            0 <= self.browser_history_index < len(self.browser_history) - 1
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
        if isinstance(item, Playlist):
            self._open_playlist(item)
        elif isinstance(item, Track):
            self.browser.toggle_pending(item)

    def _add_playlist_to_send_list(self, playlist: Playlist) -> None:
        def added(objects: object) -> None:
            tracks = (
                [item for item in objects if isinstance(item, Track)]
                if isinstance(objects, list)
                else []
            )
            if not tracks:
                self._show_error("This playlist has no downloadable tracks")
                return
            self.browser.add_pending(tracks, origin=playlist)
            self.statusBar().showMessage(f"Added {len(tracks)} song(s) from {playlist.title}")

        self._run(
            lambda: self.youtube.playlist_tracks(playlist.playlist_id),
            added,
            f"Loading {playlist.title}…",
        )

    def _download_selected(self) -> None:
        """Open the transfer assistant for the send list."""
        pending = list(self.browser.pending)
        if not pending:
            self._show_error("Add songs to the send list with + first")
            return
        if not self.device:
            self._show_error("No connected Shokz device is selected")
            return
        device = self.device
        origins = {
            origin.playlist_id if origin else ""
            for origin in (self.browser.pending_origin.get(t.video_id) for t in pending)
        }
        origin = self.browser.pending_origin.get(pending[0].video_id)
        suggested = playlist_folder_name(origin.title) if origin and len(origins) == 1 else ""
        wizard = TransferWizard(pending, device, self, suggested=suggested, last=self.destination)
        if wizard.exec() != QDialog.DialogCode.Accepted or wizard.destination is None:
            return
        kept = {track.video_id for track in wizard.tracks}
        self.browser.remove_pending([track for track in pending if track.video_id not in kept])
        self._set_destination(wizard.destination)
        self._enqueue_tracks(wizard.tracks, wizard.destination, device)

    def _enqueue_tracks(self, tracks: list[Track], destination: Path, device: Device) -> None:
        # Device I/O (recreating a vanished download folder, reading its numbering) stays off
        # the UI thread.
        def prepare() -> tuple[Path, int]:
            if device.identity is not None:
                verify_device(device.root, device.identity)
            folder = destination
            if not folder.exists() and folder.parent == device.root:
                folder = DeviceFileService(device.root).ensure_folder(device.root, folder.name)
            return folder, next_position(folder)

        self._run(
            prepare,
            lambda value: self._enqueue_from(tracks, device, value),
            "Preparing the download folder…",
        )

    def _enqueue_from(self, tracks: list[Track], device: Device, value: object) -> None:
        if isinstance(value, tuple):
            folder, start = value
            self.queue.enqueue(
                tracks, folder, device.root, start=start, expected_device=device.identity
            )
            self.browser.discard_pending(tracks)

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
        add_playlist_action = menu.addAction("Add playlist to send list") if playlist else None
        add_action = remove_action = all_action = None
        if any(not self.browser.in_pending(track) for track in tracks):
            add_action = menu.addAction("Add to send list")
        if any(self.browser.in_pending(track) for track in tracks):
            remove_action = menu.addAction("Remove from send list")
        if self.browser_page.playlist is not None and any(
            isinstance(item, Track) for item in self.browser_page.items
        ):
            all_action = menu.addAction("Add all songs to send list")
        select_all_action = menu.addAction("Select all")
        back_action = menu.addAction("Back") if self.browser_history_index > 0 else None
        forward_action = (
            menu.addAction("Forward")
            if self.browser_history_index < len(self.browser_history) - 1
            else None
        )
        chosen = menu.exec(self.results.viewport().mapToGlobal(position))
        if chosen is None:
            return
        if open_action is not None and chosen == open_action:
            self._open_selected_playlist()
        elif add_playlist_action is not None and playlist and chosen == add_playlist_action:
            self._add_playlist_to_send_list(playlist)
        elif add_action is not None and chosen == add_action:
            self.browser.add_pending(tracks)
        elif remove_action is not None and chosen == remove_action:
            self.browser.remove_pending(tracks)
        elif all_action is not None and chosen == all_action:
            self.browser.add_pending(
                [item for item in self.browser_page.items if isinstance(item, Track)]
            )
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
            self.device_combo.addItem(device.name, device)
            self.device_combo.setItemData(
                self.device_combo.count() - 1, str(device.root), Qt.ItemDataRole.ToolTipRole
            )
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
        self.sidebar.set_device(self.device)
        self._update_path_bar()
        self.files_empty_state.set_text(
            "This folder is empty\nAdd local MP3 files or send audio from your libraries."
            if self.device
            else "Connect your Shokz\nChoose a mounted device folder to manage its MP3 files."
        )
        self._update_actions()
        self.audiobookshelf.update_device()
        if not self.current_folder:
            self.folder_label.clear()
        if not self.device:
            self.folder_back.setEnabled(False)
            self.folder_forward.setEnabled(False)
            self.files.setRowCount(0)
            return
        self.folder_back.setEnabled(self.folder_history_index > 0)
        self.folder_forward.setEnabled(
            0 <= self.folder_history_index < len(self.folder_history) - 1
        )

    def _update_path_bar(self) -> None:
        self.path_edit.setText(str(self.current_folder) if self.current_folder else "")
        self.path_edit.setCursorPosition(0)

    def _refresh_files(self) -> None:
        self._update_path_bar()
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
        self.folder_label.setText(f"{len(entries)} item(s)")
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
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        LibraryEntry(path.name, values[1], "folder" if directory else "music"),
                    )
                    item.setToolTip(path.name)
                self.files.setItem(row, column, item)
        self._render_device()

    def _selected_paths(self) -> list[Path]:
        return [
            self.file_objects[index.row()]
            for index in self.files.selectionModel().selectedRows()
            if index.row() < len(self.file_objects) and not self.files.isRowHidden(index.row())
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
        rename_action = menu.addAction("Rename") if len(selected) == 1 else None
        move_action = menu.addAction("Move selected…") if selected else None
        delete_action = menu.addAction("Delete") if selected else None
        if selected:
            menu.addSeparator()
        # Folders only exist at the device root, so offer creation there only.
        new_folder_action = menu.addAction("New folder") if self._at_device_root() else None
        if new_folder_action is not None:
            new_folder_action.setEnabled(not self._device_busy)
        add_mp3_action = menu.addAction("Add local MP3 here")
        chosen = menu.exec(self.files.viewport().mapToGlobal(position))
        if open_action is not None and chosen == open_action:
            self._open_folder()
        elif rename_action is not None and chosen == rename_action:
            self._rename()
        elif move_action is not None and chosen == move_action:
            self._move_selected()
        elif delete_action is not None and chosen == delete_action:
            self._delete()
        elif new_folder_action is not None and chosen == new_folder_action:
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
        name, accepted = InputDialog.getText(self, "New folder", "Folder name:")
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
        name, accepted = InputDialog.getText(self, "Rename", "New name:", text=selected[0].stem)
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
        if not MessageDialog.question(
            self,
            "Delete",
            f"Permanently delete {len(selected)} selected item(s)?{detail}",
            destructive=True,
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
        device, folder = self.device, self.current_folder
        self._set_device_operation(
            f"Copying {len(sources)} MP3 file(s) — keep the Shokz connected", busy=True
        )

        self._run_device(
            lambda: self.local_import.import_files(
                sources,
                folder,
                device.root,
                self.deviceProgress.emit,
                self._device_cancel.is_set,
                expected_device=device.identity,
            ),
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
        self.device_operation_label.setVisible(True)
        self.device_operation_progress.setVisible(busy or complete)
        if busy:
            self.device_operation_progress.setRange(0, 0)
        else:
            self.device_operation_progress.setRange(0, 100)
            self.device_operation_progress.setValue(100 if complete else 0)

    def _set_destination(self, folder: Path | None) -> None:
        if self.device and folder is not None and folder != self.device.root:
            self.destination = folder
            self.config.destination_relative = str(folder.relative_to(self.device.root))

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
            self.voice_preview.stop()
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
