"""Cancellable Google device authorization, independent of Qt."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from .cancellation import check_cancelled, current_cancellation

CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube"


def save_private_json(path: Path, data: dict[str, Any]) -> None:
    """Replace a local credential file only after a complete, flushed write."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        check_cancelled()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, repr=False)
class OAuthClient:
    client_id: str
    client_secret: str

    def validate(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Enter both the Google OAuth client ID and client secret.")


@dataclass(frozen=True, repr=False)
class DeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    expires_at: float
    interval: float


def _wait(seconds: float) -> None:
    event = current_cancellation.get()
    if event is None:
        time.sleep(seconds)
    else:
        event.wait(seconds)
    check_cancelled()


class GoogleDeviceAuth:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        check_cancelled()
        try:
            response = self.session.post(url, data=data, timeout=15)
            check_cancelled()
            payload = response.json()
            if response.status_code >= 500:
                raise RuntimeError("Google sign-in is temporarily unavailable. Try again later.")
            if not isinstance(payload, dict):
                raise ValueError
            if response.status_code >= 400 and "error" not in payload:
                raise ValueError
            return payload
        except (requests.RequestException, ValueError):
            raise RuntimeError(
                "Could not contact Google sign-in. Check your connection and try again."
            ) from None

    def authorize(
        self, client: OAuthClient, show_code: Callable[[DeviceCode], None]
    ) -> dict[str, Any]:
        client.validate()
        raw = self._post(CODE_URL, {"client_id": client.client_id, "scope": SCOPE})
        if "error" in raw:
            raise ValueError(
                "Google rejected the OAuth client. Check its ID, enable YouTube Data API v3, "
                "and use a client of type TVs and Limited Input devices."
            )
        try:
            url = str(raw.get("verification_url") or raw["verification_uri"])
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {"www.google.com", "google.com", "accounts.google.com"}
                or parsed.username
                or parsed.password
            ):
                raise ValueError
            code = DeviceCode(
                str(raw["device_code"]),
                str(raw["user_code"]),
                url,
                time.monotonic() + max(1, min(float(raw["expires_in"]), 1800)),
                max(5, min(float(raw.get("interval", 5)), 1800)),
            )
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Google returned an invalid sign-in code. Try again.") from None
        check_cancelled()
        show_code(code)
        interval = code.interval
        while True:
            remaining = code.expires_at - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The Google sign-in code expired. Start again for a new code.")
            _wait(min(interval, remaining))
            if time.monotonic() >= code.expires_at:
                raise TimeoutError("The Google sign-in code expired. Start again for a new code.")
            token = self._post(
                TOKEN_URL,
                {
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
                    "device_code": code.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            error = token.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error in ("access_denied", "authorization_declined"):
                raise PermissionError("Google sign-in was declined. You can try again.")
            if error == "expired_token":
                raise TimeoutError("The Google sign-in code expired. Start again for a new code.")
            if error:
                raise ValueError(
                    "Google sign-in failed. Check the OAuth client settings and retry."
                )
            try:
                result = {
                    key: token[key]
                    for key in (
                        "access_token",
                        "refresh_token",
                        "scope",
                        "token_type",
                        "expires_in",
                    )
                }
                result["expires_at"] = int(time.time()) + int(result["expires_in"])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("Google returned an incomplete session. Try again.") from None
            check_cancelled()
            return result
