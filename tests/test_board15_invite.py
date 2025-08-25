import asyncio
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, ANY

# Provide minimal Pillow stub to satisfy imports in game_board15.renderer
pil = types.ModuleType('PIL')
pil.Image = types.SimpleNamespace()
pil.ImageDraw = types.SimpleNamespace()
pil.ImageFont = types.SimpleNamespace()
sys.modules.setdefault('PIL', pil)

from handlers.commands import start
from game_board15 import handlers as h
from game_board15 import storage as storage15


def test_board15_invite_flow(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            match_id='m1',
            players={'A': SimpleNamespace(user_id=1, chat_id=1, name='Alice')},
            boards={'A': SimpleNamespace(grid=[[0] * 15 for _ in range(15)])},
            messages={},
        )
        monkeypatch.setattr(storage15, 'create_match', lambda uid, cid, name=None: match)
        monkeypatch.setattr(storage15, 'save_match', lambda m: None)
        monkeypatch.setattr(h, 'render_board', lambda state: BytesIO(b'test'))
        reply_text = AsyncMock()
        reply_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text, reply_photo=reply_photo),
            effective_user=SimpleNamespace(id=1, first_name='Alice'),
            effective_chat=SimpleNamespace(id=1),
        )
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='TestBot')))
        context = SimpleNamespace(bot=bot, chat_data={}, bot_data={})

        await h.board15(update, context)

        link = f"https://t.me/TestBot?start=b15_{match.match_id}"
        assert reply_text.call_args_list == [
            call('Выберите способ приглашения соперников:', reply_markup=ANY),
            call('Матч создан. Ожидаем подключения соперников.'),
            call('Выберите клетку или введите ход текстом.'),
        ]
        assert reply_photo.call_args_list == [call(ANY, reply_markup=ANY)]

    asyncio.run(run_test())


def test_send_board15_invite_link(monkeypatch):
    async def run_test():
        match = SimpleNamespace(match_id='m1')
        monkeypatch.setattr(storage15, 'find_match_by_user', lambda uid: match)
        reply_text = AsyncMock()
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(reply_text=reply_text),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='TestBot')))
        context = SimpleNamespace(bot=bot, bot_data={})

        await h.send_board15_invite_link(update, context)

        link = f"https://t.me/TestBot?start=b15_{match.match_id}"
        assert reply_text.call_args_list == [call(f'Пригласите друга: {link}')]
        assert query.answer.call_count == 1

    asyncio.run(run_test())


def test_start_board15_join(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(user_id=1, chat_id=1, ready=False, name='Alice')},
        )
        monkeypatch.setattr(storage15, 'join_match', lambda mid, uid, cid, name=None: match)
        reply_text = AsyncMock()
        reply_photo = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text, reply_photo=reply_photo),
            effective_user=SimpleNamespace(id=2, first_name='Bob'),
            effective_chat=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(args=['b15_m1'], bot=bot, bot_data={})

        await start(update, context)

        assert reply_photo.call_count == 1
        assert reply_text.call_args_list == [
            call('Вы присоединились к матчу. Отправьте "авто" для расстановки.'),
            call('Используйте @ в начале сообщения, чтобы отправить сообщение соперникам в чат игры.'),
        ]
        assert bot.send_message.call_args_list == [
            call(1, 'Соперник присоединился. Отправьте "авто" для расстановки.'),
            call(1, 'Используйте @ в начале сообщения, чтобы отправить сообщение соперникам в чат игры.'),
        ]

    asyncio.run(run_test())

