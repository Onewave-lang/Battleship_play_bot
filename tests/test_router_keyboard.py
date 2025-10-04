import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers import router


def test_send_state_sends_new_board_message_and_updates_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=50)),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        bot.send_message.assert_awaited_once()
        call_args = bot.send_message.await_args
        assert call_args.args[0] == 1
        assert 'reply_markup' not in call_args.kwargs
        assert match.messages['A']['board'] == 50
        assert match.messages['A']['board_history'] == [50]
        assert 'text' not in match.messages['A']

    asyncio.run(run_test())


def test_send_state_appends_new_board_messages_to_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {'board': 10, 'board_history': [10]}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=20)),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        bot.send_message.assert_awaited_once()
        assert match.messages['A']['board'] == 20
        assert match.messages['A']['board_history'] == [10, 20]

    asyncio.run(run_test())


def test_send_state_initialises_history_if_missing(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {'board': 10}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=60)),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        assert match.messages['A']['board'] == 60
        assert match.messages['A']['board_history'] == [60]
        assert 'text' not in match.messages['A']

    asyncio.run(run_test())
