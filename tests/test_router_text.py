import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import storage
from handlers import router
from handlers import commands as commands_module
from models import Board, Ship
import logic.phrases as phrases


def test_router_text_board_test_two_not_registered(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "TEST:TOKEN")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com")

    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")

    handlers = list(main.bot_app.handlers.get(0, ()))
    callbacks = {getattr(h.callback, "__name__", "") for h in handlers}

    assert "router_text" in callbacks
    assert "router_text_board_test_two" not in callbacks


def test_router_text_saves_name_and_prompts(monkeypatch):
    async def run_test():
        context = SimpleNamespace(bot=SimpleNamespace(), user_data={})
        context.user_data['name_state'] = {
            'waiting': True,
            'hint': commands_module.NAME_HINT_NEWGAME,
        }
        message = SimpleNamespace(text='Иван', reply_text=AsyncMock(), reply_photo=AsyncMock())
        update = SimpleNamespace(
            message=message,
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )

        await router.router_text(update, context)

        assert context.user_data['player_name'] == 'Иван'
        message.reply_text.assert_awaited_once()
        assert message.reply_text.await_args_list[0] == call(
            'Имя сохранено: Иван. Используйте /newgame, чтобы создать матч.'
        )

    asyncio.run(run_test())


def test_router_text_name_triggers_join(monkeypatch):
    async def run_test():
        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(router, 'finalize_pending_join', finalize)
        context = SimpleNamespace(bot=SimpleNamespace(), user_data={})
        context.user_data['name_state'] = {
            'waiting': True,
            'hint': commands_module.NAME_HINT_AUTO,
            'pending': {'action': 'join', 'match_id': 'm1'},
        }
        message = SimpleNamespace(text='Bob', reply_text=AsyncMock(), reply_photo=AsyncMock())
        update = SimpleNamespace(
            message=message,
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )

        await router.router_text(update, context)

        finalize.assert_awaited_once_with(update, context, 'm1')
        message.reply_text.assert_not_awaited()

    asyncio.run(run_test())


def test_choose_mode_mode_test3_requires_admin():
    async def run_test():
        original_admin = commands_module.ADMIN_ID
        original_board15 = commands_module.BOARD15_TEST_ENABLED
        commands_module.ADMIN_ID = 42
        commands_module.BOARD15_TEST_ENABLED = True
        try:
            reply_text = AsyncMock()
            query = SimpleNamespace(
                data='mode_test3',
                message=SimpleNamespace(reply_text=reply_text),
                from_user=SimpleNamespace(id=1),
                answer=AsyncMock(),
            )
            update = SimpleNamespace(callback_query=query)
            context = SimpleNamespace()

            await commands_module.choose_mode(update, context)

            assert reply_text.call_count == 0
            assert query.answer.await_count == 1
        finally:
            commands_module.ADMIN_ID = original_admin
            commands_module.BOARD15_TEST_ENABLED = original_board15

    asyncio.run(run_test())


def test_router_text_handles_latin_coords_standard_match(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="Player A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="Player B"),
            },
            boards={
                "A": SimpleNamespace(highlight=[]),
                "B": SimpleNamespace(highlight=[], alive_cells=5),
            },
            turn="A",
            shots={
                "A": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
                "B": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
            },
            messages={},
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, "render_board_own", lambda board: "own")
        monkeypatch.setattr(router, "render_board_enemy", lambda board: "enemy")
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "random_phrase", lambda phrases: phrases[0])
        monkeypatch.setattr(router, "random_joke", lambda: "JOKE")

        apply_calls: list[tuple[object, tuple[int, int]]] = []

        def fake_apply(board, coord):
            apply_calls.append((board, coord))
            return router.MISS

        monkeypatch.setattr(router, "apply_shot", fake_apply)

        send_message = AsyncMock()
        delete_message = AsyncMock()
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=send_message, delete_message=delete_message)
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        assert apply_calls == [(match.boards["B"], (0, 0))]
        assert match.turn == "B"
        assert any("Ваш ход: a1" in call.args[1] for call in send_message.call_args_list)

    asyncio.run(run_test())


