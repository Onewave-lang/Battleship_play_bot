from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest

from game_board15 import router, storage, placement, parser
from game_board15.models import Match15, Player


class DummyBot:
    def __init__(self):
        self.sent_photos: list[tuple[int, str]] = []
        self.sent_messages: list[tuple[tuple, dict]] = []

    async def send_photo(self, chat_id, buf, caption):
        self.sent_photos.append((chat_id, caption))
        return SimpleNamespace(message_id=len(self.sent_photos))

    async def send_message(self, *args, **kwargs):
        self.sent_messages.append((args, kwargs))
        return SimpleNamespace(message_id=len(self.sent_messages))


class DummyMessage:
    def __init__(self, text: str):
        self.text = text

    async def reply_text(self, *args, **kwargs):
        return None


def _safe_coord(match: Match15) -> tuple[int, int]:
    for r in range(15):
        for c in range(15):
            if all(board.grid[r][c] == 0 for board in match.boards.values()):
                return r, c
    raise AssertionError("No safe coordinate found")


def test_three_player_snapshots_increment_each_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")

    match = storage.create_match(1, 101, "Alpha")
    match = storage.join_match(match.match_id, 2, 202, "Beta")
    match = storage.join_match(match.match_id, 3, 303, "Gamma")

    storage.save_board(match, "A", placement.random_board())
    storage.save_board(match, "B", placement.random_board())
    storage.save_board(match, "C", placement.random_board())

    initial_snapshots = len(match.snapshots)
    assert initial_snapshots == 1

    captured_boards: list[tuple[str, list[list[int]]]] = []

    def fake_render_board(state, player_key):
        board_copy = [row[:] for row in state.board]
        captured_boards.append((player_key, board_copy))
        return BytesIO(b"x")

    monkeypatch.setattr(router, "render_board", fake_render_board)

    async def play_turns():
        context = SimpleNamespace(bot=DummyBot(), bot_data={}, chat_data={})
        order = ["A", "B", "C"]
        for expected in order:
            current = storage.get_match(match.match_id)
            coord = _safe_coord(current)
            coord_text = parser.format_coord(coord)
            player = current.players[expected]
            update = SimpleNamespace(
                message=DummyMessage(coord_text),
                effective_user=SimpleNamespace(id=player.user_id),
                effective_chat=SimpleNamespace(id=player.chat_id),
            )
            await router.router_text(update, context)

    asyncio.run(play_turns())

    updated = storage.get_match(match.match_id)
    assert len(updated.snapshots) == initial_snapshots + 3
    assert len(captured_boards) > 0


def test_send_state_prefers_latest_snapshot(monkeypatch):
    match = Match15.new(1, 111, "Alpha")
    match.players["B"] = Player(user_id=2, chat_id=222, name="Beta", ready=True)
    match.players["C"] = Player(user_id=3, chat_id=333, name="Gamma", ready=True)

    base_grid = [[0 for _ in range(15)] for _ in range(15)]
    base_grid[0][0] = 1
    snapshot_history = [[[0, None] for _ in range(15)] for _ in range(15)]
    snapshot_history[0][1] = [2, "B"]
    snapshot = {
        "timestamp": "now",
        "move": 0,
        "actor": None,
        "coord": None,
        "next_turn": "A",
        "history": snapshot_history,
        "last_highlight": [(0, 1)],
        "boards": {
            "A": {
                "grid": [row[:] for row in base_grid],
                "ships": [],
                "alive_cells": 20,
            },
            "B": {
                "grid": [[0 for _ in range(15)] for _ in range(15)],
                "ships": [],
                "alive_cells": 20,
            },
            "C": {
                "grid": [[0 for _ in range(15)] for _ in range(15)],
                "ships": [],
                "alive_cells": 20,
            },
        },
    }
    match.snapshots = [snapshot]
    match.history = [[[0, None] for _ in range(15)] for _ in range(15)]
    match.last_highlight = []

    captured = {}

    def fake_render_board(state, player_key):
        captured["board"] = [row[:] for row in state.board]
        captured["owners"] = [row[:] for row in state.owners]
        captured["highlight"] = list(state.highlight)
        return BytesIO(b"x")

    class Bot:
        async def send_photo(self, *args, **kwargs):
            return SimpleNamespace(message_id=1)

    context = SimpleNamespace(bot=Bot(), bot_data={}, chat_data={})
    monkeypatch.setattr(router, "render_board", fake_render_board)

    asyncio.run(router._send_state(context, match, "A", "test"))

    assert captured["board"][0][0] == 1
    assert captured["board"][0][1] == 2
    assert captured["owners"][0][1] == "B"
    assert captured["highlight"] == [(0, 1)]


def test_send_state_hides_intact_enemy_ships(monkeypatch):
    match = Match15.new(1, 111, "Alpha")
    match.players["B"] = Player(user_id=2, chat_id=222, name="Beta", ready=True)
    match.players["C"] = Player(user_id=3, chat_id=333, name="Gamma", ready=True)

    # Own ship for player A and intact ship for player B
    match.boards["A"].grid[0][0] = 1
    match.boards["B"].grid[0][1] = 1
    match.boards["B"].grid[1][1] = 1

    # Record a hit on player B at (1, 1)
    match.history = [[[0, None] for _ in range(15)] for _ in range(15)]
    match.history[1][1] = [3, "B"]

    snapshot = {
        "timestamp": "now",
        "move": 0,
        "actor": None,
        "coord": None,
        "next_turn": "A",
        "history": [row[:] for row in match.history],
        "last_highlight": [],
        "boards": {
            "A": {
                "grid": [[0 for _ in range(15)] for _ in range(15)],
                "ships": [],
                "alive_cells": 20,
            },
            "B": {
                "grid": [[0 for _ in range(15)] for _ in range(15)],
                "ships": [],
                "alive_cells": 20,
            },
            "C": {
                "grid": [[0 for _ in range(15)] for _ in range(15)],
                "ships": [],
                "alive_cells": 20,
            },
        },
    }
    snapshot["boards"]["A"]["grid"][0][0] = 0  # force mismatch for own board
    snapshot["boards"]["B"]["grid"][0][1] = 0  # force mismatch for enemy board
    snapshot["boards"]["B"]["grid"][1][1] = 1  # keep hit cell owner information
    match.snapshots = [snapshot]

    captured: dict[str, list] = {}

    def fake_render_board(state, player_key):
        captured["board"] = [row[:] for row in state.board]
        captured["owners"] = [row[:] for row in state.owners]
        return BytesIO(b"x")

    class Bot:
        async def send_photo(self, *args, **kwargs):
            return SimpleNamespace(message_id=1)

    context = SimpleNamespace(bot=Bot(), bot_data={}, chat_data={})
    monkeypatch.setattr(router, "render_board", fake_render_board)

    asyncio.run(router._send_state(context, match, "A", "test"))

    # Own ships remain visible, intact enemy ships preserved by snapshot, hits visible
    assert captured["board"][0][0] == 1
    assert captured["owners"][0][0] == "A"
    assert captured["board"][0][1] == 1
    assert captured["owners"][0][1] == "B"
    assert captured["board"][1][1] == 3
    assert captured["owners"][1][1] == "B"

    # Snapshot grids refreshed for both own and enemy boards
    refreshed_snapshot = match.snapshots[-1]
    assert refreshed_snapshot["boards"]["A"]["grid"][0][0] == 1
    assert refreshed_snapshot["boards"]["B"]["grid"][0][1] == 1
