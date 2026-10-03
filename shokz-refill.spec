# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
package = root / "src" / "shokz_refill"
binaries = []
for name in ("ffmpeg", "ffprobe", "deno", "ffmpeg.exe", "ffprobe.exe", "deno.exe"):
    candidate = package / "bin" / name
    if candidate.exists():
        binaries.append((str(candidate), "shokz_refill/bin"))

datas = copy_metadata("yt-dlp") + copy_metadata("ytmusicapi")
datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
ffmpeg_license = package / "bin" / "FFMPEG-GPLv3.txt"
if ffmpeg_license.exists():
    datas.append((str(ffmpeg_license), "shokz_refill/bin"))
deno_license = package / "bin" / "DENO-LICENSE.md"
if deno_license.exists():
    datas.append((str(deno_license), "shokz_refill/bin"))
hiddenimports = []
for dependency in ("yt_dlp", "yt_dlp_ejs", "ytmusicapi"):
    dep_datas, dep_bins, dep_hidden = collect_all(dependency)
    datas += dep_datas
    binaries += dep_bins
    hiddenimports += dep_hidden

a = Analysis(
    [str(root / "run_shokz_refill.py")],
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
    [],
    exclude_binaries=True,
    name="shokz-refill",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Shokz-Refill",
)
