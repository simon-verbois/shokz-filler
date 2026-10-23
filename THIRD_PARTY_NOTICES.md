# Third-party notices

Shokz Refill bundles open-source dependencies in its portable distributions. Their respective
licenses remain applicable. In particular, the separate `ffmpeg` and `ffprobe` programs are built
with GPL components including libmp3lame and are distributed under GPLv3 by the binary providers
used in this project's build scripts.

- FFmpeg project and source: <https://ffmpeg.org/>
- Linux static build/source information: <https://johnvansickle.com/ffmpeg/>
- Windows build/source information: <https://www.gyan.dev/ffmpeg/builds/>
- PySide6 / Qt for Python: <https://doc.qt.io/qtforpython-6/licenses.html>
- yt-dlp: <https://github.com/yt-dlp/yt-dlp>
- yt-dlp-ejs: <https://github.com/yt-dlp/ejs>
- Deno (MIT): <https://github.com/denoland/deno>
- ytmusicapi: <https://github.com/sigma67/ytmusicapi>
- Mutagen: <https://github.com/quodlibet/mutagen>

The Linux ffmpeg archive's full GPLv3 license text is copied beside the bundled binaries by the
fetch script. Windows builders should retain the license files supplied in Gyan's archive when
redistributing that build.

## Offline neural speech synthesis

Portable builds include Piper 1.8.0 (GPLv3-or-later), its eSpeak NG phonemizer, ONNX Runtime (MIT)
and the Tom French and John English neural voice models. eSpeak provides phonemes only; Piper's
neural models produce the audio. No announcement is sent to a remote service.

- Piper engine source: <https://github.com/OHF-Voice/piper1-gpl/tree/v1.8.0>
- eSpeak NG source: <https://github.com/espeak-ng/espeak-ng>
- ONNX Runtime source: <https://github.com/microsoft/onnxruntime>
- Pinned voice repository: <https://huggingface.co/rhasspy/piper-voices/tree/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd>
- Tom model card: <https://huggingface.co/rhasspy/piper-voices/blob/main/fr/fr_FR/tom/medium/MODEL_CARD>
- Tom dataset and training source (AGPLv3): <https://git.bksp.space/Tjiho/French-tts-model-piper>
- John model card: <https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/john/medium/MODEL_CARD>

Full license texts are included under `licenses/`, and model cards beside the models in
`shokz_refill/voices/`. The voice revision and SHA-256 digests are recorded in
`scripts/tts-voices.json`; build scripts fetch and verify these files before packaging. Retain the
license and attribution files and provide corresponding source under the applicable licenses
when redistributing these components.
