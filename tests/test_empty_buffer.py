import asyncio
import logging
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.models import Board15


def test_empty_buffer_skips_send(monkeypatch, caplog):
    async def run_test():
        match = SimpleNamespace(
            players={"A": SimpleNamespace(chat_id=1)},
            boards={"A": Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={"A": {}},
        )

        monkeypatch.setattr(router, "render_board", lambda state, player_key=None: BytesIO())
        monkeypatch.setattr(router, "render_player_board", lambda board, player_key=None: BytesIO(b"own"))
        monkeypatch.setattr(router.storage, "save_match", lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        with caplog.at_level(logging.WARNING):
            await router._send_state(context, match, "A", "msg")

        bot.send_photo.assert_not_called()
        assert "empty buffer" in caplog.text.lower()

    asyncio.run(run_test())
