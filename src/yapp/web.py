"""Web addresses and web searches, said out loud.

Whisper writes "weather.com" as "weather com" or "weather dot com", and Jev can only pick
text it is offered, so code turns the spoken form into a real address. Nothing here names
a site: the address is whatever was said, and the browser is the user's default one.
"""

from __future__ import annotations

import re

# Common top-level domains, generic and country ones. A word before one of these, joined
# by "dot" or just a space, is read as an address.
TLDS = frozenset(
    "com org net io ai co dev app edu gov page me info biz tv us uk ca in de fr au jp "
    "nl es it se ch nz ie".split()
)
# Said with just a space ("weather com"), only these count: none of them is an English
# word. Any other domain ("weather dot in") needs the word "dot", or "in" in "weather in
# toronto" would become an address.
BARE_TLDS = frozenset("com org net io edu gov".split())
_JOINERS = {"dot": ".", "slash": "/", "dash": "-", "hyphen": "-"}
_NOT_NAMES = {"the", "a", "an", "to", "for", "and", "then", "at", "on", "of", "in", "my"}
_LEAD = {"www", "http", "https"}


def spoken_address(words: str) -> str | None:
    """The web address in the words, or None. "go to weather com" -> "weather.com";
    "linkedin dot com slash in" -> "linkedin.com/in"; "weather.com" stays as it is."""
    text = words.lower().strip()
    dotted = re.search(r"\b((?:[a-z0-9-]+\.)+([a-z]{2,}))(/[^\s]*)?", text)
    if dotted and dotted.group(2) in TLDS:
        return dotted.group(1) + (dotted.group(3) or "")
    tokens = re.findall(r"[a-z0-9-]+", text)
    for i, tok in enumerate(tokens):
        if tok not in TLDS or i == 0:
            continue
        j = i - 1
        said_dot = tokens[j] == "dot"
        if said_dot:
            j -= 1
        if not said_dot and tok not in BARE_TLDS:
            continue
        if j < 0 or tokens[j] in _JOINERS or tokens[j] in TLDS or tokens[j] in _NOT_NAMES:
            continue
        from yapp.intent import INSTRUCTION_VERBS  # "type com" is a command, not a site

        if tokens[j] in INSTRUCTION_VERBS:
            continue
        name = tokens[j]
        if j > 0 and tokens[j - 1] in _LEAD:
            pass  # "www weather com": the lead word is not part of the name
        host = f"{name}.{tok}"
        path: list[str] = []
        k = i + 1
        while k + 1 < len(tokens) and tokens[k] == "slash":
            segment = tokens[k + 1]
            k += 2
            while k + 1 < len(tokens) and tokens[k] in ("dash", "hyphen"):
                segment += "-" + tokens[k + 1]
                k += 2
            path.append(segment)
        return host + ("/" + "/".join(path) if path else "")
    return None


SEARCH_LEAD = re.compile(
    r"^(?:and\s+|then\s+)*(?:(?:search|look)\s+(?:the\s+web\s+|online\s+|up\s+)?(?:for\s+)?"
    r"|google\s+|look\s+up\s+)",
    re.I,
)


def search_query(words: str) -> str:
    """What to search for: the words after "search (the web) for", "google", "look up"."""
    return SEARCH_LEAD.sub("", words.strip()).strip()


def default_browser() -> str | None:
    """The name of the app that opens http links on this Mac (Launch Services)."""
    try:
        from AppKit import NSURL, NSWorkspace

        url = NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(
            NSURL.URLWithString_("https://example.com")
        )
        if url is None:
            return None
        name = str(url.lastPathComponent())
        return name[:-4] if name.endswith(".app") else name
    except Exception:  # noqa: BLE001 - no Launch Services: unknown
        return None
