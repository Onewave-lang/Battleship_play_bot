from __future__ import annotations
import re
from typing import Optional, Tuple

# Columns on the board use Cyrillic letters in user-facing messages.  For
# convenience we accept transliterated latin input as well. ``TRANSLIT`` maps
# single latin characters to their Cyrillic counterparts according to the
# classic "абвгдежзик" → "abvgdejzik" correspondence, while ``LEGACY_LATIN``
# keeps supporting the previous sequential ``a..k`` mapping so that old users'
# muscle memory continues to work.
ROWS = "абвгдежзик"

TRANSLIT = {
    "a": "а",
    "b": "б",
    "v": "в",
    "g": "г",
    "d": "д",
    "e": "е",
    "j": "ж",
    "z": "з",
    "i": "и",
    "k": "к",
}


def normalize(cell: str) -> str:
    cell = cell.strip().lower()
    return cell


def parse_coord(cell: str) -> Optional[Tuple[int, int]]:
    """Parse user coordinate like 'г7' or 'e5' into ``(row, col)``."""
    cell = normalize(cell)
    if len(cell) < 2:
        return None
    letter = cell[0]
    rest = cell[1:]
    letter = TRANSLIT.get(letter, letter)
    if letter not in ROWS:
        return None
    try:
        row = int(rest)
    except ValueError:
        return None
    if not 1 <= row <= 10:
        return None
    col = ROWS.index(letter)
    return row - 1, col


def format_coord(coord: Tuple[int, int]) -> str:
    """Convert internal (row, col) into user-facing string with Cyrillic axes."""
    r, c = coord
    return f"{ROWS[c]}{r+1}"
