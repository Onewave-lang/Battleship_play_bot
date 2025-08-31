from __future__ import annotations
from typing import Optional, Tuple

"""Parsing utilities for 15x15 board.

Historically the project used Cyrillic letters to label columns.  The modern
board displays latin letters instead, therefore outgoing coordinates and
rendered boards must also use them.  Older clients might still send Cyrillic
letters; ``CYRILLIC_ALIASES`` maps them to their latin counterparts."""

LATIN = "abcdefghijklmno"
CYRILLIC_ALIASES = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "х": "h",
    "и": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "ц": "c",
    "с": "c",
    "э": "e",
    "ф": "f",
    "й": "j",
}


def normalize(cell: str) -> str:
    return cell.strip().lower()


def parse_coord(cell: str) -> Optional[Tuple[int, int]]:
    cell = normalize(cell)
    if len(cell) < 2:
        return None
    letter = cell[0]
    letter = CYRILLIC_ALIASES.get(letter, letter)
    if letter not in LATIN:
        return None
    rest = cell[1:]
    try:
        row = int(rest)
    except ValueError:
        return None
    if not 1 <= row <= 15:
        return None
    col = LATIN.index(letter)
    return row - 1, col


def format_coord(coord: Tuple[int, int]) -> str:
    """Convert internal (row, col) into user-facing string with latin letters."""
    r, c = coord
    return f"{LATIN[c]}{r+1}"
