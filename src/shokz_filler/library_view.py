"""Card-like library rows while retaining Qt's native selection and item identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QCursor, QIcon, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)

from .audiobook_models import Audiobook
from .icons import icon
from .models import Playlist, Track
from .theme import ACCENT, MUTED, SURFACE, TEXT, polish_table


@dataclass(frozen=True)
class LibraryEntry:
    """Generic title/subtitle/glyph row for lists that are not tracks, playlists or books."""

    title: str
    subtitle: str
    glyph: str


_ROW = QColor(SURFACE)
_HOVERED = QColor("#242f3c")
_SELECTED = QColor("#273c49")
_ROW_BORDER = QColor("#252e3b")
_SELECTED_BORDER = QColor("#438b96")
_TEXT = QColor(TEXT)
_MUTED = QColor(MUTED)
_ACCENT = QColor(ACCENT)


@lru_cache(maxsize=512)
def _hue_seed(title: str) -> int:
    return hashlib.sha256(title.encode()).digest()[0]


class LibraryDelegate(QStyledItemDelegate):
    # Column whose cell hosts real widgets and must not be painted over; None when there is none.
    widget_column: int | None = 3

    def __init__(self, table: QTableWidget, *, book: bool = False) -> None:
        super().__init__(table)
        self.table = table
        self.book = book
        self._hover_row = -1
        table.viewport().installEventFilter(self)

    def track(self, widget: QWidget) -> None:
        """Keep the row highlight while the pointer is over a button hosted in the row."""
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave):
            viewport = self.table.viewport()
            point = viewport.mapFromGlobal(QCursor.pos())
            row = self.table.rowAt(point.y()) if viewport.rect().contains(point) else -1
            if row != self._hover_row:
                self._hover_row = row
                viewport.update()
        return False

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)
        row_rect = QRectF(
            0, option.rect.y() + 4, self.table.viewport().width() - 4, option.rect.height() - 8
        )
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self._hover_row
        painter.setBrush(_SELECTED if selected else _HOVERED if hovered else _ROW)
        painter.setPen(QPen(_SELECTED_BORDER if selected else _ROW_BORDER, 1))
        painter.drawRoundedRect(row_rect, 10, 10)
        value = index.sibling(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        rect = option.rect.adjusted(16, 0, -12, 0)
        if index.column() == 0:
            self._title(painter, rect, value, index.data() or "")
        elif self.book or index.column() != self.widget_column:
            painter.setPen(_MUTED)
            # The duration column is right-aligned so times line up against the row's edge.
            side = (
                Qt.AlignmentFlag.AlignRight if index.column() == 2 else Qt.AlignmentFlag.AlignLeft
            )
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignVCenter | side,
                painter.fontMetrics().elidedText(
                    str(index.data() or ""), Qt.TextElideMode.ElideRight, rect.width()
                ),
            )
        current = self.table.currentIndex()
        if self.table.hasFocus() and current.row() == index.row() and not selected:
            painter.setPen(QPen(_ACCENT, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(row_rect.adjusted(1, 1, -1, -1), 10, 10)
        painter.restore()

    def _title(self, painter: QPainter, rect: QRect, value: object, fallback: str) -> None:
        if isinstance(value, Track):
            title, subtitle, glyph = value.title, value.artist, "music"
        elif isinstance(value, Playlist):
            title, subtitle, glyph = value.title, f"{value.count or '—'} tracks · Playlist", "music"
        elif isinstance(value, LibraryEntry):
            title, subtitle, glyph = value.title, value.subtitle, value.glyph
        elif isinstance(value, Audiobook):
            title, subtitle, glyph = value.title, value.author, "book"
        else:
            title, subtitle, glyph = fallback, "", "book" if self.book else "music"
        tile = QRect(rect.left(), rect.center().y() - 24, 48, 48)
        seed = _hue_seed(title)
        gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
        gradient.setColorAt(0, QColor.fromHsv(175 + seed % 55, 145, 132))
        gradient.setColorAt(1, QColor.fromHsv(200 + seed % 45, 130, 62))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(tile), 6, 6)
        icon(glyph, "#d9f6f5").paint(painter, tile.adjusted(12, 12, -12, -12))
        text = rect.adjusted(64, 0, 0, 0)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_TEXT)
        painter.drawText(
            QRect(text.left(), text.center().y() - 20, text.width(), 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, text.width()),
        )
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(_MUTED)
        painter.drawText(
            QRect(text.left(), text.center().y() + 3, text.width(), 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, text.width()),
        )


class QueueDelegate(LibraryDelegate):
    """Card rows for transfers: status icon and name, with the progress bar hosted in column 2."""

    widget_column = 2
    _status: QIcon | None = None

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        self._status = decoration if isinstance(decoration, QIcon) else None
        super().paint(painter, option, index)

    def _title(self, painter: QPainter, rect: QRect, value: object, fallback: str) -> None:
        if self._status is not None:
            self._status.paint(painter, QRect(rect.left(), rect.center().y() - 10, 20, 20))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_TEXT)
        text = rect.adjusted(32, 0, 0, 0)
        painter.drawText(
            text,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(fallback, Qt.TextElideMode.ElideRight, text.width()),
        )


def library_rows(table: QTableWidget, *, book: bool = False, height: int = 76) -> None:
    polish_table(table, height)
    table.setProperty("library", True)
    table.setMouseTracking(True)
    table.setItemDelegate(LibraryDelegate(table, book=book))
    table.setColumnHidden(1, True)
