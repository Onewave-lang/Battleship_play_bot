from __future__ import annotations
import re
from typing import Optional, Tuple

# Columns on the board are identified by latin letters when rendered for
# users, while internally we still support both latin and Cyrillic inputs.
# ``ROWS`` keeps the Cyrillic representation to remain backward compatible
# with existing games, and ``LATIN`` mirrors it with latin characters so that
# outbound messages and rendered boards use latin coordinates.
ROWS = 'абвгдежзик'
LATIN = 'abcdefghik'


def normalize(cell: str) -> str:
    cell = cell.strip().lower()
    return cell


def parse_coord(cell: str) -> Optional[Tuple[int, int]]:
    """Parse user coordinate like 'e5' into (row, col)."""
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
    """Convert internal (row, col) into user-facing string.

    Even though we accept both latin and Cyrillic letters as input, users see
    the board labelled with latin letters.  Therefore coordinates in outgoing
    messages must also use latin letters.
    """
    r, c = coord
    return f"{LATIN[c]}{r+1}"
