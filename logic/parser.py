from __future__ import annotations
import re
from typing import Optional, Tuple

ROWS = 'абвгдежзик'
LATIN = 'abcdefghik'


def normalize(cell: str) -> str:
    cell = cell.strip().lower()
    return cell


def parse_coord(cell: str) -> Optional[Tuple[int, int]]:
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
        col = int(rest)
    except ValueError:
        return None
    if not 1 <= col <= 10:
        return None
    row = ROWS.index(letter)
    return row, col - 1
