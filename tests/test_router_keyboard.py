import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=50)),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        bot.send_message.assert_awaited_once()
        call = bot.send_message.await_args
        assert call.args[0] == 1
        assert call.kwargs['reply_markup'] is kb
        assert bot.delete_message.await_count == 0
        assert match.messages['A']['keyboard'] == 50

    asyncio.run(run_test())


def test_send_state_updates_keyboard(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            messages={'A': {'keyboard': 10}},
        )
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=60)),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot)

        await router._send_state(context, match, 'A', 'msg')

        bot.delete_message.assert_awaited_once_with(1, 10)
        call = bot.send_message.await_args
        assert call.kwargs['reply_markup'] is kb
        assert match.messages['A']['keyboard'] == 60

    asyncio.run(run_test())
