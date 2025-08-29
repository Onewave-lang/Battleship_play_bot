import asyncio
import random
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Stub Pillow before importing router
pil = types.ModuleType('PIL')
pil.Image = types.SimpleNamespace()
pil.ImageDraw = types.SimpleNamespace()
pil.ImageFont = types.SimpleNamespace()
sys.modules.setdefault('PIL', pil)

from game_board15 import router, storage, placement, parser


class DummyBot:
    def __init__(self):
        self.logs: dict[int, list[str]] = {}
        self.msg_id = 1

    async def send_photo(self, chat_id, *args, **kwargs):
        self.logs.setdefault(chat_id, []).append('photo')
        self.msg_id += 1
        return SimpleNamespace(message_id=self.msg_id)

    async def edit_message_media(self, chat_id, message_id, media):
        self.logs.setdefault(chat_id, []).append('photo')

    async def send_message(self, chat_id, *args, **kwargs):
        self.logs.setdefault(chat_id, []).append('text_send')
        self.msg_id += 1
        return SimpleNamespace(message_id=self.msg_id)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.logs.setdefault(chat_id, []).append('text_edit')

    async def delete_message(self, *args, **kwargs):
        pass


def _find_empty_cells(boards, count):
    cells = []
    for r in range(15):
        for c in range(15):
            if all(b.grid[r][c] == 0 for b in boards):
                cells.append((r, c))
                if len(cells) == count:
                    return cells
    return cells


def test_board15_message_order(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA_FILE', tmp_path / 'data15.json')
    random.seed(0)

    match = storage.create_match(1, 1, 'A')
    storage.join_match(match.match_id, 2, 2, 'B')
    storage.join_match(match.match_id, 3, 3, 'C')

    board_a = placement.random_board()
    board_b = placement.random_board()
    board_c = placement.random_board()
    storage.save_board(match, 'A', board_a)
    storage.save_board(match, 'B', board_b)
    storage.save_board(match, 'C', board_c)

    (r1, c1), (r2, c2) = _find_empty_cells([board_a, board_b, board_c], 2)
    coord1 = parser.format_coord((r1, c1))
    coord2 = parser.format_coord((r2, c2))

    monkeypatch.setattr(router, 'render_board', lambda state, player_key=None: BytesIO(b'board'))
    monkeypatch.setattr(router, 'render_player_board', lambda board, player_key=None: BytesIO(b'own'))

    bot = DummyBot()
    context = SimpleNamespace(bot=bot, bot_data={})

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

    expected = ['photo', 'photo', 'text_send', 'photo', 'photo', 'text_send', 'photo', 'photo', 'text_send']
    extra = ['photo', 'photo', 'text_send', 'photo', 'photo', 'text_send', 'photo', 'photo', 'text_send', 'photo', 'photo', 'text_send']
    assert bot.logs[1] == expected
    assert bot.logs[2] == expected
    assert bot.logs[3] == extra
