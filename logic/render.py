from __future__ import annotations
from typing import List

from models import Board
from logic.parser import ROWS


# letters on top for columns
COL_HEADER = ' '.join(ROWS)


def _render_line(cells: List[str]) -> str:
    return ' '.join(cells)


def render_board_own(board: Board) -> str:
    lines = ["   " + COL_HEADER]
    mapping = {0: '·', 1: '□', 2: 'x', 3: '■', 4: '▓', 5: 'x'}
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            if coord in highlight:
                if v == 4:
                    sym = '💣'
                else:
                    sym = f"[{mapping.get(v, '·')}]"
            else:
                sym = mapping.get(v, '·')
            cells.append(sym)
        lines.append(f"{r_idx+1:>2} " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(board: Board) -> str:
    lines = ["   " + COL_HEADER]
    mapping = {0: '·', 1: '·', 2: 'x', 3: '■', 4: '▓', 5: 'x'}
    highlight = set(board.highlight)
    for r_idx, row in enumerate(board.grid):
        cells = []
        for c_idx, v in enumerate(row):
            coord = (r_idx, c_idx)
            if coord in highlight:
                if v == 4:
                    sym = '💣'
                else:
                    sym = f"[{mapping.get(v, '·')}]"
            else:
                sym = mapping.get(v, '·')
            cells.append(sym)
        lines.append(f"{r_idx+1:>2} " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
