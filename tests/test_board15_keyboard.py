from io import BytesIO
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.utils import _new_grid
from game_board15 import router
from game_board15.models import Board15, Ship


def _populate_full_fleet(board: Board15) -> None:
    coords = []
    for idx in range(20):
        r = idx // 5
        c = idx % 5
        board.grid[r][c] = 1
        coords.append((r, c))
    board.ships = [Ship(cells=coords)]
    board.alive_cells = len(coords)


def test_send_state_records_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15()},
            history=_new_grid(15),
            messages={"A": {"history_active": True, "board_history": [], "text_history": []}},
        )
        _populate_full_fleet(match.boards["A"])
        monkeypatch.setattr(router, "render_board", lambda state, player_key=None: BytesIO(b"img"))
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)
        bot = SimpleNamespace(
            send_photo=AsyncMock(side_effect=[SimpleNamespace(message_id=51)]),
            send_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})
        await router._send_state(context, match, "A", "msg")
        assert bot.send_photo.await_count == 1
        assert bot.send_message.await_count == 0
        assert match.messages["A"]["board"] == 51
        assert "text" not in match.messages["A"]
        assert match.messages["A"]["board_history"] == [51]
        assert match.messages["A"]["text_history"] == [51]
    asyncio.run(run_test())


def test_send_state_appends_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15()},
            history=_new_grid(15),
            messages={"A": {"history_active": True, "board_history": [], "text_history": []}},
        )
        _populate_full_fleet(match.boards["A"])
        monkeypatch.setattr(router, "render_board", lambda state, player_key=None: BytesIO(b"img"))
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)
        bot = SimpleNamespace(
            send_photo=AsyncMock(side_effect=[
                SimpleNamespace(message_id=11),
                SimpleNamespace(message_id=13),
            ]),
            send_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})
        await router._send_state(context, match, "A", "first")
        await router._send_state(context, match, "A", "second")
        assert bot.send_photo.await_count == 2
        assert bot.send_message.await_count == 0
        assert match.messages["A"]["board"] == 13
        assert "text" not in match.messages["A"]
        assert match.messages["A"]["board_history"] == [11, 13]
        assert match.messages["A"]["text_history"] == [11, 13]
    asyncio.run(run_test())


def test_history_not_recorded_when_inactive(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15()},
            history=_new_grid(15),
            messages={"A": {"history_active": False, "board_history": [], "text_history": []}},
        )
        _populate_full_fleet(match.boards["A"])
        monkeypatch.setattr(router, "render_board", lambda state, player_key=None: BytesIO(b"img"))
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)
        bot = SimpleNamespace(
            send_photo=AsyncMock(side_effect=[SimpleNamespace(message_id=1)]),
            send_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})
        await router._send_state(context, match, "A", "msg")
        assert match.messages["A"]["board_history"] == []
        assert match.messages["A"]["text_history"] == []
    asyncio.run(run_test())


def test_send_state_shows_own_ships_even_with_history_marks(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15()},
            history=_new_grid(15),
            messages={"A": {"history_active": False, "board_history": [], "text_history": []}},
        )
        _populate_full_fleet(match.boards["A"])
        match.boards["A"].grid[2][3] = 1
        match.history[2][3] = [3, "B"]

        captured = {}

        def fake_render(state, player_key=None):
            captured["board"] = [row[:] for row in state.board]
            captured["owners"] = [row[:] for row in state.owners]
            return BytesIO(b"img")

        monkeypatch.setattr(router, "render_board", fake_render)
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)
        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
            send_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, "A", "msg")

        assert captured["board"][2][3] == 1
        assert captured["owners"][2][3] == "A"

    asyncio.run(run_test())
