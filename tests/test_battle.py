from models import Board, Ship
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from tests.utils import _new_grid, _state


def test_apply_shot_miss_and_repeat():
    board = Board()
    board.grid = _new_grid()
    assert apply_shot(board, (0, 0)) == MISS
    assert _state(board.grid[0][0]) == 2
    assert apply_shot(board, (0, 0)) == REPEAT


def test_apply_shot_kill_and_repeat():
    board = Board()
    board.grid = _new_grid()
    ship = Ship(cells=[(0, 0)])
    board.ships.append(ship)
    board.grid[0][0] = [1, 'A']
    board.alive_cells = 1
    assert apply_shot(board, (0, 0)) == KILL
    assert _state(board.grid[0][0]) == 4
    assert board.alive_cells == 0
    assert apply_shot(board, (0, 0)) == REPEAT


def test_apply_shot_highlight():
    board = Board()
    board.grid = _new_grid()
    # miss highlight
    assert apply_shot(board, (0, 0)) == MISS
    assert board.highlight == [(0, 0)]
    # hit/kill highlight
    ship = Ship(cells=[(1, 1)])
    board.ships.append(ship)
    board.grid[1][1] = [1, 'A']
    board.alive_cells = 1
    assert apply_shot(board, (1, 1)) == KILL
    assert board.highlight == [(1, 1)]


def test_apply_shot_kill_marks_contour():
    board = Board()
    board.grid = _new_grid()
    ship = Ship(cells=[(1, 1), (1, 2)])
    board.ships.append(ship)
    board.grid[1][1] = [1, 'A']
    board.grid[1][2] = [1, 'A']
    board.alive_cells = 2
    assert apply_shot(board, (1, 1)) == HIT
    assert apply_shot(board, (1, 2)) == KILL
    assert _state(board.grid[0][0]) == 5
    assert _state(board.grid[2][3]) == 5
