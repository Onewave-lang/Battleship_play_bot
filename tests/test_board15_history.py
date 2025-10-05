import asyncio
from contextlib import suppress
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import handlers, router, storage
from game_board15.battle import apply_shot, update_history, KILL, HIT, MISS
from game_board15.models import Board15, Ship, Match15, Player
from game_board15.utils import _get_cell_state, _get_cell_owner, _set_cell_state, record_snapshot
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


def test_hit_at_m1_updates_history_and_board(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=_new_grid(15),
            messages={'A': {}},
        )
        cell = (0, 12)  # m1
        ship = Ship(cells=[cell, (0, 13)])
        match.boards['A'].ships = [ship]
        match.boards['A'].grid[cell[0]][cell[1]] = 1
        match.boards['A'].grid[0][13] = 1

        res = apply_shot(match.boards['A'], cell)
        assert res == HIT
        update_history(match.history, match.boards, cell, {'A': res})
        assert _state(match.history[cell[0]][cell[1]]) == 3

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

        assert captured['board'][cell[0]][cell[1]] == 3

    asyncio.run(run_test())


def test_multiple_hits_recorded(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1), 'B': SimpleNamespace(chat_id=2)},
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
        )
        coord = (0, 0)
        extra = (0, 1)
        for key in ('A', 'B'):
            ship = Ship(cells=[coord, extra])
            match.boards[key].ships = [ship]
            match.boards[key].grid[coord[0]][coord[1]] = 1
            match.boards[key].grid[extra[0]][extra[1]] = 1

        res_a = apply_shot(match.boards['A'], coord)
        res_b = apply_shot(match.boards['B'], coord)
        assert res_a == HIT
        assert res_b == HIT

        update_history(match.history, match.boards, coord, {'A': res_a, 'B': res_b})
        assert _state(match.history[coord[0]][coord[1]]) == 3

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
        await router._send_state(context, match, 'B', 'msg')

        assert captured['A'][coord[0]][coord[1]] == 3
        assert captured['B'][coord[0]][coord[1]] == 3

    asyncio.run(run_test())


def test_send_state_repairs_snapshot_grid(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={'A': SimpleNamespace(chat_id=1)},
            boards={'A': Board15()},
            history=_new_grid(15),
            messages={'A': {}},
            snapshots=[],
            last_highlight=[],
            turn='A',
        )

        ship = Ship(cells=[(0, 0)])
        match.boards['A'].ships = [ship]
        match.boards['A'].grid[0][0] = 1
        match.boards['A'].alive_cells = len(ship.cells)

        snapshot = record_snapshot(match, actor=None, coord=None)
        snapshot['boards']['A']['grid'][0][0] = 0

        captured = {}

        def fake_render_board(state, player_key=None):
            captured['board'] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(context, match, 'A', 'msg')

        assert captured['board'][0][0] == 1
        assert snapshot['boards']['A']['grid'][0][0] == 1

    asyncio.run(run_test())


