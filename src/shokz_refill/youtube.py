from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import requests
import ytmusicapi
from ytmusicapi import OAuthCredentials, YTMusic

from .browser_auth import BrowserSessionImporter, LoginBrowser
from .cancellation import check_cancelled
from .models import Playlist, Track
from .youtube_oauth import DeviceCode, GoogleDeviceAuth, OAuthClient, save_private_json


class TimeoutSession(requests.Session):
    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:  # type: ignore[override]
        check_cancelled()
        kwargs.setdefault("timeout", 15)
        response = super().request(method, url, **kwargs)
        check_cancelled()
        response.raise_for_status()
        return response


class YTMusicClient(Protocol):
    def search(
        self, query: str, filter: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]: ...
    def get_playlist(self, playlistId: str, limit: int | None = 100) -> dict[str, Any]: ...
    def get_library_playlists(self, limit: int | None = 25) -> list[dict[str, Any]]: ...
    def get_account_info(self) -> dict[str, Any]: ...


def _artists(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(value.get("name", "")) for value in item.get("artists") or [] if value.get("name")
    )


def map_track(item: dict[str, Any]) -> Track | None:
    video_id = str(item.get("videoId") or "")
    if not video_id:
        return None
    duration = item.get("duration_seconds")
    if duration is None:
        duration = item.get("durationSeconds")
    try:
        seconds = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        seconds = None
    album_data = item.get("album") or {}
    return Track(
        video_id=video_id,
        title=str(item.get("title") or "Untitled"),
        artists=_artists(item),
        album=str(album_data.get("name") or ""),
        duration_seconds=seconds,
    )


def map_playlist(item: dict[str, Any]) -> Playlist | None:
    playlist_id = str(item.get("playlistId") or item.get("browseId") or "")
    if playlist_id.startswith("VL"):
        playlist_id = playlist_id[2:]
    if not playlist_id:
        return None
    return Playlist(
        playlist_id, str(item.get("title") or "Untitled playlist"), str(item.get("count") or "")
    )


