# Shokz Refill

**Your music and audiobooks, ready to take along on your Shokz.**

A desktop app for searching YouTube Music, preparing compatible MP3 files and managing your Shokz USB storage. It includes Audiobookshelf and local spoken introductions for audiobooks.

[Website and usage guide](https://simon-verbois.github.io/shokz-filler/) · [Downloads](https://github.com/simon-verbois/shokz-filler/releases/latest) · [Report an issue](https://github.com/simon-verbois/shokz-filler/issues)

Website languages: [English](https://simon-verbois.github.io/shokz-filler/) · [Français](https://simon-verbois.github.io/shokz-filler/fr/) · [Nederlands](https://simon-verbois.github.io/shokz-filler/nl/) · [Deutsch](https://simon-verbois.github.io/shokz-filler/de/) · [Español](https://simon-verbois.github.io/shokz-filler/es/)

![Shokz Refill: music search and the download and transfer queue](docs/screenshots/music.png)

_Real application screenshots with fictional demonstration data. The desktop interface is in English._

> **Feature availability.** This README and the website describe the current application. The older `2026.41.1` release predates Audiobookshelf, audiobook merging and Piper speech synthesis; use a newer release for these features.

## What it does

- **YouTube Music**: search tracks and playlists, select multiple songs, download an entire playlist and access playlists from your account.
- **Audiobookshelf**: connect to your server, search and choose books to take along. Each book gets **one folder and one MP3**, with its tracks in the order supplied by the server.
- **Offline spoken introductions**: French male voice Tom or English male voice John through Piper, **95%** default speed, normalised volume and **3 seconds of silence**. Customise the text with `$book_name` and `$author_name`.
- **Device management**: check free space, create and organise folders, import local MP3 files and confirm deletions. `SYSTEM` and `System Volume Information` are hidden from the browser and folder pickers.
- **Verified transfers**: recognise duplicates, preserve files on name conflicts, validate partial files and verify SHA-256 integrity before publishing the final file.

Conversions produce **MP3 CBR 192 kb/s · 44.1 kHz · stereo · ID3v2.3**. Importing local MP3 files copies the originals without re-encoding. Portable builds include Python, Qt, FFmpeg and their dependencies; current builds also include Piper and its voice models.

## Install

Download the file for your operating system from the [GitHub releases](https://github.com/simon-verbois/shokz-filler/releases/latest).

| System         | File                              |
| -------------- | --------------------------------- |
| Linux x86_64   | `Shokz-Refill-linux-x86_64`       |
| Windows x86_64 | `Shokz-Refill-windows-x86_64.exe` |

On Linux, make the file executable and launch it:

```bash
chmod +x Shokz-Refill-linux-x86_64
./Shokz-Refill-linux-x86_64
```

On Windows, launch the `.exe`. No separate Python or FFmpeg installation is needed to use a portable build.

## First use

1. Connect your Shokz by USB and open their storage on your computer.
2. In **Shokz device / files**, select the device. If necessary, use **Select device folder** to select its mounted volume.
3. For music, open **YouTube Music**, search for songs or a playlist and select tracks using `Ctrl` / `Shift`.
4. Click **Download / transfer selected** and choose a folder. For a complete playlist, open it and click **Download whole playlist**: its folder is created automatically.
5. Follow the queue. **Retry selected** restarts failed or cancelled items; **Cancel selected** requests cancellation.
6. Wait for transfers to finish and eject the headset through your operating system before unplugging it.

Public search does not require a YouTube account. To use **My playlists**, click **Connect YouTube Music** and follow the connection dialog.

The [illustrated usage guide](https://simon-verbois.github.io/shokz-filler/#guide) covers each workflow, voice settings and interrupted transfers in all five website languages.

## Take an Audiobookshelf book along

![Audiobookshelf book selection with a demonstration server and fictional titles](docs/screenshots/audiobooks.png)

To export a book:

1. Select your headset in the device tab first.
2. In **Audiobookshelf**, enter **Server**, **Username** and **Password**, then click **Connect**. The address must include `https://` or `http://`.
3. Choose a library and select books, then click **Download / transfer selected books**.
4. For each book, keep or disable the announcement and choose **Queue book**. **Skip book** leaves that book out.
5. The app downloads the sources, converts and merges them, and copies the MP3 into the book’s own folder.

The announcement is enabled by default. **Settings** lets you choose the voice, speed and text, for example:

```text
You are listening to $book_name.
A book by $author_name.
```

Choose **John** for an English announcement or **Tom** for French. Speech synthesis is entirely local. Downloading books requires access to your server and an account with download permission. The password is remembered only if you tick the corresponding option.

<details>
<summary>View the voice settings</summary>

![Piper settings: French male voice Tom, 95% speed and a customisable announcement template](docs/screenshots/settings.png)

</details>

## Things to know

- The conversion target is fixed. Audiobookshelf sources can include M4B, M4A, MP3, FLAC, Ogg/Opus and WAV, depending on the formats FFmpeg can decode.
- Merging preserves track order **within a book**. The app cannot guarantee the headset firmware’s playback order for separate files.
- Audiobookshelf exports exceeding the conservative **4 GiB per-file** limit are refused. Allow space on your computer for the conversion cache too.
- Duplicate detection uses identifiers embedded in MP3 files. Matching titles or authors alone are not conclusive evidence of a duplicate.
- Downloads require access to the media and the appropriate rights. The app does not bypass DRM.
- This is an independent project, not affiliated with Shokz, YouTube or Audiobookshelf.

## Develop and build

The app uses Python 3.11+ and PySide6. These commands apply to the development checkout shown here; the GitHub mirror receives application code at release time. From that checkout, on Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/fetch_tts_voices.py
scripts/fetch_ffmpeg_linux.sh
./start-shokzfiller.sh
```

The two voice models are fetched from a pinned revision and verified by SHA-256. Portable executables include them afterwards; speech synthesis does not contact a service.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
python3 scripts/build_site.py --check
scripts/build_linux.sh
```

Windows builds run natively using `scripts/build_windows.ps1`. Forgejo CI publishes releases and the GitHub mirror when a release tag is pushed.

[Full technical guide](docs/development.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Source code licence](LICENSE)

## Multilingual GitHub Pages site

The static website lives in `docs/`. It follows the Inkora and Komga Meta Manager approach: a dependency-free Python build and a manually triggered Pages workflow. English is the default; French, Dutch, German and Spanish have their own static pages. Switching languages preserves the current tutorial section. No browser-side translation service is used.

Edit `docs/site-template.html` and the complete catalogues in `docs/locales/`, then regenerate and validate the committed pages:

```bash
python3 scripts/build_site.py --generate
python3 scripts/build_site.py --check
python3 scripts/build_site.py
python3 -m http.server 8000 --directory build/site
```

The build rejects missing translations, stale generated pages and broken local links. It publishes only explicitly allowlisted public assets. Regenerate screenshots with fictional data using `.venv/bin/python scripts/capture_screenshots.py`. In GitHub Actions, run **Shokz Refill presentation site** on the default branch to publish.
