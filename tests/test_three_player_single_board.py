import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

from models import Board, Ship, Match
from logic.battle import KILL, MISS
from logic.battle_test import apply_shot_multi
from game_board15 import handlers, storage, router
from game_board15.models import Match15, Board15, Ship as Ship15, Player
from tests.utils import _new_grid


def mask_from_board(board):
    mask = [[0] * 10 for _ in range(10)]
    for ship in board.ships:
        for r, c in ship.cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < 10 and 0 <= nc < 10:
                        mask[nr][nc] = 1
    return mask


def _place_single_ship(mask):
    cells = [(r, c) for r in range(10) for c in range(10) if mask[r][c] == 0]
    coord = random.choice(cells)
    board = Board()
    board.grid = _new_grid()
    ship = Ship(cells=[coord])
    board.ships.append(ship)
    board.grid[coord[0]][coord[1]] = [1, None]
    board.alive_cells = 1
    bm = mask_from_board(board)
    for r in range(10):
        for c in range(10):
            if bm[r][c]:
                mask[r][c] = 1
    return board


def test_auto_placement_no_overlap():
    random.seed(0)
    mask = [[0] * 10 for _ in range(10)]
    boards = {k: _place_single_ship(mask) for k in ("A", "B", "C")}
    masks = {k: mask_from_board(b) for k, b in boards.items()}
    for a in ("A", "B", "C"):
        for b in ("A", "B", "C"):
            if a >= b:
                continue
            for ship in boards[a].ships:
                for r, c in ship.cells:
                    assert masks[b][r][c] == 0


def test_game_ends_after_two_fleets_destroyed():
    match = Match.new(1, 1)
    positions = {"A": (9, 9), "B": (0, 0), "C": (2, 2)}
    for key, coord in positions.items():
        board = Board()
        board.grid = _new_grid()
        ship = Ship(cells=[coord])
        board.ships.append(ship)
        board.grid[coord[0]][coord[1]] = [1, key]
        board.alive_cells = 1
        match.boards[key] = board
    history = _new_grid()
    res1 = apply_shot_multi((0, 0), {"B": match.boards["B"], "C": match.boards["C"]}, history)
    assert res1 == {"B": KILL, "C": MISS}
    res2 = apply_shot_multi((2, 2), {"B": match.boards["B"], "C": match.boards["C"]}, history)
    assert res2 == {"B": MISS, "C": KILL}
    alive = [k for k, b in match.boards.items() if b.alive_cells > 0]
    assert alive == ["A"]
    assert history[0][0][0] == 4
    assert history[2][2][0] == 4


def test_apply_shot_multi_updates_history():
    board_b = Board()
    board_b.grid = _new_grid()
    board_c = Board()
    board_c.grid = _new_grid()
    ship_b = Ship(cells=[(1, 1)])
    board_b.ships.append(ship_b)
    board_b.grid[1][1] = [1, 'B']
    board_b.alive_cells = 1
    ship_c = Ship(cells=[(3, 3)])
    board_c.ships.append(ship_c)
    board_c.grid[3][3] = [1, 'C']
    board_c.alive_cells = 1
    history = _new_grid()
    res1 = apply_shot_multi((1, 1), {"B": board_b, "C": board_c}, history)
    assert res1 == {"B": KILL, "C": MISS}
    assert history[1][1][0] == 4
    assert history[0][0][0] == 5
    res2 = apply_shot_multi((3, 3), {"B": board_b, "C": board_c}, history)
    assert res2 == {"B": MISS, "C": KILL}
    assert history[3][3][0] == 4


def test_auto_play_bots_sequence_and_history(monkeypatch):
    async def run():
        match = Match15.new(1, 1, "A")
        match.players["B"] = Player(user_id=0, chat_id=1, name="B")
        match.players["C"] = Player(user_id=0, chat_id=1, name="C")
        match.status = "playing"
        match.turn = "B"
        def place(board: Board15, coord):
            ship = Ship15(cells=[coord])
            board.ships = [ship]
            board.grid[coord[0]][coord[1]] = 1
            board.alive_cells = 1
        place(match.boards["A"], (0, 0))
        place(match.boards["B"], (14, 14))
        place(match.boards["C"], (0, 2))
        recorded = []
        orig_apply = handlers.battle.apply_shot

        def record(board, coord):
            if not recorded or recorded[-1] != coord:
                recorded.append(coord)
            return orig_apply(board, coord)
        monkeypatch.setattr(handlers.battle, "apply_shot", record)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "get_match", lambda mid: match)
        winners = []
        monkeypatch.setattr(storage, "finish", lambda m, w: winners.append(w))
        monkeypatch.setattr(router, "_send_state", AsyncMock())
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})
        async def fast_sleep(t):
            pass
        monkeypatch.setattr(asyncio, "sleep", fast_sleep)
        await handlers._auto_play_bots(match, context, 0, human="A")
        assert recorded == [(0, 0), (0, 2)]
        for r, c in [(0, 0), (0, 2), (0, 1)]:
            match.history[r][c] = [match.history[r][c], None]
        assert match.history[0][0][0] == 4
        assert match.history[0][2][0] == 4
        assert match.history[0][1][0] == 5
        assert winners == ["B"]
    asyncio.run(run())
