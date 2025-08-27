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
        assert match.messages['A']['text'] == 'msg'
        assert match.messages['A']['text_id'] == 60
        assert match.messages['A']['text_history'] == [60]

    asyncio.run(run_test())

def test_send_state_edits_existing_messages(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'player': 20, 'text': 'old', 'text_id': 30, 'text_history': [30]}},
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
        assert match.messages['A']['text'] == 'msg'
        assert match.messages['A']['text_id'] == 30
        assert match.messages['A']['text_history'] == [30]

    asyncio.run(run_test())


def test_send_state_recreates_messages_on_edit_failure(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'player': 20, 'text': 'old', 'text_id': 30, 'text_history': [30]}},
        )

        board_buf = BytesIO(b'img')
        player_buf = BytesIO(b'own')
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: board_buf)
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: player_buf)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        async def edit_media(chat_id, message_id, media):
            if edit_media.calls == 0:
                edit_media.calls += 1
                return
            edit_media.calls += 1
            raise Exception()

        edit_media.calls = 0

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(side_effect=edit_media),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=40)),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        assert bot.edit_message_media.await_count == 2
        bot.edit_message_text.assert_awaited_once()
        assert bot.delete_message.await_args_list == [call(1, 10)]
        bot.send_photo.assert_awaited_once()
        bot.send_message.assert_not_called()
        assert board_buf.tell() == 0
        assert match.messages['A']['board'] == 40
        assert match.messages['A']['text'] == 'msg'
        assert match.messages['A']['text_id'] == 30
        assert match.messages['A']['text_history'] == [30]

    asyncio.run(run_test())


def test_send_state_recreates_player_board_on_edit_failure(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {'board': 10, 'player': 20, 'text': 'old', 'text_id': 30, 'text_history': [30]}},
        )

        board_buf = BytesIO(b'img')
        player_buf = BytesIO(b'own')
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: board_buf)
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: player_buf)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        async def edit_media(chat_id, message_id, media):
            if edit_media.calls == 0:
                edit_media.calls += 1
                raise Exception()
            edit_media.calls += 1
            return

        edit_media.calls = 0

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(side_effect=edit_media),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=40)),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')

        assert bot.edit_message_media.await_count == 2
        bot.edit_message_text.assert_awaited_once()
        assert bot.delete_message.await_args_list == [call(1, 20)]
        bot.send_photo.assert_awaited_once()
        assert bot.send_photo.await_args.args[1] is player_buf
        assert player_buf.tell() == 0
        bot.send_message.assert_not_called()
        assert match.messages['A']['player'] == 40
        assert match.messages['A']['board'] == 10
        assert match.messages['A']['text'] == 'msg'
        assert match.messages['A']['text_id'] == 30
        assert match.messages['A']['text_history'] == [30]


def test_send_state_avoids_duplicate_text(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {}},
        )

        board_buf = BytesIO(b'img')
        player_buf = BytesIO(b'own')
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: board_buf)
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: player_buf)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        bot = SimpleNamespace(
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_photo=AsyncMock(side_effect=[SimpleNamespace(message_id=40), SimpleNamespace(message_id=50)]),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=60)),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        await router._send_state(context, match, 'A', 'msg')
        await router._send_state(context, match, 'A', 'msg')

        assert bot.send_message.await_count == 1
        bot.edit_message_text.assert_not_called()
        assert match.messages['A']['text'] == 'msg'
        assert match.messages['A']['text_id'] == 60
        assert match.messages['A']['text_history'] == [60]

    asyncio.run(run_test())