def test_shared_chat_board_hides_intact_enemy_ships(monkeypatch):
    async def run_test():
        shared_chat = 555
        match = Match15.new(1, shared_chat, "A")
        match.players['A'].name = 'A'
        match.players['B'] = Player(user_id=2, chat_id=shared_chat, name='B')
        match.status = 'playing'
        match.turn = 'A'
        match.history = _new_grid(15)
        match.snapshots = []
        match.last_highlight = []
        match.messages = {key: {} for key in ('A', 'B')}
        match.boards['A'] = Board15()
        match.boards['B'] = Board15()
        match.boards.pop('C', None)
        ship_a = Ship(cells=[(2, 2)])
        match.boards['A'].ships = [ship_a]
        match.boards['A'].grid[2][2] = 1
        match.boards['A'].alive_cells = len(ship_a.cells)
        ship_b = Ship(cells=[(0, 2)])
        match.boards['B'].ships = [ship_b]
        match.boards['B'].grid[0][2] = 1
        match.boards['B'].alive_cells = len(ship_b.cells)
        match.shots = {
            'A': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10, 'last_coord': None},
            'B': {'history': [], 'last_result': None, 'move_count': 0, 'joke_start': 10, 'last_coord': None},
        }

        monkeypatch.setattr(
            router.storage,
            'find_match_by_user',
            lambda user_id, chat_id=None: match if chat_id == shared_chat else None,
        )
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        coords = {'a1': (0, 0), 'c3': (2, 2)}
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: coords.get(text))
        monkeypatch.setattr(
            router.parser,
            'format_coord',
            lambda coord: next((label for label, value in coords.items() if value == coord), 'a1'),
        )

        orig_send_state = router._send_state
        send_state_calls: list[tuple[str, bool]] = []
        history_snapshots: list[list[list[int]]] = []

        async def capture_send_state(
            context,
            match_obj,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            send_state_calls.append((player_key, reveal_ships, include_all_ships))
            history_snapshots.append(
                [[_get_cell_state(cell) for cell in row] for row in match_obj.history]
            )
            await orig_send_state(
                context,
                match_obj,
                player_key,
                message,
                reveal_ships=reveal_ships,
                snapshot_override=snapshot_override,
                include_all_ships=include_all_ships,
            )

        monkeypatch.setattr(router, '_send_state', capture_send_state)

        rendered: list[tuple[str, list[list[int]]]] = []

        def fake_render_board(state, player_key=None):
            rendered.append((player_key, [row[:] for row in state.board]))
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_media=AsyncMock(),
                edit_message_text=AsyncMock(),
            ),
            bot_data={},
            chat_data={},
        )

        update_a = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=shared_chat),
        )

        await router.router_text(update_a, context)
        assert match.turn == 'B'

        update_b = SimpleNamespace(
            message=SimpleNamespace(text='c3', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=2),
            effective_chat=SimpleNamespace(id=shared_chat),
        )

        await router.router_text(update_b, context)

        assert len(send_state_calls) == 4
        assert send_state_calls == [
            ('A', True, False),
            ('B', True, False),
            ('A', True, False),
            ('B', True, False),
        ]
        assert len(rendered) == len(history_snapshots) == 4
        # First move (player A fires) - each participant receives a tailored render.
        first_player, first_board = rendered[0]
        assert first_player == 'A'
        assert first_board[0][0] == 2  # miss from the first shot
        assert first_board[0][2] == 0  # intact enemy ship remains hidden in shared view
        assert first_board[2][2] == 1  # own ship still visible prior to destruction

        second_player, second_board = rendered[1]
        assert second_player == 'B'
        assert second_board[0][0] == 2
        assert second_board[0][2] == 1  # defending player continues to see their own fleet
        assert second_board[2][2] == 0  # enemy ship is hidden until revealed by damage

        # Second move (player B fires) - renders again reflect each personal perspective.
        third_player, third_board = rendered[2]
        assert third_player == 'A'
        assert third_board[0][0] == 2
        assert third_board[0][2] == 0
        assert third_board[2][2] == 4  # kill stays highlighted in the shared history

        fourth_player, fourth_board = rendered[3]
        assert fourth_player == 'B'
        assert fourth_board[0][0] == 2
        assert fourth_board[0][2] == 1
        assert fourth_board[2][2] == 4

    asyncio.run(run_test())


def test_shared_chat_snapshot_hides_intact_enemy_ships(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=1),
            },
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
            snapshots=[],
            last_highlight=[],
            turn='A',
        )

        match.boards['A'].ships = [Ship(cells=[(2, 2)])]
        match.boards['A'].grid[2][2] = 3

        ship_b_killed = Ship(cells=[(0, 2)])
        ship_b_alive = Ship(cells=[(1, 1)])
        match.boards['B'].ships = [ship_b_killed, ship_b_alive]
        match.boards['B'].grid[0][2] = 4
        match.boards['B'].grid[1][1] = 1

        _set_cell_state(match.history, 0, 2, 4, 'B')
        _set_cell_state(match.history, 2, 2, 3, 'A')

        snapshot = record_snapshot(match, actor='A', coord=(0, 2))

        captured: dict[str, list[list[int]]] = {}

        def fake_render_board(state, player_key=None):
            captured[player_key] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_media=AsyncMock(),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(
            context,
            match,
            'A',
            'msg',
            snapshot_override=snapshot,
            include_all_ships=False,
        )
        await router._send_state(
            context,
            match,
            'B',
            'msg',
            snapshot_override=snapshot,
            include_all_ships=False,
        )

        board_a = captured['A']
        board_b = captured['B']

        assert board_a[0][2] == 4  # killed enemy segment is visible to everyone
        assert board_a[1][1] == 0  # intact enemy ship remains hidden in shared view
        assert board_a[2][2] == 3  # shared history retains damage to own ship

        assert board_b[0][2] == 4  # killed ship still visible on owner's board
        assert board_b[1][1] == 1  # owner continues to see intact ships
        assert board_b[2][2] == 3  # damage to opponent remains visible via history

    asyncio.run(run_test())


