# Shokz Refill

Shokz Refill is a small desktop utility for finding music through YouTube Music and safely
loading compatible MP3 files onto Shokz headphones with onboard storage, including OpenSwim
Pro. It also imports existing local MP3 files and provides a focused browser for the selected
device.

The application searches songs and playlists, opens playlist tracks, loads account-library
playlists, downloads up to three tracks concurrently, and transfers them sequentially. Output is
always broadly compatible MP3: **CBR 192 kbps, 44.1 kHz, stereo, ID3v2.3**.

## Use

1. Connect or manually select the mounted Shokz volume. Automatically detected media is clearly
   labelled; manual selection is available for devices whose USB metadata cannot be recognized.
2. Browse to a folder and choose **Select destination folder**.
3. Search YouTube Music, or connect an account and select **My playlists**. Open a playlist,
   use the **<** and **>** buttons to navigate, then select tracks and choose
   **Download / transfer selected**.
4. To transfer an entire playlist, choose **Download whole playlist** (or use the playlist's
   right-click menu). Shokz Refill creates or reuses a folder that keeps the playlist's original
   capitalization and spaces, such as `My Running Mix`, below the selected destination.
5. Watch download, conversion, and transfer progress in the queue. Failed items can be retried and
   active or queued items can be cancelled.

For songs selected outside a playlist, Shokz Refill always asks for a destination using its in-app
folder tree. Choose an existing folder or create a new one in the dialog; downloading directly to
the device root is intentionally disabled.

The device browser can create, rename, move, and recursively delete folders; rename, move, or delete MP3s;
and add local MP3 files. `System Volume Information` is hidden. Moves support multi-selection:
drag selected items onto a visible folder, or use **Move selected…** to choose a destination from
the in-app folder tree. Moves remain inside the selected device. Recursive deletes require explicit
confirmation and do not follow symbolic links outside the device. Name
collisions get a deterministic numbered name and never overwrite an existing file. Interrupted
transfers remain visibly marked as `.part` and resume only when the cached source fingerprint still
matches.

Names created by Shokz Refill keep readable Unicode letters, numbers, spaces, hyphens and
underscores. Other punctuation, emoji, control characters and filesystem-reserved characters are
removed consistently from MP3 and folder names.

Right-click menus expose the relevant actions for YouTube results, Shokz files/folders, and queue
items without duplicating unrelated file-manager features.

Tables are read-only. Double-clicking a playlist opens it; double-clicking a song downloads it.
Songs opened from a playlist use that playlist's automatic destination folder. In the Shokz file
browser, **<** and **>** move backward and forward through visited folders.

## YouTube Music authentication

Public search does not require a login. To show your library playlists, click **Connect YouTube
Music** and follow the in-app steps: while signed in at `music.youtube.com`, copy the request
headers from an authenticated `/browse` POST request in the browser developer tools and paste them
into the dialog. This is the current browser-header flow supported by ytmusicapi and needs no
Shokz Refill server.

The resulting browser session data remains in your per-user configuration directory with owner-only
permissions (`~/.config/shokz-refill` on Linux or `%APPDATA%\shokz-refill` on Windows). For
downloads, cookies are scoped to YouTube through a short-lived cookie file instead of being sent as
a global HTTP header. Credentials are never logged. **Disconnect** removes the stored session
locally. Logging out of YouTube can invalidate it.

Shokz Refill does not bypass DRM. Downloads work only where yt-dlp can legitimately access the
source. You are responsible for having the rights or authorization to download and transfer media.

## Linux / Fedora

Run the portable build by extracting `Shokz-Refill-linux-x86_64.tar.gz` and launching
`Shokz-Refill/shokz-refill`. Device discovery uses `lsblk`; manual folder selection works on any
mounted volume.

For development:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m shokz_refill
```

Build and verify:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
scripts/fetch_ffmpeg_linux.sh
.venv/bin/python -m PyInstaller --noconfirm --clean shokz-refill.spec
```

## Windows

Install 64-bit Python 3.12 only on the build machine, then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The resulting zip under `dist` includes Python, PySide6, yt-dlp with its EJS scripts, Deno,
dependencies, ffmpeg and ffprobe.
Windows must be built natively; the Linux build cannot cross-compile it.

## ffmpeg distribution

Build scripts bundle an ffmpeg build that includes `libmp3lame`, so end users do not need a system
installation. The Linux fetch script uses the GPLv3 static builds published by John Van Sickle; the
Windows script uses Gyan's GPL essentials build. ffmpeg is a separate bundled executable and is
redistributed under its applicable GPL terms. Distributors should retain the build's license/source
notices and provide the corresponding source offer/link; see <https://ffmpeg.org/legal.html> and the
binary distributor's accompanying documentation. Shokz Refill's own source is MIT licensed.

## Known limitations

- Automatic detection intentionally ignores unrecognized removable drives; use manual selection for
  Shokz volumes with unusual labels or USB metadata.
- Empty folders only can be deleted, reducing the risk of accidental recursive loss.
- YouTube and YouTube Music can change access behavior; authentication may need to be reconnected,
  and some content is unavailable to yt-dlp.
- A portable build is native to its operating system and CPU architecture.

## Screenshot

No screenshot is included in this source release.
