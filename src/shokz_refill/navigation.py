"""Persistent application navigation and selected-device summary."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import icon, logo_pixmap
from .models import Device
from .theme import ACCENT, ON_ACCENT, role


class NavButton(QPushButton):
    """Sidebar entry whose active bar is painted, so it always repaints with the checked state."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        # Keyboard focus only: a mouse click must not leave a full focus frame behind.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(lambda _checked: self.update())

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(0, 8, 3, self.height() - 16), 1.5, 1.5)


PAGES = (
    ("YouTube Music", "music"),
    ("Audiobookshelf", "book"),
    ("Shokz files", "folder"),
    ("Transfers", "download"),
    ("Settings", "settings"),
)
TRANSFERS_PAGE = 3
SETTINGS_PAGE = 4


class TransferIndicator(QWidget):
    """A ring that spins while transfers run, filling with progress, and a check when done."""

    SIZE = 22

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.state = "idle"
        self.percent = 0
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.setVisible(False)

    def set_state(self, state: str, percent: int = 0) -> None:
        self.state = state
        self.percent = percent
        self.setVisible(state != "idle")
        if state == "active":
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(2, 2, self.SIZE - 4, self.SIZE - 4)
        if self.state == "active":
            painter.setPen(QPen(QColor("#2f3b4a"), 2.4))
            painter.drawEllipse(box)
            pen = QPen(QColor(ACCENT), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            span = max(self.percent * 360 // 100, 40)
            painter.drawArc(box, (90 - self._angle) * 16, -span * 16)
        elif self.state in ("done", "failed"):
            color = QColor(ACCENT if self.state == "done" else "#ff8a9a")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(box)
            pen = QPen(QColor(ON_ACCENT), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if self.state == "done":
                painter.drawPolyline([QPointF(6.6, 11.4), QPointF(9.6, 14.4), QPointF(15.4, 8.0)])
            else:
                painter.drawLine(QPointF(11, 6.5), QPointF(11, 12))
                painter.drawPoint(QPointF(11, 15.2))


class Sidebar(QWidget):
    pageRequested = Signal(int)
    refreshRequested = Signal()
    tourRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(264)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 26, 16, 18)
        layout.setSpacing(8)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(34))
        mark.setAccessibleName("Shokz Refill logo")
        brand_row.addWidget(mark)
        brand = QLabel("<b>SHOKZ</b> REFILL")
        brand.setObjectName("brand")
        brand_row.addWidget(brand, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(24)
        device_row = QHBoxLayout()
        device_row.setSpacing(10)
        headphones = QLabel()
        headphones.setPixmap(icon("headphones").pixmap(26, 26))
        device_row.addWidget(headphones)
        self.device_name = QLabel()
        self.device_name.setTextFormat(Qt.TextFormat.PlainText)
        role(self.device_name, "strong")
        # One line, clipped rather than wrapped, so the row never changes height.
        self.device_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        device_row.addWidget(self.device_name, 1)
        self.refresh = QPushButton()
        self.refresh.setIcon(icon("refresh", ACCENT))
        self.refresh.setFixedSize(30, 30)
        self.refresh.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.refresh.setToolTip("Refresh connected devices")
        self.refresh.setAccessibleName("Refresh connected devices")
        role(self.refresh, "quiet")
        self.refresh.clicked.connect(self.refreshRequested)
        device_row.addWidget(self.refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(device_row)
        self.storage = QProgressBar()
        self.storage.setRange(0, 100)
        self.storage.setTextVisible(False)
        self.storage.setAccessibleName("Device storage used")
        layout.addWidget(self.storage)
        self.device_status = QLabel()
        self.device_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        role(self.device_status, "caption")
        layout.addWidget(self.device_status)
        layout.addSpacing(18)
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.pageRequested)
        self.buttons: list[QPushButton] = []
        for index, (name, glyph) in enumerate(PAGES):
            button = NavButton(name)
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(23, 23))
            button.setToolTip(f"{name} (Alt+{index + 1})")
            button.setShortcut(f"Alt+{index + 1}")
            role(button, "nav")
            self.group.addButton(button, index)
            self.buttons.append(button)
            if index == TRANSFERS_PAGE:
                layout.addStretch()
                self._add_transfer_indicator(button)
            if index == SETTINGS_PAGE:
                divider = QFrame()
                divider.setObjectName("sidebarDivider")
                divider.setFixedHeight(1)
                layout.addSpacing(4)
                layout.addWidget(divider)
                layout.addSpacing(4)
                self.tour_button = QPushButton("Guided tour")
                self.tour_button.setIcon(icon("help"))
                self.tour_button.setIconSize(QSize(23, 23))
                self.tour_button.setToolTip("Show the guided tour again")
                self.tour_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                role(self.tour_button, "nav")
                self.tour_button.clicked.connect(self.tourRequested)
                layout.addWidget(self.tour_button)
            layout.addWidget(button)
        self.set_page(0)
        self.set_device(None)

    def _add_transfer_indicator(self, button: QPushButton) -> None:
        """Live queue state on the Transfers entry, visible from every page."""
        row = QHBoxLayout(button)
        row.setContentsMargins(0, 0, 12, 0)
        row.addStretch()
        self.transfer_indicator = TransferIndicator()
        row.addWidget(self.transfer_indicator)

    def set_transfers(self, active: int, percent: int, failed: int, total: int) -> None:
        if not total:
            state, summary = "idle", "No transfers"
        elif active:
            state, summary = "active", f"{active} active · {percent}%"
        elif failed:
            state, summary = "failed", f"{failed} failed"
        else:
            state, summary = "done", "All transfers finished"
        if failed and active:
            summary += f" · {failed} failed"
        self.transfer_indicator.set_state(state, percent)
        button = self.buttons[TRANSFERS_PAGE]
        button.setToolTip(f"Transfers (Alt+{TRANSFERS_PAGE + 1}) — {summary}")
        button.setAccessibleDescription(summary)

    def set_page(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def set_device(self, device: Device | None) -> None:
        if device is None:
            self.device_name.setText("No Shokz connected")
            self.device_status.setText("Choose a device in Shokz files")
            self.device_name.setToolTip("")
            self.storage.setValue(0)
            self.storage.setToolTip("No device selected")
        else:
            self.device_name.setText(device.name)
            self.device_name.setToolTip(str(device.root))
            self.device_status.setText(
                f"{device.free / 1024**3:.1f} GiB free of {device.total / 1024**3:.1f} GiB"
            )
            self.storage.setValue(round(100 * device.used / device.total) if device.total else 0)
            self.storage.setToolTip(
                f"{device.used / 1024**3:.1f} / {device.total / 1024**3:.1f} GiB used"
            )
