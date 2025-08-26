import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import handlers, storage
from game_board15.models import Match15, Player, Ship


def test_board15_notifies_on_bot_elimination(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.status = 'playing'
        ship = Ship(cells=[(0, 0)])
        match.boards['B'].ships = [ship]
        match.boards['B'].grid[0][0] = 1
        match.boards['B'].alive_cells = 1

        state = handlers.Board15State(chat_id=1)
        state.selected = (0, 0)
        state.player_key = 'A'

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        from game_board15 import router
        monkeypatch.setattr(router, '_send_state', AsyncMock())
        monkeypatch.setattr(handlers.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(handlers, '_phrase_or_joke', lambda m, pk, ph: '')

        def fake_apply_shot(board, coord):
            board.alive_cells = 0
            return handlers.battle.KILL

        monkeypatch.setattr(handlers.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(handlers.battle, 'update_history', lambda h, b, c, r: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={handlers.STATE_KEY: {1: state}},
        )

        query = SimpleNamespace(
            data='b15|act|confirm',
            answer=AsyncMock(),
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )
        update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=1))

        await handlers.board15_on_click(update, context)

        calls = [(c.args[0], c.args[1]) for c in context.bot.send_message.call_args_list]
        assert (1, '⛔ Игрок B выбыл (флот уничтожен)') in calls

    asyncio.run(run())
