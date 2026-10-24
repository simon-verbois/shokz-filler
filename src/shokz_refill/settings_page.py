"""One place for accounts and preferences, so connections are not scattered across pages."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .page_layout import PageTemplate
from .theme import role

SAVE_CLEARANCE = 56  # keeps the last card clear of the floating Save button
SAVE_MARGIN = 20


class SettingsPage(PageTemplate):
    authRequested = Signal()
    disconnectRequested = Signal()

    def __init__(
        self, audiobookshelf_card: QWidget, speech: QWidget, save_button: QPushButton
    ) -> None:
        super().__init__("Settings", controls=False, footer=False, subtitle=False)
        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.content.addWidget(self.scroll_area)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(10)
        layout.addWidget(self._section("Accounts"))
        layout.addWidget(self._youtube_card())
        layout.addSpacing(8)
        layout.addWidget(self._section("Audiobookshelf"))
        layout.addWidget(audiobookshelf_card)
        layout.addSpacing(8)
        layout.addWidget(self._section("Audiobook announcement"))
        layout.addWidget(speech)
        layout.addSpacing(SAVE_CLEARANCE)
        layout.addStretch()
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(body, 1)
        self.scroll_area.setWidget(page)
        self.save_button = save_button
        save_button.setParent(self)
        save_button.adjustSize()
        save_button.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        button = self.save_button
        button.adjustSize()
        button.move(
            self.width() - button.width() - SAVE_MARGIN,
            self.height() - button.height() - SAVE_MARGIN,
        )
        button.raise_()

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        role(label, "section")
        return label

    def _youtube_card(self) -> QFrame:
        card = QFrame()
        role(card, "card")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        name = QLabel("YouTube Music")
        role(name, "strong")
        self.auth_label = QLabel()
        role(self.auth_label, "muted")
        self.auth_label.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(self.auth_label)
        row.addLayout(text, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.authRequested.emit)
        self.disconnect_button = QPushButton("Disconnect")
        role(self.disconnect_button, "quiet")
        self.disconnect_button.clicked.connect(self.disconnectRequested.emit)
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        return card
