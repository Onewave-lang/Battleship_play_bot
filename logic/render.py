from __future__ import annotations
from typing import List

from models import Board
from logic.parser import ROWS
from wcwidth import wcswidth


# figure space keeps alignment even when clients collapse regular spaces
FIGURE_SPACE = "\u2007"


# letters on top for columns
# expanded slightly so that emoji icons do not stretch rows or columns
CELL_WIDTH = 3


def format_cell(symbol: str) -> str:
    pad = CELL_WIDTH - wcswidth(symbol)
    if pad < 0:
        pad = 0
    return symbol + FIGURE_SPACE * pad


COL_HEADER = ''.join(format_cell(ch) for ch in ROWS)


def _render_line(cells: List[str]) -> str:
    return ''.join(cells)


def render_board_own(board: Board) -> str:
    lines = [FIGURE_SPACE * (CELL_WIDTH + 1) + COL_HEADER]
    mapping = {0: '·', 1: '□', 2: 'x', 3: '■', 4: '▓', 5: 'x'}
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            if coord in highlight:
                if v == 2:
                    sym = '❌'
                elif v == 3:
                    sym = '🟥'
                elif v == 4:
                    sym = '💣'
                else:
                    sym = mapping.get(v, '·')
            else:
                sym = mapping.get(v, '·')
            cells.append(format_cell(sym))
        num = str(r_idx + 1)
        pad = FIGURE_SPACE * (CELL_WIDTH - wcswidth(num))
        lines.append(f"{pad}{num}{FIGURE_SPACE}" + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(board: Board) -> str:
    lines = [FIGURE_SPACE * (CELL_WIDTH + 1) + COL_HEADER]
    mapping = {0: '·', 1: '·', 2: 'x', 3: '■', 4: '▓', 5: 'x'}
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            if coord in highlight:
                if v == 2:
                    sym = '❌'
                elif v == 3:
                    sym = '🟥'
                elif v == 4:
                    sym = '💣'
                else:
                    sym = mapping.get(v, '·')
            else:
                sym = mapping.get(v, '·')
            cells.append(format_cell(sym))
        num = str(r_idx + 1)
        pad = FIGURE_SPACE * (CELL_WIDTH - wcswidth(num))
        lines.append(f"{pad}{num}{FIGURE_SPACE}" + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
