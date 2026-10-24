# Desktop interface

The visual reference supplied for the redesign is a dark desktop audio library with a
persistent device sidebar, spacious track rows and a transfers page summarised in the sidebar. The implementation
remains native PySide6 and introduces no web runtime or remote design dependency.

## Design choices

| Element | Choice |
| --- | --- |
| Canvas | `#0b1119` |
| Sidebar / card surfaces | `#191e27` / `#191f29` |
| Library rows | `#1b222c` |
| Main / secondary text | `#eef3f8` / `#a4b0c0` |
| Accent | `#32d4cf`, with a teal-to-blue gradient on primary actions |
| Font | Segoe UI on Windows, Noto Sans with Qt's system fallback on Linux |
| Navigation | Persistent sidebar, Transfers entry with live count and progress, Settings at the bottom, Alt+1 through Alt+5 |
| Library rows | 76 logical pixels, title and author/artist together, native multiselection |
| Window | Minimum 1040 × 720; scrollable settings; controls use compact 20 px minimum heights |

Line icons are rendered from bundled SVG strings by Qt. Library artwork currently uses
local icon tiles; the app does not download or display album or book cover images.

Downloads and transfers have their own **Transfers** page. The sidebar entry shows the active
count, overall progress and failures from every screen, so nothing is hidden when the page is
not open. Switching pages never cancels work.

All accounts and preferences live in **Settings**: the YouTube Music connection, the
Audiobookshelf server form and the audiobook announcement. The Audiobookshelf screen links to
them with **Connection settings**. Shokz files keeps only frequent actions in a compact toolbar
(New folder, Rename, Move, Delete, Add MP3); resuming interrupted copies and cancelling a device
operation are in its overflow menu. Each screen offers a single primary action.

Sort and filter menus retain access to titles, artists and statuses even though the library
and queue headers are hidden. Filtering deselects entire hidden rows through the native
selection model, including hidden columns. Visible row actions resolve the current item
after sorting and never use the original result-list index.

All screens retain visible keyboard focus. Status icons accompany status text; percentages
remain visible for active transfers. The redesign adds no decorative animation. Network,
conversion, transfer and cancellation services remain outside the presentation layer.

## Design references

The existing UI/UX Pro Max skill informed contrast, keyboard navigation, empty states and
interaction guidance. Its generic web layout suggestions were discarded in favour of the
supplied desktop reference. Two additional skills were installed from GitHub and read:

- [Anthropic Frontend Design](https://github.com/anthropics/skills/tree/main/skills/frontend-design)
- [Interaction Design](https://github.com/wshobson/agents/tree/main/plugins/ui-design/skills/interaction-design)

They are development guidance installed in the developer's skill directory, not application
dependencies or files distributed with the portable executable.

## Reproducible previews

Run `.venv/bin/python scripts/capture_screenshots.py` to capture all four real application
screens and the audiobook export dialog using isolated, fictional data. No real account,
server, password or removable device is used. `tests/test_ui_design.py` exercises navigation,
keyboard shortcuts, sorted row actions, hidden selections, queue updates while collapsed,
connection controls and compact layouts using real Qt widgets and deterministic fakes.
