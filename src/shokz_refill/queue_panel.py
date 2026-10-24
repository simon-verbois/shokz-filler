"""Queue presentation and selection-dependent actions."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from .icons import icon
from .models import DownloadJob, JobStatus
from .page_layout import PageTemplate
from .table_filters import ColumnFilters
from .table_state import TableEmptyState
from .theme import polish_table, role

_COMPLETE_ICON = ("check", "#48dfa6")
_FAILED_ICON = ("error", "#ffb3bd")
_RUNNING_ICON = ("refresh", "#39cdd8")
_STATUS_ICONS = {
    JobStatus.COMPLETE: _COMPLETE_ICON,
    JobStatus.SKIPPED: _COMPLETE_ICON,
    JobStatus.FAILED: _FAILED_ICON,
    JobStatus.CANCELLED: _FAILED_ICON,
    JobStatus.QUEUED: ("clock", "#e6bd72"),
}
TERMINAL = {JobStatus.COMPLETE, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}


class QueuePanel(PageTemplate):
    retryRequested = Signal()
    cancelRequested = Signal()
    summaryChanged = Signal(int, int, int, int)  # active, overall %, failed, total

    def __init__(self) -> None:
        super().__init__("Transfers")
        self.rows: dict[str, int] = {}
        self.jobs: dict[str, DownloadJob] = {}
        self.progress_bars: dict[str, QProgressBar] = {}
        self.subtitle.setText("No transfers")
        self.overall = QProgressBar()
        self.overall.setTextVisible(False)
        self.overall.setAccessibleName("Overall transfer progress")
        self.retry = QPushButton("Retry selected")
        self.retry.clicked.connect(self.retryRequested)
        self.cancel = QPushButton("Cancel selected")
        self.cancel.clicked.connect(self.cancelRequested)
        self.footer.addStretch()
        self.footer.addWidget(self.retry)
        self.footer.addWidget(self.cancel)
        self.controls.addWidget(self.overall, 1)
        self.table = QTableWidget(0, 4)
        polish_table(self.table, 44)
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
                QHeaderView.ResizeMode.Stretch,
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.Fixed,
                QHeaderView.ResizeMode.Stretch,
            )
        ):
            view.setSectionResizeMode(column, mode)
        self.table.setColumnWidth(2, 120)
        self.filters = ColumnFilters(self.table, (0, 1))
        self.table.horizontalHeader().hide()
        filter_button = QPushButton()
        filter_button.setFixedWidth(36)
        filter_button.setIcon(icon("filter"))
        filter_button.setToolTip("Filter transfers")
        filter_button.setAccessibleName("Filter transfers")
        role(filter_button, "quiet")
        menu = QMenu(self)
        menu.addAction("Filter track / book…", partial(self.filters.edit, 0))
        menu.addAction("Filter status…", partial(self.filters.edit, 1))
        menu.addAction("Clear filters", self.filters.clear)
        filter_button.setMenu(menu)
        self.controls.addWidget(filter_button)
        self.content.addWidget(self.table)
        self.empty_state = TableEmptyState(
            self.table, "Your transfer queue is empty\nSelect songs or books to send to your Shokz."
        )
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
            cell = QWidget()
            progress_layout = QHBoxLayout(cell)
            progress_layout.setContentsMargins(6, 0, 14, 0)
            progress = QProgressBar()
            progress_layout.addWidget(progress, 1, Qt.AlignmentFlag.AlignVCenter)
            self.progress_bars[job.job_id] = progress
            self.table.setCellWidget(row, 2, cell)
        status = f"{job.progress}% · {job.status.value}" if job.progress else job.status.value
        self.table.setItem(row, 1, QTableWidgetItem(status))
        status_icon, status_color = _STATUS_ICONS.get(job.status, _RUNNING_ICON)
        first_item = self.table.item(row, 0)
        if first_item is not None:
            first_item.setIcon(icon(status_icon, status_color))
            first_item.setToolTip(f"{job.track.artist} — {job.track.title}")
        details = QTableWidgetItem(job.error)
        details.setToolTip(job.error)
        self.table.setItem(row, 3, details)
        bar = self.progress_bars[job.job_id]
        bar.setTextVisible(False)
        bar.setValue(job.progress)
        bar.setAccessibleName(f"{job.track.title}: {job.progress}% — {job.status.value}")
        bar.setToolTip(f"{job.progress}% — {job.status.value}")
        self.overall.setValue(
            int(sum(item.progress for item in self.jobs.values()) / len(self.jobs))
        )
        active = sum(item.status not in TERMINAL for item in self.jobs.values())
        failed = sum(item.status == JobStatus.FAILED for item in self.jobs.values())
        summary = f"{active} active · {self.overall.value()}%" if active else "Finished"
        self.subtitle.setText(summary + (f" · {failed} failed" if failed else ""))
        self.summaryChanged.emit(active, self.overall.value(), failed, len(self.jobs))
        self._update_actions()
        return job.status == JobStatus.COMPLETE and (
            previous is None or previous.status != JobStatus.COMPLETE
        )

    def _context_menu(self, point: QPoint) -> None:
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
