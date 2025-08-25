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
            effective_user=SimpleNamespace(id=2),
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


def test_router_announces_second_place(monkeypatch):
    async def run_test():
        board_b = SimpleNamespace(grid=[[0] * 15 for _ in range(15)], ships=[], alive_cells=0)
        board_c = SimpleNamespace(
            grid=[[0] * 15 for _ in range(15)],
            ships=[SimpleNamespace(cells=[(0, 0)], alive=True)],
            alive_cells=1,
        )
        board_c.grid[0][0] = 1
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10),
                'B': SimpleNamespace(user_id=2, chat_id=20),
                'C': SimpleNamespace(user_id=3, chat_id=30),
            },
            boards={'A': SimpleNamespace(alive_cells=20), 'B': board_b, 'C': board_c},
            turn='A',
            shots={
                'A': {'history': [], 'move_count': 0, 'joke_start': 10},
                'B': {'history': [], 'move_count': 0, 'joke_start': 10},
                'C': {'history': [], 'move_count': 0, 'joke_start': 10},
            },
            messages={},
            eliminated=['B'],
            eliminated_segments={'B': 0},
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(router, '_send_state', AsyncMock())
        monkeypatch.setattr(router, '_phrase_or_joke', lambda *args: '')
        monkeypatch.setattr(router.parser, 'parse_coord', lambda t: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda c: 'a1')

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message), chat_data={})
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
        )

        await router.router_text(update, context)

        assert send_message.call_args_list == [
            call(20, 'a1 - соперник промахнулся. '),
            call(30, 'a1 - ваш корабль уничтожен. '),
            call(30, 'Все ваши корабли уничтожены. Вы выбыли.'),
            call(10, 'Вы победили! Второе место занял игрок C.'),
            call(20, 'Игра окончена. Победил игрок A. Второе место занял игрок C.'),
            call(30, 'Игра окончена. Победил игрок A. Второе место занял игрок C.'),
        ]

    asyncio.run(run_test())

