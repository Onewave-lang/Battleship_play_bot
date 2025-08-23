import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import storage
from handlers import router


def test_router_invalid_cell_shows_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            shots={'A': {'history': [], 'last_result': None},
                   'B': {'history': [], 'last_result': None}},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        update = SimpleNamespace(
            message=SimpleNamespace(text='63', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy\nНе понял клетку. Пример: е5 или д10.', parse_mode='HTML')
        ]
    asyncio.run(run_test())


def test_router_wrong_turn_shows_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='B',
            shots={'A': {'history': [], 'last_result': None},
                   'B': {'history': [], 'last_result': None}},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy\nСейчас ход соперника.', parse_mode='HTML')
        ]
    asyncio.run(run_test())


def test_router_auto_shows_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='placing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10, ready=False),
                     'B': SimpleNamespace(user_id=2, chat_id=20, ready=True)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
        )

        def fake_save_board(m, key, board):
            m.boards[key] = board
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(router, 'random_board', lambda: SimpleNamespace())
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy\nКорабли расставлены. Бой начинается! Ваш ход.', parse_mode='HTML'),
            call(20, 'Ваше поле:\nown\nПоле соперника:\nenemy\nСоперник готов. Бой начинается! Ход соперника.', parse_mode='HTML'),
        ]
    asyncio.run(run_test())
