from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import yt_dlp

from .metadata import validate_mp3, write_metadata
from .models import Track

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]
_SAFE_DOWNLOAD_HEADERS = {"accept-language", "user-agent"}


def bundled_binary(name: str) -> Path:
    executable = name + (".exe" if sys.platform == "win32" else "")
    configured = os.environ.get("SHOKZ_REFILL_FFMPEG_DIR")
    roots = [
        Path(configured) if configured else Path("/__not_configured__"),
        Path(__file__).resolve().parent / "bin",
        Path(sys.executable).resolve().parent / "bin",
        Path(sys.executable).resolve().parent / "_internal" / "shokz_refill" / "bin",
    ]
    for root in roots:
        candidate = root / executable
        if candidate.is_file():
            return candidate
    system = shutil_which(executable)
    if system:
        return Path(system)
    raise FileNotFoundError(f"Bundled {executable} was not found")


def shutil_which(name: str) -> str | None:
    # Isolated to make binary lookup easy to test/patch.
    from shutil import which

    return which(name)


class DownloadCancelled(Exception):
    pass


def _download_auth_options(
    auth_path: Path, work_dir: Path
) -> tuple[dict[str, object], Path | None]:
    try:
        raw = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}, None
    if not isinstance(raw, dict):
        return {}, None

    headers: dict[str, str] = {}
    cookie_header = ""
    for key, value in raw.items():
        name = str(key)
        if name.casefold() == "cookie":
            cookie_header = str(value)
        elif name.casefold() in _SAFE_DOWNLOAD_HEADERS:
            headers[name] = str(value)

    options: dict[str, object] = {}
    if headers:
        options["http_headers"] = headers
    if not cookie_header:
        return options, None

    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name and not any(character in name + value for character in "\r\n\t"):
            cookies[name] = value
    if not cookies:
        return options, None

    work_dir.mkdir(parents=True, exist_ok=True)
    cookie_path = work_dir / "youtube-cookies.txt"
    temporary = cookie_path.with_suffix(".tmp")
    lines = ["# Netscape HTTP Cookie File", "# Created locally by Shokz Refill"]
    lines.extend(
        f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}" for name, value in cookies.items()
    )
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(cookie_path)
    options["cookiefile"] = str(cookie_path)
    return options, cookie_path


class MediaDownloader:
    def __init__(self, auth_path: Path | None = None) -> None:
        self.auth_path = auth_path

    def download(
        self, track: Track, work_dir: Path, progress: Progress, cancelled: Cancelled
    ) -> Path:
        if cancelled():
            raise DownloadCancelled("Download cancelled")
        work_dir.mkdir(parents=True, exist_ok=True)
        template = str(work_dir / "source.%(ext)s")

        def hook(data: dict[str, object]) -> None:
            if cancelled():
                raise DownloadCancelled("Download cancelled")
            if data.get("status") == "downloading":
                raw_downloaded = data.get("downloaded_bytes")
                raw_total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = int(raw_downloaded) if isinstance(raw_downloaded, (str, int)) else 0
                total = int(raw_total) if isinstance(raw_total, (str, int)) else 0
                if total:
                    progress(min(99, int(downloaded * 100 / total)))

        options: dict[str, object] = {
            "format": "bestaudio/best",
            "outtmpl": template,
            "noplaylist": True,
            "continuedl": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 10,
            "retries": 2,
            "extractor_retries": 1,
            "progress_hooks": [hook],
            "ffmpeg_location": str(bundled_binary("ffmpeg").parent),
            "js_runtimes": {"deno": {"path": str(bundled_binary("deno"))}},
        }
        cookie_path: Path | None = None
        if self.auth_path and self.auth_path.is_file():
            auth_options, cookie_path = _download_auth_options(self.auth_path, work_dir)
            options.update(auth_options)
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(track.url, download=True)
                prepared = Path(downloader.prepare_filename(info))
                if cancelled():
                    raise DownloadCancelled("Download cancelled")
        except DownloadCancelled:
            raise
        except Exception as exc:
            if cancelled():
                raise DownloadCancelled("Download cancelled") from None
            raise RuntimeError(f"Download failed: {exc}") from None
        finally:
            if cookie_path is not None:
                cookie_path.unlink(missing_ok=True)
        progress(100)
        if prepared.exists():
            return prepared
        candidates = [
            p for p in work_dir.glob("source.*") if not p.name.endswith((".part", ".ytdl"))
        ]
        if not candidates:
            raise RuntimeError("Download completed but its audio file was not found")
        return max(candidates, key=lambda path: path.stat().st_mtime)


class AudioConverter:
    def convert(
        self, source: Path, output: Path, track: Track, progress: Progress, cancelled: Cancelled
    ) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".encoding.mp3")
        command = [
            str(bundled_binary("ffmpeg")),
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-id3v2_version",
            "3",
            str(temporary),
        ]
        try:
            run_process(command, cancelled)
            if cancelled():
                raise DownloadCancelled("Conversion cancelled")
            progress(90)
            write_metadata(
                temporary,
                source_id=track.video_id,
                artist=track.artist,
                title=track.title,
                album=track.album,
            )
            validate_mp3(temporary)
            if cancelled():
                raise DownloadCancelled("Conversion cancelled")
            temporary.replace(output)
            progress(100)
            return output
        finally:
            temporary.unlink(missing_ok=True)


def run_process(
    command: list[str], cancelled: Cancelled, *, poll: Callable[[], None] | None = None
) -> None:
    """Drain errors to a temporary file and always reap the child on cancellation."""
    if cancelled():
        raise DownloadCancelled("Conversion cancelled")
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors
        )
        try:
            while True:
                if cancelled():
                    raise DownloadCancelled("Conversion cancelled")
                try:
                    code = process.wait(timeout=0.1)
                    if poll is not None:
                        poll()
                    break
                except subprocess.TimeoutExpired:
                    if poll is not None:
                        poll()
                    continue
            if code:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 4096))
                detail = errors.read().decode("utf-8", errors="replace").strip().splitlines()
                raise RuntimeError("ffmpeg failed" + (f": {detail[-1]}" if detail else ""))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
