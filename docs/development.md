# Technical guide — Shokz Refill

Shokz Refill is a small desktop utility for finding music through YouTube Music and safely
loading compatible MP3 files onto Shokz headphones with onboard storage, including OpenSwim
Pro. It also browses Audiobookshelf servers, converts selected audiobooks into ordered compatible MP3s,
imports existing local MP3 files and provides a focused browser for the selected device.

The application searches songs and playlists, opens playlist tracks, loads account-library
playlists, downloads up to three tracks concurrently, and transfers them sequentially. Converted output is
broadly compatible MP3: **CBR 192 kbps, 44.1 kHz, stereo, ID3v2.3**.

## Use

1. Connect or manually select the mounted Shokz volume. Automatically detected media is clearly
   labelled; manual selection is available for devices whose USB metadata cannot be recognized.
2. Browse the device files as needed. Standalone search downloads ask for their own destination.
3. Search YouTube Music, or connect an account and select **My playlists**. Open a playlist,
   use the **<** and **>** buttons to navigate, and add tracks to the send list with **+**.
   Nothing downloads until you choose **Send to Shokz (N)**, which opens the transfer assistant
   (`transfer_wizard.py`): step 1 reviews and reorders the songs, step 2 picks or creates a folder.
4. To transfer an entire playlist, open it and use right-click → **Add all songs to send list**,
   then **Send to Shokz**. Shokz Refill creates or reuses a folder that keeps the playlist's original
   capitalization and spaces, such as `My Running Mix`, directly at the device root.
5. Watch download, conversion, and transfer progress in the **Transfers** page and the sidebar summary. Failed or cancelled items can be retried with **Retry selected**, and
   active or queued items can be cancelled. Retrying a transfer reuses its converted MP3 cache.

Downloads, conversions, and device transfers use independent bounded worker pools. A conversion
therefore does not prevent the next track from downloading, while writes to removable storage stay
strictly sequential.

For songs selected outside a playlist, Shokz Refill uses the download folder selected with
**Change…** beside the destination or **Use as download destination**. If no folder has been chosen,
the in-app folder tree opens on the first download. The device root is hidden: choose an existing
folder or create a new top-level folder. Downloading these songs directly to the device root is
intentionally disabled. Playlists always use their automatic folder, shown below the results.

Duplicate policy is scoped to the destination folder: the same YouTube video ID cannot be queued
twice while active, and MP3 files carrying that source ID are skipped before downloading and checked
again before transfer. A title or artist match alone is not treated as proof of identity. Distinct
or unidentified files are preserved; filename conflicts receive numbered names. Skipped items remain
visible as **already present** in the queue.

Use the filter menu above YouTube Music results to sort by title, artist or duration. Repeating a sort reverses its direction. Before the first sort, search relevance order is preserved.

Use the library or transfer-queue filter menu to filter by text (case-insensitive). In Shokz files, use the magnifying glass in a column header.
Filters are available for result titles/artists, device names/types, and queue tracks/statuses;
multiple column filters combine. Clear the text or choose **Clear filters** from the menu; device header controls also support right-click to clear filters. Hidden rows are deselected before any operation on selected items.

The device browser can create, rename, move, and recursively delete folders; rename, move, or delete MP3s;
and add local MP3 files. `SYSTEM` and `System Volume Information` are hidden, regardless of case. Moves support multi-selection:
drag selected items onto a visible folder, or use **Move selected…** to choose a destination from
the in-app folder tree. Folders remain flat at the device root and cannot be nested; MP3 files can
be moved into a folder. Moves remain inside the selected device. Recursive deletes require explicit
confirmation and do not follow symbolic links outside the device. Name
collisions get a deterministic numbered name and never overwrite an existing file. Interrupted
transfers remain visibly marked as `.part` and resume only when the cached source fingerprint still
matches. Reconnection never starts a copy automatically: use **Resume interrupted copies**.
A resume verifies the existing partial against the source prefix and verifies the complete SHA-256
before publishing the MP3. Invalid partials and changed sources are preserved and reported, rather
than deleted. Final renaming cannot overwrite an existing entry; an unsupported exclusive rename
fails explicitly and keeps the partial.

Device copies, moves, renames, folder creation and deletions share one mutation lock. A destination
folder reserved by an active download cannot be renamed, moved or deleted through the interface.
Local copies show byte progress and can be cancelled. Move/delete batches stop between items;
already completed changes are retained. Closing the window cancels queued work and requests running
operations to stop, then waits asynchronously for workers and child processes before closing.
Network cancellation is cooperative and can wait for the current request timeout.

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

## Audiobookshelf

The **Audiobookshelf** tab sits between YouTube Music and the device browser. Enter three values:

