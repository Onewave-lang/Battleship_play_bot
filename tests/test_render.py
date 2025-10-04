from logic.render import render_board_own, render_board_enemy
from logic.parser import ROWS
from logic.battle import apply_shot, KILL
from models import Board, Ship
from tests.utils import _new_grid, _state


def test_render_board_own_renders_ship_symbol():
    b = Board(owner='A')
    b.grid[0][0] = 1
    own = render_board_own(b)
    assert '■' in own


def test_render_board_enemy_marks_hit():
    b = Board(owner='A')
    b.grid[0][0] = 3
    enemy = render_board_enemy(b)
    assert '■' in enemy


def test_render_last_move_symbols():
    b = Board()
    b.grid = _new_grid()

    # miss highlight
    b.grid[0][0] = [2, 'A']
    b.highlight = [(0, 0)]
    own = render_board_own(b)
    assert "❌" in own
    b.highlight = []
    own = render_board_own(b)
    assert "❌" not in own
    assert 'x' in own

    # hit highlight
    b.grid[1][1] = [3, 'B']
    b.highlight = [(1, 1)]
    enemy = render_board_enemy(b)
    assert "🟥" in enemy
    b.highlight = []
    enemy = render_board_enemy(b)
    assert "🟥" not in enemy and '■' in enemy

    # kill highlight
    b.grid[2][2] = [4, 'B']
    b.grid[2][3] = [5, 'B']

    # highlight the kill cell
    b.highlight = [(2, 2)]
    enemy = render_board_enemy(b)
    assert enemy.count('🟥') == 1

    # highlight the contour cell
    b.highlight = [(2, 3)]
    enemy = render_board_enemy(b)
    assert '🟥' not in enemy
    assert enemy.count('❌') == 1

    # no highlight
    b.highlight = []
    enemy = render_board_enemy(b)
    assert '🟥' not in enemy and '❌' not in enemy
    assert '▓' in enemy
    assert 'x' in enemy


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

    assert 'x' in own
    assert 'x' in enemy


def _extract_lines(rendered: str):
    assert rendered.startswith('<pre>')
    assert rendered.endswith('</pre>')
    inner = rendered[len('<pre>'):-len('</pre>')]
    inner = inner.strip('\n')
    return inner.split('\n')


def test_render_axis_labels():
    board = Board()
    own_lines = _extract_lines(render_board_own(board))
    enemy_lines = _extract_lines(render_board_enemy(board))

    expected_header = ' '.join(ROWS)
    for lines in (own_lines, enemy_lines):
        header = lines[0].split('|', 1)[1].strip()
        assert header == expected_header
        row_labels = [line.split('|', 1)[0].strip() for line in lines[1:]]
        assert row_labels == [str(i) for i in range(1, 11)]
