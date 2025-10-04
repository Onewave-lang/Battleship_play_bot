import asyncio
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, ANY

import pytest
from tests.utils import _new_grid

# Provide minimal Pillow stub to satisfy imports in game_board15.renderer
pil = types.ModuleType('PIL')
pil.Image = types.SimpleNamespace()
pil.ImageDraw = types.SimpleNamespace()
pil.ImageFont = types.SimpleNamespace()
sys.modules.setdefault('PIL', pil)

from game_board15 import router, storage
from game_board15.models import Board15, Ship
from game_board15.utils import _get_cell_state, _get_cell_owner, _set_cell_state


def test_router_auto_sends_boards(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='placing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, ready=True, name='Alice'),
                'B': SimpleNamespace(user_id=2, chat_id=20, ready=False, name='Bob'),
            },
            boards={
                'A': SimpleNamespace(grid=[[0] * 15 for _ in range(15)], highlight=[]),
                'B': SimpleNamespace(grid=[[0] * 15 for _ in range(15)], highlight=[]),
            },
            turn='A',
            messages={},
            history=_new_grid(15),
        )

        def fake_save_board(m, key, board=None):
            m.boards[key] = board or Board15(grid=[[0] * 15 for _ in range(15)])
            m.players[key].ready = True
            if all(p.ready for p in m.players.values()):
                m.status = 'playing'
                m.turn = 'A'

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_board', fake_save_board)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'target'))

        send_photo = AsyncMock()
        send_message = AsyncMock()
        context = SimpleNamespace(
            bot=SimpleNamespace(send_photo=send_photo, send_message=send_message),
            chat_data={},
            bot_data={},
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text='авто', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=2, first_name='Bob'),
            effective_chat=SimpleNamespace(id=20),
        )

        await router.router_text(update, context)

        assert send_photo.call_args_list == [
            call(10, ANY, caption='Соперник готов. Бой начинается! Ваш ход.'),
            call(20, ANY, caption='Корабли расставлены. Бой начинается! Ход соперника.'),
        ]
        assert send_message.call_args_list == []

    asyncio.run(run_test())


def test_last_highlight_persists_after_kill(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship(cells=[(0, 0)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        assert match.last_highlight == [(0, 0)]
        board_enemy.highlight.clear()
        assert match.last_highlight == [(0, 0)]

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "scenario, expected_state, expected_owner",
    [
        ("miss", 2, None),
        ("hit", 3, "B"),
        ("kill", 4, "B"),
    ],
)
def test_router_text_fallback_stamps_cell(monkeypatch, scenario, expected_state, expected_owner):
    async def run_test():
        coord = (1, 1)
        board_self = Board15()
        board_enemy = Board15()
        if scenario == "hit":
            ship = Ship(cells=[coord, (1, 2)])
            board_enemy.ships = [ship]
            board_enemy.grid[1][1] = 1
            board_enemy.grid[1][2] = 1
            board_enemy.alive_cells = len(ship.cells)
        elif scenario == "kill":
            ship = Ship(cells=[coord])
            board_enemy.ships = [ship]
            board_enemy.grid[1][1] = 1
            board_enemy.alive_cells = len(ship.cells)
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={
                "A": {"history": [], "move_count": 0, "joke_start": 10},
                "B": {"history": [], "move_count": 0, "joke_start": 10},
            },
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
            last_highlight=[],
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "finish", lambda m, winner: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: coord)
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "b2")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        original_update_history = router.battle.update_history

        def fake_update_history(history, boards, coord_local, results):
            original_update_history(history, boards, coord_local, results)
            r_local, c_local = coord_local
            other_r, other_c = (0, 0)
            if (other_r, other_c) == coord_local:
                other_c = 1
            other_cell = history[other_r][other_c]
            if isinstance(other_cell, list):
                other_cell[0] = 9
            else:
                history[other_r][other_c] = [9, None]
            cell = history[r_local][c_local]
            if isinstance(cell, list):
                cell[0] = 0
                if len(cell) > 1:
                    cell[1] = None
            else:
                history[r_local][c_local] = [0, None]

        monkeypatch.setattr(router.battle, "update_history", fake_update_history)

        send_state_calls = 0

        async def fake_send_state(context, match_obj, key, message, *, reveal_ships=True):
            nonlocal send_state_calls
            send_state_calls += 1
            cell = match_obj.history[coord[0]][coord[1]]
            assert _get_cell_state(cell) == expected_state
            if expected_owner is None:
                assert _get_cell_owner(cell) is None
            else:
                assert _get_cell_owner(cell) == expected_owner

        monkeypatch.setattr(router, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="b2", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            chat_data={},
            bot_data={},
        )

        await router.router_text(update, context)

        assert send_state_calls > 0

    asyncio.run(run_test())