def test_personal_view_reuses_snapshot_enemy_ships(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=2),
            },
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
            snapshots=[],
            last_highlight=[],
        )

        ship_a = Ship(cells=[(2, 2)])
        ship_b = Ship(cells=[(1, 1)])
        match.boards['A'].ships = [ship_a]
        match.boards['B'].ships = [ship_b]
        match.boards['A'].grid[2][2] = 1
        match.boards['B'].grid[1][1] = 1

        captured: dict[str, list[list[int]]] = {}

        snapshot = {
            'history': _new_grid(15),
            'last_highlight': [],
            'boards': {
                'A': {
                    'grid': [row[:] for row in match.boards['A'].grid],
                    'ships': [],
                    'alive_cells': 20,
                },
                'B': {
                    'grid': [row[:] for row in match.boards['B'].grid],
                    'ships': [],
                    'alive_cells': 20,
                },
            },
        }

        def fake_render_board(state, player_key=None):
            captured[player_key] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_media=AsyncMock(),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(
            context,
            match,
            'A',
            'msg',
            include_all_ships=False,
            snapshot_override=snapshot,
        )
        await router._send_state(
            context,
            match,
            'B',
            'msg',
            include_all_ships=False,
            snapshot_override=snapshot,
        )

        board_a = captured['A']
        board_b = captured['B']

        assert board_a[2][2] == 1  # player keeps visibility on own fleet
        assert (
            board_a[1][1] == 1
        )  # intact enemy ship recorded in snapshot stays visible for every viewer
        assert board_b[1][1] == 1  # enemy retains view of their own fleet
        assert (
            board_b[2][2] == 1
        )  # previously recorded opponent ship remains visible when snapshot is reused

    asyncio.run(run_test())


def test_personal_view_keeps_enemy_hits_from_history(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(chat_id=1),
                'B': SimpleNamespace(chat_id=2),
            },
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
            snapshots=[],
            last_highlight=[],
        )

        ship_a = Ship(cells=[(2, 2)])
        ship_b = Ship(cells=[(1, 1)])
        match.boards['A'].ships = [ship_a]
        match.boards['B'].ships = [ship_b]
        match.boards['A'].grid[2][2] = 1
        match.boards['B'].grid[1][1] = 1

        # History contains a revealed enemy kill for player A and a miss for player B.
        _set_cell_state(match.history, 1, 1, 4, 'B')
        _set_cell_state(match.history, 0, 0, 2, 'A')

        captured: dict[str, list[list[int]]] = {}

        def fake_render_board(state, player_key=None):
            captured[player_key] = [row[:] for row in state.board]
            return BytesIO(b'img')

        monkeypatch.setattr(router, 'render_board', fake_render_board)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                edit_message_media=AsyncMock(),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(),
            ),
            bot_data={},
            chat_data={},
        )

        await router._send_state(
            context,
            match,
            'A',
            'msg',
            include_all_ships=False,
        )

        board_a = captured['A']

        assert board_a[2][2] == 1  # own fleet revealed
        assert board_a[1][1] == 4  # enemy kill from history remains visible
        assert board_a[0][0] == 2  # other history states remain intact

    asyncio.run(run_test())


