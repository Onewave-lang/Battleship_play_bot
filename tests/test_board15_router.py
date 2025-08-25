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
                'A': SimpleNamespace(user_id=1, chat_id=10, ready=True, name='Alice'),
                'B': SimpleNamespace(user_id=2, chat_id=20, ready=False, name='Bob'),
            },
            boards={
                'A': SimpleNamespace(grid=[[0] * 15 for _ in range(15)]),
                'B': SimpleNamespace(grid=[[0] * 15 for _ in range(15)]),
            },
            turn='A',
            messages={},
        )

        def fake_save_board(m, key, board):
            m.boards[key] = board
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.placement, 'random_board', lambda: SimpleNamespace(grid=[[0] * 15 for _ in range(15)]))
        monkeypatch.setattr(router, 'render_board', lambda state: BytesIO(b'test'))
        monkeypatch.setattr(router, '_keyboard', lambda: 'kb')

        send_photo = AsyncMock()
        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_photo=send_photo, send_message=send_message), chat_data={})
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=2, first_name='Bob'),
        )

        await router.router_text(update, context)

        assert send_photo.call_args_list == [
            call(10, ANY, reply_markup='kb'),
            call(20, ANY, reply_markup='kb'),
        ]
        assert send_message.call_args_list == [
            call(10, 'Соперник готов. Бой начинается! Ваш ход.'),
            call(20, 'Корабли расставлены. Бой начинается! Ход соперника.'),
        ]

    asyncio.run(run_test())


def test_router_uses_player_names(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, name='Alice'),
                'B': SimpleNamespace(user_id=2, chat_id=20, name='Bob'),
                'C': SimpleNamespace(user_id=3, chat_id=30, name='Carl'),
            },
            boards={
                'A': SimpleNamespace(alive_cells=20),
                'B': SimpleNamespace(alive_cells=20),
                'C': SimpleNamespace(alive_cells=20),
            },
            turn='A',
            shots={'A': {}, 'B': {}, 'C': {}},
            messages={'A': {}},
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.battle, 'apply_shot', lambda board, coord: router.battle.MISS)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        update = SimpleNamespace(message=SimpleNamespace(text='a1'), effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(chat_data={}, bot=SimpleNamespace(send_message=AsyncMock()))

        await router.router_text(update, context)

        msg = send_state.call_args[0][3]
        assert 'Bob' in msg and 'Carl' in msg
        assert 'B:' not in msg and 'C:' not in msg
        assert msg.strip().endswith('Ход Bob.')

    asyncio.run(run_test())

