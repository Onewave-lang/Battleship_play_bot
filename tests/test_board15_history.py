import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.battle import apply_shot, update_history, KILL, HIT, MISS
from game_board15.models import Board15, Ship
from game_board15.utils import _get_cell_state, _set_cell_state
from tests.utils import _new_grid, _state


def test_update_history_records_kill_and_contour():
    history = _new_grid(15)
    boards = {'B': Board15()}
    ship = Ship(cells=[(1, 1)])
    boards['B'].ships = [ship]
    boards['B'].grid[1][1] = 1
    res = apply_shot(boards['B'], (1, 1))
    assert res == KILL
    update_history(history, boards, (1, 1), {'B': res})
    assert _state(history[1][1]) == 4
    assert _state(history[0][0]) == 5


def test_hit_then_kill_updates_all_cells():
    history = _new_grid(15)
    boards = {'A': Board15()}
    ship = Ship(cells=[(0, 2), (0, 3)])
    boards['A'].ships = [ship]
    boards['A'].grid[0][2] = 1
    boards['A'].grid[0][3] = 1

    res_hit = apply_shot(boards['A'], (0, 2))
    assert res_hit == HIT
    update_history(history, boards, (0, 2), {'A': res_hit})
    assert _state(history[0][2]) == 3

    res_kill = apply_shot(boards['A'], (0, 3))
    assert res_kill == KILL
    update_history(history, boards, (0, 3), {'A': res_kill})

    assert _state(history[0][2]) == 4
    assert _state(history[0][3]) == 4


def test_kill_contour_overwrites_previous_state():
    history = _new_grid(15)
    boards = {'B': Board15()}
    ship = Ship(cells=[(1, 1)])
    boards['B'].ships = [ship]
    boards['B'].grid[1][1] = 1

    # Pre-fill surrounding cells with various states
    history[0][0][0] = 2
    history[0][1][0] = 3
    history[0][2][0] = 2
    history[1][0][0] = 3
    history[1][2][0] = 2
    history[2][0][0] = 3
    history[2][1][0] = 2
    history[2][2][0] = 3

    res = apply_shot(boards['B'], (1, 1))
    assert res == KILL
    update_history(history, boards, (1, 1), {'B': res})

    for rr in range(0, 3):
        for cc in range(0, 3):
            state = _state(history[rr][cc])
            if (rr, cc) == (1, 1):
                assert state == 4
            else:
                assert state == 5


def test_send_state_uses_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=_new_grid(15),
            messages={'A': {}},
        )
        match.boards['A'].grid[2][2] = 1
        match.history[0][0][0] = 2

        captured = {}

        def fake_render_board(state, player_key=None):
            captured['board'] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                edit_message_media=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(context, match, 'A', 'msg')

        assert captured['board'][0][0] == 2
        assert captured['board'][2][2] == 1

    asyncio.run(run_test())


def test_friendly_ship_survives_other_board_miss(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=2),
            },
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
        )
        ship = Ship(cells=[(0, 0)])
        match.boards['A'].ships = [ship]
        match.boards['A'].grid[0][0] = 1

        res = apply_shot(match.boards['B'], (0, 0))
        assert res == MISS
        update_history(match.history, match.boards, (0, 0), {'B': res})
        assert _state(match.history[0][0]) == 0

        for b in match.boards.values():
            if b.highlight:
                for rr, cc in b.highlight:
                    if _get_cell_state(match.history[rr][cc]) == 0 and all(
                        _get_cell_state(bb.grid[rr][cc]) != 1 for bb in match.boards.values()
                    ):
                        _set_cell_state(match.history, rr, cc, 2)
            b.highlight = []

        captured = {}

        def fake_render_board(state, player_key=None):
            captured[player_key] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                edit_message_media=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(context, match, 'A', 'msg')

        assert captured['A'][0][0] == 1

    asyncio.run(run_test())


def test_kill_contour_visible_to_all_players(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=2),
                'C': SimpleNamespace(chat_id=3),
            },
            boards={'A': Board15(), 'B': Board15(), 'C': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}, 'C': {}},
        )
        ship = Ship(cells=[(1, 1)])
        match.boards['A'].ships = [ship]
        match.boards['A'].grid[1][1] = 1

        res_a = apply_shot(match.boards['A'], (1, 1))
        res_c = apply_shot(match.boards['C'], (1, 1))
        assert res_a == KILL
        update_history(match.history, match.boards, (1, 1), {'A': res_a, 'C': res_c})

        captured = {}

        def fake_render_board(state, player_key=None):
            captured[player_key] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                edit_message_media=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            ),
            bot_data={},
            chat_data={},
        )

        for key in ('A', 'B', 'C'):
            await router._send_state(context, match, key, 'msg')

        assert captured['A'][0][0] == 5
        assert captured['B'][0][0] == 5
        assert captured['C'][0][0] == 5

    asyncio.run(run_test())


def test_render_board_shows_cumulative_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=_new_grid(15),
            messages={'A': {}},
        )
        ship = Ship(cells=[(1, 1)])
        match.boards['A'].ships = [ship]
        match.boards['A'].grid[1][1] = 1

        captured = []

        def fake_render_board(state, player_key=None):
            captured.append([row[:] for row in state.board])
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                edit_message_media=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            ),
            bot_data={},
            chat_data={},
        )

        # first shot miss
        res = apply_shot(match.boards['A'], (0, 0))
        update_history(match.history, match.boards, (0, 0), {'A': res})
        await router._send_state(context, match, 'A', 'first')

        # second shot kill
        res = apply_shot(match.boards['A'], (1, 1))
        update_history(match.history, match.boards, (1, 1), {'A': res})
        await router._send_state(context, match, 'A', 'second')

        first, second = captured
        assert first[0][0] == 2
        assert first[1][1] == 1
        assert second[0][0] == 5
        assert second[1][1] == 4

    asyncio.run(run_test())
