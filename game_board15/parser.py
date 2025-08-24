from __future__ import annotations
import re
from typing import Optional, Tuple

ROWS = 'абвгдежзиклмнопр'
LATIN = 'abcdefghijklmnopr'


def normalize(cell: str) -> str:
    return cell.strip().lower()


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
        row = int(rest)
    except ValueError:
        return None
    if not 1 <= row <= 15:
        return None
    col = ROWS.index(letter)
    return row - 1, col


def format_coord(coord: Tuple[int, int]) -> str:
    r, c = coord
    return f"{ROWS[c]}{r+1}"