def test_router_text_rejects_repeat_before_apply_shot(monkeypatch):
    async def run_test():
        coord = (2, 2)
        board_self = Board15()
        board_enemy_b = Board15()
        board_enemy_c = Board15()
        board_enemy_b.grid[coord[0]][coord[1]] = 2
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
                "C": SimpleNamespace(user_id=3, chat_id=30, name="C"),
            },
            boards={
                "A": board_self,
                "B": board_enemy_b,
                "C": board_enemy_c,
            },
            turn="A",
            shots={
                "A": {},
                "B": {},
                "C": {},
            },
            messages={
                "A": {},
                "B": {},
                "C": {},
            },
            history=_new_grid(15),
            last_highlight=[],
            snapshots=[{"history": "initial"}],
        )
        _set_cell_state(match.history, coord[0], coord[1], 2)

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: coord)

        apply_mock = Mock(return_value=router.battle.MISS)
        monkeypatch.setattr(router.battle, "apply_shot", apply_mock)
        record_mock = Mock()
        monkeypatch.setattr(router, "record_snapshot", record_mock)

        reply = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(text="c3", reply_text=reply),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            chat_data={},
            bot_data={},
        )

        await router.router_text(update, context)

        reply.assert_awaited_once_with('Эта клетка уже обстреляна')
        apply_mock.assert_not_called()
        record_mock.assert_not_called()
        assert _get_cell_state(match.history[coord[0]][coord[1]]) == 2
        assert board_enemy_c.grid[coord[0]][coord[1]] == 0
        assert len(match.snapshots) == 1

    asyncio.run(run_test())


def test_last_highlight_persists_through_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")
    match = storage.create_match(1, 100, "A")
    storage.join_match(match.match_id, 2, 200, "B")
    match.status = "playing"
    match.last_highlight = [(3, 4)]
    storage.save_match(match)

    reloaded = storage.get_match(match.match_id)

    captured = {}

    def fake_render_board(state, player_key):
        captured["highlight"] = state.highlight.copy()
        return BytesIO(b"x")

    monkeypatch.setattr(router, "render_board", fake_render_board)

    send_photo = AsyncMock()
    send_message = AsyncMock()
    context = SimpleNamespace(
        bot=SimpleNamespace(send_photo=send_photo, send_message=send_message),
        bot_data={},
        chat_data={},
    )

    asyncio.run(router._send_state(context, reloaded, "A", "msg"))

    assert captured["highlight"] == [(3, 4)]


