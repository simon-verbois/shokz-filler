"""Capture the real Qt interface with fictional, isolated data and no network or device I/O."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from shokz_refill.audiobook_models import Audiobook, AudioSource, BookPage  # noqa: E402
from shokz_refill.book_dialogs import BookExportDialog  # noqa: E402
from shokz_refill.config import ConfigStore  # noqa: E402
from shokz_refill.models import Device, DownloadJob, JobStatus, Track  # noqa: E402
from shokz_refill.ui import MainWindow  # noqa: E402


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())
    app.setFont(QFont("DejaVu Sans", 10))
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="shokz-screenshots-") as directory:
        base = Path(directory)
        store = ConfigStore(base / "config", base / "cache")
        environment = dict.fromkeys(
            ("AUDIOBOOKSHELF_SERVER", "AUDIOBOOKSHELF_USERNAME", "AUDIOBOOKSHELF_PASSWORD"), ""
        )
        with (
            patch.dict(os.environ, environment),
            patch.object(MainWindow, "_poll_devices", lambda _self: None),
            patch.object(MainWindow, "_run", lambda *_args, **_kwargs: None),
        ):
            window = MainWindow(store)
            window.device_timer.stop()
            window.resize(1360, 880)
            root = Path("/media/SHOKZ")
            window.device = Device("OpenSwim Pro", root, 32 * 1024**3, 5 * 1024**3, 27 * 1024**3)
            window.current_folder = root
            window.destination = root / "Longueurs du matin"
            window.device_combo.blockSignals(True)
            window.device_combo.addItem("OpenSwim Pro — /media/SHOKZ", window.device)
            window.device_combo.setCurrentIndex(1)
            window.device_combo.blockSignals(False)
            tracks = [
                Track("demo-1", "Premier bassin", ("Les Nageurs",), "Ligne bleue", 238),
                Track("demo-2", "Au fil de l’eau", ("Atelier Minuit",), "Horizons", 204),
                Track("demo-3", "Ligne bleue", ("Les Nageurs",), "Ligne bleue", 267),
                Track("demo-4", "Le grand départ", ("Bande côtière",), "Marées", 192),
                Track("demo-5", "Une longueur de plus", ("Atelier Minuit",), "Horizons", 221),
            ]
            window._show_results(tracks)
            window.browser.search_edit.setText("Longueurs du matin")
            window.browser.browser_title.setText("Search results — Songs")
            window.results.selectRow(0)
            for index, (status, progress, detail) in enumerate(
                (
                    (JobStatus.COMPLETE, 100, "MP3 copied and verified"),
                    (JobStatus.CONVERTING, 64, "Preparing compatible MP3"),
                    (JobStatus.QUEUED, 0, "Waiting for download"),
                )
            ):
                window.queue_panel.update_job(
                    DownloadJob(
                        f"demo-{index}",
                        tracks[index],
                        window.destination,
                        status=status,
                        progress=progress,
                        error=detail,
                        device_root=root,
                    )
                )
            books = (
                Audiobook(
                    "demo-book-1",
                    "Les Cartographes du large",
                    "Camille Rivage",
                    29400,
                    (
                        AudioSource(1, "01.m4b", "/demo", 14700),
                        AudioSource(2, "02.m4b", "/demo", 14700),
                    ),
                ),
                Audiobook("demo-book-2", "Le Phare des jours", "Noé Dumas", 21600),
                Audiobook("demo-book-3", "La Traversée des saisons", "Alix Marin", 35100),
                Audiobook("demo-book-4", "Un été sur l’île", "Émile Val", 16800),
            )
            panel = window.audiobookshelf_panel
            panel.server.setText("https://livres.example.org")
            panel.username.setText("demo")
            panel.status.setText("Connected — demo library")
            panel.libraries.addItem("Livres audio", "demo-library")
            panel.set_browsing_enabled(True)
            panel.show_page(BookPage(books, len(books)))
            panel.books.selectRow(0)
            panel.details.setText("Les Cartographes du large — Camille Rivage · 2 sources · 8:10")
            panel.download.setEnabled(True)
            window._show_files(
                [
                    (root / "Longueurs du matin", True, 0),
                    (root / "Camille Rivage - Les Cartographes du large a12b34cd", True, 0),
                    (root / "Noé Dumas - Le Phare des jours e56f78ab", True, 0),
                    (root / "Balades du dimanche", True, 0),
                ]
            )
            panel.download.setEnabled(True)
            panel.disconnect_button.setEnabled(True)
            window.statusBar().showMessage("Demonstration — fictional data")
            window.show()

            def capture(name: str, widget: QWidget) -> None:
                for _ in range(8):
                    app.processEvents()
                    time.sleep(0.01)
                if not widget.grab().save(str(destination / f"{name}.png")):
                    raise RuntimeError(f"Could not save screenshot {name}")

            for index, name in ((0, "music"), (1, "audiobooks"), (2, "device"), (3, "settings")):
                window.tabs.setCurrentIndex(index)
                capture(name, window)
            dialog = BookExportDialog(books[0], window.config.book_export_options(), window)
            dialog.resize(660, 360)
            dialog.show()
            capture("book-export", dialog)
            dialog.close()
            window.close()
            while window._close_timer.isActive():
                app.processEvents()
                time.sleep(0.01)
    print(f"Captured five real application views in {destination}")


if __name__ == "__main__":
    main()
