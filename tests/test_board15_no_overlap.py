from game_board15 import storage, placement


def mask_from_board(board):
    mask = [[0] * 15 for _ in range(15)]
    for ship in board.ships:
        for r, c in ship.cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < 15 and 0 <= nc < 15:
                        mask[nr][nc] = 1
    return mask


def test_bots_do_not_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")

    match = storage.create_match(1, 1, "A")
    storage.join_match(match.match_id, 2, 2, "B")
    storage.join_match(match.match_id, 3, 3, "C")

    # human places fleet first
    storage.save_board(match, "A", placement.random_board())

    # bots place fleets automatically respecting existing ships
    storage.save_board(match, "B")
    storage.save_board(match, "C")

    masks = {k: mask_from_board(b) for k, b in match.boards.items()}
    for a in ("A", "B", "C"):
        for b in ("A", "B", "C"):
            if a >= b:
                continue
            for ship in match.boards[a].ships:
                for r, c in ship.cells:
                    assert masks[b][r][c] == 0
