from __future__ import annotations
from typing import Dict, Tuple, List

from models import Board
from .battle import apply_shot, mark_contour, MISS, HIT, KILL, REPEAT


def apply_shot_multi(
    coord: Tuple[int, int],
    boards: Dict[str, Board],
    history: List[List[int]],
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
                history[rr][cc] = 4
            for rr, cc in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < 10 and 0 <= nc < 10:
                            if history[nr][nc] == 0:
                                history[nr][nc] = 5
        history[r][c] = 4
    elif any(res == HIT for res in results.values()):
        history[r][c] = 3
    elif all(res == MISS for res in results.values()):
        if history[r][c] == 0:
            history[r][c] = 2

    return results
