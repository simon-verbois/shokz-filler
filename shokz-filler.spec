# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
package = root / "src" / "shokz_filler"
binaries = []
runtime_names = (
    ("ffmpeg.exe", "ffprobe.exe", "deno.exe")
    if sys.platform == "win32"
    else ("ffmpeg", "ffprobe", "deno")
)
for name in runtime_names:
    candidate = package / "bin" / name
    if candidate.exists():
        binaries.append((str(candidate), "shokz_filler/bin"))

datas = copy_metadata("yt-dlp") + copy_metadata("ytmusicapi") + copy_metadata("piper-tts")
datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
datas.append((str(package / "voices"), "shokz_filler/voices"))
datas.append((str(root / "CHANGELOG.md"), "shokz_filler"))
ffmpeg_license = package / "bin" / "FFMPEG-GPLv3.txt"
if ffmpeg_license.exists():
    datas.append((str(ffmpeg_license), "shokz_filler/bin"))
deno_license = package / "bin" / "DENO-LICENSE.md"
if deno_license.exists():
    datas.append((str(deno_license), "shokz_filler/bin"))
hiddenimports = []
for license_path in (root / "third_party").glob("*.txt"):
    datas.append((str(license_path), "licenses"))

for dependency in ("yt_dlp", "yt_dlp_ejs", "ytmusicapi", "piper", "onnxruntime"):
    dep_datas, dep_bins, dep_hidden = collect_all(dependency)
    datas += dep_datas
    binaries += dep_bins
    hiddenimports += dep_hidden

a = Analysis(
    [str(root / "run_shokz_filler.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Shokz-Filler",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "assets" / "shokz-filler.ico") if sys.platform == "win32" else None,
)
