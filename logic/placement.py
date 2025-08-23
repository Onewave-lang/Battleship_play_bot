from __future__ import annotations
import random
from typing import List, Tuple

from models import Board, Ship

SHIP_SIZES = [4,3,3,2,2,2,1,1,1,1]


def can_place(grid: List[List[int]], ship_cells: List[Tuple[int,int]]) -> bool:
    for r, c in ship_cells:
        if not (0 <= r < 10 and 0 <= c < 10):
            return False
        if grid[r][c] != 0:
            return False
        # check neighbors
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                nr, nc = r+dr, c+dc
                if 0 <= nr <10 and 0 <= nc <10:
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
        else:
            r = random.randint(0,9)
        if orient == 'h':
            c = random.randint(0,10-size)
        else:
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
