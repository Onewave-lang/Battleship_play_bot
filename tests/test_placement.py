import random
from models import Board
from logic.placement import place_ship, random_board


def test_vertical_start_row_respects_ship_size(monkeypatch):
    board = Board()
    monkeypatch.setattr(random, 'choice', lambda seq: 'v')
    calls = []
    def fake_randint(a, b):
        calls.append((a, b))
        return a
    monkeypatch.setattr(random, 'randint', fake_randint)
    place_ship(board, 4)
    assert calls[0] == (0, 6)
    assert calls[1] == (0, 9)
    for r, c in board.ships[0].cells:
        assert 0 <= r < 10
        assert 0 <= c < 10


def test_random_board_ship_count():
    board = random_board()
    total = sum(cell == 1 for row in board.grid for cell in row)
    assert total == 20
