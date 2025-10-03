import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router as router15
from game_board15.models import Board15, Ship as Ship15
from handlers import router as router_std
from models import Board, Ship
import storage
from tests.utils import _new_grid


def test_board15_router_updates_history_before_send(monkeypatch):
    async def run():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship15(cells=[(0, 0)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            messages={"A": {}, "B": {}},
            shots={"A": {"history": []}, "B": {}},
            history=_new_grid(15),
            last_highlight=[],
        )
        saved = False

        def fake_save_match(m):
            nonlocal saved
            saved = True

        monkeypatch.setattr(router15.storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router15.storage, "save_match", fake_save_match)
        monkeypatch.setattr(router15.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router15.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")

        captured = {}

        async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True):
            captured["cell"] = match_obj.history[0][0][0]
            captured["saved"] = saved

        monkeypatch.setattr(router15, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router15.router_text(update, context)

        assert captured["cell"] == 4
        assert not captured["saved"]
        assert saved

    asyncio.run(run())


def test_board_test_router_updates_history_before_send(monkeypatch):
    async def run():
        board_self = Board()
        board_enemy = Board()
        ship = Ship(cells=[(0, 0), (0, 1)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.grid[0][1] = 1
        board_enemy.alive_cells = 2
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"history": [], "move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=[[0] * 10 for _ in range(10)],
            last_highlight=[],
        )
        saved = False

        def fake_save_match(m):
            nonlocal saved
            saved = True

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", fake_save_match)
        monkeypatch.setattr(router_std, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router_std, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router_std, "_phrase_or_joke", lambda m, pk, ph: "")

        captured = {}

        async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True):
            captured["cell"] = match_obj.history[0][0]
            captured["saved"] = saved

        monkeypatch.setattr(router_std, "_send_state_board_test", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router_std.router_text_board_test(update, context)

        assert captured["cell"] == 3
        assert captured["saved"]

    asyncio.run(run())
