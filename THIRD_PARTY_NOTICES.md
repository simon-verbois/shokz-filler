# Third-party notices

Shokz Refill bundles open-source dependencies in its portable distributions. Their respective
licenses remain applicable. In particular, the separate `ffmpeg` and `ffprobe` programs are built
with GPL components including libmp3lame and are distributed under GPLv3 by the binary providers
used in this project's build scripts.

- FFmpeg project and source: <https://ffmpeg.org/>
- Linux static build/source information: <https://johnvansickle.com/ffmpeg/>
- Windows build/source information: <https://www.gyan.dev/ffmpeg/builds/>
- macOS build/source information: <https://formulae.brew.sh/formula/ffmpeg>
- PySide6 / Qt for Python: <https://doc.qt.io/qtforpython-6/licenses.html>
- yt-dlp: <https://github.com/yt-dlp/yt-dlp>
- yt-dlp-ejs: <https://github.com/yt-dlp/ejs>
- Deno (MIT): <https://github.com/denoland/deno>
- ytmusicapi: <https://github.com/sigma67/ytmusicapi>
- Mutagen: <https://github.com/quodlibet/mutagen>

The Linux ffmpeg archive's full GPLv3 license text is copied beside the bundled binaries by the
fetch script. Windows builders should retain the license files supplied in Gyan's archive when
redistributing that build.