def test_snapshot_sequence_preserves_ships_and_moves():
    match = Match15.new(1, 100, "A")
    match.players['B'] = Player(user_id=2, chat_id=100, name='B')
    match.boards['B'] = Board15()
    match.boards.pop('C', None)
    match.history = _new_grid(15)
    match.snapshots = []
    match.last_highlight = []

    ship_a = Ship(cells=[(1, 1)])
    match.boards['A'].ships = [ship_a]
    match.boards['A'].grid[1][1] = 1
    ship_b = Ship(cells=[(0, 2)])
    match.boards['B'].ships = [ship_b]
    match.boards['B'].grid[0][2] = 1

    first_snapshot = record_snapshot(match, actor=None, coord=None)
    assert first_snapshot['boards']['A']['grid'][1][1] == 1
    assert first_snapshot['boards']['B']['grid'][0][2] == 1
    assert first_snapshot['history'][1][1][0] == 0

    coord = (1, 1)
    res = apply_shot(match.boards['A'], coord)
    assert res == KILL
    update_history(match.history, match.boards, coord, {'A': res, 'B': MISS})
    match.last_highlight = match.boards['A'].highlight.copy()
    match.turn = 'B'

    second_snapshot = record_snapshot(match, actor='B', coord=coord)
    assert second_snapshot['history'][1][1][0] == 4
    assert second_snapshot['boards']['B']['grid'][0][2] == 1
    assert tuple(coord) in second_snapshot['last_highlight']

    # Mutate live state to ensure snapshots stay immutable
    match.boards['A'].grid[1][1] = 0
    match.history[1][1][0] = 0

    assert match.snapshots[0]['boards']['A']['grid'][1][1] == 1
    assert match.snapshots[1]['history'][1][1][0] == 4


def test_kill_contour_preserves_previous_states():
    history = _new_grid(15)
    boards = {'B': Board15()}
    ship = Ship(cells=[(1, 1)])
    boards['B'].ships = [ship]
    boards['B'].grid[1][1] = 1

    preset = {
        (0, 0): (2, 'miss_owner'),
        (0, 1): (3, 'hit_owner'),
        (1, 0): (5, 'contour_owner'),
        (1, 2): (3, 'another_hit'),
        (2, 2): (4, 'kill_owner'),
    }
    for (rr, cc), (state, owner) in preset.items():
        history[rr][cc][0] = state
        history[rr][cc][1] = owner

    res = apply_shot(boards['B'], (1, 1))
    assert res == KILL
    update_history(history, boards, (1, 1), {'B': res})

    for rr in range(0, 3):
        for cc in range(0, 3):
            state = _state(history[rr][cc])
            if (rr, cc) == (1, 1):
                assert state == 4
            elif (rr, cc) in preset:
                assert state == preset[(rr, cc)][0]
            else:
                assert state == 5


def test_kill_contour_marks_only_unknown_cells():
    history = _new_grid(15)
    boards = {'B': Board15()}
    ship = Ship(cells=[(1, 1)])
    boards['B'].ships = [ship]
    boards['B'].grid[1][1] = 1

    # Pre-mark a miss that should remain unchanged
    history[0][0][0] = 2

    res = apply_shot(boards['B'], (1, 1))
    assert res == KILL
    update_history(history, boards, (1, 1), {'B': res})

    for rr in range(0, 3):
        for cc in range(0, 3):
            if (rr, cc) == (1, 1):
                assert _state(history[rr][cc]) == 4
            elif (rr, cc) == (0, 0):
                assert _state(history[rr][cc]) == 2
            else:
                assert _state(history[rr][cc]) == 5


def test_ignore_foreign_board_ships_for_miss():
    history = _new_grid(15)
    boards = {'A': Board15(), 'B': Board15()}
    ship = Ship(cells=[(0, 0)])
    boards['B'].ships = [ship]
    boards['B'].grid[0][0] = 1

    res = apply_shot(boards['A'], (0, 0))
    assert res == MISS
    update_history(history, boards, (0, 0), {'A': res})
    assert _get_cell_state(history[0][0]) == 2

    import sys
    import importlib
    sys.modules.pop('PIL', None)
    sys.modules.pop('game_board15.renderer', None)
    from PIL import Image
    renderer = importlib.import_module('game_board15.renderer')
    from game_board15.state import Board15State

    board = [[_get_cell_state(cell) for cell in row] for row in history]
    state = Board15State(board=board)
    buf = renderer.render_board(state)

    img = Image.open(buf)
    x0 = renderer.TILE_PX
    y0 = renderer.TILE_PX
    cx = x0 + renderer.TILE_PX // 2
    cy = y0 + renderer.TILE_PX // 2
    assert img.getpixel((cx, cy)) == renderer.COLORS[renderer.THEME]['miss']
    sample = (cx + 6, cy)
    assert img.getpixel(sample) == renderer.COLORS[renderer.THEME]['bg']


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


