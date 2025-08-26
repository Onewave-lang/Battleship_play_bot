import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from handlers import router


def test_send_state_sets_keyboard_on_new_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[
                SimpleNamespace(message_id=50),
                SimpleNamespace(message_id=51),
            ]),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        assert bot.send_message.await_count == 2
        first_call, second_call = bot.send_message.await_args_list
        assert first_call.args[0] == 1
        assert first_call.kwargs['reply_markup'] is kb
        assert 'reply_markup' not in second_call.kwargs
        assert bot.delete_message.await_count == 0
        assert match.messages['A']['board'] == 50
        assert match.messages['A']['text'] == 51

    asyncio.run(run_test())


def test_send_state_updates_keyboard(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {'board': 10, 'text': 11}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[
                SimpleNamespace(message_id=60),
                SimpleNamespace(message_id=61),
            ]),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        assert bot.delete_message.await_args_list == [call(1, 10), call(1, 11)]
        first_call, second_call = bot.send_message.await_args_list
        assert first_call.kwargs['reply_markup'] is kb
        assert 'reply_markup' not in second_call.kwargs
        assert match.messages['A']['board'] == 60
        assert match.messages['A']['text'] == 61

    asyncio.run(run_test())
