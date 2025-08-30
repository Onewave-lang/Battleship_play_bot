from __future__ import annotations
from typing import List, Tuple, Union
import re

from models import Board
from logic.parser import LATIN
from wcwidth import wcswidth


# figure space keeps alignment even when clients collapse regular spaces
FIGURE_SPACE = "\u2007"


# letters on top for columns
# expanded slightly so that emoji icons do not stretch rows or columns
CELL_WIDTH = 3

# colours per player for ship cells
PLAYER_COLORS = {
    "A": "#add8e6",  # light blue
    "B": "#90ee90",  # light green
    "C": "#ffc88c",  # light orange
}


def format_cell(symbol: str) -> str:
    """Pad cell contents so that the board remains aligned.

    ``symbol`` may contain HTML tags.  To keep alignment we strip the tags
    before measuring the visual width of the content.
    """
    visible = re.sub(r"<[^>]+>", "", symbol)
    pad = CELL_WIDTH - wcswidth(visible)
    if pad < 0:
        pad = 0
    return symbol + FIGURE_SPACE * pad


"""Letters on the top of the board are rendered using latin characters.

The project historically used Cyrillic letters internally, but players now see
latin columns on the board.  ``LATIN`` mirrors the internal set and is used for
display purposes.
"""
COL_HEADER = ''.join(format_cell(ch) for ch in LATIN)


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
    lines = [FIGURE_SPACE * (CELL_WIDTH + 1) + COL_HEADER]
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            cell_state, owner = _resolve_cell(v)
            color = PLAYER_COLORS.get(owner or getattr(board, "owner", None), "#000")
            if cell_state == 1:
                sym = f'<span style="color:{color}">□</span>'
            elif cell_state in (2, 5):
                sym = '<span style="color:red;background-color:orange">x</span>'
            elif cell_state == 3:
                sym = '<span style="color:#8b0000">■</span>'
            elif cell_state == 4:
                sym = '💣'
            else:
                sym = '·'
            if coord in highlight:
                sym = f'<span style="border:1px solid red">{sym}</span>'
            cells.append(format_cell(sym))
        num = str(r_idx + 1)
        pad = FIGURE_SPACE * (CELL_WIDTH - wcswidth(num))
        lines.append(f"{pad}{num}{FIGURE_SPACE}" + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(board: Board) -> str:
    lines = [FIGURE_SPACE * (CELL_WIDTH + 1) + COL_HEADER]
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            cell_state, owner = _resolve_cell(v)
            color = PLAYER_COLORS.get(owner or getattr(board, "owner", None), "#000")
            if cell_state == 1:
                sym = '·'
            elif cell_state in (2, 5):
                sym = '<span style="color:red;background-color:orange">x</span>'
            elif cell_state == 3:
                sym = '<span style="color:#8b0000">■</span>'
            elif cell_state == 4:
                sym = '💣'
            else:
                sym = '·'
            if coord in highlight:
                sym = f'<span style="border:1px solid red">{sym}</span>'
            cells.append(format_cell(sym))
        num = str(r_idx + 1)
        pad = FIGURE_SPACE * (CELL_WIDTH - wcswidth(num))
        lines.append(f"{pad}{num}{FIGURE_SPACE}" + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
