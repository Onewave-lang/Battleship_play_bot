from models import Board
from logic.render import render_board_own, render_board_enemy
from wcwidth import wcswidth


def _lines(text: str):
    return [l.rstrip() for l in text.replace('<pre>', '').replace('</pre>', '').splitlines()]


def test_render_board_own_and_enemy():
    board = Board()
    board.grid[0][0] = 1
    board.grid[0][1] = 2
    board.grid[0][2] = 3
    board.grid[0][3] = 4
    board.grid[0][4] = 5
    own = _lines(render_board_own(board))
    enemy = _lines(render_board_enemy(board))
    assert own[1] == " 1 □ x ■ ▓ x · · · · ·"
    assert enemy[1] == " 1 · x ■ ▓ x · · · · ·"
    assert all(wcswidth(l) == 22 for l in own)
    assert all(wcswidth(l) == 22 for l in enemy)


def test_render_highlight_last_move():
    board = Board()
    # miss highlight
    board.grid[0][0] = 2
    board.highlight = [(0, 0)]
    own = _lines(render_board_own(board))
    enemy = _lines(render_board_enemy(board))
    assert own[1].startswith(" 1 x́")
    assert enemy[1].startswith(" 1 x́")
    assert wcswidth(own[1]) == wcswidth(enemy[1]) == 22
    # hit highlight
    board.grid[0][0] = 3
    board.highlight = [(0, 0)]
    own = _lines(render_board_own(board))
    assert own[1].startswith(" 1 ■́")
    assert wcswidth(own[1]) == 22
    # kill highlight
    board.grid[0][0] = 4
    board.grid[0][1] = 4
    board.highlight = [(0, 0), (0, 1)]
    own = _lines(render_board_own(board))
    enemy = _lines(render_board_enemy(board))
    assert own[1].startswith(" 1 💣💣")
    assert enemy[1].startswith(" 1 💣💣")
    assert wcswidth(own[1]) == wcswidth(enemy[1]) == 22
    # after next move (no highlight)
    board.highlight = []
    own = _lines(render_board_own(board))
    enemy = _lines(render_board_enemy(board))
    assert own[1].startswith(" 1 ▓ ▓")
    assert enemy[1].startswith(" 1 ▓ ▓")
    assert wcswidth(own[1]) == wcswidth(enemy[1]) == 22
