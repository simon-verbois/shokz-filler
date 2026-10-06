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
2. Browse the device files as needed. Standalone search downloads ask for their own destination.
3. Search YouTube Music, or connect an account and select **My playlists**. Open a playlist,
   use the **<** and **>** buttons to navigate, then select tracks and choose
   **Download / transfer selected**.
4. To transfer an entire playlist, choose **Download whole playlist** (or use the playlist's
   right-click menu). Shokz Refill creates or reuses a folder that keeps the playlist's original
   capitalization and spaces, such as `My Running Mix`, directly at the device root.
5. Watch download, conversion, and transfer progress in the queue. Failed items can be retried and
   active or queued items can be cancelled.

Downloads, conversions, and device transfers use independent bounded worker pools. A conversion
therefore does not prevent the next track from downloading, while writes to removable storage stay
strictly sequential.

For songs selected outside a playlist, Shokz Refill always asks for a destination using its in-app
folder tree. The device root is hidden: choose an existing folder or create a new top-level folder
in the dialog. Downloading directly to the device root is intentionally disabled.

Click a YouTube Music result-column header to sort ascending; click it again for descending order.
Before the first click, search relevance order is preserved.

The device browser can create, rename, move, and recursively delete folders; rename, move, or delete MP3s;
and add local MP3 files. `System Volume Information` is hidden. Moves support multi-selection:
drag selected items onto a visible folder, or use **Move selected…** to choose a destination from
the in-app folder tree. Folders remain flat at the device root and cannot be nested; MP3 files can
be moved into a folder. Moves remain inside the selected device. Recursive deletes require explicit
confirmation and do not follow symbolic links outside the device. Name
collisions get a deterministic numbered name and never overwrite an existing file. Interrupted
transfers remain visibly marked as `.part` and resume only when the cached source fingerprint still
matches.

The device tab keeps the current or last file operation visible. During a move or local MP3 copy it
explicitly warns not to disconnect the Shokz, then reports completion or failure.

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

The portable build is one executable. Make it executable if needed, then launch it:

```bash
chmod +x Shokz-Refill-linux-x86_64
./Shokz-Refill-linux-x86_64
```

It bundles Python, PySide6, yt-dlp, Deno, ffmpeg and the other runtime dependencies. Device
discovery uses `lsblk`; manual folder selection works on any mounted volume.

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
scripts/build_linux.sh
```

The resulting single binary is `dist/Shokz-Refill-linux-x86_64` with its SHA-256 checksum beside
it.

## Windows

Install 64-bit Python 3.12 and PowerShell 7.3 or newer only on the build machine, then run:

```powershell
pwsh -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The resulting `dist\Shokz-Refill-windows-x86_64.exe` includes Python, PySide6, yt-dlp with its EJS
scripts, Deno, dependencies, ffmpeg and ffprobe. Its SHA-256 checksum is written beside it.
Windows must be built natively; the Linux build cannot cross-compile it.

## Forgejo CI and releases

The Forgejo workflow keeps the existing triggers: pull requests run the quality gate, and tags
matching `YYYY.*.*` run tests followed by native Linux and Windows builds. Both builds are collected
only after all required jobs succeed, then the cleaned source mirror, tag, and release assets are
pushed to <https://github.com/simon-verbois/shokz-filler>.

The Forgejo installation must provide runners labelled `ubuntu-latest` and `windows-11`.
The Windows host job uses PowerShell 7, checks out the exact commit over the LAN, and downloads
portable Python (via uv) and Node into its fresh checkout without administrator rights. Node runs
the official v3 artifact upload script directly; no JavaScript Actions or cache are needed on that
runner. A manual workflow dispatch runs quality checks and both native builds without publishing
a release, allowing the runner and checkout authentication to be tested first.
Configure `GITHUBPAT_TOKEN` preferably as an Actions secret (an existing Actions variable with the
same name is also supported) with write access to the public GitHub repository. From a clean `main`
branch, create a release with:

```bash
scripts/release.sh
```

The script generates the ISO year/week release number, commits `VERSION`, tags it, and pushes the
branch and tag atomically to Forgejo. The tag starts the release workflow. Forgejo uses v3 artifact
actions for compatibility and publishes the GitHub release through GitHub CLI.

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
- Recursive folder deletion requires an explicit confirmation.
- YouTube and YouTube Music can change access behavior; authentication may need to be reconnected,
  and some content is unavailable to yt-dlp.
- A portable build is native to its operating system and CPU architecture.
- The one-file build extracts its bundled libraries to the operating system's temporary directory
  while running, so startup is slower and Linux systems with a `noexec` temporary directory need to
  point `TMPDIR` to an executable filesystem.

## Screenshot

No screenshot is included in this source release.
