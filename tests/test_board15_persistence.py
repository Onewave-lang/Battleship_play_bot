from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import battle, router
from game_board15.models import Board15, Ship
from tests.utils import _new_grid, _state


def test_sequence_of_moves_preserves_history():
    history = _new_grid(15)
    boards = {"A": Board15(), "B": Board15()}

    # Human player A shoots at bot B (miss)
    res = battle.apply_shot(boards["B"], (0, 0))
    battle.update_history(history, boards, (0, 0), {"B": res})

    # Bot B shoots back at A (miss)
    res2 = battle.apply_shot(boards["A"], (1, 1))
    battle.update_history(history, boards, (1, 1), {"A": res2})

    assert _state(history[0][0]) == 2
    assert _state(history[1][1]) == 2


def test_hit_is_rendered(monkeypatch):
    async def run():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15(), "B": Board15()},
            history=_new_grid(15),
            messages={"A": {}},
        )

        ship = Ship(cells=[(0, 0), (0, 1)])
        match.boards["B"].ships = [ship]
        match.boards["B"].grid[0][0] = 1
        match.boards["B"].grid[0][1] = 1

        res = battle.apply_shot(match.boards["B"], (0, 0))
        assert res == battle.HIT
        battle.update_history(match.history, match.boards, (0, 0), {"B": res})

        captured = {}

        def fake_render_board(state, player_key=None):
            captured["board"] = [row[:] for row in state.board]
            return BytesIO(b"img")

        monkeypatch.setattr(router, "render_board", fake_render_board)
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(context, match, "A", "msg")

        assert captured["board"][0][0] == 3

    import asyncio
    asyncio.run(run())


def test_highlight_turns_into_history(monkeypatch):
    async def run():
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=1, name="A"),
                "B": SimpleNamespace(user_id=0, chat_id=0, name="B"),
            },
            boards={"A": Board15(), "B": Board15()},
            turn="A",
            shots={"A": {"history": [], "move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
            last_highlight=[],
        )

        # Previous shot highlight that wasn't yet fixed in history
        match.boards["B"].highlight = [(0, 0)]

        monkeypatch.setattr(router.storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (1, 1))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "b2")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router, "_send_state", AsyncMock())
        monkeypatch.setattr(router.battle, "apply_shot", lambda board, coord: battle.MISS)

        update = SimpleNamespace(
            message=SimpleNamespace(text="b2", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={}, chat_data={})

        await router.router_text(update, context)

        assert _state(match.history[0][0]) == 2
        assert match.boards["B"].highlight == []

    import asyncio
    asyncio.run(run())

