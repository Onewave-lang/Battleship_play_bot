from __future__ import annotations
from typing import Dict, Tuple, List, Union

from models import Board
from .battle import apply_shot, mark_contour, MISS, HIT, KILL, REPEAT


def _get_cell_state(cell: Union[int, List[int], Tuple[int, str]]) -> int:
    return cell[0] if isinstance(cell, (list, tuple)) else cell


def _set_cell_state(grid: List[List[Union[int, List[int]]]], r: int, c: int, value: int) -> None:
    cell = grid[r][c]
    if isinstance(cell, list):
        cell[0] = value
    else:
        grid[r][c] = value


def apply_shot_multi(
    coord: Tuple[int, int],
    boards: Dict[str, Board],
    history: List[List[Union[int, List[int]]]],
) -> Dict[str, str]:
    """Apply a shot to multiple opponent boards and update global history.

    Parameters
    ----------
    coord: tuple
        Shot coordinate (row, col).
    boards: dict
        Mapping of opponent keys to their boards.
    history: list[list[int]]
        Global shot history grid shared between all players.

    Returns
    -------
    dict
        Mapping of opponent keys to the result of the shot
        (``miss``, ``hit`` or ``kill``).
    """

    results: Dict[str, str] = {}
    killed: List[List[Tuple[int, int]]] = []

    # Apply the shot to every opponent board
    for key, board in boards.items():
        res = apply_shot(board, coord)
        results[key] = res
        if res == KILL:
            # ``apply_shot`` sets ``highlight`` to ship cells on kill
            killed.append(board.highlight[:])

    r, c = coord
    if killed:
        # For every killed ship, mark its contour on all boards and history
        for cells in killed:
            for b in boards.values():
                mark_contour(b, cells)
            for rr, cc in cells:
                _set_cell_state(history, rr, cc, 4)
            for rr, cc in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < 10 and 0 <= nc < 10:
                            if _get_cell_state(history[nr][nc]) == 0:
                                _set_cell_state(history, nr, nc, 5)
        _set_cell_state(history, r, c, 4)
    elif any(res == HIT for res in results.values()):
        _set_cell_state(history, r, c, 3)
    elif all(res == MISS for res in results.values()):
        if _get_cell_state(history[r][c]) == 0:
            _set_cell_state(history, r, c, 2)

    return results
