import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, router, storage
from game_board15.models import Match15, Player
from tests.utils import _new_grid


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
