import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, ANY

from game_board15 import router, storage


def test_router_auto_sends_boards(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='placing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, ready=True),
                'B': SimpleNamespace(user_id=2, chat_id=20, ready=False),
            },
            boards={
                'A': SimpleNamespace(grid=[[0] * 15 for _ in range(15)]),
                'B': SimpleNamespace(grid=[[0] * 15 for _ in range(15)]),
            },
            turn='A',
        )

        def fake_save_board(m, key, board):
            m.boards[key] = board
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(router.placement, 'random_board', lambda: SimpleNamespace(grid=[[0] * 15 for _ in range(15)]))
        monkeypatch.setattr(router, 'render_board', lambda state: BytesIO(b'test'))
        monkeypatch.setattr(router, '_keyboard', lambda: 'kb')

        send_photo = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_photo=send_photo))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=2),
        )

        await router.router_text(update, context)

        assert send_photo.call_args_list == [
            call(10, ANY, caption='Соперник готов. Бой начинается! Ваш ход.', reply_markup='kb'),
            call(20, ANY, caption='Корабли расставлены. Бой начинается! Ход соперника.', reply_markup='kb'),
        ]

    asyncio.run(run_test())

