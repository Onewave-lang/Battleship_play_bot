from __future__ import annotations
from typing import Dict, Tuple, List

from models import Board
from .battle import apply_shot, mark_contour, MISS, HIT, KILL, REPEAT


def apply_shot_multi(
    coord: Tuple[int, int],
    boards: Dict[str, Board],
    history: List[List[list]],
) -> Dict[str, str]:
    """Apply a shot to multiple opponent boards and update global history.

    Parameters
    ----------
    coord: tuple
        Shot coordinate (row, col).
    boards: dict
        Mapping of opponent keys to their boards.
    history: list[list[list]]
        Global shot history grid shared between all players.  Each cell is
        ``[state, owner]`` where ``owner`` is the key of the board that owns
        the ship in that cell.

    Returns
    -------
    dict
        Mapping of opponent keys to the result of the shot
        (``miss``, ``hit`` or ``kill``).
    """

    results: Dict[str, str] = {}
    killed: List[Tuple[str, List[Tuple[int, int]]]] = []

    # Apply the shot to every opponent board
    for key, board in boards.items():
        res = apply_shot(board, coord)
        results[key] = res
        if res == KILL:
            # ``apply_shot`` sets ``highlight`` to ship cells on kill
            killed.append((board.owner, board.highlight[:]))

    r, c = coord
    if killed:
        # For every killed ship, mark its contour on all boards and history
        for owner, cells in killed:
            for b in boards.values():
                mark_contour(b, cells)
            for rr, cc in cells:
                history[rr][cc][0] = 4
                history[rr][cc][1] = owner
            for rr, cc in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < 10 and 0 <= nc < 10:
                            if history[nr][nc][0] == 0:
                                history[nr][nc] = [5, None]
        history[r][c][0] = 4
        history[r][c][1] = killed[0][0]
    elif any(res == HIT for res in results.values()):
        # owner of first board that registered a hit
        owner = next(board.owner for key, board in boards.items() if results[key] == HIT)
        history[r][c][0] = 3
        history[r][c][1] = owner
    elif all(res == MISS for res in results.values()):
        if history[r][c][0] == 0:
            history[r][c] = [2, None]

    return results
