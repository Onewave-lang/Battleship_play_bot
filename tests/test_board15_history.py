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
        monkeypatch.setattr(router, '_keyboard', lambda: None)
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
