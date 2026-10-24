import json
import os
import threading
from http.cookiejar import Cookie
from unittest.mock import Mock

import pytest
import requests
from yt_dlp.cookies import YoutubeDLCookieJar

from shokz_refill import browser_auth, youtube
from shokz_refill.browser_auth import BrowserSessionImporter, LoginBrowser
from shokz_refill.cancellation import current_cancellation
from shokz_refill.media import _download_auth_options
from shokz_refill.youtube import YouTubeMusicService

BROWSER = LoginBrowser("firefox", "Firefox", ("/usr/bin/firefox",))


def cookie(domain, name, value="secret", expires=None):
    return Cookie(
        0,
        name,
        value,
        None,
        False,
        domain,
        True,
        domain.startswith("."),
        "/",
        True,
        True,
        expires,
        expires is None,
        None,
        None,
        {},
    )


def jar(*cookies):
    result = YoutubeDLCookieJar()
    for item in cookies:
        result.set_cookie(item)
    return result


def test_only_cookies_for_music_are_imported_and_logs_suppressed(monkeypatch, capsys):
    def extract(key, logger, profile=None):
        assert key == "firefox"
        logger.warning("private cookie value")
        logger.error("private path")
        return jar(
            cookie(".youtube.com", "__Secure-3PAPISID", "youtube-secret"),
            cookie("music.youtube.com", "SID", "music-secret"),
            cookie(".google.com", "SID", "google-secret"),
            cookie("unrelated.invalid", "private", "other-secret"),
            cookie("evil.youtube.com", "evil", "evil-secret"),
            cookie(".youtube.com", "old", "expired-secret", expires=1),
        )

    monkeypatch.setattr(browser_auth, "extract_cookies_from_browser", extract)
    headers = BrowserSessionImporter().headers(BROWSER)
    assert "youtube-secret" in headers["cookie"]
    assert "music-secret" in headers["cookie"]
    assert all(
        value not in str(headers)
        for value in (
            "google-secret",
            "other-secret",
            "evil-secret",
            "expired-secret",
        )
    )
    assert headers["authorization"].startswith("SAPISIDHASH ")
    assert capsys.readouterr() == ("", "")


def test_missing_login_and_unreadable_browser_are_actionable(monkeypatch):
    monkeypatch.setattr(browser_auth, "extract_cookies_from_browser", lambda *a, **k: jar())
    with pytest.raises(ValueError, match="Sign in in a normal"):
        BrowserSessionImporter().headers(BROWSER)

    def locked(*args, **kwargs):
        raise PermissionError("private browser path and cookie value")

    monkeypatch.setattr(browser_auth, "extract_cookies_from_browser", locked)
    with pytest.raises(RuntimeError, match="Close that browser") as error:
        BrowserSessionImporter().headers(BROWSER)
    assert "private" not in str(error.value)


def test_import_can_be_cancelled_without_exposing_extractor_errors(monkeypatch):
    event = threading.Event()
    context = current_cancellation.set(event)

    def extract(*args, **kwargs):
        event.set()
        return jar(cookie(".youtube.com", "__Secure-3PAPISID"))

    monkeypatch.setattr(browser_auth, "extract_cookies_from_browser", extract)
    try:
        with pytest.raises(InterruptedError):
            BrowserSessionImporter().headers(BROWSER)
    finally:
        current_cancellation.reset(context)


def test_opens_exact_selected_browser_without_shell(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(browser_auth.subprocess, "Popen", popen)
    browser_auth.open_login(BROWSER)
    assert popen.call_args.args[0] == ["/usr/bin/firefox", browser_auth.MUSIC_URL]
    assert not popen.call_args.kwargs.get("shell")


def test_discovers_windows_installation_without_running_browsers(tmp_path, monkeypatch):
    firefox = tmp_path / "Mozilla Firefox/firefox.exe"
    firefox.parent.mkdir()
    firefox.touch()
    monkeypatch.setattr(browser_auth.sys, "platform", "win32")
    monkeypatch.setattr(browser_auth.shutil, "which", lambda name: None)
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path))
    assert browser_auth.available_browsers() == [
        LoginBrowser("firefox", "Firefox", (str(firefox),)),
    ]


def test_validated_import_is_saved_and_used_for_downloads(tmp_path, monkeypatch):
    auth = tmp_path / "browser.json"
    service = YouTubeMusicService(auth)
    headers = {"cookie": "__Secure-3PAPISID=secret", "authorization": "SAPISIDHASH value"}
    monkeypatch.setattr(BrowserSessionImporter, "headers", lambda *a: headers)
    client = Mock()
    client.get_account_info.return_value = {"accountName": "Tester"}
    monkeypatch.setattr(youtube, "YTMusic", lambda *a, **k: client)
    assert service.connect_browser(BROWSER) == "Tester"
    assert service.connection_verified
    assert json.loads(auth.read_text()) == headers
    if os.name != "nt":
        assert auth.stat().st_mode & 0o777 == 0o600
    options, path = _download_auth_options(auth, tmp_path / "download")
    assert path is not None
    assert "secret" in path.read_text()
    assert "http_headers" not in options  # Do not forward API authorization to media hosts.


@pytest.mark.parametrize(
    "failure", [ValueError("private"), requests.Timeout("private"), InterruptedError("cancelled")]
)
def test_failed_validation_keeps_previous_session(tmp_path, monkeypatch, failure):
    auth = tmp_path / "browser.json"
    auth.write_text("old-session")
    service = YouTubeMusicService(auth)
    original = Mock()
    service._auth_client = original
    monkeypatch.setattr(BrowserSessionImporter, "headers", lambda *a: {})
    candidate = Mock()
    candidate.get_account_info.side_effect = failure
    monkeypatch.setattr(youtube, "YTMusic", lambda *a, **k: candidate)
    with pytest.raises((ValueError, RuntimeError, InterruptedError)) as error:
        service.connect_browser(BROWSER)
    assert "private" not in str(error.value)
    assert auth.read_text() == "old-session"
    assert service._auth_client is original
    assert not list(tmp_path.glob("*.tmp"))


def test_real_ytmusic_recognizes_imported_headers(monkeypatch):
    monkeypatch.setattr(
        browser_auth,
        "extract_cookies_from_browser",
        lambda *a, **k: jar(
            cookie(".youtube.com", "__Secure-3PAPISID", "youtube-secret"),
        ),
    )
    # ytmusicapi retrieves a visitor ID while initializing authenticated clients.
    monkeypatch.setattr("ytmusicapi.ytmusic.get_visitor_id", lambda *a: {})
    headers = BrowserSessionImporter().headers(BROWSER)
    client = youtube.YTMusic(headers, requests_session=youtube.TimeoutSession())
    assert client.headers["authorization"].startswith("SAPISIDHASH ")
    assert client.sapisid == "youtube-secret"