def test_router_text_handles_latin_coords_board_test_two(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="Player A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="Player B"),
            },
            boards={
                "A": SimpleNamespace(highlight=[]),
                "B": SimpleNamespace(highlight=[], alive_cells=5),
            },
            turn="A",
            shots={
                "A": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
                "B": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
            },
            messages={"_flags": {"mode_test2": True}},
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "random_phrase", lambda phrases: phrases[0])
        monkeypatch.setattr(router, "random_joke", lambda: "JOKE")
        monkeypatch.setattr(storage, "save_match", lambda m: None)

        apply_calls: list[tuple[object, tuple[int, int]]] = []

        def fake_apply(board, coord):
            apply_calls.append((board, coord))
            return router.MISS

        monkeypatch.setattr(router, "apply_shot", fake_apply)

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        context = SimpleNamespace(bot=SimpleNamespace())
        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        assert apply_calls == [(match.boards["B"], (0, 0))]
        assert match.turn == "B"
        send_state.assert_awaited()

    asyncio.run(run_test())


def test_handle_board_test_two_hit_message_second_person(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="Player A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="Player B"),
            },
            boards={
                "A": SimpleNamespace(highlight=[]),
                "B": SimpleNamespace(highlight=[], alive_cells=5),
            },
            turn="A",
            shots={
                "A": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
                "B": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
            },
            messages={"_flags": {"mode_test2": True}},
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "random_phrase", lambda phrases: phrases[0])
        monkeypatch.setattr(router, "random_joke", lambda: "JOKE")
        monkeypatch.setattr(storage, "save_match", lambda m: None)

        apply_calls: list[tuple[object, tuple[int, int]]] = []

        def fake_apply(board, coord):
            apply_calls.append((board, coord))
            return router.HIT

        monkeypatch.setattr(router, "apply_shot", fake_apply)

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        context = SimpleNamespace(bot=SimpleNamespace())
        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        assert apply_calls == [(match.boards["B"], (0, 0))]
        assert match.turn == "A"
        assert send_state.await_count >= 1
        messages = [call.args[3] for call in send_state.await_args_list]
        player_message = next(msg for msg in messages if msg.startswith("Ваш ход:"))
        assert player_message.endswith("Следующим ходите вы.")

    asyncio.run(run_test())


def test_router_text_auto_board_test_two_matches_standard_flow(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status="placing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, ready=False, name="Player A"),
                "B": SimpleNamespace(user_id=0, chat_id=10, ready=True, name="Bot"),
            },
            boards={
                "A": SimpleNamespace(highlight=[]),
                "B": SimpleNamespace(highlight=[]),
            },
            turn="A",
            shots={
                "A": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
                "B": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10},
            },
            messages={"_flags": {"mode_test2": True}},
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)

        board_instance = SimpleNamespace(owner=None)
        monkeypatch.setattr(router, "random_board", lambda: board_instance)

        def fake_save_board(match_obj, player_key, board):
            match_obj.players[player_key].ready = True
            match_obj.boards[player_key] = board
            match_obj.status = "playing"
            match_obj.turn = player_key

        monkeypatch.setattr(storage, "save_board", fake_save_board)
        monkeypatch.setattr(storage, "save_match", lambda m: None)

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(), delete_message=AsyncMock())
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text="авто", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        update.message.reply_text.assert_not_awaited()
        assert match.status == "playing"
        assert match.turn == "A"
        assert match.messages["_flags"]["mode_test2"] is True
        assert send_state.await_args_list == [
            call(context, match, "A", "Корабли расставлены. Бой начинается! Ваш ход."),
        ]
        assert match.messages["B"]["last_bot_message"] == (
            "Player A готов. Бой начинается! Ход соперника."
        )

    asyncio.run(run_test())


