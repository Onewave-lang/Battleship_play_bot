import asyncio
from types import SimpleNamespace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router, storage
from game_board15.models import Match15, Player, Ship


def test_router_notifies_on_bot_elimination(monkeypatch):
    async def run():
        match = Match15.new(1, 1, 'A')
        match.players['B'] = Player(user_id=0, chat_id=1, name='B')
        match.status = 'playing'
        ship = Ship(cells=[(0, 0)])
        match.boards['B'].ships = [ship]
        match.boards['B'].grid[0][0] = 1
        match.boards['B'].alive_cells = 1

        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)

        send_state = AsyncMock()
        monkeypatch.setattr(router, '_send_state', send_state)
        monkeypatch.setattr(router.parser, 'parse_coord', lambda text: (0, 0))
        monkeypatch.setattr(router.parser, 'format_coord', lambda coord: 'a1')
        monkeypatch.setattr(router, '_phrase_or_joke', lambda m, pk, ph: '')

        def fake_apply_shot(board, coord):
            board.alive_cells = 0
            return router.battle.KILL

        monkeypatch.setattr(router.battle, 'apply_shot', fake_apply_shot)
        monkeypatch.setattr(router.battle, 'update_history', lambda h, b, c, r: None)

        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={},
            chat_data={},
        )
        update = SimpleNamespace(
            message=SimpleNamespace(text='a1', reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )

        await router.router_text(update, context)

        assert context.bot.send_message.call_count == 1
        assert 'B выбывает' in context.bot.send_message.call_args.args[1]
        calls = [(c.args[2], c.args[3]) for c in send_state.call_args_list]
        assert any(
            player == 'A' and 'уничтожен корабль игрока B!' in msg
            for player, msg in calls
        )

    asyncio.run(run())
