"""Fetch pinned Piper voice files for development and portable builds."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import requests


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "src" / "shokz_filler" / "voices"
    destination.mkdir(exist_ok=True)
    entries = json.loads(Path(__file__).with_name("tts-voices.json").read_text())
    for entry in entries:
        output = destination / entry["name"]
        if output.is_file():
            with output.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() == entry["sha256"]:
                    continue
        temporary = output.with_name(output.name + f".{uuid.uuid4().hex}.part")
        try:
            digest = hashlib.sha256()
            with requests.get(entry["url"], stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                with temporary.open("xb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError(f"Voice checksum mismatch: {output.name}")
            temporary.replace(output)
            print(f"Verified Piper voice file: {output.name}", flush=True)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
