import threading
from logic.placement import random_board
import storage


def test_concurrent_save_board(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    match = storage.create_match(1, 100)
    storage.join_match(match.match_id, 2, 200)

    board_a = random_board()
    board_b = random_board()

    barrier = threading.Barrier(2)

    def worker(key, board):
        barrier.wait()
        storage.save_board(match, key, board)

    t1 = threading.Thread(target=worker, args=("A", board_a))
    t2 = threading.Thread(target=worker, args=("B", board_b))
    t1.start(); t2.start()
    t1.join(); t2.join()

    updated = storage.get_match(match.match_id)
    assert updated.status == "playing"
    assert updated.players["A"].ready and updated.players["B"].ready
    # match object passed into save_board should also be updated
    assert match.status == "playing"
    assert match.players["A"].ready and match.players["B"].ready
