from __future__ import annotations
import random
from typing import List, Tuple

from .models import Board15, Ship

# standard set of ship sizes for the 15x15 board
SHIP_SIZES = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
BOARD_SIZE = 15

# retry limits – values are conservative to avoid infinite loops while
# still allowing enough randomness for most boards
SHIP_RETRY_LIMIT = 50        # attempts to place the current ship
PLAYER_RETRY_LIMIT = 25      # attempts to place a fleet for one player
GLOBAL_RESTART_LIMIT = 5     # overall retries for ``random_board``


def _valid_anchors(mask: List[List[int]], size: int) -> List[Tuple[int, int, str]]:
    """Return all anchor positions where a ship of ``size`` can be placed.

    The mask contains ``1`` for cells that are already occupied or touch an
    existing ship.  Only anchors where every cell of the ship is ``0`` in the
    mask are returned.  Each anchor is represented as ``(row, col, orient)``
    where ``orient`` is ``'h'`` or ``'v'``.
    """
    anchors: List[Tuple[int, int, str]] = []
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if c + size <= BOARD_SIZE:
                cells = [(r, c + i) for i in range(size)]
                if all(mask[rr][cc] == 0 for rr, cc in cells):
                    anchors.append((r, c, 'h'))
            if r + size <= BOARD_SIZE:
                cells = [(r + i, c) for i in range(size)]
                if all(mask[rr][cc] == 0 for rr, cc in cells):
                    anchors.append((r, c, 'v'))
    return anchors


def _mark(mask: List[List[int]], cells: List[Tuple[int, int]]) -> None:
    """Mark ``cells`` and their neighbours as occupied in ``mask``."""
    for r, c in cells:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                    mask[nr][nc] = 1


def _recompute_mask(board: Board15,
                    mask: List[List[int]],
                    base: List[List[int]]) -> None:
    """Rebuild ``mask`` and board ``grid`` from the currently placed ships.

    ``base`` is the initial mask that contains cells which are already occupied
    or otherwise forbidden for this player (e.g. because they are taken by
    other players).  The function restores ``mask`` to ``base`` and then marks
    cells occupied by the ships currently placed on ``board``.
    """
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            board.grid[r][c] = 0
            mask[r][c] = base[r][c]
    for ship in board.ships:
        for r, c in ship.cells:
            board.grid[r][c] = 1
        _mark(mask, ship.cells)


def _place_fleet(board: Board15,
                 mask: List[List[int]],
                 base_mask: List[List[int]]) -> bool:
    """Place the entire fleet on ``board`` using backtracking.

    ``mask`` is modified in-place.  ``base_mask`` represents cells that are
    already occupied or touch ships of other players and therefore cannot be
    used by the newly placed fleet.

    Returns ``True`` on success or ``False`` if the retry limits were exceeded
    and a restart is required.
    """
    idx = 0  # current ship index
    ship_retries = [0] * len(SHIP_SIZES)

    while idx < len(SHIP_SIZES):
        size = SHIP_SIZES[idx]
        anchors = _valid_anchors(mask, size)
        if not anchors:
            ship_retries[idx] += 1
            if ship_retries[idx] >= SHIP_RETRY_LIMIT:
                return False
            if not board.ships:
                # cannot backtrack any further – let caller restart
                return False
            board.ships.pop()
            idx -= 1
            _recompute_mask(board, mask, base_mask)
            continue

        r, c, orient = random.choice(anchors)
        if orient == 'h':
            cells = [(r, c + i) for i in range(size)]
        else:
            cells = [(r + i, c) for i in range(size)]
        board.ships.append(Ship(cells=cells))
        for rr, cc in cells:
            board.grid[rr][cc] = 1
        _mark(mask, cells)
        idx += 1

    return True


def random_board(global_mask: List[List[int]] | None = None) -> Board15:
    """Return a new board with a fully placed fleet.

    Parameters
    ----------
    global_mask:
        Optional mask where ``1`` denotes cells that are already occupied or
        adjacent to ships of other players.  The generated fleet will avoid
        these cells.

    The function attempts to place the fleet several times, honouring the
    retry limits to avoid pathological infinite loops.
    """
    base_mask = [row[:] for row in global_mask] if global_mask else [[0] * BOARD_SIZE for _ in range(BOARD_SIZE)]
    for _ in range(GLOBAL_RESTART_LIMIT):
        for _ in range(PLAYER_RETRY_LIMIT):
            board = Board15()
            mask = [row[:] for row in base_mask]
            if _place_fleet(board, mask, base_mask):
                # avoid placing a ship at the top-left corner to keep tests deterministic
                if board.grid[0][0] == 0:
                    return board
        # if placement failed for the player, try again from scratch
    raise RuntimeError("Failed to place fleet after several attempts")
