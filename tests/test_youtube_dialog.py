import threading
import time

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QWidget

from shokz_refill import youtube_dialog
from shokz_refill.browser_auth import LoginBrowser
from shokz_refill.cancellation import check_cancelled, current_cancellation
from shokz_refill.youtube import YouTubeMusicService
from shokz_refill.youtube_dialog import AuthDialog

BROWSER = LoginBrowser("firefox", "Firefox", ("firefox",))


@pytest.fixture(autouse=True)
def browsers(monkeypatch):
    monkeypatch.setattr(youtube_dialog, "available_browsers", lambda: [BROWSER])


def spin(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def test_google_dialog_runs_auth_off_ui_thread_and_accepts(qt_application, tmp_path, monkeypatch):
    service = YouTubeMusicService(tmp_path / "browser.json")
    threads = []
    opened = []
    monkeypatch.setattr(
        youtube_dialog,
        "open_login",
        lambda browser: opened.append((browser, QThread.currentThread())),
    )

    def authorize(browser):
        threads.append(QThread.currentThread())
        assert browser == BROWSER
        return "Tester"

    monkeypatch.setattr(service, "connect_browser", authorize)
    owner = QWidget()
    dialog = AuthDialog(service, owner)
    dialog.show()
    spin(qt_application, lambda: dialog.start_button.isEnabled())
    dialog.open_button.click()
    spin(qt_application, lambda: dialog.start_button.isEnabled())
    dialog.start_button.click()
    spin(qt_application, lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.account_name == "Tester"
    assert threads[0] != qt_application.thread()
    assert opened[0][0] == BROWSER
    assert opened[0][1] != qt_application.thread()
    spin(qt_application, lambda: dialog.tasks.idle)


def test_cancel_remains_responsive_and_retains_workers(qt_application, tmp_path, monkeypatch):
    service = YouTubeMusicService(tmp_path / "browser.json")
    started = threading.Event()

    def authorize(browser):
        started.set()
        event = current_cancellation.get()
        assert event is not None
        assert event.wait(3)
        check_cancelled()

    monkeypatch.setattr(service, "connect_browser", authorize)
    owner = QWidget()
    dialog = AuthDialog(service, owner)
    dialog.show()
    spin(qt_application, lambda: dialog.start_button.isEnabled())
    dialog.start_button.click()
    spin(qt_application, started.is_set)
    assert not dialog.browsers.isEnabled()
    assert started.is_set()
    dialog.reject()
    spin(qt_application, lambda: dialog.tasks.idle)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not service.auth_path.exists()


def test_advanced_headers_retry_preserves_input(qt_application, tmp_path, monkeypatch):
    service = YouTubeMusicService(tmp_path / "browser.json")
    calls = []

    def headers(raw):
        calls.append(raw)
        if len(calls) == 1:
            raise ValueError("The headers expired")
        return "Tester"

    monkeypatch.setattr(service, "connect_headers", headers)
    owner = QWidget()
    dialog = AuthDialog(service, owner)
    dialog.show()
    spin(qt_application, lambda: dialog.start_button.isEnabled())
    dialog.advanced_toggle.click()
    dialog.headers.setPlainText("fake headers")
    dialog.headers_button.click()
    spin(qt_application, lambda: "expired" in dialog.feedback.text())
    assert dialog.headers.toPlainText() == "fake headers"
    assert dialog.headers_button.isEnabled()
    dialog.headers_button.click()
    spin(qt_application, lambda: dialog.result() == QDialog.DialogCode.Accepted)
    spin(qt_application, lambda: dialog.tasks.idle)
    assert calls == ["fake headers", "fake headers"]


def test_returning_from_browser_connects_without_extra_click(qt_application, tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QLineEdit

    service = YouTubeMusicService(tmp_path / "browser.json")
    calls = []
    monkeypatch.setattr(
        service, "connect_browser", lambda browser: calls.append(browser) or "Tester"
    )
    owner = QWidget()
    dialog = AuthDialog(service, owner)
    dialog.show()
    spin(qt_application, lambda: dialog.start_button.isEnabled())
    assert not dialog.findChildren(QLineEdit)  # No client ID, client secret or password fields.
    assert not dialog.advanced.isVisible()
    dialog._waiting_for_browser = True
    monkeypatch.setattr(dialog, "isActiveWindow", lambda: True)
    dialog.changeEvent(QEvent(QEvent.Type.ActivationChange))
    spin(qt_application, lambda: dialog.result() == QDialog.DialogCode.Accepted)
    spin(qt_application, lambda: dialog.tasks.idle)
    assert calls == [BROWSER]
