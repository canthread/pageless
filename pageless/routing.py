"""URL normalization and route matching. Visitor URLs are untrusted data, never instructions."""

import difflib
import re
from urllib.parse import unquote

_UNSAFE = re.compile(r"[^a-z0-9_-]")
ALIASES = {"/index": "/", "/indexhtml": "/", "/home": "/"}
_CRAWLER = re.compile(r"bot|crawl|spider|slurp|facebookexternalhit|embedly|preview|lighthouse", re.I)


def normalize_path(raw: str, max_chars: int = 200) -> str:
    path = unquote(raw.split("?", 1)[0].split("#", 1)[0])[:max_chars].lower()
    segments = [_UNSAFE.sub("", s) for s in path.split("/")]
    return "/" + "/".join(s for s in segments if s)


def resolve(path: str, known: set[str]) -> tuple[str | None, bool]:
    """Return (route, exact). Unknown paths map to the closest known route, or None for not-found."""
    if path in known:
        return path, True
    if path in ALIASES and ALIASES[path] in known:
        return ALIASES[path], False
    first = "/" + path.strip("/").split("/")[0]
    if first != "/" and first in known:
        return first, False
    candidates = [k for k in known if k != "/"]
    match = difflib.get_close_matches(first, candidates, n=1, cutoff=0.75)
    return (match[0], False) if match else (None, False)


def is_crawler(user_agent: str | None) -> bool:
    return bool(user_agent and _CRAWLER.search(user_agent))
