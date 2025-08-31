from __future__ import annotations
from typing import Tuple, Dict, List

from .models import Board15, Ship
from .utils import _get_cell_state, _set_cell_state, _get_cell_owner

MISS, HIT, KILL, REPEAT = 'miss', 'hit', 'kill', 'repeat'


def mark_contour(board: Board15, cells: list[Tuple[int, int]]) -> None:
    """Mark the contour around ``cells`` on a 15×15 board."""

    contour: set[Tuple[int, int]] = set()
    for r, c in cells:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < 15 and 0 <= nc < 15:
                    contour.add((nr, nc))

    for r, c in contour.difference(cells):
        if board.grid[r][c] == 0:
            board.grid[r][c] = 5


def apply_shot(board: Board15, coord: Tuple[int, int]) -> str:
    board.highlight = []
    r, c = coord
    cell = board.grid[r][c]
    if cell in (2, 3, 4, 5):
        board.highlight = [coord]
        return REPEAT
    if cell == 0:
        board.grid[r][c] = 2
        board.highlight = [coord]
        return MISS
    if cell == 1:
        board.grid[r][c] = 3
        board.alive_cells -= 1
        ship = None
        for s in board.ships:
            if coord in s.cells:
                ship = s
                break
        if ship:
            all_hit = all(board.grid[rr][cc] == 3 for rr, cc in ship.cells)
            if all_hit:
                ship.alive = False
                for rr, cc in ship.cells:
                    board.grid[rr][cc] = 4
                mark_contour(board, ship.cells)
                board.highlight = ship.cells.copy()
                return KILL
        board.highlight = [coord]
        return HIT
    return MISS


def update_history(
    history: List[List[List[object]]],
    boards: Dict[str, Board15],
    coord: Tuple[int, int],
    results: Dict[str, str],
) -> None:
    """Update global shot history grid based on results for the shot."""

    r, c = coord
    if any(res == KILL for res in results.values()):
        for key, res in results.items():
            if res != KILL:
                continue
            board = boards[key]
            ship = next((s for s in board.ships if coord in s.cells), None)
            if not ship:
                continue
            for rr, cc in ship.cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < 15 and 0 <= nc < 15:
                            _set_cell_state(
                                history,
                                nr,
                                nc,
                                5,
                                _get_cell_owner(history[nr][nc]),
                            )
            for rr, cc in ship.cells:
                _set_cell_state(history, rr, cc, 4, key)
    elif any(res == HIT for res in results.values()):
        for key, res in results.items():
            if res == HIT:
                _set_cell_state(history, r, c, 3, key)
    elif all(res == MISS for res in results.values()):
        if _get_cell_state(history[r][c]) == 0 and all(
            _get_cell_state(boards[k].grid[r][c]) != 1 for k in results
        ):
            _set_cell_state(history, r, c, 2)
