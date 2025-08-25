import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import handlers, storage, router
from game_board15.models import Board15


def test_board15_test_manual(monkeypatch):
    async def run():
        boards = [Board15(), Board15(), Board15()]
        monkeypatch.setattr(handlers.placement, 'random_board', lambda: boards.pop(0))
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        def fake_finish(match, winner):
            match.status = 'finished'
        monkeypatch.setattr(storage, 'finish', fake_finish)
        created_match = None
        def fake_create_match(uid, cid, name):
            nonlocal created_match
            created_match = storage.Match15.new(uid, cid, name)
            return created_match
        monkeypatch.setattr(handlers.storage, 'create_match', fake_create_match)
        monkeypatch.setattr(handlers.storage, 'find_match_by_user', lambda uid: created_match)
        shot_counter = {'count': 0}
        def fake_apply_shot(board, coord):
            if created_match.turn == 'A':
                return handlers.battle.MISS
            shot_counter['count'] += 1
            if shot_counter['count'] == 1:
                board.alive_cells = 0
                return handlers.battle.KILL
            if shot_counter['count'] == 2:
                return handlers.battle.MISS
            if shot_counter['count'] == 3:
                board.alive_cells = 0
                return handlers.battle.KILL
            return handlers.battle.MISS
        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        sends = []
        async def fake_send_state(context, match, player_key, message):
            sends.append((player_key, message))
        monkeypatch.setattr(router, '_send_state', fake_send_state)
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
            effective_chat=SimpleNamespace(id=100),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})
        await handlers.board15_test(update, context)
        await asyncio.sleep(0.1)
        assert context.bot.send_message.call_count == 0
        states = context.bot_data.setdefault(handlers.STATE_KEY, {})
        state = handlers.Board15State(chat_id=update.effective_chat.id)
        state.selected = (0, 0)
        states[update.effective_chat.id] = state
        query = SimpleNamespace(
            data='b15|act|confirm',
            answer=AsyncMock(),
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )
        update_click = SimpleNamespace(callback_query=query, effective_chat=update.effective_chat)
        await handlers.board15_on_click(update_click, context)
        await asyncio.gather(*tasks)
        assert len(sends) >= 7
        messages = [c.args[1] for c in context.bot.send_message.call_args_list]
        assert any('Вы победили' in m or 'Победил соперник' in m for m in messages)
    asyncio.run(run())
