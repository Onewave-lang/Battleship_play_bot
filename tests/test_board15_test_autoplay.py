import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import handlers, storage
from game_board15.models import Board15


def test_board15_test_autoplay(monkeypatch):
    async def run():
        boards = [Board15(), Board15(alive_cells=0), Board15(alive_cells=0)]
        def fake_random_board():
            return boards.pop(0)
        monkeypatch.setattr(handlers.placement, 'random_board', fake_random_board)
        monkeypatch.setattr(storage, 'save_match', lambda m: None)
        monkeypatch.setattr(storage, 'finish', lambda m, w: None)
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1, first_name='Tester'),
            effective_chat=SimpleNamespace(id=100)
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await handlers.board15_test(update, context)
        assert 'Победил игрок A' in context.bot.send_message.call_args_list[-1][0][1]
    asyncio.run(run())
