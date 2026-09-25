"""Provenance for src/yapp/ui.

Pulled 2026-09-22 from the Claude Design project
https://claude.ai/design/p/be45c375-77cb-4cdf-9646-2ea5843fa7ee via Share -> Export ->
Project archive (.zip), unzipped, and copied byte-for-byte: window.html, permissions.html,
avatar.html, yapp-avatar.js, tokens.css, icon.svg, icon-1024.png, icon-16.png, icon-32.png,
menubar-glyph.svg, menubar-glyph-listening.svg, menubar-glyph-paused.svg,
menubar-glyph-attention.svg, and yapp_theme.py -> src/yapp/theme.py (reformatted by ruff only).

Icon refresh 2026-09-24: icon.svg, icon-1024.png, icon-16.png, icon-32.png re-pulled from the same
project after the icon was redesigned there (pebble + ring, the avatar's idle contour with its mic
ring). The showcase pages and icon-sheet.png live under brand/design for reference.

No edits were made on port. Visual changes go through the design project first.
Not ported: support.js (Claude Design's preview runtime), Yapp.dc.html and wireframes.dc.html
(showcase pages), screenshots/.
"""

FILES = [
    "window.html",
    "permissions.html",
    "avatar.html",
    "yapp-avatar.js",
    "tokens.css",
    "icon.svg",
    "icon-1024.png",
    "icon-16.png",
    "icon-32.png",
    "menubar-glyph.svg",
    "menubar-glyph-listening.svg",
    "menubar-glyph-paused.svg",
    "menubar-glyph-attention.svg",
    "yapp_theme.py",
]

if __name__ == "__main__":
    print(__doc__)
    print("\n".join(FILES))
