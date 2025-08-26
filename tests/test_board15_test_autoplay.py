import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, storage, router
from game_board15.models import Board15, Match15, Player


def test_board15_test_autoplay(monkeypatch):
    async def run():
        boards = [Board15(), Board15(alive_cells=0), Board15(alive_cells=0)]
        def fake_random_board(*args, **kwargs):
            return boards.pop(0)
        monkeypatch.setattr(handlers.placement, 'random_board', fake_random_board)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
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
        assert any('Вы победили' in m for m in messages)
    asyncio.run(run())


def test_auto_play_bots_skips_closed(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=0, name='B')
        match.status = 'playing'
        match.turn = 'B'
        match.history[0][0] = 2
        match.history[0][1] = 3
        match.history[0][2] = 5

        recorded = {}

        def fake_apply_shot(board, coord):
            recorded['coord'] = coord
            raise RuntimeError('stop')

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

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
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 0)

        assert recorded['coord'] == (0, 1)

    asyncio.run(run())


def test_auto_play_bots_notifies_human(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.players['C'] = Player(user_id=0, chat_id=1, name='C')
        match.status = 'playing'
        match.turn = 'B'

        calls: list[tuple[str, str]] = []

        async def fake_send_state(context, match_, player_key, message):
            calls.append((player_key, message))
            if player_key == 'A' and message.endswith('Ваш ход.'):
                raise RuntimeError('stop')

        monkeypatch.setattr(router, '_send_state', fake_send_state)
        monkeypatch.setattr(handlers.battle, 'apply_shot', lambda board, coord: handlers.battle.MISS)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        with pytest.raises(RuntimeError):
            await handlers._auto_play_bots(match, context, 1)

        assert any(player == 'A' and msg.endswith('Ваш ход.') for player, msg in calls)
        assert all(player == 'A' for player, _ in calls)

    asyncio.run(run())
