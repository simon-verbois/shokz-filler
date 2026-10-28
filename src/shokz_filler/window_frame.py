"""Frameless window chrome: themed title bar, rounded corners and edge resizing."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QWidget

from .icons import icon
from .theme import role

EDGE_MARGIN = 6


def edges_at(position: QPoint, size: QSize, margin: int = EDGE_MARGIN) -> Qt.Edge:
    """Window edges under a point; empty when the point is in the interior."""
    edges = Qt.Edge(0)
    if position.x() < margin:
        edges |= Qt.Edge.LeftEdge
    elif position.x() >= size.width() - margin:
        edges |= Qt.Edge.RightEdge
    if position.y() < margin:
        edges |= Qt.Edge.TopEdge
    elif position.y() >= size.height() - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
    horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
    vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
    if horizontal and vertical:
        diagonal = (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge) or (
            edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge
        )
        return Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
    if horizontal:
        return Qt.CursorShape.SizeHorCursor
    if vertical:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


class TitleBar(QWidget):
    """Drag area with window controls, painted in the application's own colours."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__()
        self._window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 8, 0)
        layout.setSpacing(2)
        layout.addStretch()
        self.minimize = self._button("minimize", "Minimize", window.showMinimized)
        self.maximize = self._button("maximize", "Maximize", self.toggle_maximized)
        self.close_button = self._button("close", "Close", window.close)
        self.close_button.setProperty("danger", True)
        for button in (self.minimize, self.maximize, self.close_button):
            layout.addWidget(button)

    def _button(self, glyph: str, label: str, handler: object) -> QPushButton:
        button = QPushButton()
        button.setIcon(icon(glyph))
        button.setFixedSize(34, 28)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        role(button, "window")
        button.clicked.connect(handler)
        return button

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def sync(self) -> None:
        maximized = self._window.isMaximized()
        self.maximize.setIcon(icon("restore" if maximized else "maximize"))
        label = "Restore" if maximized else "Maximize"
        self.maximize.setToolTip(label)
        self.maximize.setAccessibleName(label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        handle = self._window.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
