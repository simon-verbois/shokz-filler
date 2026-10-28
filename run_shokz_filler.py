"""PyInstaller-safe application and isolated speech-worker entry point."""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--tts-worker":
    from shokz_filler.tts_worker import main

    raise SystemExit(main(sys.argv[2:]))

if len(sys.argv) > 1 and sys.argv[1] == "--tts-smoke-test":
    from shokz_filler.packaging_smoke import speech_smoke_test

    raise SystemExit(speech_smoke_test())

from shokz_filler.app import main

raise SystemExit(main())
