import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from game_board15 import router
from game_board15.models import Board15


def test_send_state_sends_board_without_keyboard(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'player': 20}},
        )

        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'img'))
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=50)),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=60)),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        bot.edit_message_media.assert_awaited_once()
        bot.edit_message_text.assert_not_called()
        bot.send_photo.assert_awaited_once()
        bot.send_message.assert_awaited_once()
        call_photo = bot.send_photo.await_args
        assert call_photo.args[0] == 1
        assert 'caption' not in call_photo.kwargs
        assert 'reply_markup' not in call_photo.kwargs
        assert bot.delete_message.await_count == 0
        assert match.messages['A']['board'] == 50
        assert match.messages['A']['text'] == 60

    asyncio.run(run_test())

def test_send_state_edits_existing_messages(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'player': 20, 'text': 30}},
        )

        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'img'))
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        assert bot.edit_message_media.await_count == 2
        bot.edit_message_text.assert_awaited_once()
        bot.send_photo.assert_not_called()
        bot.send_message.assert_not_called()
        bot.delete_message.assert_not_called()
        assert match.messages['A']['board'] == 10
        assert match.messages['A']['text'] == 30

    asyncio.run(run_test())


def test_send_state_recreates_messages_on_edit_failure(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'player': 20, 'text': 30}},
        )

        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'img'))
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(side_effect=[None, Exception()]),
            edit_message_text=AsyncMock(side_effect=Exception()),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=40)),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=41)),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        assert bot.edit_message_media.await_count == 2
        bot.edit_message_text.assert_awaited_once()
        assert bot.delete_message.await_args_list == [call(1, 10), call(1, 30)]
        bot.send_photo.assert_awaited_once()
        bot.send_message.assert_awaited_once()
        assert match.messages['A']['board'] == 40
        assert match.messages['A']['text'] == 41

    asyncio.run(run_test())
