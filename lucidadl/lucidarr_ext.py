"""Fork-only search/matching helpers, kept out of upstream's modules.

downloader.py calls these from two one-line hooks, so upstream's files stay almost
untouched and merge cleanly. See UPSTREAM.md.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List

from .matching import _split_query, _tokens


def simplify(text: str) -> str:
    """Strip characters lucida's search chokes on: ellipses ("The Truth Is…") and curly
    quotes. Returns the text unchanged when it has none of them."""
    out = (text.replace("…", " ").replace("...", " ")
           .replace("‘", "'").replace("’", "'")
           .replace("“", '"').replace("”", '"'))
    return re.sub(r"\s+", " ", out).strip()


def simplified_variants(variants: List[str]) -> List[str]:
    """The same search queries with ellipses/curly quotes simplified; only those that
    differ. Appended after the originals so ordinary titles keep their search order."""
    return [s for s in (simplify(v) for v in variants) if s not in variants]


# Words that only label an edition of the same album; ignored when comparing titles.
EDITION_WORDS = {
    "deluxe", "special", "edition", "expanded", "remaster", "remastered", "anniversary",
    "version", "bonus", "track", "tracks", "explicit", "clean", "digital", "standard",
    "super", "collectors", "collector", "reissue", "mono", "stereo", "the",
}


def title_agrees(query: str, item: Dict[str, str], min_cover: float = 0.8) -> bool:
    """For ALBUM matching: does the result's title really name the album asked for?

    The generic score happily accepts a *different* album by the same artist that shares
    most words ("Christmas With Elvis Presley" vs "Elvis Presley Christmas Duets").
    Here at least ``min_cover`` of the wanted title's words must appear in the result,
    and the result may add only a few words of its own (edition labels such as
    "Deluxe" or "Special Edition", and bare years, never count)."""
    def words(text: str) -> set:
        return {w for w in _tokens(text) - EDITION_WORDS
                if not (len(w) == 4 and w.isdigit())}

    _, wanted = _split_query(query)
    wt = words(wanted)
    if not wt:
        return True
    rt = words(item.get("title", ""))
    if len(wt & rt) / len(wt) < min_cover:
        return False
    return len(rt - wt) <= len(wt) // 3


def album_title_ok(line: str, items: List[Dict[str, str]], url: str,
                   log: Callable[[str], None], quiet: bool = False) -> bool:
    """Hook for downloader._resolve_url: is the picked ALBUM really the wanted one?"""
    picked = next((it for it in items if it.get("url") == url), {})
    if title_agrees(line, picked):
        return True
    if not quiet:
        log(f"  ↳ rejected \"{picked.get('title', '?')}\": title differs from the wanted album")
    return False
