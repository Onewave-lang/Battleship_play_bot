from models import Board
from logic.render import render_board_own, render_board_enemy


def test_render_board_own_and_enemy():
    board = Board()
    board.grid[0][0] = 1
    board.grid[0][1] = 2
    board.grid[0][2] = 3
    board.grid[0][3] = 4
    board.grid[0][4] = 5
    own = render_board_own(board).replace('<pre>', '').replace('</pre>', '').splitlines()
    enemy = render_board_enemy(board).replace('<pre>', '').replace('</pre>', '').splitlines()
    assert own[1] == " 1 □ x ■ ▓ x · · · · ·"
    assert enemy[1] == " 1 · x ■ ▓ x · · · · ·"
