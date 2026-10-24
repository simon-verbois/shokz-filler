"""Frameless dialogs in the application's own style: title bar, message and text prompts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .theme import role


class _DialogTitleBar(QWidget):
    def __init__(self, dialog: QDialog, title: str) -> None:
        super().__init__()
        self._dialog = dialog
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 4, 8, 0)
        self.label = QLabel(title)
        role(self.label, "section")
        layout.addWidget(self.label, 1)
        close = QPushButton()
        close.setIcon(icon("close"))
        close.setFixedSize(34, 28)
        close.setToolTip("Close")
        close.setAccessibleName("Close")
        close.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        role(close, "window")
        close.setProperty("danger", True)
        close.clicked.connect(dialog.reject)
        layout.addWidget(close)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        handle = self._dialog.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class ThemedDialog(QDialog):
    """Put widgets in `self.content`; the frame, rounded corners and title bar are provided."""

    def __init__(self, parent: QWidget | None, title: str) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("dialogFrame")
        outer.addWidget(frame)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        self._title_bar = _DialogTitleBar(self, title)
        inner.addWidget(self._title_bar)
        self.content = QWidget()
        inner.addWidget(self.content, 1)
        super().setWindowTitle(title)

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 - Qt override
        super().setWindowTitle(title)
        if hasattr(self, "_title_bar"):
            self._title_bar.label.setText(title)


class _Prompt(ThemedDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        *,
        accept: str,
        reject: str | None,
        destructive: bool = False,
        field: str | None = None,
    ) -> None:
        super().__init__(parent, title)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(18, 8, 18, 16)
        layout.setSpacing(12)
        message = QLabel(text)
        message.setWordWrap(True)
        message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(message)
        self.field: QLineEdit | None = None
        if field is not None:
            self.field = QLineEdit(field)
            self.field.selectAll()
            self.field.setAccessibleName(title)
            layout.addWidget(self.field)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        cancel = None
        if reject is not None:
            cancel = QPushButton(reject)
            role(cancel, "quiet")
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
        ok = QPushButton(accept)
        role(ok, "danger" if destructive else "primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addLayout(row)
        # A destructive question opens on the safe answer.
        default = cancel if destructive and cancel is not None else ok
        default.setDefault(True)
        default.setFocus()
        if self.field is not None:
            self.field.setFocus()


class MessageDialog:
    @staticmethod
    def question(
        parent: QWidget | None, title: str, text: str, *, destructive: bool = False
    ) -> bool:
        return (
            _Prompt(
                parent,
                title,
                text,
                accept="Delete" if destructive else "Yes",
                reject="Cancel",
                destructive=destructive,
            ).exec()
            == QDialog.DialogCode.Accepted
        )

    @staticmethod
    def warning(parent: QWidget | None, title: str, text: str) -> None:
        _Prompt(parent, title, text, accept="OK", reject=None).exec()


class InputDialog:
    @staticmethod
    def getText(  # noqa: N802 - mirrors QInputDialog.getText
        parent: QWidget | None, title: str, label: str, text: str = ""
    ) -> tuple[str, bool]:
        prompt = _Prompt(parent, title, label, accept="OK", reject="Cancel", field=text)
        accepted = prompt.exec() == QDialog.DialogCode.Accepted
        return (prompt.field.text() if prompt.field else "", accepted)
