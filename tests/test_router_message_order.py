import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers import router
from logic import placement, parser
import storage


class DummyBot:
    def __init__(self):
        self.logs: dict[int, list[str]] = {}
        self.msg_id = 1

    async def send_message(self, chat_id, *args, **kwargs):
        kind = 'board_send' if 'reply_markup' in kwargs else 'text_send'
        self.logs.setdefault(chat_id, []).append(kind)
        self.msg_id += 1
        return SimpleNamespace(message_id=self.msg_id)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        kind = 'board_edit' if 'reply_markup' in kwargs else 'text_edit'
        self.logs.setdefault(chat_id, []).append(kind)

    async def delete_message(self, *args, **kwargs):
        pass


def _find_empty_cells(board1, board2):
    cells = []
    for r in range(10):
        for c in range(10):
            if board1.grid[r][c] == 0 and board2.grid[r][c] == 0:
                cells.append((r, c))
                if len(cells) == 2:
                    return cells
    return cells


def test_router_message_order(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA_FILE', tmp_path / 'data.json')
    random.seed(0)

    match = storage.create_match(1, 1)
    storage.join_match(match.match_id, 2, 2)

    board_a = placement.random_board()
    board_b = placement.random_board()
    storage.save_board(match, 'A', board_a)
    storage.save_board(match, 'B', board_b)

    (r1, c1), (r2, c2) = _find_empty_cells(board_a, board_b)
    coord1 = parser.format_coord((r1, c1))
    coord2 = parser.format_coord((r2, c2))

    bot = DummyBot()
    context = SimpleNamespace(bot=bot)

    async def play_moves():
        upd1 = SimpleNamespace(
            message=SimpleNamespace(text=coord1, reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        await router.router_text(upd1, context)

        upd2 = SimpleNamespace(
            message=SimpleNamespace(text=coord2, reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=2),
            effective_chat=SimpleNamespace(id=2),
        )
        await router.router_text(upd2, context)

    asyncio.run(play_moves())

    expected = ['board_send', 'text_send', 'board_send', 'text_edit']
    assert bot.logs[1] == expected
    assert bot.logs[2] == expected
