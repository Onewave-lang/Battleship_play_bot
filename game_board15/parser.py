from __future__ import annotations
import re
from typing import Optional, Tuple

"""Parsing utilities for 15x15 board.

Historically the project used Cyrillic letters to label columns.  The modern
board displays latin letters instead, therefore outgoing coordinates and
rendered boards must also use them.  ``ROWS`` keeps the Cyrillic sequence for
backwards compatible parsing while ``LATIN`` is the user-facing counterpart."""

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
    """Convert internal (row, col) into user-facing string with latin letters."""
    r, c = coord
    return f"{LATIN[c]}{r+1}"