def test_kill_marks_all_cells_and_contour(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship(cells=[(0, 0), (0, 1)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 3
        board_enemy.grid[0][1] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 1))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "b1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="b1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        assert set(match.last_highlight) == {(0, 0), (0, 1)}
        assert _get_cell_state(match.history[0][2]) == 5

    asyncio.run(run_test())


def test_kill_highlight_only_last_ship(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_enemy = Board15()
        # Previously destroyed ship cells remain on the grid
        board_enemy.grid[5][5] = 4
        board_enemy.grid[5][6] = 4
        # Current ship about to be killed
        ship = Ship(cells=[(0, 0), (0, 1)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 3  # already hit part
        board_enemy.grid[0][1] = 1  # intact part
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 1))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "b1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="b1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        assert set(match.last_highlight) == {(0, 0), (0, 1)}

    asyncio.run(run_test())


def test_router_notifies_other_players_on_hit(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_b = Board15()
        board_c = Board15()
        ship = Ship(cells=[(0, 0)])
        board_b.ships = [ship]
        board_b.grid[0][0] = 1
        board_b.alive_cells = 1
        board_c.alive_cells = 1
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, name='A'),
                'B': SimpleNamespace(user_id=2, chat_id=20, name='B'),
                'C': SimpleNamespace(user_id=3, chat_id=30, name='C'),
            },
            boards={'A': board_self, 'B': board_b, 'C': board_c},
            turn='A',
            shots={'A': {'move_count': 0, 'joke_start': 10}, 'B': {}, 'C': {}},
            messages={'A': {}, 'B': {}, 'C': {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')

        def fake_apply_shot(board, coord):
            return router.battle.HIT if board is board_b else router.battle.MISS

        monkeypatch.setattr(router.battle, 'apply_shot', fake_apply_shot)

        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        calls = [c for c in send_state.call_args_list if c.args[2] == 'C']
        assert len(calls) >= 1
        msg = calls[-1].args[3]
        assert msg.startswith('Ход игрока A: a1 - игрок A поразил корабль игрока B')
        assert msg.strip().endswith('Следующим ходит A.')

    asyncio.run(run_test())


def test_hit_keeps_turn(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship(cells=[(0, 0), (0, 1)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.grid[0][1] = 1
        board_enemy.alive_cells = 2
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        assert match.turn == "A"

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "result, expected",
    [
        (router.battle.HIT, "ваш корабль ранен"),
        (router.battle.KILL, "ваш корабль уничтожен"),
    ],
)
def test_router_notifies_attacked_player(monkeypatch, result, expected):
    async def run_test():
        board_self = Board15()
        board_b = Board15()
        board_c = Board15()
        ship = Ship(cells=[(0, 0)])
        board_b.ships = [ship]
        board_b.grid[0][0] = 1
        board_b.alive_cells = 1
        board_c.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
                "C": SimpleNamespace(user_id=3, chat_id=30, name="C"),
            },
            boards={"A": board_self, "B": board_b, "C": board_c},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}, "C": {}},
            messages={"A": {}, "B": {}, "C": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        def fake_apply_shot(board, coord):
            return result if board is board_b else router.battle.MISS

        monkeypatch.setattr(router.battle, "apply_shot", fake_apply_shot)

        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})

        await router.router_text(update, context)

        calls = [c for c in send_state.call_args_list if c.args[2] == "B"]
        assert calls, "Attacked player must receive a message"
        msg = calls[-1].args[3]
        assert expected in msg
        assert "соперник промахнулся" not in msg

    asyncio.run(run_test())


def test_router_notifies_next_player_on_miss(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, name='A'),
                'B': SimpleNamespace(user_id=2, chat_id=20, name='B'),
                'C': SimpleNamespace(user_id=3, chat_id=30, name='C'),
            },
            boards={'A': Board15(), 'B': Board15(), 'C': Board15()},
            turn='A',
            shots={'A': {'move_count': 0, 'joke_start': 10}, 'B': {}, 'C': {}},
            messages={'A': {}, 'B': {}, 'C': {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.battle, 'apply_shot', lambda board, coord: router.battle.MISS)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'target'))

        send_photo = AsyncMock()
        send_message = AsyncMock()
        context = SimpleNamespace(
            bot=SimpleNamespace(send_photo=send_photo, send_message=send_message),
            chat_data={},
            bot_data={},
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        b_msgs = [c for c in send_photo.call_args_list if c.args[0] == 20]
        assert b_msgs and b_msgs[0].kwargs["caption"].endswith('Следующим ходит B.')
        assert 'a1 - мимо' in b_msgs[0].kwargs["caption"]
        assert send_message.call_args_list == []

    asyncio.run(run_test())


def test_router_move_sends_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, name='Alice'),
                'B': SimpleNamespace(user_id=2, chat_id=20, name='Bob'),
            },
            boards={'A': Board15(), 'B': Board15()},
            turn='A',
            shots={'A': {}, 'B': {}},
            messages={'A': {'board': 1}, 'B': {'board': 3}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.battle, 'apply_shot', lambda board, coord: router.battle.MISS)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'target'))

        send_photo = AsyncMock()
        context = SimpleNamespace(
            bot=SimpleNamespace(
                edit_message_media=AsyncMock(),
                edit_message_text=AsyncMock(),
                send_photo=send_photo,
                send_message=AsyncMock(),
            ),
            chat_data={},
            bot_data={},
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        assert {c.args[0] for c in send_photo.call_args_list} == {10, 20}

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
                'A': Board15(),
                'B': Board15(),
                'C': Board15(),
            },
            turn='A',
            shots={'A': {}, 'B': {}, 'C': {}},
            messages={'A': {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.battle, 'apply_shot', lambda board, coord: router.battle.MISS)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1'),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(chat_data={}, bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router.router_text(update, context)

        calls = [c for c in send_state.call_args_list if c.args[2] == 'C']
        msg = calls[0].args[3]
        assert msg.startswith('Ход игрока Alice: a1 - ')
        assert 'B:' not in msg and 'C:' not in msg
        assert msg.strip().endswith('Следующим ходит Bob.')

    asyncio.run(run_test())


def test_router_miss_single_phrase(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10, name='Alice'),
                'B': SimpleNamespace(user_id=2, chat_id=20, name='Bob'),
                'C': SimpleNamespace(user_id=3, chat_id=30, name='Carl'),
            },
            boards={
                'A': Board15(),
                'B': Board15(),
                'C': Board15(),
            },
            turn='A',
            shots={'A': {}, 'B': {}, 'C': {}},
            messages={'A': {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.battle, 'apply_shot', lambda board, coord: router.battle.MISS)

        def phrase_mock(match, pk, phrases):
            return {'A': 'SELF_JOKE', 'B': 'B_JOKE', 'C': 'C_JOKE'}[pk]

        monkeypatch.setattr(router, '_phrase_or_joke', Mock(side_effect=phrase_mock))
        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1'),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(chat_data={}, bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router.router_text(update, context)

        msg = send_state.call_args[0][3]
        assert msg.count('SELF_JOKE') == 1
        assert 'B_JOKE' not in msg and 'C_JOKE' not in msg
        assert 'B:' not in msg and 'C:' not in msg

    asyncio.run(run_test())


def test_router_repeat_shot(monkeypatch):
    async def run_test():
        board_enemy = Board15()
        board_enemy.grid[0][0] = 2  # already opened
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': Board15(), 'B': board_enemy},
            turn='A',
            shots={'A': {'move_count': 0, 'joke_start': 10},
                   'B': {'move_count': 0, 'joke_start': 10}},
            messages={},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        save_match = Mock()
        monkeypatch.setattr(storage, 'save_match', save_match)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})
        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        await router.router_text(update, context)

        update.message.reply_text.assert_called_once_with('Эта клетка уже обстреляна')
        assert not send_state.called
        assert match.turn == 'A'
        assert match.shots['A']['move_count'] == 0
        assert match.shots['B']['move_count'] == 0
        assert context.bot.send_message.call_count == 0
        assert save_match.call_count == 0

    asyncio.run(run_test())


