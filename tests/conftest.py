"""Keep a single Qt application and drain asynchronous window shutdowns between tests."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shokz_refill.background import TaskRunner  # noqa: E402
from shokz_refill.ui import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qt_application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def finish_qt_windows(
    qt_application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    # UI tests inject temporary devices; background discovery must not remove them.
    monkeypatch.setattr(MainWindow, "_poll_devices", lambda _self: None)
    yield
    windows = list(qt_application.topLevelWidgets())
    for window in windows:
        window.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        qt_application.processEvents()
        if all(
            not isinstance(window, MainWindow)
            or (
                all(queue.idle for queue in window._queues)
                and all(runner.idle for runner in window.findChildren(TaskRunner))
                and not window._close_timer.isActive()
            )
            for window in windows
        ):
            break
        time.sleep(0.001)
    else:
        pytest.fail("Qt workers did not finish during test cleanup")
    for window in windows:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
