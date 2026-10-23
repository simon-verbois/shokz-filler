import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import requests

from shokz_refill.audiobook_models import (
    Audiobook,
    AudiobookshelfCredentials,
    AudioSource,
    Chapter,
    export_plan,
    map_book,
    server_url,
)
from shokz_refill.audiobook_settings import AudiobookshelfSettings
from shokz_refill.audiobookshelf import AudiobookshelfClient, Connection


def response(data=None, *, content: bytes = b"", status: int = 200):  # type: ignore[no-untyped-def]
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode() if data is not None else content
    result._content_consumed = True
    result.headers["Content-Length"] = str(len(result._content))
    return result


def item() -> dict:
    def track(index: int, name: str) -> dict:
        return {
            "index": index,
            "duration": 10,
            "contentUrl": f"/s/item/book/{name}",
            "metadata": {"filename": name, "relPath": name, "size": 12, "mtimeMs": 123},
        }

    return {
        "id": "book",
        "mediaType": "book",
        "media": {
            "metadata": {"title": "Title", "authors": [{"name": "Author"}]},
            "tracks": [track(2, "A.mp3"), track(1, "Z.m4b")],
            "chapters": [
                {"title": "One", "start": 0, "end": 15},
                {"title": "Two", "start": 15, "end": 20},
            ],
        },
        "libraryFiles": [{"ino": "new-inode", "metadata": {"relPath": "Z.m4b"}}],
    }


def test_merged_book_follows_server_order_instead_of_filenames() -> None:
    book = map_book(item(), expanded=True)
    assert [source.filename for source in book.sources] == ["Z.m4b", "A.mp3"]
    assert book.sources[0].download_path == "/api/items/book/file/new-inode/download"
    plan = export_plan(book)
    assert len(plan) == 1 and plan[0].filename == "Title.mp3"
    assert [(s.source_index, s.offset, s.duration) for s in plan[0].segments] == [
        (1, 0, 10),
        (2, 0, 10),
    ]


def test_merging_keeps_all_audio_even_if_chapters_overlap_or_have_gaps() -> None:
    book = map_book(item(), expanded=True)
    book = replace(book, chapters=(Chapter("Invalid", 0, 25), Chapter("Overlap", 5, 10)))
    merged = export_plan(book)[0]
    assert sum(segment.duration for segment in merged.segments) == 20


def test_duplicate_source_indices_are_rejected() -> None:
    book = map_book(item(), expanded=True)
    book = replace(book, sources=(book.sources[0], book.sources[0]))
    with pytest.raises(ValueError, match="ambiguous"):
        export_plan(book)


def test_book_folder_is_safe_unique_and_stable_across_sessions() -> None:
    book = Audiobook("id", "../CON:Title?", "Author/")
    first = book.folder_name("https://server")
    assert "/" not in first and ".." not in first
    assert first == book.folder_name("https://server")
    assert first != replace(book, item_id="different").folder_name("https://server")


def test_source_identity_changes_when_layout_or_source_revision_changes() -> None:
    book = map_book(item(), expanded=True)
    part = export_plan(book)[0]
    identity = part.source_id("https://server", book)
    assert identity != replace(part, segments=part.segments[:1]).source_id("https://server", book)
    modified = replace(book, sources=(replace(book.sources[0], modified="new"), book.sources[1]))
    assert identity != part.source_id("https://server", modified)


@pytest.mark.parametrize(
    "value",
    ["server.local", "file:///tmp/server", "https://u:p@server", "https://server/?token=secret"],
)
def test_invalid_server_url_is_rejected_without_request(value: str) -> None:
    with pytest.raises(ValueError):
        server_url(value)