def test_friendly_ship_visible_to_owner_after_miss(monkeypatch):
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
        assert _state(match.history[0][0]) == 2

        for owner_key, board in match.boards.items():
            if board.highlight:
                for rr, cc in board.highlight:
                    history_state = _get_cell_state(match.history[rr][cc])
                    if history_state != 0:
                        continue
                    board_state = _get_cell_state(board.grid[rr][cc])
                    if board_state == 1:
                        continue
                    if board_state == 3:
                        _set_cell_state(match.history, rr, cc, 3, owner_key)
                        continue
                    if board_state == 4:
                        _set_cell_state(match.history, rr, cc, 4, owner_key)
                        for dr in (-1, 0, 1):
                            for dc in (-1, 0, 1):
                                nr, nc = rr + dr, cc + dc
                                if 0 <= nr < 15 and 0 <= nc < 15:
                                    if _get_cell_state(match.history[nr][nc]) == 0 and _get_cell_state(board.grid[nr][nc]) == 5:
                                        _set_cell_state(
                                            match.history,
                                            nr,
                                            nc,
                                            5,
                                            _get_cell_owner(match.history[nr][nc]),
                                        )
                        continue
                    if board_state == 5:
                        _set_cell_state(
                            match.history,
                            rr,
                            cc,
                            5,
                            _get_cell_owner(match.history[rr][cc]),
                        )
                        continue
                    if all(_get_cell_state(other.grid[rr][cc]) != 1 for other in match.boards.values()):
                        _set_cell_state(match.history, rr, cc, 2)
            board.highlight = []

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
        await router._send_state(context, match, 'B', 'msg')

        assert captured['A'][0][0] == 1
        assert captured['B'][0][0] == 2

    asyncio.run(run_test())


def test_clear_highlight_preserves_miss():
    match = SimpleNamespace(
        boards={'A': Board15(), 'B': Board15()},
        history=_new_grid(15),
    )
    match.boards['A'].highlight = [(0, 0)]

    for owner_key, board in match.boards.items():
        if board.highlight:
            for rr, cc in board.highlight:
                history_state = _get_cell_state(match.history[rr][cc])
                if history_state != 0:
                    continue
                board_state = _get_cell_state(board.grid[rr][cc])
                if board_state == 1:
                    continue
                if board_state == 3:
                    _set_cell_state(match.history, rr, cc, 3, owner_key)
                    continue
                if board_state == 4:
                    _set_cell_state(match.history, rr, cc, 4, owner_key)
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            nr, nc = rr + dr, cc + dc
                            if 0 <= nr < 15 and 0 <= nc < 15:
                                if _get_cell_state(match.history[nr][nc]) == 0 and _get_cell_state(board.grid[nr][nc]) == 5:
                                    _set_cell_state(
                                        match.history,
                                        nr,
                                        nc,
                                        5,
                                        _get_cell_owner(match.history[nr][nc]),
                                    )
                    continue
                if board_state == 5:
                    _set_cell_state(
                        match.history,
                        rr,
                        cc,
                        5,
                        _get_cell_owner(match.history[rr][cc]),
                    )
                    continue
                if all(_get_cell_state(other.grid[rr][cc]) != 1 for other in match.boards.values()):
                    _set_cell_state(match.history, rr, cc, 2)
        board.highlight = []

    assert _get_cell_state(match.history[0][0]) == 2


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
        assert second[0][0] == 2
        assert second[1][1] == 4

    asyncio.run(run_test())


