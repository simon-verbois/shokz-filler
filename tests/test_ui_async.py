import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shokz_refill.config import ConfigStore  # noqa: E402
from shokz_refill.ui import MainWindow  # noqa: E402


def test_background_result_reaches_ui(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(tmp_path / "config", tmp_path / "cache"))
    received: list[str] = []
    window._run(lambda: "result", lambda value: received.append(str(value)))
    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window.pool.waitForDone(3_000)
    window.close()
    assert received == ["result"]
