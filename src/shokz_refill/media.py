from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import yt_dlp

from .metadata import validate_mp3, write_metadata
from .models import Track

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]


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


class MediaDownloader:
    def __init__(self, auth_path: Path | None = None) -> None:
        self.auth_path = auth_path

    def download(
        self, track: Track, work_dir: Path, progress: Progress, cancelled: Cancelled
    ) -> Path:
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
            "progress_hooks": [hook],
            "ffmpeg_location": str(bundled_binary("ffmpeg").parent),
            "js_runtimes": {"deno": {"path": str(bundled_binary("deno"))}},
        }
        if self.auth_path and self.auth_path.is_file():
            try:
                headers = json.loads(self.auth_path.read_text(encoding="utf-8"))
                if isinstance(headers, dict):
                    options["http_headers"] = {
                        str(key): str(value) for key, value in headers.items()
                    }
            except (OSError, ValueError, TypeError):
                pass
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(track.url, download=True)
                prepared = Path(downloader.prepare_filename(info))
        except DownloadCancelled:
            raise
        except Exception as exc:
            if cancelled():
                raise DownloadCancelled("Download cancelled") from None
            raise RuntimeError(f"Download failed: {exc}") from None
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
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
        )
        while process.poll() is None:
            if cancelled():
                process.terminate()
                process.wait(timeout=5)
                temporary.unlink(missing_ok=True)
                raise DownloadCancelled("Conversion cancelled")
            threading.Event().wait(0.1)
        if process.returncode:
            detail = (process.stderr.read() if process.stderr else "").strip().splitlines()
            temporary.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg failed" + (f": {detail[-1]}" if detail else ""))
        progress(90)
        write_metadata(
            temporary,
            source_id=track.video_id,
            artist=track.artist,
            title=track.title,
            album=track.album,
        )
        validate_mp3(temporary)
        temporary.replace(output)
        progress(100)
        return output
