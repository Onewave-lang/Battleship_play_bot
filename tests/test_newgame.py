import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, ANY

import storage
from handlers.commands import newgame


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
            call(f'Пригласите друга: {link}'),
            call('Матч создан. Ожидаем подключения соперника.'),
        ]

    asyncio.run(run_test())
