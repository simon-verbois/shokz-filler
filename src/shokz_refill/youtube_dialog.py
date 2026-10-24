"""A browser login followed by a local session import; no developer setup required."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .background import TaskRunner
from .browser_auth import LoginBrowser, available_browsers, open_login
from .theme import RoundedComboBox, role
from .themed_dialog import ThemedDialog
from .youtube import YouTubeMusicService


class AuthDialog(ThemedDialog):
    def __init__(self, service: YouTubeMusicService, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Connect YouTube Music")
        self.service = service
        # Keep workers alive while a cancelled request winds down after closing.
        self.tasks = TaskRunner(parent or self)
        self.account_name = ""
        self._busy = False
        self._waiting_for_browser = False
        self.setWindowTitle("Connect YouTube Music")
        self.resize(560, 450)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(18, 8, 18, 16)
        title = QLabel("Sign in with your browser")
        role(title, "section")
        layout.addWidget(title)
        description = QLabel(
            "Open YouTube Music and sign in as usual. Come back here to finish connecting. "
            "If you're already signed in, connect directly."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.browsers = RoundedComboBox()
        self.browsers.setEnabled(False)
        form.addRow("&Browser", self.browsers)
        layout.addLayout(form)
        self.open_button = QPushButton("Open YouTube Music")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_browser)
        layout.addWidget(self.open_button)
        self.start_button = QPushButton("I'm signed in — Connect")
        role(self.start_button, "primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._connect_browser)
        layout.addWidget(self.start_button)
        privacy = QLabel(
            "Connecting imports your YouTube session from the selected browser onto this "
            "computer. Only YouTube cookies are saved. Your password is never requested. "
            "The browser’s main Google account is used."
        )
        privacy.setWordWrap(True)
        privacy.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        role(privacy, "muted")
        layout.addWidget(privacy)
        self.feedback = QLabel("Finding your browsers…")
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.feedback)

        self.advanced_toggle = QPushButton("Advanced connection options")
        role(self.advanced_toggle, "quiet")
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        instructions = QLabel(
            "If browser import is unavailable: sign in at music.youtube.com, open Developer "
            "Tools → Network, select a /browse POST request and copy its request headers."
        )
        instructions.setWordWrap(True)
        advanced_layout.addWidget(instructions)
        self.headers = QTextEdit()
        self.headers.setAccessibleName("YouTube Music request headers")
        self.headers.setPlaceholderText("Paste request headers here…")
        advanced_layout.addWidget(self.headers)
        self.headers_button = QPushButton("Connect using browser headers")
        self.headers_button.clicked.connect(self._start_headers)
        advanced_layout.addWidget(self.headers_button)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tasks.start(available_browsers, self._browsers_loaded, self._failed)

    def _browsers_loaded(self, browsers: list[LoginBrowser]) -> None:
        for browser in browsers:
            self.browsers.addItem(browser.label, browser)
        self._set_busy(False)
        if browsers:
            self.feedback.setText(
                "Ready. Sign in in a normal browser window, not a private window."
            )
            self.open_button.setFocus()
        else:
            self.feedback.setText(
                "No supported browser found. Install Firefox, Chrome, Edge, Brave or Chromium, "
                "then reopen this window."
            )

    def _browser(self) -> LoginBrowser | None:
        value = self.browsers.currentData()
        return value if isinstance(value, LoginBrowser) else None

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        browser_available = self._browser() is not None
        self.start_button.setEnabled(not busy and browser_available)
        self.open_button.setEnabled(not busy and browser_available)
        self.browsers.setEnabled(not busy and browser_available)
        self.headers_button.setEnabled(not busy)
        self.headers.setEnabled(not busy)
        self.advanced_toggle.setEnabled(not busy)

    def _open_browser(self) -> None:
        browser = self._browser()
        if self._busy or browser is None:
            return
        self._set_busy(True)
        self.feedback.setText(f"Opening {browser.label}…")
        self.tasks.start(
            lambda: open_login(browser), self._browser_opened, self._failed, key="auth"
        )

    def _browser_opened(self, _value: object) -> None:
        self._set_busy(False)
        self._waiting_for_browser = True
        self.feedback.setText("Sign in to YouTube Music, then come back here to connect.")
        self.start_button.setFocus()

    def _connect_browser(self) -> None:
        browser = self._browser()
        if self._busy or browser is None:
            return
        self._waiting_for_browser = False
        self._set_busy(True)
        self.feedback.setText(f"Connecting with your {browser.label} session…")
        self.tasks.start(
            lambda: self.service.connect_browser(browser),
            self._connected,
            self._failed,
            key="auth",
        )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ActivationChange
            and self.isActiveWindow()
            and self.isVisible()
            and self._waiting_for_browser
            and not self._busy
        ):
            self._waiting_for_browser = False
            QTimer.singleShot(0, self._connect_browser)

    def _start_headers(self) -> None:
        if self._busy:
            return
        raw = self.headers.toPlainText()
        if not raw.strip():
            self.feedback.setText("Paste your browser request headers first.")
            return
        self._set_busy(True)
        self.feedback.setText("Validating your YouTube Music account…")
        self.tasks.start(
            lambda: self.service.connect_headers(raw),
            self._connected,
            self._failed,
            key="auth",
        )

    def _connected(self, name: str) -> None:
        self.account_name = name
        self.accept()

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.feedback.setText(message)

    def done(self, result: int) -> None:
        self._waiting_for_browser = False
        self.tasks.shutdown()
        super().done(result)
