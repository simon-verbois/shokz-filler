"""PyInstaller-safe application and isolated speech-worker entry point."""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--tts-worker":
    from shokz_refill.tts_worker import main

    raise SystemExit(main(sys.argv[2:]))

if len(sys.argv) > 1 and sys.argv[1] == "--tts-smoke-test":
    from shokz_refill.packaging_smoke import speech_smoke_test

    raise SystemExit(speech_smoke_test())

from shokz_refill.app import main

raise SystemExit(main())
