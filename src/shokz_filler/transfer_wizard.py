"""Two-step "Send to Shokz" assistant: review the song order, then pick or create a folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .background import TaskRunner
from .files import DeviceFileService
from .icons import icon
from .models import Device, Track
from .theme import ON_ACCENT, role
from .themed_dialog import InputDialog, ThemedDialog

_HIDDEN_FOLDERS = {"system volume information", "$recycle.bin"}
_NEW_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class TransferWizard(ThemedDialog):
    """`tracks` (final order) and `destination` are valid after the dialog is accepted."""

    def __init__(
        self,
        tracks: list[Track],
        device: Device,
        parent: QWidget | None = None,
        *,
        suggested: str = "",
        last: Path | None = None,
    ) -> None:
        super().__init__(parent, "Send to Shokz")
        self.device = device
        self.tracks = list(tracks)
        self.destination: Path | None = None
        self._suggested = suggested
        self._last = last
        self.tasks = TaskRunner(self)
        self.setMinimumSize(520, 520)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(18, 8, 18, 16)
        layout.setSpacing(10)
        self.step_label = QLabel()
        role(self.step_label, "muted")
        layout.addWidget(self.step_label)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._songs_page())
        self.pages.addWidget(self._folder_page())
        layout.addWidget(self.pages, 1)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        layout.addWidget(self.feedback)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.cancel_button = QPushButton("Cancel")
        role(self.cancel_button, "quiet")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton("Back")
        role(self.back_button, "quiet")
        self.back_button.clicked.connect(lambda: self._go(0))
        self.next_button = QPushButton("Next")
        role(self.next_button, "primary")
        self.next_button.clicked.connect(self._next)
        row.addWidget(self.cancel_button)
        row.addStretch()
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        layout.addLayout(row)
        self._go(0)
        self.next_button.setDefault(True)
        self.next_button.setFocus()
        self._load_folders()

    # -- step 1: songs and their playback order -------------------------------------------
    def _songs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Songs")
        role(title, "section")
        layout.addWidget(title)
        hint = QLabel("They play in this order. Drag to reorder.")
        role(hint, "muted")
        layout.addWidget(hint)
        self.song_list = self._styled_list()
        self.song_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.song_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for track in self.tracks:
            item = QListWidgetItem(f"{track.title} — {track.artist}")
            item.setToolTip(item.text())
            item.setData(Qt.ItemDataRole.UserRole, track)
            self.song_list.addItem(item)
        self.song_list.model().rowsMoved.connect(self._songs_changed)
        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self.song_list, 1)
        tools = QVBoxLayout()
        tools.setSpacing(6)
        for glyph, label, handler in (
            ("up", "Move up", lambda: self._move(-1)),
            ("down", "Move down", lambda: self._move(1)),
            ("close", "Remove", self._remove),
        ):
            button = QPushButton()
            button.setIcon(icon(glyph))
            button.setFixedSize(36, 36)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(handler)
            tools.addWidget(button)
        tools.addStretch()
        body.addLayout(tools)
        layout.addLayout(body, 1)
        return page

    @staticmethod
    def _styled_list() -> QListWidget:
        widget = QListWidget()
        widget.setProperty("role", "wizardList")
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        return widget

    def _songs_changed(self) -> None:
        self.tracks = [
            track
            for row in range(self.song_list.count())
            if isinstance(track := self.song_list.item(row).data(Qt.ItemDataRole.UserRole), Track)
        ]
        self._refresh_buttons()

    def _move(self, delta: int) -> None:
        rows = sorted(index.row() for index in self.song_list.selectedIndexes())
        if not rows:
            return
        if delta > 0:
            rows.reverse()
        for row in rows:
            target = row + delta
            if 0 <= target < self.song_list.count():
                item = self.song_list.takeItem(row)
                self.song_list.insertItem(target, item)
                item.setSelected(True)
        self._songs_changed()

    def _remove(self) -> None:
        for index in sorted(self.song_list.selectedIndexes(), key=lambda i: -i.row()):
            self.song_list.takeItem(index.row())
        self._songs_changed()

    # -- step 2: destination folder --------------------------------------------------------
    def _folder_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title = QLabel(f"Folder on {self.device.name}")
        role(title, "section")
        header.addWidget(title, 1)
        self.new_folder_button = QPushButton("New folder")
        self.new_folder_button.setIcon(icon("plus"))
        self.new_folder_button.clicked.connect(self._create_folder)
        header.addWidget(self.new_folder_button)
        layout.addLayout(header)
        hint = QLabel("Choose where to add the songs, or create a new folder.")
        role(hint, "muted")
        layout.addWidget(hint)
        self.folder_list = self._styled_list()
        self.folder_list.currentItemChanged.connect(lambda *_: self._refresh_buttons())
        layout.addWidget(self.folder_list, 1)
        return page

    def _load_folders(self) -> None:
        root = self.device.root

        def read() -> list[Path]:
            return [
                entry
                for entry in DeviceFileService(root).list_dir(root)
                if entry.is_dir() and entry.name.casefold() not in _HIDDEN_FOLDERS
            ]

        self.tasks.start(read, self._folders_loaded, self._show_error)

    def _folders_loaded(self, value: object) -> None:
        folders = sorted(
            (path for path in value if isinstance(path, Path)) if isinstance(value, list) else [],
            key=lambda path: path.name.casefold(),
        )
        self.folder_list.clear()
        names = {path.name for path in folders}
        wanted: QListWidgetItem | None = None
        if self._suggested and self._suggested not in names:
            item = QListWidgetItem(f"{self._suggested}  (new folder)")
            item.setData(Qt.ItemDataRole.UserRole, str(self.device.root / self._suggested))
            item.setData(_NEW_ROLE, True)
            self.folder_list.addItem(item)
            wanted = item
        for path in folders:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.folder_list.addItem(item)
            if wanted is None and (path.name == self._suggested or path == self._last):
                wanted = item
        if wanted is not None:
            self.folder_list.setCurrentItem(wanted)
        self._refresh_buttons()

    def _create_folder(self) -> None:
        name, accepted = InputDialog.getText(self, "New folder", "Folder name:")
        if not accepted or not name.strip():
            return
        self.new_folder_button.setEnabled(False)
        root = self.device.root
        self.tasks.start(
            lambda: DeviceFileService(root).create_folder(root, name),
            self._folder_created,
            self._show_error,
        )

    def _folder_created(self, value: object) -> None:
        self.new_folder_button.setEnabled(True)
        if not isinstance(value, Path):
            return
        self.feedback.setVisible(False)
        item = QListWidgetItem(value.name)
        item.setData(Qt.ItemDataRole.UserRole, str(value))
        self.folder_list.addItem(item)
        self.folder_list.setCurrentItem(item)

    def _show_error(self, message: str) -> None:
        self.new_folder_button.setEnabled(True)
        self.feedback.setText(message or "The operation failed")
        self.feedback.setVisible(True)

    # -- navigation ------------------------------------------------------------------------
    def _go(self, step: int) -> None:
        self.pages.setCurrentIndex(step)
        self.step_label.setText(f"Step {step + 1} of 2")
        self.back_button.setVisible(step == 1)
        self.next_button.setText("Send" if step == 1 else "Next")
        self.next_button.setIcon(icon("download", ON_ACCENT) if step == 1 else icon("forward"))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        if self.pages.currentIndex() == 0:
            self.next_button.setEnabled(bool(self.tracks))
        else:
            self.next_button.setEnabled(self.folder_list.currentItem() is not None)

    def _next(self) -> None:
        if self.pages.currentIndex() == 0:
            self._go(1)
            return
        item = self.folder_list.currentItem()
        raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(raw, str) and self.tracks:
            self.destination = Path(raw)
            self.accept()

    def done(self, result: int) -> None:
        self.tasks.shutdown()
        super().done(result)
