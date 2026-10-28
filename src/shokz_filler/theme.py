"""Shared native desktop palette, typography and control styling."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QListWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

BACKGROUND = "#0b1119"
SURFACE = "#1b222c"
TEXT = "#eef3f8"
MUTED = "#a4b0c0"
ACCENT = "#32d4cf"
ON_ACCENT = "#071b25"  # text and icons drawn on accent-coloured buttons

STYLE = """
QWidget { color: #eef3f8; font-size: 13px; }
QDialog { background: #0b1119; }
QMainWindow, QWidget#workspace, QWidget#windowShell { background: transparent; }
QFrame#windowFrame { background: #0b1119; border: none; border-radius: 12px; }
QFrame#windowFrame[maximized="true"] { border-radius: 0; }
QWidget#titleBar { background: transparent; }
QFrame#dialogFrame { background: #0b1119; border: 1px solid #2b3441; border-radius: 12px; }
QPushButton[role="window"] {
    background: transparent; border: none; border-radius: 6px; padding: 0;
}
QPushButton[role="window"]:hover { background: #2b3441; }
QPushButton[role="window"][danger="true"]:hover { background: #b3404f; }
QPushButton[role="window"]:focus { border: 2px solid #32d4cf; }
QWidget#sidebar {
    background: #191e27; border: none;
    border-top-left-radius: 12px; border-bottom-left-radius: 12px;
}
QWidget#sidebar[maximized="true"] { border-radius: 0; }
QFrame#sidebarDivider { background: #2a313d; border: none; }
QWidget#sidebar QLabel { background: transparent; border: none; }
QLabel[role="muted"] { color: #a4b0c0; }
QLabel[role="caption"] { color: #a4b0c0; font-size: 11px; }
QLabel[role="title"] { font-size: 22px; font-weight: 600; }
QLabel[role="section"] { font-size: 15px; font-weight: 600; }
QLabel[role="badge"] {
    background: #245863; color: #eef3f8; border-radius: 9px; padding: 1px 8px; font-size: 11px;
}
QLabel[role="badge-alert"] {
    background: #6b2d3a; color: #ffd6dc; border-radius: 9px; padding: 1px 8px; font-size: 11px;
}
QLabel#brand { font-size: 23px; letter-spacing: 1px; }
QFrame[role="card"] {
    background: #191f29; border: 1px solid #303845; border-radius: 12px;
}
QPushButton {
    background: #252d39; border: 1px solid #354050; border-radius: 8px;
    padding: 5px 11px; min-height: 20px;
}
QPushButton::menu-indicator { image: none; width: 0; }
QToolButton { background: transparent; border: none; padding: 0; min-height: 0; }
QPushButton:hover, QToolButton:hover { background: #313d4b; border-color: #637387; }
QPushButton:pressed, QToolButton:pressed { background: #3b495a; }
QPushButton:disabled, QToolButton:disabled {
    color: #7e8b9c; background: #171e28; border-color: #2b3441;
}
QPushButton:focus, QToolButton:focus, QComboBox:focus, QSpinBox:focus,
QLineEdit:focus, QPlainTextEdit:focus {
    border: 2px solid #32d4cf;
}
QPushButton[role="primary"] {
    color: #071b25; font-weight: 600; border: 1px solid #40d9d3;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #25d7c5,stop:1 #40abf5);
    padding: 5px 14px;
}
QPushButton[role="primary"]:hover { background: #66e0e1; }
QPushButton[role="primary"]:focus { border: 2px solid #eef3f8; }
QPushButton[role="primary"]:disabled { color: #879aaa; background: #233642; border-color: #364b58; }
QPushButton[role="danger"] { color: #ffafba; }
QPushButton[role="nav"] {
    background: transparent; border: 2px solid transparent; text-align: left;
    font-size: 13px; padding: 7px 12px; min-height: 22px;
}
QPushButton[role="nav"]:hover { background: #232c38; }
QPushButton[role="nav"]:checked { background: #2b3441; }
QPushButton[role="nav"]:focus { border-color: #32d4cf; }
QPushButton[role="footnote"] {
    background: transparent; border-color: transparent; color: #a4b0c0;
    font-size: 11px; padding: 2px 8px; min-height: 0;
}
QPushButton[role="footnote"]:hover { background: #283440; color: #eef3f8; }
QPushButton[role="footnote"]:focus { border: 1px solid #32d4cf; }
QPushButton[role="quiet"] { background: transparent; border-color: transparent; }
QPushButton[role="quiet"]:hover { background: #283440; }
QPushButton[role="quiet"]:focus { border-color: #32d4cf; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: #191f29; border: 1px solid #354050; border-radius: 8px;
    padding: 6px 10px; selection-background-color: #245863; selection-color: #ffffff;
}
QLineEdit:disabled, QComboBox:disabled { color: #7e8b9c; border-color: #28313e; }
QComboBox::drop-down { border: none; width: 25px; }
QListWidget#optionList { background: transparent; border: none; outline: none; }
QListWidget#optionList::item {
    padding: 0 10px; min-height: 30px; border-radius: 7px; margin: 1px 0;
}
QListWidget#optionList::item:hover { background: #313d4b; }
QListWidget#optionList::item:selected { background: #245863; }
QCheckBox { spacing: 9px; padding: 5px 0; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #465265; border-radius: 5px;
    background: #191f29;
}
QCheckBox::indicator:checked { background: #32d4cf; border-color: #32d4cf; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
QCheckBox:focus { color: #58e2dc; }
QTabWidget::pane { border: 0; background: transparent; }
QListWidget[role="wizardList"] {
    background: #101722; border: 1px solid #2b3441; border-radius: 8px; padding: 4px; outline: none;
}
QListWidget[role="wizardList"]::item { padding: 9px 10px; border-radius: 6px; }
QListWidget[role="wizardList"]::item:hover { background: #1b2430; }
QListWidget[role="wizardList"]::item:selected { background: #245863; color: #ffffff; }
QTableWidget, QTreeWidget {
    background: transparent; alternate-background-color: #161e29; border: 1px solid transparent;
    gridline-color: transparent; selection-background-color: #253e4a;
    selection-color: #ffffff; outline: none;
}
QTableWidget::item { padding: 6px 10px; border: none; }
QTableWidget::item:selected { background: #253e4a; }
QTableWidget::item:focus { border: 1px solid #32d4cf; }
QTableWidget[library="true"] { selection-background-color: transparent; }
QTableWidget[library="true"]::item, QTableWidget[library="true"]::item:selected,
QTableWidget[library="true"]::item:hover { background: transparent; padding: 0; border: none; }
QTableWidget[library="true"]::item:focus { border: none; }
QPushButton[role="rowbutton"] {
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
    background: #2d3846; border: 1px solid #465265; border-radius: 8px; padding: 0;
}
QPushButton[role="rowbutton"]:hover { background: #3a4859; border-color: #637387; }
QPushButton[role="rowbutton"]:focus { border: 2px solid #32d4cf; }
QLabel[role="strong"] { font-weight: 600; }
QHeaderView { background: transparent; }
QHeaderView::section {
    color: #a4b0c0; background: #111923; border: none;
    border-bottom: 1px solid #2a3441; padding: 10px; text-align: left;
}
QTableCornerButton::section { background: #111923; border: none; }
QProgressBar {
    background: #293945; border: none; border-radius: 3px;
    min-height: 6px; max-height: 6px; text-align: center;
}
QProgressBar::chunk {
    border-radius: 3px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #2bd4bd,stop:1 #3db4ef);
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a4859; min-height: 30px; border-radius: 5px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #3a4859; min-width: 30px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: transparent; height: 12px; }
QSplitter::handle:hover { background: #293945; }
QStatusBar { color: #a4b0c0; background: transparent; font-size: 11px; }
QStatusBar::item { border: 0; }
QMenu, QToolTip {
    color: #eef3f8; background: #252d39; border: 1px solid #4b596c;
    border-radius: 6px; padding: 6px;
}
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #245863; }
QMenu::item:disabled { color: #7e8b9c; }
QMenu::separator { height: 1px; background: #465364; margin: 5px; }
"""


class _HandCursorOnButtons(QObject):
    """Give every button and drop-down, including ones created later, the pointing-hand cursor."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Polish and isinstance(watched, QAbstractButton | QComboBox):
            watched.setCursor(Qt.CursorShape.PointingHandCursor)
        return False


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    hand_cursor = _HandCursorOnButtons(app)
    app.installEventFilter(hand_cursor)
    font = QFont("Segoe UI" if sys.platform == "win32" else "Noto Sans", 10)
    app.setFont(font)
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BACKGROUND),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, BACKGROUND),
        (QPalette.ColorRole.AlternateBase, SURFACE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, SURFACE),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, "#245863"),
        (QPalette.ColorRole.HighlightedText, TEXT),
        (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.ToolTipBase, SURFACE),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#7e8b9c"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


def role(widget: QWidget, value: str) -> None:
    widget.setProperty("role", value)


def polish_table(table: QTableWidget, height: int = 58) -> None:
    table.setShowGrid(False)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(height)
    table.setAlternatingRowColors(False)
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


class _OptionPopup(QFrame):
    """Rounded dropdown list painted by hand, so it never depends on the platform's popup frame."""

    optionChosen = Signal(int)
    ROW_HEIGHT = 32
    PADDING = 5
    MAX_ROWS = 8

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("optionPopup")
        self.options = QListWidget(self)
        self.options.setObjectName("optionList")
        self.options.setFrameShape(QFrame.Shape.NoFrame)
        self.options.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.options.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([self.PADDING] * 4))
        layout.addWidget(self.options)
        self.options.itemClicked.connect(
            lambda item: self.optionChosen.emit(self.options.row(item))
        )
        self.options.itemActivated.connect(
            lambda item: self.optionChosen.emit(self.options.row(item))
        )

    def populate(self, labels: list[str], current: int) -> None:
        self.options.clear()
        self.options.addItems(labels)
        self.options.setCurrentRow(max(current, 0))

    def fit(self, minimum_width: int) -> None:
        """Size the popup to its content: longest label wide, one row tall per option."""
        count = self.options.count()
        row_height = max(self.options.sizeHintForRow(0), self.ROW_HEIGHT) if count else 0
        list_height = min(count, self.MAX_ROWS) * row_height + 4
        metrics = self.options.fontMetrics()
        text_width = max(
            (metrics.horizontalAdvance(self.options.item(row).text()) for row in range(count)),
            default=0,
        )
        self.options.setFixedHeight(list_height)
        self.setFixedSize(
            max(minimum_width, text_width + 48 + 2 * self.PADDING),
            list_height + 2 * self.PADDING,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#4b596c"), 1))
        painter.setBrush(QColor("#252d39"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.optionChosen.emit(self.options.currentRow())
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            self.options.setFocus()
            QApplication.sendEvent(self.options, event)


class RoundedComboBox(QComboBox):
    """Combo box with a rounded dropdown, used everywhere for a consistent look."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup = _OptionPopup(self)
        self._popup.optionChosen.connect(self._choose)

    def showPopup(self) -> None:
        if not self.count():
            return
        popup = self._popup
        popup.populate([self.itemText(index) for index in range(self.count())], self.currentIndex())
        popup.fit(self.width())
        popup.move(self.mapToGlobal(QPoint(0, self.height() + 4)))
        popup.show()
        popup.options.setFocus()

    def hidePopup(self) -> None:
        self._popup.close()

    def _choose(self, index: int) -> None:
        self._popup.close()
        if 0 <= index < self.count():
            changed = index != self.currentIndex()
            self.setCurrentIndex(index)
            self.activated.emit(index)
            if changed:
                self.textActivated.emit(self.itemText(index))
