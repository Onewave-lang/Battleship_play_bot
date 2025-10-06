import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, storage, router
from game_board15.models import Board15, Match15, Player, Ship
from tests.utils import _new_grid
from game_board15.utils import _get_cell_state


def test_board15_test_autoplay(monkeypatch):
    async def run():
        boards = [Board15(), Board15(alive_cells=0), Board15(alive_cells=0)]
        def fake_random_board(mask):
            return boards.pop(0)
        monkeypatch.setattr(handlers.placement, 'random_board_global', fake_random_board)
        holder = {}

        def fake_save_match(m: Match15):
            holder['match'] = m

        monkeypatch.setattr(storage, 'save_match', fake_save_match)
        monkeypatch.setattr(storage, 'get_match', lambda mid: holder.get('match'))
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        tasks = []
        orig_create_task = asyncio.create_task
        def fake_create_task(coro):
            task = orig_create_task(coro)
            tasks.append(task)
            return task
        monkeypatch.setattr(asyncio, 'create_task', fake_create_task)
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1, first_name='Tester'),
            effective_chat=SimpleNamespace(id=100)
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock()),
            bot_data={},
        )
        context.bot.send_photo.return_value = SimpleNamespace(message_id=1)
        await handlers.board15_test(update, context)
        await asyncio.gather(*tasks)
        messages = [c.args[1] for c in context.bot.send_message.call_args_list]
        assert any('Вы победили!🏆' in m for m in messages)
    asyncio.run(run())


def test_auto_play_bots_skips_closed(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'B'
        match.history = _new_grid(15)
        match.history = _new_grid(15)
        match.history = _new_grid(15)
        match.history[0][0][0] = 2
        match.history[0][1][0] = 3
        match.history[0][2][0] = 5

        recorded = {}

        def fake_apply_shot(board, coord):
            recorded['coord'] = coord
            raise RuntimeError('stop')

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 0)

        assert recorded['coord'] == (0, 3)

    asyncio.run(run())


def test_auto_play_bots_skips_own_ship(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'B'
        match.boards['B'].grid[0][0] = 1

        recorded = {}

        def fake_apply_shot(board, coord):
            recorded['coord'] = coord
            raise RuntimeError('stop')

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 0)

        assert recorded['coord'] == (0, 2)

    asyncio.run(run())


def test_auto_play_bots_notifies_human_on_hit_without_board(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.players['C'] = Player(user_id=0, chat_id=2, name='C')
        match.status = 'playing'
        match.turn = 'B'

        state_calls: list[tuple[str, str]] = []

        async def fake_send_state(
            context,
            match_,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            state_calls.append((player_key, message))

        hits = {'count': 0}

        def fake_apply_shot(board, coord):
            hits['count'] += 1
            if hits['count'] == 1 and board is match.boards['A']:
                return handlers.battle.HIT
            if hits['count'] == 2:
                return handlers.battle.MISS
            raise RuntimeError('stop')

        monkeypatch.setattr(router, '_send_state', fake_send_state)
        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(handlers, '_phrase_or_joke', lambda *args, **kwargs: '')

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 1, delay=0)

        assert all(player != 'A' for player, _ in state_calls)
        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args[0][1]
        assert 'Ход игрока B' in sent_text

    asyncio.run(run())


def test_auto_play_bots_accepts_int_history(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.players['C'] = Player(user_id=0, chat_id=2, name='C')
        match.status = 'playing'
        match.turn = 'B'
        match.history = [[0 for _ in range(15)] for _ in range(15)]

        calls = {'count': 0}

        def fake_apply_shot(board, coord):
            calls['count'] += 1
            if calls['count'] >= 2:
                raise RuntimeError('stop')
            return handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(router, '_send_state', AsyncMock())

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 1)

        assert calls['count'] == 2

    asyncio.run(run())


def test_auto_play_bots_waits_for_human(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'A'

        called = {'n': 0}

        def fake_apply_shot(board, coord):
            called['n'] += 1
            return handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(router, '_send_state', AsyncMock())

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                handlers._auto_play_bots(match, context, 0, delay=1),
                timeout=0.05,
            )

        assert called['n'] == 0

    asyncio.run(run())


def test_auto_play_bots_reports_hits(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.players['C'] = Player(user_id=0, chat_id=2, name='C')
        match.status = 'playing'
        match.turn = 'B'
        ship = Ship(cells=[(0, 0)])
        match.boards['C'].ships = [ship]
        match.boards['C'].grid[0][0] = 1
        match.boards['C'].alive_cells = 1

        def fake_apply_shot(board, coord):
            return handlers.battle.HIT if board is match.boards['C'] else handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: (0, 0))

        calls: list[tuple[str, str]] = []

        async def fake_send_state(
            context,
            match_,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            calls.append((player_key, message))

            await asyncio.sleep(0)


        monkeypatch.setattr(router, '_send_state', fake_send_state)

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            # Allow the event loop to run other tasks without real delay
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                handlers._auto_play_bots(match, context, 1, delay=1),
                timeout=0.01,
            )

        assert all(player != 'A' for player, _ in calls)
        assert context.bot.send_message.call_count == 0
        hist = match.shots['B']['history']
        assert any(entry['enemy'] == 'C' and entry['result'] == handlers.battle.HIT for entry in hist)
        assert any(entry['enemy'] == 'A' and entry['result'] == handlers.battle.MISS for entry in hist)

    asyncio.run(run())


def test_auto_play_bots_persists_previous_highlight(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['A'].name = 'A'
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.players['C'] = Player(user_id=0, chat_id=2, name='C')
        match.status = 'playing'
        match.turn = 'B'
        match.history = _new_grid(15)
        match.messages = {key: {} for key in match.players}
        match.shots = {
            key: {
                'history': [],
                'last_result': None,
                'move_count': 0,
                'joke_start': 1,
                'last_coord': None,
            }
            for key in match.players
        }

        board_c = match.boards['C']
        board_c.highlight = [(0, 0), (0, 1)]
        for rr, cc in board_c.highlight:
            board_c.grid[rr][cc] = 4
        board_c.grid[1][0] = 5
        board_c.grid[1][1] = 5

        def fake_apply_shot(board, coord):
            return handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(router, '_send_state', AsyncMock())
        monkeypatch.setattr(handlers, '_phrase_or_joke', lambda *a, **k: '')
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])
        monkeypatch.setattr(handlers.random, 'randint', lambda a, b: a)
        monkeypatch.setattr(handlers.parser, 'format_coord', lambda coord: 'a1')

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={},
            chat_data={},
        )

        task = asyncio.create_task(
            handlers._auto_play_bots(match, context, 1, human='A', delay=0)
        )

        for _ in range(10):
            await asyncio.sleep(0)
            if _get_cell_state(match.history[0][0]) == 4:
                break

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert _get_cell_state(match.history[0][0]) == 4
        assert _get_cell_state(match.history[0][1]) == 4
        assert _get_cell_state(match.history[1][0]) == 5
        assert _get_cell_state(match.history[1][1]) == 5
        assert all(cell not in board_c.highlight for cell in [(0, 0), (0, 1)])

    asyncio.run(run())


