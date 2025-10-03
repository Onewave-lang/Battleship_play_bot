from types import SimpleNamespace

import asyncio
from types import SimpleNamespace

from models import Board, Ship
from handlers import router
import storage
from unittest.mock import AsyncMock


def _new_grid():
    return [[0] * 10 for _ in range(10)]


def test_send_state_board_test_uses_match_highlight(monkeypatch):
    async def run_test():
        board = Board()
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            messages={"A": {}},
            history=_new_grid(),
            boards={"A": board},
            last_highlight=[(1, 1)],
            shots={"A": {"last_coord": (2, 2)}},
        )

        captured = {}

        def fake_render_board_own(b):
            captured["highlight"] = b.highlight.copy()
            return "board"

        monkeypatch.setattr(router, "render_board_own", fake_render_board_own)
        send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
        bot = SimpleNamespace(send_message=send_message)
        context = SimpleNamespace(bot=bot)
        async def fast_sleep(t):
            pass
        monkeypatch.setattr(asyncio, "sleep", fast_sleep)
        monkeypatch.setattr(storage, "save_match", lambda m: None)

        await router._send_state_board_test(context, match, "A", "msg")

        assert captured["highlight"] == [(1, 1)]

    asyncio.run(run_test())


def test_last_highlight_persists_after_kill(monkeypatch):
    async def run_test():
        board_self = Board()
        board_enemy = Board()
        ship = Ship(cells=[(0, 0)])
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
            shots={"A": {"history": [], "move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(),
            last_highlight=[],
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router, "_send_state_board_test", AsyncMock())

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router.router_text_board_test(update, context)

        assert match.last_highlight == [(0, 0)]
        board_enemy.highlight.clear()
        assert match.last_highlight == [(0, 0)]

    asyncio.run(run_test())

