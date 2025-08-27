import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import router, storage
from game_board15.models import Match15, Player


def test_router_text_blocks_own_ship(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=2, chat_id=2, name='B')
        match.status = 'playing'
        match.board.grid[0][0] = 1
        match.cell_owner[0][0] = 'A'

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))

        called = {'val': False}

        def fake_apply_shot(*args, **kwargs):
            called['val'] = True
            return router.battle.MISS

        monkeypatch.setattr(router.battle, 'apply_shot', fake_apply_shot)

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=reply_text),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={}, chat_data={})

        await router.router_text(update, context)
        assert reply_text.call_args[0][0] == 'Здесь ваш корабль'
        assert not called['val']

    asyncio.run(run())
