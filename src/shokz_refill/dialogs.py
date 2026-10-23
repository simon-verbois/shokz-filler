from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .background import TaskRunner
from .device import is_within
from .files import DeviceFileService
from .models import Device


class DeviceFolderDialog(QDialog):
    _LOADED_ROLE = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(
        self,
        device: Device,
        sources: list[Path],
        parent: QWidget | None = None,
        *,
        title: str = "Choose destination folder",
        allow_root: bool = True,
        allow_create: bool = False,
    ) -> None:
        super().__init__(parent)
        self.device = device
        self.allow_root = allow_root
        self.destination: Path | None = None
        self.tasks = TaskRunner(self)
        self._blocked_roots = [path.resolve() for path in sources if path.is_dir()]
        self._moving_folders = bool(self._blocked_roots)
        self.setWindowTitle(title)
        self.resize(480, 520)
        layout = QVBoxLayout(self)
        label = QLabel(f"Choose a destination folder on {device.name}")
        layout.addWidget(label)
        self.feedback = QLabel(
            "Choose an existing folder or create a new one. The device root cannot be used."
            if not allow_root
            else ""
        )
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Folder")
        self.tree.itemExpanded.connect(self._load_children)
        self.tree.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.tree)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.new_folder_button = buttons.addButton(
            "New folder", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.new_folder_button.setVisible(allow_create)
        self.new_folder_button.clicked.connect(self._create_folder)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if allow_root:
            root = QTreeWidgetItem([device.name])
            root.setData(0, Qt.ItemDataRole.UserRole, str(device.root))
            root.addChild(QTreeWidgetItem(["Loading…"]))
            self.tree.addTopLevelItem(root)
            self.tree.setCurrentItem(root)
            root.setExpanded(True)
            self._selection_changed(root, None)
        else:
            # The invisible tree root represents the device root. Its children are
            # shown directly, so the forbidden device root cannot be selected.
            root = self.tree.invisibleRootItem()
            root.setData(0, Qt.ItemDataRole.UserRole, str(device.root))
            self._load_children(root)
            self._selection_changed(None, None)

    def _is_blocked(self, path: Path) -> bool:
        return any(is_within(source, path) for source in self._blocked_roots)

    def _is_valid_destination(self, path: Path) -> bool:
        return (
            not self._is_blocked(path)
            and (self.allow_root or path != self.device.root)
            and (not self._moving_folders or path == self.device.root)
        )

    def _load_children(self, item: QTreeWidgetItem) -> None:
        if item.data(0, self._LOADED_ROLE):
            return
        raw_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(raw_path, str):
            return
        item.setData(0, self._LOADED_ROLE, True)
        item.takeChildren()
        loading = QTreeWidgetItem(["Loading…"])
        loading.setDisabled(True)
        item.addChild(loading)
        path = Path(raw_path)

        def read_folders() -> list[Path]:
            return [
                entry
                for entry in DeviceFileService(self.device.root).list_dir(path)
                if entry.is_dir()
            ]

        def completed(value: object) -> None:
            item.takeChildren()
            folders = list(value) if isinstance(value, list) else []
            for folder in folders:
                if not isinstance(folder, Path):
                    continue
                child = QTreeWidgetItem([folder.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(folder))
                if self._moving_folders:
                    child.setDisabled(True)
                    child.setToolTip(0, "Folders can only be placed at the device root")
                elif self._is_blocked(folder):
                    child.setDisabled(True)
                    child.setToolTip(0, "A folder cannot be moved inside itself")
                else:
                    child.addChild(QTreeWidgetItem(["Loading…"]))
                item.addChild(child)

        def failed(message: str) -> None:
            item.takeChildren()
            error = QTreeWidgetItem([f"Unable to read folder: {message}"])
            error.setDisabled(True)
            item.addChild(error)

        self.tasks.start(read_folders, completed, failed)

    def _accept_selection(self) -> None:
        item = self.tree.currentItem()
        raw_path = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(raw_path, str):
            path = Path(raw_path)
            if self._is_valid_destination(path):
                self.destination = path
                self.accept()

    def _selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        raw_path = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(raw_path, str):
            self.ok_button.setEnabled(False)
            return
        path = Path(raw_path)
        self.ok_button.setEnabled(self._is_valid_destination(path))

    def _create_folder(self) -> None:
        # Shokz Refill deliberately keeps a flat folder layout. New folders are
        # always top-level, even when an existing folder happens to be selected.
        parent = self.device.root
        name, accepted = QInputDialog.getText(self, "New folder", "Folder name:")
        if not accepted or not name:
            return
        self.new_folder_button.setEnabled(False)
        self.ok_button.setEnabled(False)
        self.feedback.setText("Creating folder…")

        def completed(value: object) -> None:
            if isinstance(value, Path):
                self.destination = value
                self.accept()

        def failed(message: str) -> None:
            self.feedback.setText(message or "The folder could not be created")
            self.new_folder_button.setEnabled(True)
            self._selection_changed(self.tree.currentItem(), None)

        self.tasks.start(
            lambda: DeviceFileService(self.device.root).create_folder(parent, name),
            completed,
            failed,
        )

    def done(self, result: int) -> None:
        self.tasks.shutdown()
        super().done(result)


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