def test_router_test_mode_skips_commands(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
            turn='A',
            shots={'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10},
                   'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10}},
            messages={'_flags': {'mode_test2': True}},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(
                text='/quit',
                entities=[SimpleNamespace(type='bot_command', offset=0, length=5)],
                reply_text=AsyncMock(),
            ),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        handled = await router._handle_board_test_two(update, context)
        assert handled is False
        assert send_message.call_count == 0
    asyncio.run(run_test())


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

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='63', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert len(send_message.call_args_list) == 1
        msg_call = send_message.call_args_list[0]
        assert msg_call.args[0] == 10
        assert msg_call.kwargs.get('parse_mode') == 'HTML'
        assert msg_call.args[1] == (
            'Ваше поле:\nown\nПоле соперника:\nenemy\nНе понял клетку. Пример: е5 или д10.'
        )
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

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert len(send_message.call_args_list) == 1
        msg_call = send_message.call_args_list[0]
        assert msg_call.args[0] == 10
        assert msg_call.kwargs.get('parse_mode') == 'HTML'
        assert msg_call.args[1] == (
            'Ваше поле:\nown\nПоле соперника:\nenemy\nСейчас ход соперника.'
        )
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

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        calls = send_message.call_args_list
        assert len(calls) == 2
        for call_args in calls:
            assert call_args.kwargs.get('parse_mode') == 'HTML'
        messages_by_chat = {c.args[0]: c.args[1] for c in calls}
        assert messages_by_chat[10] == (
            'Ваше поле:\nown\nПоле соперника:\nenemy\nКорабли расставлены. Бой начинается! Ваш ход.'
        )
        assert messages_by_chat[20] == (
            'Ваше поле:\nown\nПоле соперника:\nenemy\nИгрок A готов. Бой начинается! Ход соперника.'
        )
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

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        calls = send_message.call_args_list
        assert len(calls) == 3
        assert calls[0].kwargs.get('parse_mode') == 'HTML'
        assert calls[1].kwargs.get('parse_mode') == 'HTML'
        assert calls[2].kwargs == {}
        messages_by_chat = [(c.args[0], c.args[1]) for c in calls]
        assert messages_by_chat[0] == (
            10,
            'Ваше поле:\nown\nПоле соперника:\nenemy\nКорабли расставлены. Ожидаем соперника.',
        )
        assert messages_by_chat[1] == (
            20,
            'Ваше поле:\nown\nПоле соперника:\nenemy\nИгрок A готов. Отправьте "авто" для расстановки кораблей.',
        )
        assert messages_by_chat[2] == (
            20,
            'Используйте @ в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
        )

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
        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        calls = send_message.call_args_list
        assert len(calls) == 2
        for call_args in calls:
            assert call_args.kwargs.get('parse_mode') == 'HTML'
        messages_by_chat = {c.args[0]: c.args[1] for c in calls}
        msg_self = messages_by_chat[10]
        msg_enemy = messages_by_chat[20]
        coord_str = router.format_coord((0, 0))
        assert f'Ваш ход: {coord_str} — Корабль соперника уничтожен!' in msg_self
        assert any(p in msg_self for p in phrases.SELF_KILL)
        assert msg_self.strip().endswith('Следующим ходит A.')
        assert f'Ход игрока A: {coord_str} — Соперник уничтожил ваш корабль.' in msg_enemy
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
            messages={},
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

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, delete_message=AsyncMock()))
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        msg_self = send_message.call_args_list[1].args[1]
        assert '\n\nСлушай анекдот по этому поводу:\nJOKE\n\nСледующим ходит B.' in msg_self

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
        final_message = 'Игра завершена! Используйте /newgame, чтобы начать новую партию.'
        assert texts[-2] == final_message
        assert texts[-1] == final_message
    asyncio.run(run_test())
