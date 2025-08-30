import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import storage
from handlers import router
from models import Board, Ship
import logic.phrases as phrases


def test_router_invalid_cell_shows_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
            messages={},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='63', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(10, 'Не понял клетку. Пример: е5 или д10.', parse_mode='HTML'),
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
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
            messages={},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(10, 'Сейчас ход соперника.', parse_mode='HTML'),
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
            messages={},
        )

        def fake_save_board(m, key, board):
            m.boards[key] = board
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'random_board', lambda: SimpleNamespace())
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(10, 'Корабли расставлены. Бой начинается! Ваш ход.', parse_mode='HTML'),
            call(20, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(20, 'Соперник готов. Бой начинается! Ход соперника.', parse_mode='HTML'),
        ]
    asyncio.run(run_test())


def test_router_auto_waits_and_sends_instruction(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='placing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, ready=False),
                'B': SimpleNamespace(user_id=2, chat_id=20, ready=False),
            },
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            messages={},
        )

        def fake_save_board(m, key, board):
            m.boards[key] = board
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'random_board', lambda: SimpleNamespace())
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [
            call(10, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(10, 'Корабли расставлены. Ожидаем соперника.', parse_mode='HTML'),
            call(20, 'Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML', reply_markup=kb),
            call(20, 'Соперник готов. Отправьте "авто" для расстановки кораблей.', parse_mode='HTML'),
            call(20, 'Используйте @ в начале сообщения, чтобы отправить сообщение соперникам в чат игры.'),
        ]

    asyncio.run(run_test())


def test_router_kill_message(monkeypatch):
    async def run_test():
        board_self = Board()
        board_enemy = Board()
        ship1 = Ship(cells=[(0, 0)])
        ship2 = Ship(cells=[(9, 9)])
        board_enemy.ships = [ship1, ship2]
        board_enemy.grid[0][0] = 1
        board_enemy.grid[9][9] = 1
        board_enemy.alive_cells = 2
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': board_self, 'B': board_enemy},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
            messages={},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)
        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        calls = send_message.call_args_list
        assert len(calls) == 4
        msg_self = calls[1].args[1]
        msg_enemy = calls[3].args[1]
        assert 'Ваш ход: a1 — Корабль соперника уничтожен!' in msg_self
        assert any(p in msg_self for p in phrases.SELF_KILL)
        assert msg_self.strip().endswith('Следующим ходит A.')
        assert 'Ход игрока A: a1 — Соперник уничтожил ваш корабль.' in msg_enemy
        assert any(p in msg_enemy for p in phrases.ENEMY_KILL)
        assert msg_enemy.strip().endswith('Следующим ходит A.')
    asyncio.run(run_test())


def test_router_at_sends_to_opponent(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        update = SimpleNamespace(
            message=SimpleNamespace(text='@ Привет', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert send_message.call_args_list == [call(20, 'Привет')]

    asyncio.run(run_test())


def test_router_joke_format(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 9, 'joke_start': 0},
                   'B': {'history': [], 'last_result': None, 'move_count': 9, 'joke_start': 0}},
            messages={},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(router, 'apply_shot', lambda board, coord: router.MISS)
        monkeypatch.setattr(router, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router, 'random_phrase', lambda phrases: phrases[0])
        monkeypatch.setattr(router, 'random_joke', lambda: 'JOKE')
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        msg_self = send_message.call_args_list[1].args[1]
        assert 'Слушай анекдот по этому поводу:\nJOKE\n\n Следующим ходит B.' in msg_self

    asyncio.run(run_test())


def test_router_game_over_messages(monkeypatch):
    async def run_test():
        board_self = Board()
        board_enemy = Board()
        ship1 = Ship(cells=[(0, 0)])
        board_enemy.ships = [ship1]
        board_enemy.grid[0][0] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': board_self, 'B': board_enemy},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
            messages={},
        )
        def fake_finish(m, winner):
            m.status = 'finished'
            return None
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, 'render_board_own', lambda b: 'own')
        monkeypatch.setattr(router, 'render_board_enemy', lambda b: 'enemy')
        monkeypatch.setattr(storage, 'finish', fake_finish)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        kb = object()
        monkeypatch.setattr(router, 'move_keyboard', lambda: kb)
        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        calls = send_message.call_args_list
        texts = [c.args[1] for c in calls]
        assert any('Флот игрока B потоплен! B занял 2 место. Вы победили!🏆' in t for t in texts)
        assert any('Флот игрока B потоплен! B занял 2 место. Игрок A победил!' in t for t in texts)
        assert any('Все ваши корабли уничтожены' in t for t in texts)
        assert texts[-2] == 'Игра завершена!'
        assert texts[-1] == 'Игра завершена!'
        assert calls[-2].kwargs['reply_markup'].keyboard[0][0].text == 'Начать новую игру'
        assert calls[-1].kwargs['reply_markup'].keyboard[0][0].text == 'Начать новую игру'
    asyncio.run(run_test())
