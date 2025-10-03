import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import GameState, handle_text


def test_handle_text_replaces_previous_prompt():
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
        assert state.prompt_msg_id == 10
        first_call = bot.send_message.await_args_list[0]
        assert "reply_markup" not in first_call.kwargs
        assert first_call.kwargs["text"].startswith("Введите координату")

        await handle_text(update, context)
        bot.delete_message.assert_awaited_once_with(chat_id=1, message_id=10)
        assert state.prompt_msg_id == 20

    asyncio.run(run_test())
