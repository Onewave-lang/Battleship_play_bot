import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.battle import apply_shot, update_history, KILL
from game_board15.models import Board15, Ship


def test_update_history_records_kill_and_contour():
    history = [[0] * 15 for _ in range(15)]
    boards = {'B': Board15()}
    ship = Ship(cells=[(1, 1)])
    boards['B'].ships = [ship]
    boards['B'].grid[1][1] = 1
    res = apply_shot(boards['B'], (1, 1))
    assert res == KILL
    update_history(history, boards, (1, 1), {'B': res})
    assert history[1][1] == 4
    assert history[0][0] == 5


def test_send_state_uses_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=[[0] * 15 for _ in range(15)],
            messages={'A': {}},
        )
        match.boards['A'].grid[2][2] = 1
        match.history[0][0] = 2

        captured = {}

        def fake_render_board(state, player_key=None):
            captured['board'] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)
        monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))
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


def test_kill_contour_visible_to_all_players(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=2),
                'C': SimpleNamespace(chat_id=3),
            },
            boards={'A': Board15(), 'B': Board15(), 'C': Board15()},
            history=[[0] * 15 for _ in range(15)],
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
        monkeypatch.setattr(
            router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own')
        )
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
            history=[[0] * 15 for _ in range(15)],
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
        monkeypatch.setattr(
            router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own')
        )
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
        assert second[0][0] == 2
        assert second[1][1] == 4

    asyncio.run(run_test())
