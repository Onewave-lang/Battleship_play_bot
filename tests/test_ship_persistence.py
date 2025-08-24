from models import Board, Ship
from logic.battle import apply_shot, HIT, KILL
import storage


def test_kill_after_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    match = storage.create_match(1, 100)
    storage.join_match(match.match_id, 2, 200)

    board_b = Board()
    ship = Ship(cells=[(0, 0), (1, 0)])
    board_b.ships = [ship]
    board_b.grid[0][0] = 1
    board_b.grid[1][0] = 1
    board_b.alive_cells = 2

    storage.save_board(match, "B", board_b)
    storage.save_board(match, "A", Board())

    loaded = storage.get_match(match.match_id)

    assert apply_shot(loaded.boards["B"], (0, 0)) == HIT
    assert apply_shot(loaded.boards["B"], (1, 0)) == KILL

    assert loaded.boards["B"].grid[0][1] == 5
    assert loaded.boards["B"].grid[2][0] == 5
