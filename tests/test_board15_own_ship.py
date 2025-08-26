import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, router, storage
from game_board15.models import Match15, Player


def test_board15_on_click_blocks_own_ship(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=2, chat_id=2, name='B')
        match.status = 'playing'
        match.boards['A'].grid[0][0] = 1

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)

        called = {'val': False}

        def fake_apply_shot(board, coord):
            called['val'] = True
            return handlers.battle.MISS

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)

        state = handlers.Board15State(chat_id=1)
        state.selected = (0, 0)
        state.player_key = 'A'
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={handlers.STATE_KEY: {1: state}})

        query = SimpleNamespace(
            data='b15|act|confirm',
            answer=AsyncMock(),
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )
        update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=1))

        await handlers.board15_on_click(update, context)
        assert query.answer.call_args[0][0] == 'Здесь ваш корабль'
        assert not called['val']

    asyncio.run(run())


def test_router_text_blocks_own_ship(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=2, chat_id=2, name='B')
        match.status = 'playing'
        match.boards['A'].grid[0][0] = 1

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))

        called = {'val': False}

        def fake_apply_shot(board, coord):
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
