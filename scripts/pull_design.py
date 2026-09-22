"""Provenance for src/yapp/ui: pulled 2026-09-21 from the Claude Design project
https://claude.ai/design/p/be45c375-77cb-4cdf-9646-2ea5843fa7ee via DesignSync get_file.

Ported verbatim: yapp-avatar.js, tokens.css, icon-1024.png, yapp_theme.py -> src/yapp/theme.py.
Edited on port: window.html (Google Fonts link -> fonts.css; idle hint says
"press ⌥ Space to talk"; setState merges the demo SAMPLES only in demo mode, the embedded
app passes real transcript/decision text, fixed 2026-09-22),
icon.svg (c2pa provenance <metadata> block removed; drawing untouched).
Not ported: support.js (Claude Design's own preview runtime, unreferenced by window.html).
Fonts: Bricolage Grotesque and Figtree (OFL) fetched from fonts.gstatic.com as Latin woff2 subsets.

Re-pull from a Claude Code session with the DesignSync tool; this file is a record, not a fetcher.
"""

FILES = [
    "window.html",
    "yapp-avatar.js",
    "tokens.css",
    "icon.svg",
    "icon-1024.png",
    "yapp_theme.py",
]

if __name__ == "__main__":
    print(__doc__)
    print("\n".join(FILES))