class YouTubeMusicService:
    def __init__(self, auth_path: Path, client: YTMusicClient | None = None) -> None:
        self.auth_path = auth_path
        self._client = client
        self._public_client: YTMusicClient | None = None
        self._auth_client: YTMusicClient | None = None
        self._auth_invalid = False
        self._auth_verified = False

    @property
    def authenticated(self) -> bool:
        return self._client is not None or (not self._auth_invalid and self.auth_path.is_file())

    @property
    def connection_verified(self) -> bool:
        return self._client is not None or (self.authenticated and self._auth_verified)

    def _invalid_session(self) -> PermissionError:
        self._auth_invalid = True
        self._auth_verified = False
        self._auth_client = None
        return PermissionError(
            "The saved YouTube Music session could not be validated; it may be invalid or expired. "
            "Click Connect YouTube Music to sign in again, "
            "or use Advanced to paste fresh request headers."
        )

    def _public(self) -> YTMusicClient:
        if self._client is not None:
            return self._client
        if self._public_client is None:
            self._public_client = cast(YTMusicClient, YTMusic(requests_session=TimeoutSession()))
        return self._public_client

    def _authenticated(self) -> YTMusicClient:
        if self._client is not None:
            return self._client
        if self._auth_invalid:
            raise self._invalid_session()
        if not self.auth_path.is_file():
            raise PermissionError("Connect YouTube Music first")
        if self._auth_client is None:
            try:
                raw = json.loads(self.auth_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("shokz_oauth") == 1:
                    self._auth_client = self._oauth_client(
                        OAuthClient(raw["client_id"], raw["client_secret"]), raw["token"]
                    )
                else:
                    self._auth_client = cast(
                        YTMusicClient,
                        YTMusic(str(self.auth_path), requests_session=TimeoutSession()),
                    )
            except InterruptedError:
                raise
            except Exception:
                raise self._invalid_session() from None
        return self._auth_client

    def oauth_settings(self) -> OAuthClient:
        """Load local client settings; environment variables can provision installations."""
        try:
            raw = json.loads(self.auth_path.with_name("oauth-client.json").read_text("utf-8"))
            client = OAuthClient(str(raw["client_id"]), str(raw["client_secret"]))
        except (OSError, ValueError, KeyError, TypeError):
            client = OAuthClient("", "")
        return OAuthClient(
            os.environ.get("SHOKZ_YOUTUBE_CLIENT_ID", client.client_id),
            os.environ.get("SHOKZ_YOUTUBE_CLIENT_SECRET", client.client_secret),
        )

    @staticmethod
    def _oauth_client(client: OAuthClient, token: dict[str, Any]) -> YTMusicClient:
        session = TimeoutSession()
        return cast(
            YTMusicClient,
            YTMusic(
                dict(token),
                oauth_credentials=OAuthCredentials(client.client_id, client.client_secret, session),
                requests_session=session,
            ),
        )

    def connect_oauth(self, client: OAuthClient, show_code: Callable[[DeviceCode], None]) -> str:
        """Authorize and validate a replacement without disturbing the previous session."""
        client.validate()
        save_private_json(
            self.auth_path.with_name("oauth-client.json"),
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
            },
        )
        token = GoogleDeviceAuth().authorize(client, show_code)
        try:
            authenticated = self._oauth_client(client, token)
            info = authenticated.get_account_info()
        except InterruptedError:
            raise
        except Exception:
            raise ValueError(
                "Google authorization succeeded, but YouTube Music could not validate the account. "
                "Try again or use Advanced browser headers."
            ) from None
        save_private_json(
            self.auth_path,
            {
                "shokz_oauth": 1,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "token": token,
            },
        )
        self._auth_client = authenticated
        self._auth_invalid = False
        self._auth_verified = True
        return str(info.get("accountName") or info.get("channelHandle") or "Connected")

    def connect_browser(self, browser: LoginBrowser) -> str:
        """Validate the selected browser's session before replacing saved credentials."""
        headers = BrowserSessionImporter().headers(browser)
        try:
            client = YTMusic(headers, requests_session=TimeoutSession())
            info = client.get_account_info()
        except InterruptedError:
            raise
        except (requests.Timeout, requests.ConnectionError):
            raise RuntimeError(
                "Could not reach YouTube Music. Check your connection and try again."
            ) from None
        except Exception:
            raise ValueError(
                "YouTube Music could not validate this session. Sign in again in the selected "
                "browser, or try Firefox. If you use several Google accounts, sign in with "
                "the account you want as the browser's first Google account."
            ) from None
        save_private_json(self.auth_path, headers)
        self._auth_client = cast(YTMusicClient, client)
        self._auth_invalid = False
        self._auth_verified = True
        return str(info.get("accountName") or info.get("channelHandle") or "Connected")

    def connect_headers(self, raw_headers: str) -> str:
        if not raw_headers.strip():
            raise ValueError("No request headers were pasted")
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.auth_path.with_suffix(".tmp")
        try:
            ytmusicapi.setup(filepath=str(temporary), headers_raw=raw_headers)
            os.chmod(temporary, 0o600)
            client = YTMusic(str(temporary), requests_session=TimeoutSession())
            info = client.get_account_info()
            check_cancelled()
            temporary.replace(self.auth_path)
            self._auth_client = cast(YTMusicClient, client)
            self._auth_invalid = False
            self._auth_verified = True
            name = str(info.get("accountName") or info.get("channelHandle") or "Connected")
            return name
        except InterruptedError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception:
            temporary.unlink(missing_ok=True)
            raise ValueError("The YouTube Music headers are invalid or expired") from None

    def disconnect(self) -> None:
        self._client = None
        self._auth_client = None
        self._auth_invalid = False
        self._auth_verified = False
        self.auth_path.unlink(missing_ok=True)
        self.auth_path.with_name("oauth-client.json").unlink(missing_ok=True)

    def search_songs(self, query: str) -> list[Track]:
        return [
            track
            for item in self._public().search(query, filter="songs", limit=40)
            if (track := map_track(item))
        ]

    def search_playlists(self, query: str) -> list[Playlist]:
        return [
            playlist
            for item in self._public().search(query, filter="playlists", limit=40)
            if (playlist := map_playlist(item))
        ]

    def library_playlists(self) -> list[Playlist]:
        client = self._authenticated()
        try:
            if not self.connection_verified:
                client.get_account_info()
            items = client.get_library_playlists(limit=None)
            playlists = [playlist for item in items if (playlist := map_playlist(item))]
        except (requests.Timeout, requests.ConnectionError):
            raise RuntimeError(
                "Could not reach YouTube Music. Check your connection and try My playlists again."
            ) from None
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                raise self._invalid_session() from None
            raise RuntimeError(
                "YouTube Music is temporarily unavailable. Try again later."
            ) from None
        except InterruptedError:
            raise
        except Exception:
            raise self._invalid_session() from None
        self._auth_verified = True
        return playlists

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        client = self._authenticated() if self.authenticated else self._public()
        try:
            data = client.get_playlist(playlist_id, limit=None)
        except InterruptedError:
            raise
        except Exception:
            message = "Could not load this playlist from YouTube Music"
            if self.authenticated:
                message += ". Your connection may have expired; disconnect and reconnect it"
            raise RuntimeError(message) from None
        return [track for item in data.get("tracks") or [] if (track := map_track(item))]
