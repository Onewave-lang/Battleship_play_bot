from __future__ import annotations
import re
from typing import Optional, Tuple

# Columns on the board use Cyrillic letters in user-facing messages, while we
# still accept latin input for convenience. ``ROWS`` keeps the Cyrillic
# representation and ``LATIN`` mirrors it with latin characters so that we can
# normalise incoming coordinates.
ROWS = 'абвгдежзик'
LATIN = 'abcdefghik'


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
    if letter in LATIN:
        letter = ROWS[LATIN.index(letter)]
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
