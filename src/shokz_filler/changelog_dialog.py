"""The changelog window opened from the sidebar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .about import changelog_text
from .theme import role
from .themed_dialog import ThemedDialog


def show_changelog(parent: QWidget | None) -> None:
    dialog = ThemedDialog(parent, "Changelog")
    dialog.resize(560, 460)
    layout = QVBoxLayout(dialog.content)
    layout.setContentsMargins(18, 8, 18, 16)
    browser = QTextBrowser()
    browser.setOpenLinks(False)
    browser.setFrameShape(QFrame.Shape.NoFrame)
    browser.setMarkdown(changelog_text())
    browser.setAccessibleName("Changelog")
    layout.addWidget(browser)
    close = QPushButton("Close")
    role(close, "primary")
    close.clicked.connect(dialog.accept)
    close.setDefault(True)
    layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
    dialog.exec()