def test_router_blocks_contour_cell(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={'A': SimpleNamespace(user_id=1, chat_id=10),
                     'B': SimpleNamespace(user_id=2, chat_id=20)},
            boards={'A': Board15(), 'B': Board15()},
            turn='A',
            shots={'A': {'move_count': 0, 'joke_start': 10},
                   'B': {'move_count': 0, 'joke_start': 10}},
            messages={},
            history=_new_grid(15),
        )
        match.history[0][0][0] = 5

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        save_match = Mock()
        monkeypatch.setattr(storage, 'save_match', save_match)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})
        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        await router.router_text(update, context)

        update.message.reply_text.assert_called_once_with('Эта клетка уже обстреляна')
        assert not send_state.called
        assert save_match.call_count == 0

    asyncio.run(run_test())


def test_router_skips_eliminated_players(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            status='playing',
            players={
                'A': SimpleNamespace(user_id=1, chat_id=10),
                'B': SimpleNamespace(user_id=2, chat_id=20),
                'C': SimpleNamespace(user_id=3, chat_id=30),
            },
            boards={'A': Board15(), 'B': Board15(), 'C': Board15()},
            turn='A',
            shots={'A': {}, 'B': {}, 'C': {}},
            messages={'A': {}},
            history=_new_grid(15),
        )
        match.boards['B'].alive_cells = 0

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')

        calls = []

        def fake_apply_shot(board, coord):
            calls.append(board)
            return router.battle.MISS

        monkeypatch.setattr(router.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')

        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)

        send_message = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message), chat_data={}, bot_data={})
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1'),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        assert calls == [match.boards['C']]
        assert all(call.args[0] != 20 for call in send_message.call_args_list)
        assert match.turn == 'C'

    asyncio.run(run_test())


def test_router_blocks_shots_in_kill_contour(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_b = Board15()
        board_c = Board15()
        ship_b = Ship(cells=[(0, 0)])
        board_b.ships = [ship_b]
        board_b.grid[0][0] = 1
        board_b.alive_cells = 1
        ship_c = Ship(cells=[(2, 2)])
        board_c.ships = [ship_c]
        board_c.grid[2][2] = 1
        board_c.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
                "C": SimpleNamespace(user_id=3, chat_id=30, name="C"),
            },
            boards={"A": board_self, "B": board_b, "C": board_c},
            turn="A",
            shots={"A": {"move_count": 0, "joke_start": 10}, "B": {}, "C": {}},
            messages={"A": {}, "B": {}, "C": {}},
            history=_new_grid(15),
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        coords = {"a1": (0, 0), "b1": (0, 1)}
        monkeypatch.setattr(router.parser, "parse_coord", lambda text: coords[text.lower()])
        rev = {v: k for k, v in coords.items()}
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: rev[coord])
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")
        send_state = AsyncMock()
        monkeypatch.setattr(router, "_send_state", send_state)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), chat_data={}, bot_data={})
        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update, context)
        assert _get_cell_state(match.history[0][1]) == 5

        move_before = match.shots["A"]["move_count"]
        turn_before = match.turn

        update2 = SimpleNamespace(
            message=SimpleNamespace(text="b1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        await router.router_text(update2, context)

        update2.message.reply_text.assert_called_once_with("Эта клетка уже обстреляна")
        assert match.turn == turn_before
        assert match.shots["A"]["move_count"] == move_before

    asyncio.run(run_test())

