"""Read-only Audiobookshelf API adapter. Secrets never enter URLs or error messages."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests

from .audiobook_models import (
    Audiobook,
    AudiobookshelfCredentials,
    AudioSource,
    BookPage,
    Library,
    map_book,
    server_url,
)
from .cancellation import check_cancelled

Cancelled = Callable[[], bool]
Progress = Callable[[int], None]


@dataclass(frozen=True)
class Connection:
    server: str
    username: str
    token: str = field(repr=False)
    can_download: bool = True


class AudiobookshelfClient:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @staticmethod
    def _response(method: str, url: str, *, token: str = "", **kwargs: Any) -> requests.Response:
        check_cancelled()
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            response = requests.request(
                method, url, headers=headers, timeout=(10, 20), allow_redirects=False, **kwargs
            )
        except requests.RequestException:
            raise ConnectionError(
                "Could not reach Audiobookshelf; check the server address and connection"
            ) from None
        try:
            check_cancelled()
        except InterruptedError:
            response.close()
            raise
        if response.status_code in {401, 403}:
            response.close()
            raise PermissionError(
                "Audiobookshelf rejected the credentials or download permission; reconnect"
            )
        if response.status_code == 404:
            response.close()
            raise FileNotFoundError("Audiobookshelf item or audio file was not found")
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            raise RuntimeError(f"Audiobookshelf returned HTTP {status}; check the server address")
        return response

    @classmethod
    def login(cls, credentials: AudiobookshelfCredentials) -> AudiobookshelfClient:
        server = server_url(credentials.server)
        if not credentials.username.strip() or not credentials.password:
            raise ValueError("Enter the Audiobookshelf username and password")
        with cls._response(
            "POST",
            server + "/login",
            json={
                "username": credentials.username,
                "password": credentials.password,
            },
        ) as response:
            try:
                data = response.json()
                user = data["user"]
                token = user.get("token") or user.get("accessToken") or data.get("accessToken")
                if not isinstance(token, str) or not token:
                    raise ValueError
                permissions = user.get("permissions") or {}
                return cls(
                    Connection(
                        server,
                        credentials.username,
                        token,
                        bool(permissions.get("download", False)),
                    )
                )
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ValueError("Invalid Audiobookshelf login response") from None

    def _json(self, path: str, **params: object) -> dict[str, Any]:
        with self._response(
            "GET", self._url(path), token=self.connection.token, params=params
        ) as response:
            try:
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError
                return value
            except ValueError:
                raise ValueError("Audiobookshelf returned an invalid response") from None

    def _url(self, path: str) -> str:
        parsed = urlsplit(path)
        base = urlsplit(self.connection.server)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ValueError("Unsafe Audiobookshelf download URL")
        if (
            (parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc))
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Unsafe Audiobookshelf download URL")
        clean = unquote(parsed.path)
        if any(part in {"..", "."} for part in clean.split("/")) or "\\" in clean:
            raise ValueError("Unsafe Audiobookshelf path")
        if parsed.netloc:
            if not parsed.path.startswith(base.path.rstrip("/") + "/"):
                raise ValueError("Download URL leaves the configured server path")
            return path
        if base.path and parsed.path.startswith(base.path + "/"):
            return f"{base.scheme}://{base.netloc}" + parsed.path
        return self.connection.server + "/" + parsed.path.lstrip("/")

    def libraries(self) -> tuple[Library, ...]:
        return tuple(
            Library(str(value["id"]), str(value.get("name") or "Books"))
            for value in self._json("/api/libraries").get("libraries", [])
            if value.get("mediaType") == "book"
        )

    def books(self, library_id: str, *, page: int = 0, query: str = "") -> BookPage:
        path = "/api/libraries/" + quote(library_id, safe="")
        if query.strip():
            data = self._json(path + "/search", q=query.strip(), limit=100)
            entries = data.get("book") or data.get("books") or []
            books = tuple(map_book(entry.get("libraryItem", entry)) for entry in entries)
            return BookPage(books, len(books), limit=max(1, len(books)))
        data = self._json(
            path + "/items",
            page=page,
            limit=50,
            minified=1,
            sort="media.metadata.title",
            collapseseries=0,
        )
        return BookPage(
            tuple(map_book(entry) for entry in data.get("results", [])),
            int(data.get("total", 0)),
            page,
        )

    def book(self, item_id: str) -> Audiobook:
        return map_book(
            self._json("/api/items/" + quote(item_id, safe=""), expanded=1), expanded=True
        )

    def download(
        self, source: AudioSource, output: Path, progress: Progress, cancelled: Cancelled
    ) -> Path:
        if not self.connection.can_download:
            raise PermissionError("This Audiobookshelf account cannot download audio")
        if cancelled():
            raise InterruptedError("Audiobook download cancelled")
        if source.size and shutil.disk_usage(output.parent).free < source.size:
            raise OSError("Not enough local cache space for this audiobook source")
        temporary = output.with_suffix(output.suffix + ".download.part")
        try:
            with self._response(
                "GET", self._url(source.download_path), token=self.connection.token, stream=True
            ) as response:
                if response.status_code != 200:
                    raise OSError("Audiobookshelf returned a partial download; retry it")
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/" in content_type or "json" in content_type:
                    raise ValueError("Audiobookshelf returned a page instead of an audio file")
                length = int(response.headers.get("Content-Length", 0))
                copied = 0
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 256):
                        if cancelled():
                            raise InterruptedError("Audiobook download cancelled")
                        check_cancelled()
                        if chunk:
                            handle.write(chunk)
                            copied += len(chunk)
                            if length or source.size:
                                progress(min(99, int(copied * 100 / (length or source.size))))
                    handle.flush()
                    os.fsync(handle.fileno())
                if cancelled():
                    raise InterruptedError("Audiobook download cancelled")
                if (
                    not copied
                    or (length and copied != length)
                    or (source.size and copied != source.size)
                ):
                    raise OSError("Audiobook download is incomplete; retry it")
            temporary.replace(output)
            progress(100)
            return output
        except requests.RequestException:
            raise ConnectionError(
                "Audiobook download interrupted; check the connection and retry"
            ) from None