- **Server**: the full server URL, including `http://` or `https://` and any reverse-proxy path.
- **Username**: your Audiobookshelf account name.
- **Password**: your account password (masked in the interface).

These fields can also be initialized with the environment variables `AUDIOBOOKSHELF_SERVER`,
`AUDIOBOOKSHELF_USERNAME` and `AUDIOBOOKSHELF_PASSWORD`. The development `.creds` file is never loaded
by the application or included in the portable build.

Click **Connect**, choose a book library, browse pages or search by title/author, and select one or
more books with the usual Ctrl/Shift selection controls. **Send to Shokz**
queues only the selected books. Choose the Shokz device in the device tab first.

Each book gets a separate top-level folder named from its author and title, with a short stable ID
to distinguish books sharing the same name. **Each chapter becomes one MP3** named `NN - Title.mp3`
(zero-padded to the book's size). Chapters come from Audiobookshelf when they tile the book without
gaps or overlaps, possibly spanning several source files; otherwise each server track becomes one
file, in the server's track order. Shokz documents both name order (help article) and transfer time
(OpenSwim Pro FAQ), so `playback_order.py` applies both: padded prefixes, strictly sequential
publication, and `TRCK` tags. Two optional texts are spoken before the files: one for chapter 1 (by default the book, author
and chapter number) and one for the others (by default the chapter number), using `$book_name`,
`$author_name`, `$chapter_number` and `$chapter_title`. Music downloads use the same component: files are numbered
`NNN - Artist - Title.mp3`, continue after the highest number already in the folder, and an
`OrderGate` releases transfers strictly in playlist order even though downloads run concurrently.

Selected books are queued directly. **Settings → Audiobook announcement** controls **Read the book
title and author before each book** (on by default), the voice, speed and text, and lets you preview
the voice. The resulting file contains:

1. The spoken announcement, generated offline with Piper neural speech.
2. **1.5 seconds of silence.**
3. The complete book in Audiobookshelf source order.

When the option is disabled, no introduction or extra silence is inserted.

The **Settings** tab configures the announcement template, male voice (French Tom or English John) and speech
speed (60–120%, default **100%**). The voice is normalized to **−16 LUFS** with a
−1.5 dB true-peak target before the silence is appended. The default text is
`$book_name, de $author_name.`. Supported variables are `$book_name` and `$author_name`, including the `${book_name}` form; `$$` inserts a literal dollar sign. For example:

```text
Vous écoutez $book_name. Auteur : $author_name.
```

An example preview and variable validation are provided before saving. Each queued job captures
its own choices, so later settings changes do not alter an export already in progress. Speech uses
**Piper 1.8.0**, with the **Tom** French male voice by default and **John** for English. The
engine and voice models are included in the portable app: **no Internet, Google account, API key,
separate service, or user-installed runtime is needed**. Speed is controlled by the neural model's
duration scaling, preserving pitch. Generated announcements are validated and cached locally by
voice, text and speed. Failed synthesis stops the export with a retryable error. Previous engine
settings migrate to Piper at 100%; existing device files are preserved.

The dedicated normalization engine accepts M4B/M4A/AAC, MP3, FLAC, Ogg/Opus, WAV and other audio
containers supported by the bundled ffmpeg. Sources are normalized individually into **MP3 CBR
192 kbps, 44.1 kHz, stereo** and then concatenated without a second lossy encode. Ordinary MP3
sources are supported too. Generated intermediate filenames keep the final concat command short
even for books with many files. Both the intermediate and final MP3 formats are validated.

A single audiobook worker downloads, converts and copies books sequentially. YouTube's bounded
pipeline can continue in parallel; all writes still use the shared device lock. The common queue
shows download, speech/conversion and copy progress. Cancelled or failed exports retain cached sources,
normalized components and resumable device-transfer partials for **Retry selected**. No incomplete
book is presented as a finished MP3.

An identical complete export is skipped. Changing the spoken text, voice, rate, introduction option
or source content changes its identity. Existing exports, including older chapter-by-chapter
folders, are preserved; a different version is placed in a new numbered folder. Each new export
therefore contains only the numbered chapter files. A chapter that would exceed the conservative
4 GiB single-file limit is rejected explicitly.

The account needs download permission. The integration reads libraries and original audio through
the [Audiobookshelf API](https://api.audiobookshelf.org/); it does not change the library, server
chapter order, listening progress or playback sessions. Encrypted/DRM-protected content that ffmpeg
cannot decode reports an error.

The server, username and password are remembered after a successful connection, in the private
per-user `audiobookshelf.json` configuration file (readable by this user only). The session token remains in memory. **Disconnect / forget** cancels audiobook
jobs and removes the saved connection. Credentials are never placed in download URLs or logs;
authenticated redirects to other locations are rejected.

## YouTube Music authentication

Public search does not require a login. To show your library playlists, click **Connect YouTube
Music** and follow the in-app steps: while signed in at `music.youtube.com`, copy the request
headers from an authenticated `/browse` POST request in the browser developer tools and paste them
into the dialog. This is the current browser-header flow supported by ytmusicapi and needs no
Shokz Refill server.

A saved session is labelled as unverified until an account request succeeds. If **My playlists**
rejects an old or malformed session, the application displays a reconnect message and stays open.
Use **Settings → Accounts → Connect** to replace it with fresh headers. Temporary network/server failures
report an error without invalidating the saved session.

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
.venv/bin/python scripts/fetch_tts_voices.py
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

The Forgejo workflow runs only when a release tag matching `YYYY.*.*` is pushed. It runs quality
checks followed by native Linux and Windows builds, then publishes the release. Both builds are collected
only after all required jobs succeed, then the cleaned source mirror, tag, and release assets are
pushed to <https://github.com/simon-verbois/shokz-filler>.

The Forgejo installation must provide runners labelled `ubuntu-latest` and `windows-11`.
The Windows host job uses PowerShell 7, checks out the exact commit over the LAN, and downloads
portable Python (via uv) and Node into its fresh checkout without administrator rights. Node runs
the official v3 artifact upload script directly; no JavaScript Actions or cache are needed on that
runner. Branch pushes and pull requests do not trigger the workflow.
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

## Code organization

- `ui.py` orchestrates application actions and navigation.
- `browser_panel.py`, `queue_panel.py` and `dialogs.py` own focused Qt presentation components.
- `background.py` owns workers and discards superseded results on the Qt thread;
  `cancellation.py` supplies cancellation to services without importing Qt.
- `downloads.py` coordinates bounded YouTube pipeline stages and the duplicate policy.
- `audiobookshelf.py` handles the read-only server API; `audiobook_models.py` builds ordered export
  plans, `audiobook_normalizer.py` converts each chapter, `playback_order.py` names and sequences files, and `audiobook_queue.py` publishes them in order.
  `audiobook_panel.py` owns connection, browsing and selection; `audiobook_settings.py` persists
  opt-in credentials. `book_export.py` snapshots export options and validates announcement
  templates; `book_dialogs.py` owns export and speech settings dialogs. `speech.py` runs the
  isolated Piper `tts_worker.py`; `packaging_smoke.py` verifies both bundled neural voices and MP3 processing
  in portable builds without network access.
- `transfer.py`, `files.py` and `filesystem.py` implement verified copies and coordinated mutations.

## Screenshots

The [presentation site](https://simon-verbois.github.io/shokz-filler/) includes current application
captures and a five-language usage guide. Captures use isolated, fictional data; regenerate them with
`.venv/bin/python scripts/capture_screenshots.py`.

## Presentation site

The static five-language site is in `docs/`, following the Inkora and Komga Meta Manager pattern.
`python3 scripts/build_site.py --check` validates references, anchors and the public asset allowlist.
`python3 scripts/build_site.py` assembles `build/site` (the destination must be empty). Preview with
`python3 -m http.server 8000 --directory build/site`. The site has no remote fonts, analytics,
account connection or third-party JavaScript. Only the explicitly listed public files are uploaded;
credentials, developer documentation and application caches are excluded.

GitHub Pages uses GitHub Actions. From the repository's default branch, manually run
**Shokz Refill presentation site** in Actions to publish. The workflow pins its actions and grants
Pages write permission only to the deployment job. Publishing the website does not create an app
release. The release mirror preserves `.github`, `docs` and `scripts/build_site.py`. Update the
feature-availability note in the page when Audiobookshelf and Piper reach a public release.

### Website translations

English is served at the site root. French, Dutch, German and Spanish use `fr/`, `nl/`, `de/`
and `es/`. The header language picker uses ordinary links, works without JavaScript and preserves
the current section when JavaScript is available. All pages include their own `lang`, canonical
URL and alternate-language metadata. Screenshots show the actual English desktop interface.

Edit `docs/site-template.html` and the five complete `docs/locales/*.json` catalogues. Keep the
English button names unchanged because they are labels from the desktop app. Announcement examples
use French or English, the languages supported by the bundled voices. Run:

```bash
python3 scripts/build_site.py --generate
python3 scripts/build_site.py --check
```

Generated pages are committed for direct inspection. The build rejects incomplete catalogues,
invalid inline translation markup and stale generated pages. Only the final HTML and explicitly
allowlisted assets enter the Pages artifact; templates and catalogues remain source files.