def test_auto_play_bots_records_snapshots(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'B'
        match.history = _new_grid(15)

        captured: dict[str, object] = {}

        async def fake_send_state(
            context,
            match_,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            captured['snapshot'] = snapshot_override
            await asyncio.sleep(0)

        monkeypatch.setattr(router, '_send_state', fake_send_state)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.battle, 'apply_shot', lambda board, coord: handlers.battle.MISS)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                handlers._auto_play_bots(match, context, 1, delay=0),
                timeout=0.01,
            )

        assert len(match.snapshots) >= 1
        snapshot = match.snapshots[-1]
        assert snapshot['actor'] == 'B'
        assert snapshot['coord'] == (0, 0)
        captured_snapshot = captured.get('snapshot')
        assert captured_snapshot is None or captured_snapshot is snapshot

    asyncio.run(run())


def test_auto_play_bots_uses_fallback_when_only_own_cells_left(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.players['C'] = Player(user_id=0, chat_id=0, name='C')
        match.status = 'playing'
        match.turn = 'B'

        for r in range(15):
            for c in range(15):
                if r == 0 and c == 0:
                    continue
                match.history[r][c][0] = 2
        match.boards['B'].grid[0][0] = 1

        recorded = {}

        def fake_apply_shot(board, coord):
            recorded.setdefault('coords', []).append(coord)
            raise RuntimeError('stop')

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 0)

        assert recorded['coords'][0] == (0, 0)

    asyncio.run(run())


def test_auto_play_bots_refreshes_match(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'B'
        match.history = _new_grid(15)

        recorded: list[tuple[int, int]] = []
        import copy
        current = copy.deepcopy(match)
        calls = 0

        def fake_get_match(match_id: str):
            nonlocal current, calls
            calls += 1
            if calls == 2:
                current.history[0][1][0] = 2
                current.turn = 'B'
            return copy.deepcopy(current)

        def fake_save_match(m: Match15):
            nonlocal current
            current = copy.deepcopy(m)

        monkeypatch.setattr(storage, 'get_match', fake_get_match)
        monkeypatch.setattr(storage, 'save_match', fake_save_match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        monkeypatch.setattr(router, '_send_state', AsyncMock())
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        async def fake_sleep(t):
            return None

        monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

        def fake_apply_shot(board, coord):
            recorded.append(coord)
            if len(recorded) == 2:
                raise RuntimeError('stop')
            return handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 0)

        assert recorded == [(0, 0), (0, 2)]
        assert calls >= 2

    asyncio.run(run())
