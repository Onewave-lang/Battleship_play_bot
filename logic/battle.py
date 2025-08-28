from __future__ import annotations
from typing import Tuple

from models import Board, Ship


MISS, HIT, KILL, REPEAT = 'miss', 'hit', 'kill', 'repeat'


def _get_cell_state(board: Board, r: int, c: int) -> int:
    """Return the state value for a cell, accounting for tuple/list storage."""
    cell = board.grid[r][c]
    return cell[0] if isinstance(cell, (list, tuple)) else cell


def _set_cell_state(board: Board, r: int, c: int, value: int) -> None:
    """Set the state value for a cell, supporting tuple/list storage."""
    cell = board.grid[r][c]
    if isinstance(cell, list):
        cell[0] = value
    else:
        board.grid[r][c] = value


def mark_contour(board: Board, cells: list[Tuple[int,int]]) -> None:
    for r, c in cells:
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                nr, nc = r+dr, c+dc
                if 0 <= nr < 10 and 0 <= nc < 10:
                    if _get_cell_state(board, nr, nc) == 0:
                        _set_cell_state(board, nr, nc, 5)


def apply_shot(board: Board, coord: Tuple[int,int]) -> str:
    board.highlight = []
    r, c = coord
    cell_state = _get_cell_state(board, r, c)
    if cell_state in (2,3,4,5):
        board.highlight = [coord]
        return REPEAT  # already shot here or around
    if cell_state == 0:
        _set_cell_state(board, r, c, 2)
        board.highlight = [coord]
        return MISS
    if cell_state == 1:
        _set_cell_state(board, r, c, 3)
        board.alive_cells -= 1
        # find ship
        ship = None
        for s in board.ships:
            if coord in s.cells:
                ship = s
                break
        if ship:
            all_hit = True
            for rr, cc in ship.cells:
                if _get_cell_state(board, rr, cc) != 3:  # some not hit yet
                    all_hit = False
                    break
            if all_hit:
                ship.alive = False
                for rr, cc in ship.cells:
                    _set_cell_state(board, rr, cc, 4)
                mark_contour(board, ship.cells)
                board.highlight = ship.cells.copy()
                return KILL
        board.highlight = [coord]
        return HIT
    return MISS
