from __future__ import annotations

import logging
import sys
from importlib import import_module
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from .config import ConfigStore
from .icons import app_icon
from .media import bundled_binary
from .theme import apply_theme
from .ui import MainWindow


def _logging(store: ConfigStore) -> None:
    store.ensure_dirs()
    handler = RotatingFileHandler(
        store.cache_dir / "shokz-refill.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> int:
    store = ConfigStore()
    _logging(store)
    QCoreApplication.setOrganizationName("Shokz Refill")
    QCoreApplication.setApplicationName("Shokz Refill")
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setDesktopFileName("shokz-refill")
    apply_theme(app)
    window = MainWindow(store)
    window.show()
    if "--smoke-test" in sys.argv:
        bundled_binary("ffmpeg")
        bundled_binary("deno")
        import_module("yt_dlp_ejs")
        QTimer.singleShot(500, window.close)
    else:
        window.connect_saved_accounts()
    return app.exec()
