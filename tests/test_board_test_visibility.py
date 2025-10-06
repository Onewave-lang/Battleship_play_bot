import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers import router
import storage


def _grid():
    return [[0] * 10 for _ in range(10)]


def test_router_text_board_test_skips_unaffected_enemy(monkeypatch):
    async def run():
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
                "C": SimpleNamespace(user_id=3, chat_id=30, name="C"),
            },
            boards={
                "A": SimpleNamespace(grid=_grid(), highlight=[], alive_cells=20),
                "B": SimpleNamespace(grid=_grid(), highlight=[], alive_cells=20),
                "C": SimpleNamespace(grid=_grid(), highlight=[], alive_cells=20),
            },
            turn="A",
            shots={
                "A": {"history": [], "move_count": 0, "joke_start": 10},
                "B": {"history": [], "move_count": 0, "joke_start": 10},
                "C": {"history": [], "move_count": 0, "joke_start": 10},
            },
            messages={"A": {}, "B": {}, "C": {}},
            history=_grid(),
            last_highlight=[],
        )

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda *args, **kwargs: "")
        monkeypatch.setattr(
            router,
            "apply_shot_multi",
            lambda coord, boards, history: {"B": router.HIT, "C": router.MISS},
        )
        monkeypatch.setattr(router.random, "choice", lambda seq: seq[0])

        calls: list[str] = []

        async def fake_send_state(context_obj, match_obj, player_key, message):
            calls.append(player_key)

        monkeypatch.setattr(router, "_send_state_board_test", fake_send_state)

        await router.router_text_board_test(update, context)

        assert calls.count("A") == 1
        assert calls.count("B") == 1
        assert calls.count("C") == 0

    asyncio.run(run())
