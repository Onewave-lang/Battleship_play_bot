from __future__ import annotations
import random
from typing import List, Tuple

from models import Board, Ship

SHIP_SIZES = [4,3,3,2,2,2,1,1,1,1]


def can_place(grid: List[List[int]], ship_cells: List[Tuple[int,int]]) -> bool:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    for r, c in ship_cells:
        if not (0 <= r < rows and 0 <= c < cols):
            return False
        if grid[r][c] != 0:
            return False
        # check neighbors
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                nr, nc = r+dr, c+dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    if grid[nr][nc] != 0:
                        # allow if neighbor cell is part of ship itself later? but since grid[r][c]==0 already, safe
                        return False
    return True


def place_ship(board: Board, size: int) -> None:
    placed = False
    while not placed:
        orient = random.choice(['h','v'])
        if orient == 'h':
            r = random.randint(0,9)
            c = random.randint(0,10-size)
        else:
            r = random.randint(0,10-size)
            c = random.randint(0,9)
        cells = []
        for i in range(size):
            rr = r + (i if orient=='v' else 0)
            cc = c + (i if orient=='h' else 0)
            cells.append((rr,cc))
        if can_place(board.grid, cells):
            ship = Ship(cells=cells)
            board.ships.append(ship)
            for rr, cc in cells:
                board.grid[rr][cc] = 1
            placed = True


def random_board() -> Board:
    board = Board()
    for size in SHIP_SIZES:
        place_ship(board, size)
    return board


def random_board_global(global_mask: List[List[int]]) -> Board:
    """Generate a board avoiding cells marked in ``global_mask``.

    ``global_mask`` uses ``1`` to denote cells that are occupied or touch ships
    of previously placed fleets.  The mask is updated in-place with the newly
    placed fleet so that subsequent calls will avoid those areas as well.
    """

    if global_mask:
        mask_rows = len(global_mask)
        mask_cols = min((len(row) for row in global_mask), default=0)
        board_size = min(mask_rows, mask_cols) if mask_rows and mask_cols else 10
    else:
        board_size = 10

    def _cell_clear(mask: List[List[int]], r: int, c: int) -> bool:
        if r < 0 or c < 0:
            return False
        if r >= len(mask):
            return True
        row = mask[r]
        if c >= len(row):
            return True
        return row[c] == 0

    while True:
        board = Board()
        if len(board.grid) != board_size or (board.grid and len(board.grid[0]) != board_size):
            board.grid = [[0] * board_size for _ in range(board_size)]
        mask = [row[:] for row in global_mask]
        success = True

        for size in SHIP_SIZES:
            placed = False
            for _ in range(500):
                orient = random.choice(['h', 'v'])
                if orient == 'h':
                    r = random.randint(0, board_size - 1)
                    c = random.randint(0, board_size - size)
                else:
                    r = random.randint(0, board_size - size)
                    c = random.randint(0, board_size - 1)

                cells: List[Tuple[int, int]] = []
                for i in range(size):
                    rr = r + (i if orient == 'v' else 0)
                    cc = c + (i if orient == 'h' else 0)
                    cells.append((rr, cc))

                if not all(_cell_clear(mask, rr, cc) for rr, cc in cells):
                    continue
                if not can_place(board.grid, cells):
                    continue

                ship = Ship(cells=cells)
                board.ships.append(ship)
                for rr, cc in cells:
                    board.grid[rr][cc] = 1
                for rr, cc in cells:
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            nr, nc = rr + dr, cc + dc
                            if nr < 0 or nc < 0:
                                continue
                            if nr >= len(mask):
                                continue
                            if nc >= len(mask[nr]):
                                continue
                            mask[nr][nc] = 1
                placed = True
                break

            if not placed:
                success = False
                break

        if not success:
            continue

        for r in range(len(mask)):
            row_len = len(mask[r])
            for c in range(row_len):
                if mask[r][c]:
                    global_mask[r][c] = 1
        return board
