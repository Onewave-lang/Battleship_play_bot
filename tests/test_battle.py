from models import Board, Ship
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT


def test_apply_shot_miss_and_repeat():
    board = Board()
    assert apply_shot(board, (0, 0)) == MISS
    assert board.grid[0][0] == 2
    assert apply_shot(board, (0, 0)) == REPEAT


def test_apply_shot_kill_and_repeat():
    board = Board()
    ship = Ship(cells=[(0, 0)])
    board.ships.append(ship)
    board.grid[0][0] = 1
    board.alive_cells = 1
    assert apply_shot(board, (0, 0)) == KILL
    assert board.grid[0][0] == 4
    assert board.alive_cells == 0
    assert apply_shot(board, (0, 0)) == REPEAT


def test_apply_shot_highlight():
    board = Board()
    # miss highlight
    assert apply_shot(board, (0, 0)) == MISS
    assert board.highlight == [(0, 0)]
    # hit/kill highlight
    ship = Ship(cells=[(1, 1)])
    board.ships.append(ship)
    board.grid[1][1] = 1
    board.alive_cells = 1
    assert apply_shot(board, (1, 1)) == KILL
    assert board.highlight == [(1, 1)]
