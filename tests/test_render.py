from logic.render import render_board_own, render_board_enemy, PLAYER_COLORS
from logic.battle import apply_shot, KILL
from models import Board, Ship
from tests.utils import _new_grid, _state


def test_render_board_own_uses_board_owner_color():
    b = Board(owner='A')
    b.grid[0][0] = 1
    own = render_board_own(b)
    assert PLAYER_COLORS['A'] in own


def test_render_board_enemy_marks_hit_dark_red():
    b = Board(owner='B')
    b.grid[0][0] = 3
    enemy = render_board_enemy(b)
    assert "#8b0000" in enemy


def test_render_last_move_symbols():
    b = Board()
    b.grid = _new_grid()

    # miss highlight
    b.grid[0][0] = [2, 'A']
    b.highlight = [(0, 0)]
    own = render_board_own(b)
    assert "border:1px solid red" in own
    b.highlight = []
    own = render_board_own(b)
    assert "border:1px solid red" not in own and 'background-color:orange' in own

    # hit highlight
    b.grid[1][1] = [3, 'B']
    b.highlight = [(1, 1)]
    enemy = render_board_enemy(b)
    assert "border:1px solid red" in enemy and "#8b0000" in enemy
    b.highlight = []
    enemy = render_board_enemy(b)
    assert "border:1px solid red" not in enemy and "#8b0000" in enemy

    # kill highlight
    b.grid[2][2] = [4, 'B']
    b.grid[2][3] = [5, 'B']
    b.highlight = [(2, 3)]
    enemy = render_board_enemy(b)
    assert enemy.count('💣') >= 1
    assert enemy.count('background-color:orange') >= 1
    assert enemy.count("border:1px solid red") == 1
    b.highlight = []
    enemy = render_board_enemy(b)
    assert enemy.count('💣') >= 1 and "border:1px solid red" not in enemy


def test_apply_shot_marks_contour():
    b = Board()
    b.grid = _new_grid()
    ship = Ship(cells=[(5, 5)])
    b.ships = [ship]
    b.grid[5][5] = [1, 'A']
    b.alive_cells = 1

    res = apply_shot(b, (5, 5))
    assert res == KILL
    # all surrounding cells become 5 (miss markers)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            nr, nc = 5 + dr, 5 + dc
            if dr == 0 and dc == 0:
                continue
            if 0 <= nr < 10 and 0 <= nc < 10:
                assert _state(b.grid[nr][nc]) == 5
