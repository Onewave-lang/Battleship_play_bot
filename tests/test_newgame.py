import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, ANY

import storage
from handlers.commands import newgame, send_invite_link


def test_newgame_message_sequence(monkeypatch):
    async def run_test():
        match = SimpleNamespace(match_id='m1')
        monkeypatch.setattr(storage, 'create_match', lambda user_id, chat_id: match)

        reply_text = AsyncMock()
        reply_photo = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text, reply_photo=reply_photo),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='TestBot')))
        context = SimpleNamespace(bot=bot)

        await newgame(update, context)

        link = f"https://t.me/TestBot?start=inv_{match.match_id}"
        assert reply_photo.call_args_list == [call(ANY, caption='Добро пожаловать в игру!')]
        assert reply_text.call_args_list == [
            call('Подождите, подготавливаем игровую среду...'),
            call('Среда игры готова.'),
            call('Выберите способ приглашения соперника:', reply_markup=ANY),
            call('Матч создан. Ожидаем подключения соперника.'),
        ]

    asyncio.run(run_test())


def test_send_invite_link(monkeypatch):
    async def run_test():
        match = SimpleNamespace(match_id='m1')
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        reply_text = AsyncMock()
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(reply_text=reply_text),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='TestBot')))
        context = SimpleNamespace(bot=bot)

        await send_invite_link(update, context)

        link = f"https://t.me/TestBot?start=inv_{match.match_id}"
        assert reply_text.call_args_list == [call(f'Пригласите друга: {link}')]
        assert query.answer.call_count == 1

    asyncio.run(run_test())
