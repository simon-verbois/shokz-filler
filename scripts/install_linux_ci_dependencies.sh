#!/usr/bin/env bash
set -euo pipefail

# Qt still links to these libraries when QT_QPA_PLATFORM=offscreen.
# Forgejo's minimal Ubuntu runner image does not include them.
privilege=()
if [[ "$(id -u)" != "0" ]]; then
  privilege=(sudo -n)
fi

"${privilege[@]}" apt-get update
"${privilege[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  libgl1 libegl1 libopengl0 libglib2.0-0 libdbus-1-3 libxkbcommon0 \
  libxkbcommon-x11-0 libxcb-cursor0 fontconfig
