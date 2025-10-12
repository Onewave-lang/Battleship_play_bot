"""Coordinate parsing helpers for the 15×15 mode."""
from __future__ import annotations

import re
from typing import Tuple

Coord = Tuple[int, int]

COLS = "ABCDEFGHIJKLMNO"
_ROW_RE = re.compile(r"^\s*([a-oA-O]|[а-яА-Я])\s*(\d{1,2})\s*$")


class ParseError(ValueError):
    pass


def parse_coord(text: str) -> Coord:
    if not text:
        raise ParseError("Пустой ввод")
    text = text.strip()
    match = _ROW_RE.match(text)
    if not match:
        raise ParseError("Введите координату формата A1")
    col_raw, row_raw = match.groups()
    col_char = col_raw.upper()
    if col_char in COLS:
        col = COLS.index(col_char)
    else:
        # basic transliteration for Russian letters
        mapping = {
            "А": "A",
            "Б": "B",
            "В": "C",
            "Г": "D",
            "Д": "E",
            "Е": "F",
            "Ж": "G",
            "З": "H",
            "И": "I",
            "Й": "J",
            "К": "K",
            "Л": "L",
            "М": "M",
            "Н": "N",
            "О": "O",
        }
        mapped = mapping.get(col_char)
        if mapped is None:
            raise ParseError("Неизвестная буква координаты")
        col = COLS.index(mapped)
    row = int(row_raw)
    if not (1 <= row <= 15):
        raise ParseError("Номер строки должен быть от 1 до 15")
    return row - 1, col


def format_coord(coord: Coord) -> str:
    row, col = coord
    if not (0 <= row < 15 and 0 <= col < 15):
        raise ValueError("Координата вне поля")
    return f"{COLS[col]}{row + 1}"


__all__ = ["parse_coord", "format_coord", "ParseError"]
