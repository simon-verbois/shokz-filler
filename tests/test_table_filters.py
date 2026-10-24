import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QTableWidget,
    QTableWidgetItem,
)

from shokz_refill.table_filters import ColumnFilters  # noqa: E402
from shokz_refill.themed_dialog import InputDialog  # noqa: E402


def test_filters_combine_ignore_case_and_clear_hidden_selection() -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(3, 3)
    table.setHorizontalHeaderLabels(["Title", "Artist", "Duration"])
    for row, values in enumerate(
        [("Ocean", "Alice", "1:00"), ("OCEAN live", "Bob", "2:00"), ("River", "Alice", "3:00")]
    ):
        for column, text in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(text))
    filters = ColumnFilters(table, (0, 1))
    table.selectRow(1)
    filters.set_filter(0, " ocean ")
    filters.set_filter(1, "ALICE")
    assert [table.isRowHidden(row) for row in range(3)] == [False, True, True]
    assert not table.selectedItems()
    assert not table.selectionModel().selectedRows()
    assert filters.buttons[0].isChecked()
    assert set(filters.buttons) == {0, 1}
    filters.clear()
    assert not any(table.isRowHidden(row) for row in range(3))
    assert not filters.buttons[0].isChecked()
    table.close()
    app.processEvents()


def test_filter_follows_sort_refresh_and_status_changes() -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(2, 1)
    table.setHorizontalHeaderLabels(["Status"])
    table.setItem(0, 0, QTableWidgetItem("Waiting"))
    table.setItem(1, 0, QTableWidgetItem("Complete"))
    filters = ColumnFilters(table, (0,))
    filters.set_filter(0, "complete")
    table.sortItems(0, Qt.SortOrder.AscendingOrder)
    app.processEvents()
    assert not table.isRowHidden(0)
    assert table.isRowHidden(1)
    table.item(1, 0).setText("Complete")
    app.processEvents()
    assert not table.isRowHidden(1)
    table.setRowCount(0)
    table.setRowCount(1)
    table.setItem(0, 0, QTableWidgetItem("Waiting"))
    app.processEvents()
    assert table.isRowHidden(0)
    table.close()


def test_filter_button_edits_and_cancel_preserves_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use the real button signal, so the header control's connection is exercised.
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 1)
    table.setHorizontalHeaderLabels(["Title"])
    filters = ColumnFilters(table, (0,))
    monkeypatch.setattr(InputDialog, "getText", lambda *args, **kwargs: ("Ocean", True))
    filters.buttons[0].click()
    assert filters.filters == {0: "Ocean"}
    monkeypatch.setattr(InputDialog, "getText", lambda *args, **kwargs: ("River", False))
    filters.buttons[0].click()
    assert filters.filters == {0: "Ocean"}
    assert filters.buttons[0].isChecked()
    monkeypatch.setattr(InputDialog, "getText", lambda *args, **kwargs: ("", True))
    filters.buttons[0].click()
    assert not filters.filters
    table.close()
    app.processEvents()
