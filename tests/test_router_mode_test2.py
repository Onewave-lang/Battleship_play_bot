import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers import router
from logic import placement
from models import Player
import storage


class DummyBot:
    def __init__(self):
        self.logs: dict[int, list[str]] = {}
        self.msg_id = 0

    async def send_message(self, chat_id, text, *args, **kwargs):
        kind = 'board_send' if 'Поле соперника:' in text else 'text_send'
        self.logs.setdefault(chat_id, []).append(kind)
        self.msg_id += 1
        return SimpleNamespace(message_id=self.msg_id)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        kind = 'board_edit' if 'Поле соперника:' in text else 'text_edit'
        self.logs.setdefault(chat_id, []).append(kind)

    async def delete_message(self, *args, **kwargs):
        pass


def test_mode_test2_autoplace_sends_single_board(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA_FILE', tmp_path / 'data.json')
    monkeypatch.setattr(router, 'STATE_DELAY', 0)
    random.seed(0)

    match = storage.create_match(1, 1)
    match.players['B'] = Player(user_id=0, chat_id=1, ready=True)
    board_b = placement.random_board()
    board_b.owner = 'B'
    match.boards['B'] = board_b
    match.status = 'placing'
    match.turn = 'A'
    match.messages.setdefault('_flags', {})['mode_test2'] = True
    storage.save_match(match)

    bot = DummyBot()
    context = SimpleNamespace(bot=bot)

    message = SimpleNamespace(
        text='авто',
        reply_text=AsyncMock(),
        entities=[],
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=1),
    )

    asyncio.run(router.router_text(update, context))

    assert bot.logs[1] == ['board_send']
