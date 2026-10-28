"""Accessible empty-state guidance that follows a native table's viewport."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QTableWidget
from shiboken6 import isValid

from .theme import role


class TableEmptyState(QObject):
    def __init__(self, table: QTableWidget, message: str) -> None:
        super().__init__(table)
        self.table = table
        self.label = QLabel(message, table.viewport())
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        role(self.label, "muted")
        table.viewport().installEventFilter(self)
        model = table.model()
        model.rowsInserted.connect(self.update)
        model.rowsRemoved.connect(self.update)
        model.modelReset.connect(self.update)
        self.update()

    def set_text(self, message: str) -> None:
        self.label.setText(message)
        self.update()

    def update(self) -> None:
        if not isValid(self.table) or not isValid(self.label):
            return
        self.label.setGeometry(self.table.viewport().rect().adjusted(24, 12, -24, -12))
        self.label.setVisible(self.table.rowCount() == 0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.update()
        return super().eventFilter(watched, event)
