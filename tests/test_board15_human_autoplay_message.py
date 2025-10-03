import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, router, storage
from game_board15.models import Match15, Player
from tests.utils import _new_grid, _state


def test_human_shot_no_autoplay_and_message(monkeypatch):
    async def run():
        match = Match15.new(1, 10, 'A')
        match.players['B'] = Player(user_id=1, chat_id=20, name='B')
        match.status = 'playing'
        match.turn = 'A'
        match.history = _new_grid(15)

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'get_match', lambda mid: match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        shot_calls = {'n': 0}

        def fake_apply_shot(board, coord):
            shot_calls['n'] += 1
            return handlers.battle.MISS

        monkeypatch.setattr(router.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')

        send_calls = []

        async def fake_send_state(context, match_, player_key, message):
            send_calls.append((player_key, message))

        monkeypatch.setattr(router, '_send_state', fake_send_state)

        orig_sleep = asyncio.sleep

        async def fast_sleep(t):
            await orig_sleep(0)

        monkeypatch.setattr(asyncio, 'sleep', fast_sleep)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock()),
            bot_data={},
            chat_data={},
        )

        task = asyncio.create_task(handlers._auto_play_bots(match, context, 10, human='A', delay=0.01))
        await asyncio.sleep(0)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert shot_calls['n'] == 1
        assert any(player == 'A' and msg.startswith('Ход игрока A:') for player, msg in send_calls)

    asyncio.run(run())


def test_human_board_highlight_before_bot_move(monkeypatch):
    async def run():
        match = Match15.new(1, 10, 'A')
        match.players['A'].name = 'A'
        match.players['B'] = Player(user_id=0, chat_id=20, name='B')
        match.status = 'playing'
        match.turn = 'A'
        match.history = _new_grid(15)

        saved_state = copy.deepcopy(match)
        save_counter = {'count': 0}

        def fake_find_match_by_user(user_id, chat_id=None):
            return match

        def fake_save_match(obj):
            nonlocal saved_state
            save_counter['count'] += 1
            saved_state = copy.deepcopy(obj)
            return None

        def fake_get_match(match_id):
            return copy.deepcopy(saved_state)

        monkeypatch.setattr(storage, 'find_match_by_user', fake_find_match_by_user)
        monkeypatch.setattr(storage, 'save_match', fake_save_match)
        monkeypatch.setattr(storage, 'get_match', fake_get_match)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router.random, 'randint', lambda a, b: a)
        monkeypatch.setattr(handlers.random, 'randint', lambda a, b: a)
        monkeypatch.setattr(handlers.random, 'choice', lambda seq: seq[0])

        events: list[dict[str, object]] = []

        async def fake_send_state(context, match_obj, player_key, message):
            history = getattr(match_obj, 'history', [])
            history_state = [
                [_state(cell) for cell in row]
                for row in history
            ] if history else []
            events.append(
                {
                    'player': player_key,
                    'message': message,
                    'highlight': [tuple(cell) for cell in getattr(match_obj, 'last_highlight', [])],
                    'history': history_state,
                    'save_count': save_counter['count'],
                }
            )

        monkeypatch.setattr(router, '_send_state', fake_send_state)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock()),
            bot_data={},
            chat_data={},
        )

        task = asyncio.create_task(
            handlers._auto_play_bots(match, context, 10, human='A', delay=0)
        )
        await asyncio.sleep(0)

        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        await router.router_text(update, context)

        for _ in range(20):
            if len(events) >= 2:
                break
            await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert events, 'expected at least one board update'
        human_events = [e for e in events if e['player'] == 'A']
        assert human_events, 'expected human board update'
        assert human_events[0]['message'].startswith('Ваш ход:')
        assert human_events[0]['highlight'] == [(0, 0)]
        assert human_events[0]['save_count'] == 0

        bot_updates = [
            e for e in events[1:]
            if e['player'] == 'A' and isinstance(e['message'], str) and e['message'].startswith('Ход игрока B')
        ]
        assert bot_updates, 'expected bot move notification'
        assert bot_updates[0]['save_count'] >= 2
        assert bot_updates[0]['history'][0][0] == 2

        assert save_counter['count'] >= 2

    asyncio.run(run())
