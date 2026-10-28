#!/usr/bin/env bash
# Registers a launcher and icon for this checkout (or a portable binary given as $1), so Wayland
# desktops, which take the taskbar icon from a .desktop file, show the Shokz Filler logo.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-$project_dir/start-shokz-filler.sh}"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$data_home/applications" "$data_home/icons/hicolor/scalable/apps" \
  "$data_home/icons/hicolor/512x512/apps"
install -m 0644 "$project_dir/assets/logo.svg" "$data_home/icons/hicolor/scalable/apps/shokz-filler.svg"
install -m 0644 "$project_dir/assets/logo-512.png" "$data_home/icons/hicolor/512x512/apps/shokz-filler.png"
cat > "$data_home/applications/shokz-filler.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Shokz Filler
Comment=Find audio and manage music on your Shokz MP3 player
Exec="$target"
Icon=shokz-filler
Terminal=false
Categories=AudioVideo;Audio;
StartupWMClass=shokz-filler
DESKTOP
command -v update-desktop-database >/dev/null && update-desktop-database "$data_home/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$data_home/icons/hicolor" || true
echo "Installed launcher: $data_home/applications/shokz-filler.desktop"
