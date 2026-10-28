"""Shared page template: every screen has the same regions at the same positions.

Header (title and page actions), subtitle line, controls row, content and footer have fixed
heights, so switching pages never makes titles, fields or buttons jump.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from .theme import role

HEADER_HEIGHT = 40
SUBTITLE_HEIGHT = 22
CONTROLS_HEIGHT = 38
FOOTER_HEIGHT = 38
SPACING = 10
NO_DEVICE_MESSAGE = "No Shokz selected — choose a device in Shokz files"


class CenteredRow(QHBoxLayout):
    """Row whose widgets sit on the vertical centre unless given another alignment."""

    def addWidget(  # noqa: N802 - Qt override
        self,
        arg__1: QWidget,
        stretch: int | None = 0,
        alignment: Qt.AlignmentFlag | None = None,
    ) -> None:
        super().addWidget(arg__1, stretch or 0, alignment or Qt.AlignmentFlag.AlignVCenter)

    def addLayout(  # noqa: N802 - Qt override
        self, layout: QLayout, stretch: int | None = 0
    ) -> None:
        super().addLayout(layout, stretch or 0)
        self.setAlignment(layout, Qt.AlignmentFlag.AlignVCenter)


def _row(height: int, *, centered: bool = False) -> tuple[QWidget, QHBoxLayout]:
    host = QWidget()
    host.setFixedHeight(height)
    layout: QHBoxLayout = CenteredRow(host) if centered else QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    return host, layout


class PageTemplate(QWidget):
    """Title + actions, subtitle, controls, content (stretching), footer."""

    def __init__(
        self, title: str, *, controls: bool = True, footer: bool = True, subtitle: bool = True
    ) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACING)
        header_host, self.header = _row(HEADER_HEIGHT)
        self.title_label = QLabel(title)
        role(self.title_label, "title")
        self.header.addWidget(self.title_label, 1)
        outer.addWidget(header_host)
        self.subtitle = QLabel()
        self.subtitle.setFixedHeight(SUBTITLE_HEIGHT)
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        role(self.subtitle, "muted")
        self.subtitle.setVisible(subtitle)
        outer.addWidget(self.subtitle)
        self.controls_host, self.controls = _row(CONTROLS_HEIGHT)
        self.controls_host.setVisible(controls)
        outer.addWidget(self.controls_host)
        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.content, 1)
        self.footer_host, self.footer = _row(FOOTER_HEIGHT, centered=True)
        self.footer_host.setVisible(footer)
        outer.addWidget(self.footer_host)
