"""Import a user-selected browser session without exposing browser internals to Qt."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp.cookies import extract_cookies_from_browser
from ytmusicapi.auth.browser import get_authorization
from ytmusicapi.helpers import initialize_headers

from .cancellation import check_cancelled

MUSIC_URL = "https://music.youtube.com/"


@dataclass(frozen=True)
class LoginBrowser:
    key: str
    label: str
    command: tuple[str, ...]
    profile: str | None = None


# executable names, Windows relative installation paths, Flatpak application ID
_BROWSERS = (
    ("firefox", "Firefox", ("firefox",), "Mozilla Firefox/firefox.exe", "org.mozilla.firefox"),
    (
        "chrome",
        "Chrome",
        ("google-chrome", "google-chrome-stable"),
        "Google/Chrome/Application/chrome.exe",
        "com.google.Chrome",
    ),
    (
        "edge",
        "Edge",
        ("microsoft-edge", "microsoft-edge-stable"),
        "Microsoft/Edge/Application/msedge.exe",
        "com.microsoft.Edge",
    ),
    (
        "brave",
        "Brave",
        ("brave-browser", "brave"),
        "BraveSoftware/Brave-Browser/Application/brave.exe",
        "com.brave.Browser",
    ),
    (
        "chromium",
        "Chromium",
        ("chromium", "chromium-browser"),
        "Chromium/Application/chrome.exe",
        "org.chromium.Chromium",
    ),
)


def available_browsers() -> list[LoginBrowser]:
    """Discover installed browsers in a worker, without reading their sessions."""
    result = []
    for key, label, executables, windows_path, flatpak_id in _BROWSERS:
        check_cancelled()
        command: tuple[str, ...] = ()
        profile = None
        for executable in executables:
            found = shutil.which(executable)
            if found:
                command = (found,)
                break
        if not command and sys.platform == "win32":
            for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                root = os.environ.get(variable)
                if root and (path := Path(root) / windows_path).is_file():
                    command = (str(path),)
                    break
        if not command and sys.platform.startswith("linux"):
            flatpak = shutil.which("flatpak")
            if flatpak and (Path.home() / ".var/app" / flatpak_id).is_dir():
                command = (flatpak, "run", flatpak_id)
                if key != "firefox":
                    relative = {
                        "chrome": "google-chrome",
                        "edge": "microsoft-edge",
                        "brave": "BraveSoftware/Brave-Browser",
                        "chromium": "chromium",
                    }[key]
                    profile = str(Path.home() / ".var/app" / flatpak_id / "config" / relative)
        if command:
            result.append(LoginBrowser(key, label, command, profile))
    return result


def open_login(browser: LoginBrowser) -> None:
    """Open the selected browser, ensuring import targets the same browser."""
    check_cancelled()
    try:
        subprocess.Popen(
            [*browser.command, MUSIC_URL],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise RuntimeError(
            f"Could not open {browser.label}. Open YouTube Music in that browser and sign in."
        ) from None


class _QuietCookieLogger:
    """Discard dependency logs which can contain private paths and cookie details."""

    def debug(self, *args: Any, **kwargs: Any) -> None:
        check_cancelled()

    info = debug
    warning = debug
    error = debug


class BrowserSessionImporter:
    def headers(self, browser: LoginBrowser) -> dict[str, str]:
        """Read cookies locally; return only cookies sent to YouTube Music."""
        check_cancelled()
        try:
            jar = extract_cookies_from_browser(
                browser.key, profile=browser.profile, logger=_QuietCookieLogger()
            )
            # CookieJar applies domain, path, secure and expiration rules. Never persist
            # or forward Google login cookies or cookies belonging to unrelated sites.
            request = urllib.request.Request(MUSIC_URL)
            jar.add_cookie_header(request)
            cookie_header = request.get_header("Cookie") or ""
            cookies = dict(
                part.strip().split("=", 1) for part in cookie_header.split(";") if "=" in part
            )
            sapisid = cookies.get("__Secure-3PAPISID")
        except InterruptedError:
            raise
        except Exception:
            raise RuntimeError(
                f"Could not read the {browser.label} session. Close that browser and try again. "
                "If it still fails, use Firefox or the advanced connection method."
            ) from None
        check_cancelled()
        if not sapisid:
            raise ValueError(
                f"No YouTube Music login found in {browser.label}. Sign in in a normal "
                "browser window (not private browsing), then try again."
            )
        headers: dict[str, str] = dict(initialize_headers())
        headers.update(
            {
                "cookie": cookie_header,
                "authorization": get_authorization(sapisid + " https://music.youtube.com"),
                "origin": "https://music.youtube.com",
                "x-origin": "https://music.youtube.com",
                "x-goog-authuser": "0",
                "accept": "*/*",
                "content-type": "application/json",
            }
        )
        return headers
