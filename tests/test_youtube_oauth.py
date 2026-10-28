import json
import os
import threading
from unittest.mock import Mock

import pytest
import requests

from shokz_filler import youtube, youtube_oauth
from shokz_filler.cancellation import current_cancellation
from shokz_filler.media import _download_auth_options
from shokz_filler.youtube import YouTubeMusicService
from shokz_filler.youtube_oauth import GoogleDeviceAuth, OAuthClient

CLIENT = OAuthClient("test-client", "private-secret")
CODE = {
    "device_code": "private-device-code",
    "user_code": "ABCD-EFGH",
    "verification_url": "https://www.google.com/device",
    "expires_in": 120,
    "interval": 5,
}
TOKEN = {
    "access_token": "private-access-token",
    "refresh_token": "private-refresh-token",
    "scope": youtube_oauth.SCOPE,
    "token_type": "Bearer",
    "expires_in": 3600,
}


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


@pytest.fixture
def fake_clock(monkeypatch):
    now = [100.0]
    waits = []

    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(youtube_oauth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(youtube_oauth, "_wait", wait)
    return waits


def test_pending_slow_down_and_success(fake_clock):
    session = Mock()
    session.post.side_effect = [
        response(CODE),
        response({"error": "authorization_pending"}, 428),
        response({"error": "slow_down"}, 400),
        response(TOKEN),
    ]
    shown = []
    token = GoogleDeviceAuth(session).authorize(CLIENT, shown.append)
    assert shown[0].user_code == "ABCD-EFGH"
    assert fake_clock == [5, 5, 10]
    assert token["refresh_token"] == TOKEN["refresh_token"]
    assert token["expires_at"] > 0
    calls = session.post.call_args_list
    assert calls[0].args == (youtube_oauth.CODE_URL,)
    assert calls[1].kwargs["data"]["device_code"] == CODE["device_code"]
    assert all(call.kwargs["timeout"] == 15 for call in calls)


@pytest.mark.parametrize(
    "error, expected, message",
    [
        ("access_denied", PermissionError, "declined"),
        ("expired_token", TimeoutError, "expired"),
        ("invalid_client", ValueError, "client settings"),
    ],
)
def test_google_errors_are_actionable_and_redacted(fake_clock, error, expected, message):
    session = Mock()
    session.post.side_effect = [
        response(CODE),
        response(
            {
                "error": error,
                "error_description": "private-secret",
            },
            400,
        ),
    ]
    with pytest.raises(expected, match=message) as caught:
        GoogleDeviceAuth(session).authorize(CLIENT, lambda code: None)
    assert "private-secret" not in str(caught.value)


def test_expiration_stops_polling(fake_clock):
    session = Mock()
    session.post.side_effect = [response({**CODE, "expires_in": 5})]
    with pytest.raises(TimeoutError, match="expired"):
        GoogleDeviceAuth(session).authorize(CLIENT, lambda code: None)
    assert session.post.call_count == 1


def test_cancellation_stops_before_token_request():
    session = Mock()
    session.post.return_value = response(CODE)
    event = threading.Event()
    context = current_cancellation.set(event)
    try:
        with pytest.raises(InterruptedError):
            GoogleDeviceAuth(session).authorize(CLIENT, lambda code: event.set())
        assert session.post.call_count == 1
    finally:
        current_cancellation.reset(context)


@pytest.mark.parametrize("url", ["http://www.google.com/device", "https://evil.invalid/device"])
def test_untrusted_verification_url_is_not_opened(url):
    session = Mock()
    session.post.return_value = response({**CODE, "verification_url": url})
    shown = []
    with pytest.raises(RuntimeError, match="invalid sign-in code"):
        GoogleDeviceAuth(session).authorize(CLIENT, shown.append)
    assert not shown


def test_network_failure_does_not_expose_request_details():
    session = Mock()
    session.post.side_effect = requests.Timeout("private-secret")
    with pytest.raises(RuntimeError, match="Check your connection") as caught:
        GoogleDeviceAuth(session).authorize(CLIENT, lambda code: None)
    assert "private-secret" not in str(caught.value)


def test_success_persists_reloadable_oauth_and_disconnects(tmp_path, monkeypatch):
    auth = tmp_path / "browser.json"
    auth.write_text('{"cookie": "old"}')
    service = YouTubeMusicService(auth)
    monkeypatch.setattr(GoogleDeviceAuth, "authorize", lambda *a: dict(TOKEN))
    observed = []
    client = Mock()
    client.get_account_info.return_value = {"accountName": "Tester"}
    client.get_library_playlists.return_value = []

    def construct(token, **kwargs):
        observed.append((token, kwargs))
        return client

    monkeypatch.setattr(youtube, "YTMusic", construct)
    assert service.connect_oauth(CLIENT, lambda code: None) == "Tester"
    assert service.connection_verified
    saved = json.loads(auth.read_text())
    assert saved["shokz_oauth"] == 1
    assert saved["token"] == TOKEN
    if os.name != "nt":
        assert auth.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))
    assert service.oauth_settings() == CLIENT
    reloaded = YouTubeMusicService(auth)
    assert reloaded.library_playlists() == []
    assert observed[-1][0] == TOKEN
    assert observed[-1][1]["oauth_credentials"].client_id == CLIENT.client_id
    # Only browser cookies can authenticate media downloads; never forward OAuth tokens.
    assert _download_auth_options(auth, tmp_path / "download") == ({}, None)
    reloaded.disconnect()
    assert not auth.exists()
    assert not (tmp_path / "oauth-client.json").exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_validation_failure_or_cancellation_preserves_previous_session(
    tmp_path, monkeypatch, cancel
):
    auth = tmp_path / "browser.json"
    original = '{"cookie":"old-session"}'
    auth.write_text(original)
    service = YouTubeMusicService(auth)
    previous = Mock()
    service._auth_client = previous
    monkeypatch.setattr(GoogleDeviceAuth, "authorize", lambda *a: dict(TOKEN))
    client = Mock()
    client.get_account_info.side_effect = (
        InterruptedError("cancelled") if cancel else ValueError("private-secret")
    )
    monkeypatch.setattr(service, "_oauth_client", lambda *a: client)
    with pytest.raises(InterruptedError if cancel else ValueError):
        service.connect_oauth(CLIENT, lambda code: None)
    assert auth.read_text() == original
    assert service._auth_client is previous
    assert not list(tmp_path.glob("*.tmp"))


def test_cancelled_write_preserves_existing_file(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text("old")
    event = threading.Event()
    event.set()
    context = current_cancellation.set(event)
    try:
        with pytest.raises(InterruptedError):
            youtube_oauth.save_private_json(path, {"new": "secret"})
        assert path.read_text() == "old"
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        current_cancellation.reset(context)


def test_real_ytmusic_adapter_refreshes_expired_token_without_network(tmp_path, monkeypatch):
    """Exercise ytmusicapi's actual OAuth recognition and refresh integration."""
    refreshed = []

    def request(self, method, url, **kwargs):
        refreshed.append(kwargs["data"])
        return response({**TOKEN, "access_token": "fresh-access"})

    monkeypatch.setattr(requests.Session, "request", request)
    expired = {**TOKEN, "expires_at": 1}
    client = YouTubeMusicService._oauth_client(CLIENT, expired)
    client.base_headers = {}
    # Accessing auth headers invokes the dependency's automatic refresh.
    assert client.headers["authorization"] == "Bearer fresh-access"
    assert refreshed[0]["refresh_token"] == TOKEN["refresh_token"]
