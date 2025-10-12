"""Automatic fleet placement for the 15×15 shared board."""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

from .models import Board15, Ship, PLAYER_ORDER

Coord = Tuple[int, int]

SHIP_LAYOUT = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
MAX_ATTEMPTS = 5000


def _neighbors(coord: Coord) -> List[Coord]:
    r, c = coord
    out: List[Coord] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < 15 and 0 <= nc < 15:
                out.append((nr, nc))
    return out


def _can_place(board: Board15, mask: List[List[bool]], cells: List[Coord]) -> bool:
    for r, c in cells:
        if not (0 <= r < 15 and 0 <= c < 15):
            return False
        if board.grid[r][c] != 0:
            return False
        if mask[r][c]:
            return False
    return True


def _reserve(mask: List[List[bool]], cells: List[Coord]) -> None:
    for cell in cells:
        for nr, nc in [(cell[0], cell[1]), * _neighbors(cell)]:
            mask[nr][nc] = True


def generate_field() -> Tuple[Board15, Dict[str, List[Ship]]]:
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        board = Board15()
        mask = [[False] * 15 for _ in range(15)]
        fleets: Dict[str, List[Ship]] = {key: [] for key in PLAYER_ORDER}
        success = True
        for owner in PLAYER_ORDER:
            for size in SHIP_LAYOUT:
                placed = False
                for _ in range(200):
                    horizontal = random.choice([True, False])
                    if horizontal:
                        r = random.randrange(15)
                        c = random.randrange(15 - size + 1)
                        cells = [(r, c + offset) for offset in range(size)]
                    else:
                        r = random.randrange(15 - size + 1)
                        c = random.randrange(15)
                        cells = [(r + offset, c) for offset in range(size)]
                    if not _can_place(board, mask, cells):
                        continue
                    ship = Ship(cells=cells, owner=owner)
                    fleets[owner].append(ship)
                    for r_cell, c_cell in cells:
                        board.grid[r_cell][c_cell] = 1
                        board.owners[r_cell][c_cell] = owner
                    _reserve(mask, cells)
                    placed = True
                    break
                if not placed:
                    success = False
                    break
            if not success:
                break
        if success:
            board.ships = fleets
            return board, fleets
    raise RuntimeError("Failed to place fleets on the 15×15 board after many attempts")


__all__ = ["generate_field"]
