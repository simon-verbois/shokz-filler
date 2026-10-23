"""Queue presentation and selection-dependent actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import DownloadJob, JobStatus
from .table_filters import ColumnFilters

TERMINAL = {JobStatus.COMPLETE, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}


class QueuePanel(QWidget):
    retryRequested = Signal()
    cancelRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, int] = {}
        self.jobs: dict[str, DownloadJob] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Download and transfer queue"))
        self.overall = QProgressBar()
        self.overall.setFormat("Overall %p%")
        self.overall.setMaximumWidth(220)
        header.addWidget(self.overall)
        header.addStretch()
        self.retry = QPushButton("Retry selected")
        self.retry.clicked.connect(self.retryRequested)
        self.cancel = QPushButton("Cancel selected")
        self.cancel.clicked.connect(self.cancelRequested)
        header.addWidget(self.retry)
        header.addWidget(self.cancel)
        layout.addLayout(header)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Track / book", "Status", "Progress", "Details"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self._update_actions)
        view = self.table.horizontalHeader()
        view.setStretchLastSection(False)
        for column, mode in enumerate(
            (
                QHeaderView.ResizeMode.Interactive,
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.Fixed,
                QHeaderView.ResizeMode.Stretch,
            )
        ):
            view.setSectionResizeMode(column, mode)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(2, 160)
        self.filters = ColumnFilters(self.table, (0, 1))
        layout.addWidget(self.table)
        self._update_actions()

    def selected_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is not None and not self.table.isRowHidden(index.row()):
                ids.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def _update_actions(self) -> None:
        selected = [self.jobs[key] for key in self.selected_ids() if key in self.jobs]
        self.retry.setEnabled(
            any(job.status in {JobStatus.FAILED, JobStatus.CANCELLED} for job in selected)
        )
        self.cancel.setEnabled(any(job.status not in TERMINAL for job in selected))

    def update_job(self, job: DownloadJob) -> bool:
        previous = self.jobs.get(job.job_id)
        self.jobs[job.job_id] = job
        row = self.rows.get(job.job_id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.rows[job.job_id] = row
            first = QTableWidgetItem(f"{job.track.artist} — {job.track.title}")
            first.setData(Qt.ItemDataRole.UserRole, job.job_id)
            self.table.setItem(row, 0, first)
            self.table.setCellWidget(row, 2, QProgressBar())
        self.table.setItem(row, 1, QTableWidgetItem(job.status.value))
        self.table.setItem(row, 3, QTableWidgetItem(job.error))
        bar = self.table.cellWidget(row, 2)
        if isinstance(bar, QProgressBar):
            bar.setValue(job.progress)
        self.overall.setValue(
            int(sum(item.progress for item in self.jobs.values()) / len(self.jobs))
        )
        self._update_actions()
        return job.status == JobStatus.COMPLETE and (
            previous is None or previous.status != JobStatus.COMPLETE
        )

    def _context_menu(self, position: object) -> None:
        point = self.table.viewport().mapFromGlobal(self.cursor().pos())
        row = self.table.rowAt(point.y())
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None and not item.isSelected():
            self.table.clearSelection()
            self.table.selectRow(row)
        if not self.selected_ids():
            return
        menu = QMenu(self)
        retry = menu.addAction("Retry selected")
        retry.setEnabled(self.retry.isEnabled())
        cancel = menu.addAction("Cancel selected")
        cancel.setEnabled(self.cancel.isEnabled())
        chosen = menu.exec(self.table.viewport().mapToGlobal(point))
        if chosen == retry:
            self.retryRequested.emit()
        elif chosen == cancel:
            self.cancelRequested.emit()
