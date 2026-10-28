"""Qt worker lifecycle, cancellation and latest-request delivery."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from .cancellation import current_cancellation


class WorkerSignals(QObject):
    finished = Signal(object, object)


class Worker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.cancelled = threading.Event()

    @Slot()
    def run(self) -> None:
        value: object = None
        error: str | None = None
        token = current_cancellation.set(self.cancelled)
        try:
            if not self.cancelled.is_set():
                value = self.function()
        except Exception as exc:
            error = str(exc)
        finally:
            current_cancellation.reset(token)
            self.signals.finished.emit(value, error)


@dataclass
class PendingTask:
    worker: Worker
    success: Callable[[Any], None]
    failure: Callable[[str], None]
    key: str | None


class TaskRunner(QObject):
    """Own workers until completion and deliver current results on the Qt thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.pending: dict[WorkerSignals, PendingTask] = {}
        self.closed = False

    def cancel(self, key: str) -> None:
        for task in self.pending.values():
            if task.key == key:
                task.worker.cancelled.set()

    def active(self, key: str) -> bool:
        return any(task.key == key for task in self.pending.values())

    def start(
        self,
        function: Callable[[], Any],
        success: Callable[[Any], None],
        failure: Callable[[str], None],
        *,
        key: str | None = None,
    ) -> None:
        if self.closed:
            return
        if key is not None:
            self.cancel(key)
        worker = Worker(function)
        worker.signals.setParent(self)
        self.pending[worker.signals] = PendingTask(worker, success, failure, key)
        worker.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)

    @Slot(object, object)
    def _finished(self, value: object, error: object) -> None:
        signals = self.sender()
        if not isinstance(signals, WorkerSignals):
            return
        task = self.pending.pop(signals, None)
        signals.deleteLater()
        if task is None or self.closed or task.worker.cancelled.is_set():
            return
        if isinstance(error, str):
            task.failure(error)
        else:
            task.success(value)

    def shutdown(self) -> None:
        self.closed = True
        for task in self.pending.values():
            task.worker.cancelled.set()

    @property
    def idle(self) -> bool:
        return not self.pending and self.pool.activeThreadCount() == 0
