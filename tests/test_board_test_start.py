import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers.board_test import board_test
from handlers import router
import storage
from logic import placement
from models import Match, Board

def test_board_test_start_order(monkeypatch):
    async def run():
        match = Match.new(1, 100)
        monkeypatch.setattr(storage, "create_match", lambda uid, cid: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(placement, "random_board_global", lambda mask: Board())

        calls: list[str] = []

        async def reply_text(msg):
            calls.append("text")
            return SimpleNamespace()

        async def fake_send_state(context, match_, key, message):
            calls.append("send_state")

        monkeypatch.setattr(router, "_send_state_board_test", fake_send_state)

        orig_create_task = asyncio.create_task

        def fake_create_task(coro):
            coro.close()
            return orig_create_task(asyncio.sleep(0))

        monkeypatch.setattr(asyncio, "create_task", fake_create_task)

        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=100),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock()), bot_data={})

        await board_test(update, context)

        assert calls[:2] == ["text", "send_state"]

    asyncio.run(run())
