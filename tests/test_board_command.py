import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import storage
from handlers import commands


def test_board_command_shows_fields(monkeypatch):
    async def run_test():
        match = SimpleNamespace(
            players={
                'A': SimpleNamespace(user_id=1, chat_id=1),
                'B': SimpleNamespace(user_id=2, chat_id=2),
            },
            boards={'A': SimpleNamespace(), 'B': SimpleNamespace()},
        )
        monkeypatch.setattr(storage, 'find_match_by_user', lambda uid: match)
        monkeypatch.setattr(commands, 'render_board_own', lambda board: 'own')
        monkeypatch.setattr(commands, 'render_board_enemy', lambda board: 'enemy')

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=1),
        )

        await commands.board(update, None)

        assert reply_text.call_args_list == [
            call('Ваше поле:\nown\nПоле соперника:\nenemy', parse_mode='HTML')
        ]

    asyncio.run(run_test())

