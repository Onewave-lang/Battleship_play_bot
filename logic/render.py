from __future__ import annotations
from typing import List, Tuple, Union
import re

from models import Board
from logic.parser import ROWS
from wcwidth import wcswidth

# fixed-width layout for board cells
#
# Emoji symbols that we use for hits, misses and ships can have a display
# width larger than the standard ASCII characters.  When Telegram renders the
# board, these wide symbols tend to stretch a cell beyond the intended column
# boundaries, which breaks the rectangular shape of the grid.  With a compact
# ``CELL_WIDTH`` of three characters we stay within narrow screens, and when a
# symbol consumes two visual columns we rely on a thin-space shim to keep it
# visually centred.
CELL_WIDTH = 3
THIN_SPACE = "\u200A"

# text symbols for board rendering
EMPTY_SYMBOL = "·"
MISS_SYMBOL = "x"
SHIP_SYMBOL = "🔲"
HIT_SYMBOL = "⬛️"
SUNK_SYMBOL = "⬛️"
LAST_MOVE_MISS_SYMBOL = "❌"
LAST_MOVE_HIT_SYMBOL = "🟥"
LAST_MOVE_SUNK_SYMBOL = "💣"

# text symbols for board rendering -  RESERVE OPTION
# EMPTY_SYMBOL = "·"
# MISS_SYMBOL = "x"
# SHIP_SYMBOL = "◻"
# HIT_SYMBOL = "◼"
# SUNK_SYMBOL = "▩"
# LAST_MOVE_MISS_SYMBOL = "✖"
# LAST_MOVE_HIT_SYMBOL = "▣"
# LAST_MOVE_SUNK_SYMBOL = "🔥"

def format_cell(symbol: str) -> str:
    """Pad cell contents so that the board remains aligned.

    ``symbol`` may contain HTML tags.  To keep alignment we strip the tags
    before measuring the visual width of the content.
    """
    visible = re.sub(r"<[^>]+>", "", symbol)
    pad = CELL_WIDTH - wcswidth(visible)
    if pad < 0:
        pad = 0
    pad_left = pad // 2
    pad_right = pad - pad_left
    thin_left = ""
    thin_right = ""
    if pad % 2 == 1:
        if pad_left < pad_right and pad_right:
            pad_right -= 1
            thin_left = THIN_SPACE
        elif pad_left > pad_right and pad_left:
            pad_left -= 1
            thin_right = THIN_SPACE
        else:
            thin_right = THIN_SPACE
    return (" " * pad_left) + thin_left + symbol + thin_right + (" " * pad_right)


COL_HEADERS = ''.join(format_cell(letter) for letter in ROWS)


def _render_line(cells: List[str]) -> str:
    return ''.join(cells)


def _resolve_cell(v: Union[int, Tuple[int, str]]) -> Tuple[int, str | None]:
    """Return ``(state, owner)`` from a cell value."""
    if isinstance(v, (list, tuple)):
        state = v[0]
        owner = v[1] if len(v) > 1 else None
    else:
        state = v
        owner = None
    return state, owner


def render_board_own(board: Board) -> str:
    header = format_cell("") + "|" + " " + COL_HEADERS
    lines = [header]
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            cell_state, owner = _resolve_cell(v)
            if cell_state == 1:
                sym = SHIP_SYMBOL
            elif cell_state == 2:
                sym = MISS_SYMBOL
            elif cell_state == 3:
                sym = HIT_SYMBOL
            elif cell_state == 4:
                sym = SUNK_SYMBOL
            elif cell_state == 5:
                sym = MISS_SYMBOL
            else:
                sym = EMPTY_SYMBOL
            if coord in highlight:
                if cell_state in (2, 5):
                    sym = LAST_MOVE_MISS_SYMBOL
                elif cell_state == 4:
                    sym = LAST_MOVE_SUNK_SYMBOL
                elif cell_state == 3:
                    sym = LAST_MOVE_HIT_SYMBOL
            cells.append(format_cell(sym))
        row_label = format_cell(str(r_idx + 1))
        lines.append(f"{row_label}| " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(board: Board) -> str:
    header = format_cell("") + "|" + " " + COL_HEADERS
    lines = [header]
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            cell_state, owner = _resolve_cell(v)
            if cell_state == 2:
                sym = MISS_SYMBOL
            elif cell_state == 3:
                sym = HIT_SYMBOL
            elif cell_state == 4:
                sym = SUNK_SYMBOL
            elif cell_state == 5:
                sym = MISS_SYMBOL
            else:
                sym = EMPTY_SYMBOL
            if coord in highlight:
                if cell_state in (2, 5):
                    sym = LAST_MOVE_MISS_SYMBOL
                elif cell_state == 4:
                    sym = LAST_MOVE_SUNK_SYMBOL
                elif cell_state == 3:
                    sym = LAST_MOVE_HIT_SYMBOL
            cells.append(format_cell(sym))
        row_label = format_cell(str(r_idx + 1))
        lines.append(f"{row_label}| " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
