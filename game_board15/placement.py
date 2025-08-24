from __future__ import annotations
import random
from typing import List, Tuple

from .models import Board15, Ship

SHIP_SIZES = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]


def can_place(grid: List[List[int]], ship_cells: List[Tuple[int, int]]) -> bool:
    for r, c in ship_cells:
        if not (0 <= r < 15 and 0 <= c < 15):
            return False
        if grid[r][c] != 0:
            return False
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < 15 and 0 <= nc < 15:
                    if grid[nr][nc] != 0:
                        return False
    return True


def place_ship(board: Board15, size: int) -> None:
    placed = False
    while not placed:
        orient = random.choice(['h', 'v'])
        if orient == 'h':
            r = random.randint(0, 14)
            c = random.randint(0, 15 - size)
        else:
            r = random.randint(0, 15 - size)
            c = random.randint(0, 14)
        cells = []
        for i in range(size):
            rr = r + (i if orient == 'v' else 0)
            cc = c + (i if orient == 'h' else 0)
            cells.append((rr, cc))
        if can_place(board.grid, cells):
            ship = Ship(cells=cells)
            board.ships.append(ship)
            for rr, cc in cells:
                board.grid[rr][cc] = 1
            placed = True


def random_board() -> Board15:
    board = Board15()
    for size in SHIP_SIZES:
        place_ship(board, size)
    return board
