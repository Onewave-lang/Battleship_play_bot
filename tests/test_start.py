import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, ANY

from handlers.commands import start, choose_mode


def test_start_shows_logo_and_menu(monkeypatch):
    async def run_test():
        reply_photo = AsyncMock()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_photo=reply_photo, reply_text=reply_text),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(user_data={})

        await start(update, context)

        assert reply_photo.call_args_list == [call(ANY, caption='Добро пожаловать в игру!')]
        assert reply_text.call_args_list == [call('Выберите режим игры:', reply_markup=ANY)]

        texts = [reply_photo.call_args_list[0].kwargs.get('caption', '')]
        texts.append(reply_text.call_args_list[0].args[0])
        assert all('/newgame' not in t for t in texts)

    asyncio.run(run_test())


def test_choose_mode_two_players():
    async def run_test():
        reply_text = AsyncMock()
        query = SimpleNamespace(
            data='mode_2',
            message=SimpleNamespace(reply_text=reply_text),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace()

        await choose_mode(update, context)

        assert reply_text.call_args_list == [
            call('Перед началом игры напишите, как вас представить сопернику.'),
            call('Введите имя одним сообщением (например: Иван).'),
        ]
        assert query.answer.call_count == 1

    asyncio.run(run_test())
