import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers import board_test
from handlers import router as router_std
import storage
from models import Board, Match, Player


def test_auto_play_bots_skips_unrelated_human_updates(monkeypatch):
    async def run():
        match = Match.new(1, 100)
        match.players["B"] = Player(user_id=0, chat_id=200, name="B")
        match.players["C"] = Player(user_id=0, chat_id=300, name="C")
        match.status = "playing"
        match.turn = "B"

        state_calls: list[tuple[str, str]] = []

        async def fake_send_state(context, match_, player_key, message):
            state_calls.append((player_key, message))

        monkeypatch.setattr(router_std, "_send_state_board_test", fake_send_state)

        shots = {"count": 0}

        def fake_apply_shot_multi(coord, enemy_boards, history):
            shots["count"] += 1
            for board in enemy_boards.values():
                board.highlight = [coord]
            if shots["count"] == 1:
                return {
                    "A": board_test.battle.MISS,
                    "C": board_test.battle.HIT,
                }
            raise RuntimeError("stop")

        monkeypatch.setattr(board_test.battle, "apply_shot_multi", fake_apply_shot_multi)
        monkeypatch.setattr(board_test.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(board_test, "_phrase_or_joke", lambda *args, **kwargs: "")
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "finish", lambda m, w: None)
        monkeypatch.setattr(storage, "get_match", lambda mid: match)

        orig_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await board_test._auto_play_bots(match, context, 0, human="A", delay=0)

        assert state_calls == []
        context.bot.send_message.assert_not_called()

    asyncio.run(run())


def test_available_bot_targets_skip_diagonal_from_wounded() -> None:
    board = Board()
    board.grid[5][5] = 3

    targets = board_test._available_bot_targets(board)

    assert (4, 4) not in targets
    assert (4, 6) not in targets
    assert (6, 4) not in targets
    assert (6, 6) not in targets
    assert (5, 6) in targets

