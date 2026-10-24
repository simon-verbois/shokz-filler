# Local MP3 import fixtures

These two short sine waves were generated locally with the bundled ffmpeg.
Tests use their bytes with Mutagen and do not execute ffmpeg or access the network.

- `target-stereo.mp3`: CBR 192 kbps, 44.1 kHz, stereo, ID3v2.3.
- `source-mono.mp3`: CBR 128 kbps, 22.05 kHz, mono, ID3v2.3.

Generation command (adjust the output name and audio options for each fixture):

```sh
ffmpeg -f lavfi -i sine=frequency=440:duration=0.2 -c:a libmp3lame \
  -b:a 192k -ar 44100 -ac 2 -metadata artist='Local artist' \
  -metadata title='Local title' -id3v2_version 3 target-stereo.mp3
```
