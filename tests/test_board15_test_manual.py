import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, router, storage
from game_board15.models import Board15, Ship, Match15


def test_board15_test_manual(monkeypatch):
    async def run():
        # prepare deterministic boards: A has ship at o15, B at a1, C at b1
        def make_board(coord):
            b = Board15()
            r, c = coord
            b.grid = [[0] * 15 for _ in range(15)]
            b.grid[r][c] = 1
            b.ships = [Ship(cells=[(r, c)])]
            b.alive_cells = 1
            return b
        boards = iter([
            make_board((14, 14)),  # A
            make_board((0, 0)),    # B
            make_board((0, 1)),    # C
        ])
        monkeypatch.setattr(handlers.placement, "random_board_global", lambda mask: next(boards))

        # in-memory match handling
        match = Match15.new(1, 100, "Tester")
        monkeypatch.setattr(storage, "create_match", lambda uid, cid, name: match)
        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        finished = {}
        def fake_finish(m, w):
            finished["winner"] = w
        monkeypatch.setattr(storage, "finish", fake_finish)

        # renderers
        monkeypatch.setattr(handlers, "render_board", lambda *a, **k: BytesIO())
        monkeypatch.setattr(router, "render_board", lambda *a, **k: BytesIO())

        # capture background tasks
        tasks = []
        orig_create_task = asyncio.create_task
        def fake_create_task(coro):
            t = orig_create_task(coro)
            tasks.append(t)
            return t
        monkeypatch.setattr(asyncio, "create_task", fake_create_task)

        calls: list[tuple[str, str]] = []

        async def reply_text(msg):
            calls.append(("text", msg))
            return SimpleNamespace()

        async def reply_photo(buf, caption=None):
            calls.append(("photo", caption))
            return SimpleNamespace(message_id=1)

        update = SimpleNamespace(
            message=SimpleNamespace(
                reply_text=reply_text,
                reply_photo=reply_photo,
                text="",
            ),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=100),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=3)),
            ),
            bot_data={},
        )

        await handlers.board15_test(update, context)

        # ensure start text sent before board image
        assert calls[0][0] == "text"
        assert calls[1][0] == "photo"

        state = context.bot_data[handlers.STATE_KEY][update.effective_chat.id]
        assert state.owners[14][14] == "A"

        # first human move: miss at c3
        update.message.reply_text = AsyncMock()
        update.message.text = "c3"
        await router.router_text(update, context)
        assert match.turn == "B"
        assert update.message.reply_text.call_count == 0

        # wait for bots to play until our turn again
        while match.turn != "A":
            await asyncio.sleep(0.05)

        # second human move: sink B at a1
        update.message.reply_text.reset_mock()
        update.message.text = "a1"
        await router.router_text(update, context)
        assert update.message.reply_text.call_count == 0

        # allow background tasks to finish
        await asyncio.gather(*tasks)

        assert finished.get("winner") == "A"
        messages = [c.args[1] for c in context.bot.send_message.call_args_list]
        assert any("Вы победили" in m for m in messages)

    asyncio.run(run())
