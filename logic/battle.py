from __future__ import annotations
from typing import Tuple

from models import Board, Ship


MISS, HIT, KILL, REPEAT = 'miss', 'hit', 'kill', 'repeat'


def mark_contour(board: Board, cells: list[Tuple[int,int]]) -> None:
    for r, c in cells:
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                nr, nc = r+dr, c+dc
                if 0 <= nr < 10 and 0 <= nc < 10:
                    if board.grid[nr][nc][0] == 0:
                        board.grid[nr][nc][0] = 5
                        board.grid[nr][nc][1] = None


def apply_shot(board: Board, coord: Tuple[int,int]) -> str:
    board.highlight = []
    r, c = coord
    cell = board.grid[r][c]
    state = cell[0]
    if state in (2,3,4,5):
        board.highlight = [coord]
        return REPEAT  # already shot here or around
    if state == 0:
        board.grid[r][c][0] = 2
        board.grid[r][c][1] = None
        board.highlight = [coord]
        return MISS
    if state == 1:
        board.grid[r][c][0] = 3
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
                if board.grid[rr][cc] != 3:  # some not hit yet
                    all_hit = False
                    break
            if all_hit:
                ship.alive = False
                for rr, cc in ship.cells:
                    board.grid[rr][cc][0] = 4
                mark_contour(board, ship.cells)
                board.highlight = ship.cells.copy()
                return KILL
        board.highlight = [coord]
        return HIT
    return MISS
