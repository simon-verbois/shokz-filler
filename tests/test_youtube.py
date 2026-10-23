from pathlib import Path
from typing import Any

import pytest
import requests

from shokz_refill import youtube
from shokz_refill.youtube import YouTubeMusicService, map_playlist, map_track


class FakeClient:
    def search(
        self, query: str, filter: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if filter == "songs":
            return [
                {
                    "videoId": "v1",
                    "title": "Song",
                    "artists": [{"name": "Artist"}],
                    "duration_seconds": "61",
                }
            ]
        return [{"playlistId": "PL1", "title": "Mix", "count": "2"}]

    def get_playlist(self, playlistId: str, limit: int | None = 100) -> dict[str, Any]:
        return {"tracks": [{"videoId": "v2", "title": "Inside", "artists": []}]}

    def get_library_playlists(self, limit: int | None = 25) -> list[dict[str, Any]]:
        return [{"playlistId": "PL2", "title": "Mine"}]

    def get_account_info(self) -> dict[str, Any]:
        return {"accountName": "Tester"}


def test_mapping_and_mocked_service(tmp_path: Path) -> None:
    service = YouTubeMusicService(tmp_path / "auth.json", client=FakeClient())
    song = service.search_songs("query")[0]
    assert song.video_id == "v1" and song.artist == "Artist" and song.duration_seconds == 61
    assert service.search_playlists("query")[0].playlist_id == "PL1"
    assert service.library_playlists()[0].title == "Mine"
    assert service.playlist_tracks("PL1")[0].video_id == "v2"
    assert map_track({"title": "missing"}) is None
    assert map_playlist({"browseId": "VLPL3", "title": "Browse"}).playlist_id == "PL3"  # type: ignore[union-attr]


def test_connected_service_uses_authentication_for_private_playlist(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    service = YouTubeMusicService(auth_path)
    authenticated = FakeClient()
    service._auth_client = authenticated

    assert service.playlist_tracks("private-playlist")[0].video_id == "v2"


def test_expired_saved_session_can_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    service = YouTubeMusicService(auth_path)

    class ExpiredClient(FakeClient):
        def get_account_info(self) -> dict[str, Any]:
            raise KeyError("private-cookie-do-not-display")

    service._auth_client = ExpiredClient()
    assert service.authenticated and not service.connection_verified
    with pytest.raises(PermissionError, match="paste fresh request headers") as error:
        service.library_playlists()
    assert "private-cookie" not in str(error.value)
    assert not service.authenticated and not service.connection_verified
    assert auth_path.is_file()

    def setup(*, filepath: str, headers_raw: str) -> None:
        Path(filepath).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(youtube.ytmusicapi, "setup", setup)
    monkeypatch.setattr(youtube, "YTMusic", lambda *args, **kwargs: FakeClient())
    assert service.connect_headers("fresh fake headers") == "Tester"
    assert service.connection_verified
    assert service.library_playlists()[0].title == "Mine"


def test_network_timeout_keeps_saved_session(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    service = YouTubeMusicService(auth_path)

    class OfflineClient(FakeClient):
        def get_account_info(self) -> dict[str, Any]:
            raise requests.Timeout("request timed out")

    service._auth_client = OfflineClient()
    with pytest.raises(RuntimeError, match="Check your connection"):
        service.library_playlists()
    assert service.authenticated
    assert not service.connection_verified
    assert auth_path.is_file()


def test_malformed_saved_session_reports_reconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("not json", encoding="utf-8")
    service = YouTubeMusicService(auth_path)

    def invalid_client(*args: object, **kwargs: object) -> None:
        raise ValueError("malformed headers")

    monkeypatch.setattr(youtube, "YTMusic", invalid_client)
    with pytest.raises(PermissionError, match="Connect YouTube Music"):
        service.library_playlists()
    assert not service.authenticated


@pytest.mark.parametrize("status", [401, 403, 500])
def test_library_http_errors_distinguish_expired_session_from_server_failure(
    tmp_path: Path, status: int
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    service = YouTubeMusicService(auth_path)

    class HttpClient(FakeClient):
        def get_account_info(self) -> dict[str, Any]:
            response = requests.Response()
            response.status_code = status
            raise requests.HTTPError("private response details", response=response)

    service._auth_client = HttpClient()
    error_type = PermissionError if status in (401, 403) else RuntimeError
    with pytest.raises(error_type) as error:
        service.library_playlists()
    assert service.authenticated == (status == 500)
    assert "private response details" not in str(error.value)


def test_timeout_session_preserves_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[object] = []

    def request(*args: object, **kwargs: object) -> requests.Response:
        observed.append(kwargs["timeout"])
        response = requests.Response()
        response.status_code = 403
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    with pytest.raises(requests.HTTPError) as error:
        youtube.TimeoutSession().request("POST", "https://example.invalid/browse")
    assert observed == [15]
    assert error.value.response is not None and error.value.response.status_code == 403


def test_cancelled_network_task_never_starts_another_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from shokz_refill.cancellation import current_cancellation
    from shokz_refill.youtube import TimeoutSession

    event = threading.Event()
    event.set()
    token = current_cancellation.set(event)
    called: list[bool] = []
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: called.append(True))
    try:
        with pytest.raises(InterruptedError):
            TimeoutSession().get("https://unused.invalid")
        assert not called
    finally:
        current_cancellation.reset(token)


def test_cancelled_auth_initialization_keeps_saved_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    service = YouTubeMusicService(auth)

    def interrupted(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise InterruptedError("Cancelled")

    monkeypatch.setattr(youtube, "YTMusic", interrupted)
    with pytest.raises(InterruptedError):
        service.library_playlists()
    assert service.authenticated and auth.exists()
