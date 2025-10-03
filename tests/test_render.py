import pytest
from logic.render import (
    render_board_own,
    render_board_enemy,
    PLAYER_COLORS,
    PLAYER_COLORS_DARK,
)
from logic.battle import apply_shot, KILL
from models import Board, Ship
from tests.utils import _new_grid, _state
from constants import BOMB


def test_render_board_own_uses_board_owner_color():
    b = Board(owner='A')
    b.grid[0][0] = 1
    own = render_board_own(b)
    assert PLAYER_COLORS['A'] in own
@pytest.mark.parametrize(
    "owner, expected",
    [
        ("A", PLAYER_COLORS_DARK["A"]),
        ("B", PLAYER_COLORS_DARK["B"]),
        ("C", PLAYER_COLORS_DARK["C"]),
    ],
)
def test_render_board_enemy_marks_hit_player_color(owner, expected):
    b = Board(owner=owner)
    b.grid[0][0] = 3
    enemy = render_board_enemy(b)
    assert expected in enemy


def test_render_last_move_symbols():
    b = Board()
    b.grid = _new_grid()

    # miss highlight
    b.grid[0][0] = [2, 'A']
    b.highlight = [(0, 0)]
    own = render_board_own(b)
    assert "<b>✖</b>" in own
    b.highlight = []
    own = render_board_own(b)
    assert "<b>✖</b>" not in own
    assert '✖' in own

    # hit highlight
    b.grid[1][1] = [3, 'B']
    b.highlight = [(1, 1)]
    enemy = render_board_enemy(b)
    assert f"<b>{PLAYER_COLORS_DARK['B']}</b>" in enemy
    b.highlight = []
    enemy = render_board_enemy(b)
    assert f"<b>{PLAYER_COLORS_DARK['B']}</b>" not in enemy and PLAYER_COLORS_DARK['B'] in enemy

    # kill highlight
    b.grid[2][2] = [4, 'B']
    b.grid[2][3] = [5, 'B']

    # highlight the kill cell
    b.highlight = [(2, 2)]
    enemy = render_board_enemy(b)
    assert enemy.count(BOMB) == 1
    assert enemy.count('<b>') == 1

    # highlight the contour cell
    b.highlight = [(2, 3)]
    enemy = render_board_enemy(b)
    assert BOMB not in enemy
    assert enemy.count('⚠️') >= 1
    assert enemy.count('<b>') >= 1

    # no highlight
    b.highlight = []
    enemy = render_board_enemy(b)
    assert BOMB not in enemy and '<b>' not in enemy
    assert '💥' in enemy
    assert '✖' in enemy


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


def test_render_state5_symbol():
    b = Board()
    b.grid = _new_grid()
    b.grid[0][0] = [5, 'A']

    own = render_board_own(b)
    enemy = render_board_enemy(b)

    assert '•' in own
    assert '•' in enemy
