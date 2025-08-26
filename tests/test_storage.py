import threading
from logic.placement import random_board
import storage
from datetime import datetime, timedelta
from models import Board, Ship


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


def test_concurrent_save_board_separate_objects(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    base = storage.create_match(1, 100)
    storage.join_match(base.match_id, 2, 200)

    board_a = Board()
    board_a.grid[0][0] = 1
    board_a.ships = [Ship(cells=[(0, 0)])]
    board_a.alive_cells = 1

    board_b = Board()
    board_b.grid[9][9] = 1
    board_b.ships = [Ship(cells=[(9, 9)])]
    board_b.alive_cells = 1

    barrier = threading.Barrier(2)

    def worker(key, board):
        m = storage.get_match(base.match_id)
        barrier.wait()
        storage.save_board(m, key, board)

    t1 = threading.Thread(target=worker, args=("A", board_a))
    t2 = threading.Thread(target=worker, args=("B", board_b))
    t1.start(); t2.start()
    t1.join(); t2.join()

    updated = storage.get_match(base.match_id)
    assert updated.status == "playing"
    assert updated.players["A"].ready and updated.players["B"].ready
    assert updated.boards["A"].grid[0][0] == 1
    assert updated.boards["B"].grid[9][9] == 1


def _set_time(match, dt):
    """Helper to set created_at and persist match."""
    match.created_at = dt.isoformat()
    storage.save_match(match)


def test_find_match_by_user_returns_latest_active(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    base = datetime(2023, 1, 1)

    m1 = storage.create_match(1, 100)
    _set_time(m1, base)

    m2 = storage.create_match(1, 200)
    m2.status = "placing"
    _set_time(m2, base + timedelta(seconds=1))

    m3 = storage.create_match(1, 300)
    m3.status = "playing"
    _set_time(m3, base + timedelta(seconds=2))

    found = storage.find_match_by_user(1)
    assert found.match_id == m3.match_id


def test_find_match_by_user_ignores_finished(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    base = datetime(2023, 1, 1)

    active = storage.create_match(1, 100)
    active.status = "playing"
    _set_time(active, base)

    finished = storage.create_match(1, 200)
    finished.status = "finished"
    _set_time(finished, base + timedelta(seconds=1))

    finished_only = storage.create_match(2, 300)
    finished_only.status = "finished"
    _set_time(finished_only, base + timedelta(seconds=2))

    assert storage.find_match_by_user(1).match_id == active.match_id
    assert storage.find_match_by_user(2) is None


def test_find_match_by_user_prefers_chat(monkeypatch, tmp_path):
    """When user participates in multiple matches, chat_id narrows the search."""
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data.json")
    m1 = storage.create_match(1, 100)
    m1.status = "playing"
    storage.save_match(m1)
    m2 = storage.create_match(1, 200)
    m2.status = "playing"
    storage.save_match(m2)

    assert storage.find_match_by_user(1, chat_id=100).match_id == m1.match_id
    # unknown chat_id falls back to latest by created_at
    assert storage.find_match_by_user(1, chat_id=999).match_id == m2.match_id
