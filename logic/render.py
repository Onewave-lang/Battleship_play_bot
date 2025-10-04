from __future__ import annotations
from typing import List, Tuple, Union
import re

from models import Board
from logic.parser import ROWS
from wcwidth import wcswidth
from constants import BOMB


# fixed-width layout for board cells
CELL_WIDTH = 2

# text symbols for board rendering
EMPTY_SYMBOL = "·"
MISS_SYMBOL = "x"
HIT_SYMBOL = "■"
SHIP_SYMBOL = "□"
SUNK_SYMBOL = "▓"


def format_cell(symbol: str) -> str:
    """Pad cell contents so that the board remains aligned.

    ``symbol`` may contain HTML tags.  To keep alignment we strip the tags
    before measuring the visual width of the content.
    """
    visible = re.sub(r"<[^>]+>", "", symbol)
    pad = CELL_WIDTH - wcswidth(visible)
    if pad < 0:
        pad = 0
    return symbol + " " * pad


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
                if cell_state == 4:
                    sym = f"<b>{BOMB}</b>"
                else:
                    sym = f"<b>{sym}</b>"
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
                if cell_state == 4:
                    sym = f"<b>{BOMB}</b>"
                else:
                    sym = f"<b>{sym}</b>"
            cells.append(format_cell(sym))
        row_label = format_cell(str(r_idx + 1))
        lines.append(f"{row_label}| " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
