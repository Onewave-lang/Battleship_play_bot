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
# ``CELL_WIDTH`` of two characters we stay within narrow screens.
CELL_WIDTH = 2

# text symbols for board rendering
EMPTY_SYMBOL = "·"
MISS_SYMBOL = "×"
SHIP_SYMBOL = "▢"
HIT_SYMBOL = "■"
SUNK_SYMBOL = "▩"
LAST_MOVE_MISS_SYMBOL = "✕"
LAST_MOVE_HIT_SYMBOL = "▣"
LAST_MOVE_SUNK_SYMBOL = "▣"

# text symbols for board rendering - PREVIOUS SET
# EMPTY_SYMBOL = "·"
# MISS_SYMBOL = "x"
# SHIP_SYMBOL = "🔲"
# HIT_SYMBOL = "⬛️"
# SUNK_SYMBOL = "⬛️"
# LAST_MOVE_MISS_SYMBOL = "❌"
# LAST_MOVE_HIT_SYMBOL = "🟥"
# LAST_MOVE_SUNK_SYMBOL = "💣"

def format_cell(symbol: str) -> str:
    """Pad cell contents so that the board remains aligned.

    ``symbol`` may contain HTML tags.  To keep alignment we strip the tags
    before measuring the visual width of the content.  We then append regular
    spaces to the right until the cell reaches ``CELL_WIDTH`` columns.
    """
    visible = re.sub(r"<[^>]+>", "", symbol)
    width = wcswidth(visible)
    if width < 0:
        # fall back to treating the cell as already correct if width can't be
        # determined (``wcswidth`` returns ``-1`` for non-printable strings)
        return symbol
    if width >= CELL_WIDTH:
        return symbol
    slack = CELL_WIDTH - width
    left_pad = (slack + 1) // 2
    right_pad = slack - left_pad
    visible = (" " * left_pad) + visible + (" " * right_pad)
    padded = (" " * left_pad) + symbol + (" " * right_pad)
    # ensure the padding did not break wcswidth; fall back if it did
    if wcswidth(visible) != CELL_WIDTH:
        return symbol
    return padded


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