def test_router_text_patches_history_on_noop_update(monkeypatch):
    async def run_test():
        coord = (0, 0)
        player_a = SimpleNamespace(chat_id=1, user_id=101, name='A')
        player_b = SimpleNamespace(chat_id=1, user_id=202, name='B')
        match = SimpleNamespace(
            players={'A': player_a, 'B': player_b},
            boards={'A': Board15(), 'B': Board15()},
            history=_new_grid(15),
            messages={'A': {}, 'B': {}},
            status='playing',
            turn='A',
        )
        ship = Ship(cells=[coord])
        match.boards['B'].ships = [ship]
        match.boards['B'].grid[coord[0]][coord[1]] = 1
        match.boards['B'].alive_cells = len(ship.cells)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=player_a.user_id),
            effective_chat=SimpleNamespace(id=player_a.chat_id),
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                send_photo=AsyncMock(),
            ),
            bot_data={},
            chat_data={},
        )

        monkeypatch.setattr(
            router.storage,
            'find_match_by_user',
            lambda *args, **kwargs: match,
        )
        monkeypatch.setattr(router.storage, 'save_match', lambda m: None)
        monkeypatch.setattr(router.storage, 'finish', lambda *args, **kwargs: None)
        monkeypatch.setattr(router.battle, 'update_history', lambda *args, **kwargs: None)

        calls: list[tuple[str, list[list[int]]]] = []

        async def fake_send_state(
            ctx,
            match_obj,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            board_copy = [
                [_get_cell_state(cell) for cell in row]
                for row in match_obj.history
            ]
            calls.append((player_key, board_copy))

        monkeypatch.setattr(router, '_send_state', fake_send_state)

        await router.router_text(update, context)

        assert calls, 'expected _send_state to be invoked'
        player_key, board_state = calls[0]
        assert player_key == 'A'
        assert board_state[coord[0]][coord[1]] == 4
        assert _get_cell_state(match.history[coord[0]][coord[1]]) == 4
        assert _get_cell_owner(match.history[coord[0]][coord[1]]) == 'B'

    asyncio.run(run_test())


def test_board15_test_autoplay_preserves_kill_highlight(monkeypatch):
    async def run():
        match = Match15.new(1, 10, "Tester")

        board_a = Board15()
        ship_a = Ship(cells=[(7, 7)])
        board_a.ships = [ship_a]
        board_a.grid[7][7] = 1
        board_a.alive_cells = len(ship_a.cells)

        board_b = Board15()
        ship_b = Ship(cells=[(5, 5)])
        board_b.ships = [ship_b]
        board_b.grid[5][5] = 1
        board_b.alive_cells = len(ship_b.cells)

        board_c = Board15()
        ship_c = Ship(cells=[(0, 0)])
        board_c.ships = [ship_c]
        board_c.grid[0][0] = 1
        board_c.alive_cells = len(ship_c.cells)

        boards = [board_a, board_b, board_c]

        monkeypatch.setattr(
            handlers.placement,
            "random_board_global",
            lambda mask: boards.pop(0),
        )

        monkeypatch.setattr(storage, "create_match", lambda uid, cid, name="": match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "get_match", lambda mid: match)
        monkeypatch.setattr(storage, "finish", lambda m, w: None)

        captured: list[list[list[int]]] = []
        board_ready = asyncio.Event()

        def fake_render_board(state, player_key=None):
            board_copy = [row[:] for row in state.board]
            if player_key == "A":
                captured.append(board_copy)
                if board_copy[0][0] == 4:
                    board_ready.set()
            return BytesIO(b"img")

        monkeypatch.setattr(handlers, "render_board", fake_render_board)
        monkeypatch.setattr(router, "render_board", fake_render_board)

        orig_choice = handlers.random.choice

        def choose_target(seq):
            if (0, 0) in seq:
                return (0, 0)
            return orig_choice(seq)

        monkeypatch.setattr(handlers.random, "choice", choose_target)

        orig_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await orig_sleep(0)

        monkeypatch.setattr(handlers.asyncio, "sleep", fast_sleep)

        update = SimpleNamespace(
            message=SimpleNamespace(
                reply_text=AsyncMock(),
                reply_photo=AsyncMock(
                    return_value=SimpleNamespace(message_id=101)
                ),
            ),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=200),
        )

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=202)),
            ),
            bot_data={},
            chat_data={},
        )

        await handlers.board15_test(update, context)
        match.turn = "B"

        await asyncio.wait_for(board_ready.wait(), timeout=0.2)

        board = next(board for board in captured if board[0][0] == 4)
        assert board[0][0] == 4
        contour_cells = [
            board[r][c]
            for r in range(0, 2)
            for c in range(0, 2)
            if (r, c) != (0, 0)
        ]
        assert any(cell == 5 for cell in contour_cells)

        for task in list(context.chat_data.get("_board15_auto_tasks", [])):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(run())