def test_login_listing_and_search_use_bearer_header_not_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict]] = []

    def request(method, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((method, url, kwargs))
        if url.endswith("/login"):
            return response({"user": {"token": "secret-token", "permissions": {"download": True}}})
        if url.endswith("/libraries"):
            return response(
                {
                    "libraries": [
                        {"id": "books", "name": "Books", "mediaType": "book"},
                        {"id": "podcasts", "mediaType": "podcast"},
                    ]
                }
            )
        if url.endswith("/search"):
            return response({"book": [{"libraryItem": item()}]})
        return response({"results": [item()], "total": 75})

    monkeypatch.setattr(requests, "request", request)
    credentials = AudiobookshelfCredentials("https://server/abs/", "user", "secret-password")
    client = AudiobookshelfClient.login(credentials)
    assert client.libraries()[0].library_id == "books"
    assert client.books("books", page=1).total == 75
    assert client.books("books", query="Title").books[0].title == "Title"
    assert calls[2][2]["params"]["page"] == 1
    for _method, url, kwargs in calls[1:]:
        assert "secret" not in url
        assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
        assert kwargs["allow_redirects"] is False
    assert "secret" not in repr(credentials) and "secret" not in repr(client.connection)


@pytest.mark.parametrize(
    "path",
    [
        "https://elsewhere/audio",
        "//elsewhere/audio",
        "/../audio",
        "/%2e%2e/audio",
        "/audio?token=secret",
        "file:///audio",
    ],
)
def test_unsafe_download_urls_are_rejected(path: str) -> None:
    client = AudiobookshelfClient(Connection("https://server/abs", "u", "token"))
    with pytest.raises(ValueError):
        client._url(path)
    assert client._url("/s/item/id/audio") == "https://server/abs/s/item/id/audio"


def test_download_validates_size_and_retains_interrupted_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = AudiobookshelfClient(Connection("https://server", "u", "token"))
    monkeypatch.setattr(requests, "request", lambda *a, **k: response(content=b"audio"))
    source = AudioSource(1, "file.m4b", "/api/file", 1, size=10)
    output = tmp_path / "source.audio"
    with pytest.raises(OSError, match="incomplete"):
        client.download(source, output, lambda _: None, lambda: False)
    assert not output.exists()
    assert output.with_suffix(".audio.download.part").read_bytes() == b"audio"
    result = client.download(replace(source, size=5), output, lambda _: None, lambda: False)
    assert result.read_bytes() == b"audio"


def test_download_without_permission_never_requests_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = AudiobookshelfClient(Connection("https://server", "u", "token", can_download=False))

    def unexpected(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("No network request permitted")

    monkeypatch.setattr(requests, "request", unexpected)
    with pytest.raises(PermissionError):
        client.download(
            AudioSource(1, "a.mp3", "/file", 1), tmp_path / "a", lambda _: None, lambda: False
        )


def test_errors_do_not_include_response_body_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests, "request", lambda *a, **k: response(content=b"secret-password", status=401)
    )
    with pytest.raises(PermissionError) as error:
        AudiobookshelfClient.login(
            AudiobookshelfCredentials("https://server", "u", "secret-password")
        )
    assert "secret-password" not in str(error.value)


def test_settings_password_is_opt_in_private_and_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AudiobookshelfSettings(tmp_path / "audiobookshelf.json")
    credentials = AudiobookshelfCredentials("https://server", "user", "secret-password")
    store.save(credentials, remember_password=False)
    assert "secret-password" not in store.path.read_text()
    store.save(credentials, remember_password=True)
    assert store.load() == credentials
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o077 == 0
    monkeypatch.setenv("AUDIOBOOKSHELF_SERVER", "https://other")
    assert store.load().server == "https://other"
    store.forget()
    assert not store.path.exists()


def test_ebook_only_items_are_not_marked_downloadable() -> None:
    data = item()
    data["media"]["numTracks"] = 0
    assert not map_book(data).available


def test_environment_password_does_not_enable_implicit_password_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AudiobookshelfSettings(tmp_path / "audiobookshelf.json")
    store.save(AudiobookshelfCredentials("https://server", "user"), remember_password=False)
    monkeypatch.setenv("AUDIOBOOKSHELF_PASSWORD", "environment-secret")
    assert store.load().password == "environment-secret"
    assert not store.has_saved_password()


def test_cancelled_http_download_keeps_partial_out_of_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requests, "request", lambda *a, **k: response(content=b"audio"))
    client = AudiobookshelfClient(Connection("https://server", "u", "token"))
    stop = False

    def progress(value: int) -> None:
        nonlocal stop
        stop = True

    output = tmp_path / "source.audio"
    with pytest.raises(InterruptedError):
        client.download(AudioSource(1, "book.mp3", "/file", 1, 5), output, progress, lambda: stop)
    assert not output.exists()
    assert output.with_suffix(".audio.download.part").exists()
