from __future__ import annotations
from typing import List

from models import Board
from logic.parser import ROWS


COL_HEADER = ' '.join(str(i) for i in range(1,11))


def _render_line(cells: List[str]) -> str:
    return ' '.join(cells)


def render_board_own(board: Board) -> str:
    lines = ["  " + COL_HEADER]
    mapping = {0:'·',1:'□',2:'x',3:'■',4:'▓',5:'x'}
    for idx, row in enumerate(board.grid):
        cells = [mapping.get(v,'·') for v in row]
        lines.append(f"{ROWS[idx]} " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(board: Board) -> str:
    lines = ["  " + COL_HEADER]
    mapping = {0:'·',1:'·',2:'x',3:'■',4:'▓',5:'x'}
    for idx, row in enumerate(board.grid):
        cells = [mapping.get(v,'·') for v in row]
        lines.append(f"{ROWS[idx]} " + _render_line(cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
