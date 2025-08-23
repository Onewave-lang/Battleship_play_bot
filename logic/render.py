from __future__ import annotations
from typing import List, Iterable, Tuple

from models import Board
from logic.parser import ROWS


# letters on top, numbers on the left
COL_HEADER = ' '.join(ROWS)


def _render_line(cells: List[str]) -> str:
    return ' '.join(cells)


def render_board_own(
    board: Board,
    blink_cells: Iterable[Tuple[int, int]] | None = None,
    show_dot: bool = False,
    blink_red: bool = False,
) -> str:
    lines = ["  " + COL_HEADER]
    mapping = {0: '·', 1: '⬜', 2: 'x', 3: '⬛', 4: '▓', 5: 'x'}
    blink = set(blink_cells or [])
    for idx, row in enumerate(board.grid):
        row_cells = []
        for j, v in enumerate(row):
            ch = mapping.get(v, '·')
            if (idx, j) in blink:
                ch = '·' if show_dot else ch
                if blink_red:
                    ch = f"<span style='color:red'>{ch}</span>"
            row_cells.append(ch)
        lines.append(f"{idx + 1:>2} " + _render_line(row_cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'


def render_board_enemy(
    board: Board,
    blink_cells: Iterable[Tuple[int, int]] | None = None,
    show_dot: bool = False,
    blink_red: bool = False,
) -> str:
    lines = ["  " + COL_HEADER]
    mapping = {0: '·', 1: '·', 2: 'x', 3: '⬛', 4: '▓', 5: 'x'}
    blink = set(blink_cells or [])
    for idx, row in enumerate(board.grid):
        row_cells = []
        for j, v in enumerate(row):
            ch = mapping.get(v, '·')
            if (idx, j) in blink:
                ch = '·' if show_dot else ch
                if blink_red:
                    ch = f"<span style='color:red'>{ch}</span>"
            row_cells.append(ch)
        lines.append(f"{idx + 1:>2} " + _render_line(row_cells))
    return '<pre>' + '\n'.join(lines) + '</pre>'
