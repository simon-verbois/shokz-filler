from __future__ import annotations

from functools import partial

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QInputDialog, QMenu, QTableWidget, QToolButton
from shiboken6 import isValid


class ColumnFilters(QObject):
    """Filter displayed rows without changing item identities or worker data."""

    def __init__(self, table: QTableWidget, columns: tuple[int, ...]) -> None:
        super().__init__(table)
        self.table = table
        self.filters: dict[int, str] = {}
        self.buttons: dict[int, QToolButton] = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        header = table.horizontalHeader()
        header.setStyleSheet("QHeaderView::section { padding-right: 40px; }")
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(table.palette().text().color(), 1.8))
        painter.drawEllipse(2, 2, 8, 8)
        painter.drawLine(9, 9, 14, 14)
        painter.end()
        for column in columns:
            button = QToolButton(header.viewport())
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(16, 16))
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.clicked.connect(partial(self.edit, column))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(partial(self.context_menu, column))
            self.buttons[column] = button
            self.update_button(column)
        header.viewport().installEventFilter(self)
        header.sectionResized.connect(self.position_buttons)
        header.sectionMoved.connect(self.position_buttons)
        header.geometriesChanged.connect(self.position_buttons)
        header.sortIndicatorChanged.connect(self.position_buttons)
        table.horizontalScrollBar().valueChanged.connect(self.position_buttons)
        table.itemChanged.connect(self.schedule)
        model = table.model()
        model.rowsInserted.connect(self.schedule)
        model.rowsRemoved.connect(self.schedule)
        model.modelReset.connect(self.schedule)
        model.layoutChanged.connect(self.schedule)
        self.position_buttons()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.position_buttons()
        return super().eventFilter(watched, event)

    def position_buttons(self) -> None:
        if not isValid(self.table):
            return
        header = self.table.horizontalHeader()
        for column, button in self.buttons.items():
            if not isValid(button):
                continue
            offset = 18 if header.isSortIndicatorShown() else 2
            x = header.sectionViewportPosition(column) + header.sectionSize(column) - 24 - offset
            button.setGeometry(x, max(0, (header.height() - 24) // 2), 24, 24)
            button.setVisible(not header.isSectionHidden(column))

    def update_button(self, column: int) -> None:
        item = self.table.horizontalHeaderItem(column)
        name = item.text() if item else str(column)
        query = self.filters.get(column, "")
        button = self.buttons[column]
        button.setChecked(bool(query))
        button.setAccessibleName(f"Filter {name}")
        button.setToolTip(
            f"Filter {name}: {query}\nRight-click to clear" if query else f"Filter {name}"
        )

    def edit(self, column: int) -> None:
        item = self.table.horizontalHeaderItem(column)
        name = item.text() if item else str(column)
        text, accepted = QInputDialog.getText(
            self.table,
            f"Filter {name}",
            "Contains (leave empty to clear):",
            text=self.filters.get(column, ""),
        )
        if accepted:
            self.set_filter(column, text)
        else:
            self.update_button(column)

    def context_menu(self, column: int, position: object) -> None:
        menu = QMenu(self.table)
        clear = menu.addAction("Clear this filter")
        clear.setEnabled(column in self.filters)
        clear.triggered.connect(lambda: self.set_filter(column, ""))
        clear_all = menu.addAction("Clear all filters")
        clear_all.setEnabled(bool(self.filters))
        clear_all.triggered.connect(self.clear)
        menu.exec(self.buttons[column].mapToGlobal(self.buttons[column].rect().bottomLeft()))

    def set_filter(self, column: int, text: str) -> None:
        if column not in self.buttons:
            raise ValueError("This column cannot be filtered")
        text = text.strip()
        if text:
            self.filters[column] = text
        else:
            self.filters.pop(column, None)
        self.update_button(column)
        self.apply()

    def clear(self) -> None:
        self.filters.clear()
        for column in self.buttons:
            self.update_button(column)
        self.apply()

    def schedule(self) -> None:
        if self.filters:
            self.timer.start(0)

    def apply(self) -> None:
        for row in range(self.table.rowCount()):
            hidden = any(
                query.casefold() not in (item.text().casefold() if item else "")
                for column, query in self.filters.items()
                for item in [self.table.item(row, column)]
            )
            self.table.setRowHidden(row, hidden)
        # Hidden selections must not be included in download/delete operations.
        for item in self.table.selectedItems():
            if self.table.isRowHidden(item.row()):
                item.setSelected(False)
