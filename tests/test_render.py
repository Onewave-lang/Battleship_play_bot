from logic.render import render_board_own, render_board_enemy
from logic.battle import apply_shot, KILL
from models import Board, Ship


def test_render_last_move_symbols():
    b = Board()

    # miss highlight
    b.grid[0][0] = 2
    b.highlight = [(0, 0)]
    own = render_board_own(b)
    assert '❌' in own
    b.highlight = []
    own = render_board_own(b)
    assert '❌' not in own and 'x' in own

    # hit highlight
    b.grid[1][1] = 3
    b.highlight = [(1, 1)]
    enemy = render_board_enemy(b)
    assert '🟥' in enemy
    b.highlight = []
    enemy = render_board_enemy(b)
    assert '🟥' not in enemy and '■' in enemy

    # kill highlight
    b.grid[2][2] = 4
    b.grid[2][3] = 4
    b.highlight = [(2, 2), (2, 3)]
    enemy = render_board_enemy(b)
    assert enemy.count('💣') == 2
    b.highlight = []
    enemy = render_board_enemy(b)
    assert '💣' not in enemy and '▓' in enemy


def test_apply_shot_marks_contour():
    b = Board()
    ship = Ship(cells=[(5, 5)])
    b.ships = [ship]
    b.grid[5][5] = 1
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
                assert b.grid[nr][nc] == 5
