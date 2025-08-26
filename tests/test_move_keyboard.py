import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import GameState, move_keyboard, handle_text


def test_move_keyboard_has_five_by_five():
    kb = move_keyboard(GameState())
    assert len(kb.inline_keyboard) == 5
    assert all(len(row) == 5 for row in kb.inline_keyboard)


def test_keyboard_reappears_after_second_move():
    async def run_test():
        state = GameState()
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[
                SimpleNamespace(message_id=10),
                SimpleNamespace(message_id=20),
            ]),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, chat_data={"game_state": state})
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))
        await handle_text(update, context)
        assert state.keyboard_msg_id == 10
        await handle_text(update, context)
        bot.delete_message.assert_awaited_once_with(chat_id=1, message_id=10)
        assert state.keyboard_msg_id == 20
    asyncio.run(run_test())
