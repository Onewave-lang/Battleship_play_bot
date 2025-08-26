import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.models import Board15


def test_send_state_updates_inline_keyboard(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'status': 11}},
        )

        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'img'))
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))
        kb = object()
        monkeypatch.setattr(router, '_keyboard', lambda: kb)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=50)),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        bot.edit_message_reply_markup.assert_awaited_once_with(
            chat_id=1, message_id=10, reply_markup=kb
        )

    asyncio.run(run_test())
