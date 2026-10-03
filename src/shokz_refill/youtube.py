from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, cast

import requests
import ytmusicapi
from ytmusicapi import YTMusic

from .models import Playlist, Track


class TimeoutSession(requests.Session):
    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:  # type: ignore[override]
        kwargs.setdefault("timeout", 15)
        return super().request(method, url, **kwargs)


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

    @property
    def authenticated(self) -> bool:
        return self._client is not None or self.auth_path.is_file()

    def _public(self) -> YTMusicClient:
        if self._client is not None:
            return self._client
        if self._public_client is None:
            self._public_client = cast(YTMusicClient, YTMusic(requests_session=TimeoutSession()))
        return self._public_client

    def _authenticated(self) -> YTMusicClient:
        if self._client is not None:
            return self._client
        if not self.auth_path.is_file():
            raise PermissionError("Connect YouTube Music first")
        if self._auth_client is None:
            self._auth_client = cast(
                YTMusicClient,
                YTMusic(str(self.auth_path), requests_session=TimeoutSession()),
            )
        return self._auth_client

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
            temporary.replace(self.auth_path)
            self._auth_client = cast(YTMusicClient, client)
            name = str(info.get("accountName") or info.get("channelHandle") or "Connected")
            return name
        except Exception:
            temporary.unlink(missing_ok=True)
            raise ValueError("The YouTube Music headers are invalid or expired") from None

    def disconnect(self) -> None:
        self._client = None
        self._auth_client = None
        self.auth_path.unlink(missing_ok=True)

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
        return [
            playlist
            for item in self._authenticated().get_library_playlists(limit=None)
            if (playlist := map_playlist(item))
        ]

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        data = self._public().get_playlist(playlist_id, limit=None)
        return [track for item in data.get("tracks") or [] if (track := map_track(item))]
