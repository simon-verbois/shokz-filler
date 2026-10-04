from pathlib import Path
from typing import Any

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
