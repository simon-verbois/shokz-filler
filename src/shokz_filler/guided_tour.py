"""Read-only onboarding with a spotlight on the real application controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, BACKGROUND, role

if TYPE_CHECKING:
    from .ui import MainWindow


@dataclass(frozen=True, slots=True)
class TourStep:
    """A page and an existing control to explain, without activating the control."""

    page: int
    target: QWidget
    title: str
    description: str


def application_tour_steps(window: MainWindow) -> tuple[TourStep, ...]:
    """Keep these instructions aligned with the current user-facing workflows."""
    return (
        TourStep(
            0,
            window.sidebar,
            "Welcome to Shokz Filler",
            "Load music, audiobooks and local MP3s onto your Shokz. "
            "This quick tour shows you where to start. You can skip it at any time.",
        ),
        TourStep(
            2,
            window.device_combo,
            "Choose your Shokz",
            "Connect your headphones in USB storage mode and select the mounted device here. "
            "If it is not detected, use Browse… to select its mounted folder. "
            "The sidebar shows the selected device and available space.",
        ),
        TourStep(
            4,
            window.settings_page,
            "Connect your accounts",
            "Connect YouTube Music to access My playlists. For Audiobookshelf, enter your "
            "server address and credentials here. You can also choose and preview offline "
            "voice announcements for audiobook chapters before saving your settings.",
        ),
        TourStep(
            0,
            window.browser.search_edit,
            "Find your music",
            "Choose Songs or Playlists, type a title or artist and press Enter. "
            "My playlists opens your connected account's library. "
            "Open a playlist to browse its tracks; use the arrows to go back and forward.",
        ),
        TourStep(
            0,
            window.download_button,
            "Build your send list",
            "Use + beside a song or playlist to add it to your send list. "
            "Send to Shokz lets you review and reorder songs, then choose a destination "
            "before starting. Output is MP3 at 192 kbps, 44.1 kHz, stereo, "
            "or mono if you enable it in Settings.",
        ),
        TourStep(
            1,
            window.audiobookshelf_panel.libraries,
            "Take audiobooks with you",
            "After connecting in Settings, choose a library and find a book. "
            "Send to Shokz exports one numbered MP3 per chapter in playback order. "
            "You can review chapter voice announcements before exporting; "
            "Settings also holds the mono option.",
        ),
        TourStep(
            2,
            window.file_buttons["Add local MP3"],
            "Manage files and import MP3s",
            "Browse folders in Shokz files and use Add MP3 to import local music. "
            "Files are converted to the required MP3 format when needed. "
            "Use the file actions to organize your device; deletion asks for confirmation.",
        ),
        TourStep(
            3,
            window.sidebar.buttons[3],
            "Follow your transfers",
            "Watch downloads, conversion and copies here. Cancel active or queued items, "
            "retry failed and cancelled items, or clear finished ones. The sidebar indicator "
            "keeps you informed while you browse other pages. Existing files are preserved.",
        ),
        TourStep(
            0,
            window.sidebar.tour_button,
            "Ready when you are",
            "Open Guided tour here whenever you need a reminder. "
            "You will return to the page you were using when you close the tour.",
        ),
    )


class GuidedTour(QDialog):
    """Modeless execution with window modality: no nested event loop or real actions."""

    def __init__(self, parent: QWidget, pages: QTabWidget, steps: tuple[TourStep, ...]) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle("Guided tour — Shokz Filler")
        self._host = parent
        self._pages = pages
        self._original_page = pages.currentIndex()
        self._original_focus = QApplication.focusWidget()
        self.steps = steps
        self.index = 0
        self.spotlight = QRect()
        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setStyleSheet(
            f"QFrame#tourCard {{ background: {BACKGROUND}; "
            f"border: 1px solid {ACCENT}; border-radius: 12px; }}"
        )
        self.card.setFixedWidth(396)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        self.counter = QLabel()
        role(self.counter, "muted")
        layout.addWidget(self.counter)
        self.title = QLabel()
        self.title.setWordWrap(True)
        role(self.title, "title")
        layout.addWidget(self.title)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.description)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip = QPushButton("Skip tour")
        role(self.skip, "quiet")
        self.skip.clicked.connect(self.reject)
        buttons.addWidget(self.skip)
        buttons.addStretch()
        self.back = QPushButton("Back")
        self.back.clicked.connect(self.previous_step)
        buttons.addWidget(self.back)
        self.next = QPushButton("Next")
        self.next.setDefault(True)
        role(self.next, "primary")
        self.next.clicked.connect(self.next_step)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        QWidget.setTabOrder(self.skip, self.back)
        QWidget.setTabOrder(self.back, self.next)
        self._host.installEventFilter(self)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._show_step()

    def next_step(self) -> None:
        """Advance or finish the tour."""
        if self.index == len(self.steps) - 1:
            self.accept()
        else:
            self.index += 1
            self._show_step()

    def previous_step(self) -> None:
        """Return to the previous explanation."""
        if self.index:
            self.index -= 1
            self._show_step()

    def _show_step(self) -> None:
        step = self.steps[self.index]
        self._pages.setCurrentIndex(step.page)
        self.counter.setText(f"QUICK START  ·  {self.index + 1} / {len(self.steps)}")
        self.title.setText(step.title)
        self.description.setText(step.description)
        self.setAccessibleDescription(f"{step.title}. {step.description}")
        self.back.setEnabled(self.index > 0)
        self.next.setText("Finish" if self.index == len(self.steps) - 1 else "Next")
        self._position_card()
        # A newly visible tab may finish laying out on the next event-loop iteration.
        QTimer.singleShot(0, self._position_card)
        self.next.setFocus(Qt.FocusReason.OtherFocusReason)

    def _position_card(self) -> None:
        if not self.isVisible():
            return
        self.setGeometry(QRect(self._host.mapToGlobal(QPoint()), self._host.size()))
        target = self.steps[self.index].target
        self.spotlight = (
            QRect(target.mapTo(self._host, QPoint()), target.size())
            .adjusted(-5, -5, 5, 5)
            .intersected(self.rect().adjusted(6, 6, -6, -6))
        )
        self.card.adjustSize()
        width, height = self.card.width(), self.card.height()
        area = self.rect().adjusted(24, 24, -24, -24)
        gap = 20
        candidates = (
            QPoint(self.spotlight.right() + gap, self.spotlight.center().y() - height // 2),
            QPoint(self.spotlight.center().x() - width // 2, self.spotlight.bottom() + gap),
            QPoint(self.spotlight.center().x() - width // 2, self.spotlight.top() - gap - height),
            QPoint(self.spotlight.left() - gap - width, self.spotlight.center().y() - height // 2),
        )
        position = area.center() - QPoint(width // 2, height // 2)
        for candidate in candidates:
            fitted = QPoint(
                max(area.left(), min(candidate.x(), area.right() - width + 1)),
                max(area.top(), min(candidate.y(), area.bottom() - height + 1)),
            )
            if not QRect(fitted, self.card.size()).intersects(self.spotlight):
                position = fitted
                break
        self.card.move(position)
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._position_card()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scrim = QPainterPath()
        scrim.addRect(QRectF(self.rect()))
        scrim.addRoundedRect(QRectF(self.spotlight), 10, 10)
        painter.fillPath(scrim, QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(ACCENT), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.spotlight), 10, 10)

    def done(self, result: int) -> None:
        self._host.removeEventFilter(self)
        self._pages.setCurrentIndex(self._original_page)
        super().done(result)
        self._host.activateWindow()
        if self._original_focus is not None and self._original_focus.isVisible():
            self._original_focus.setFocus(Qt.FocusReason.OtherFocusReason)
