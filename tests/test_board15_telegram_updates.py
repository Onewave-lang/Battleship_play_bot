import asyncio
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Stub Pillow before importing router
pil = types.ModuleType("PIL")
pil.Image = types.SimpleNamespace()
pil.ImageDraw = types.SimpleNamespace()
pil.ImageFont = types.SimpleNamespace()
sys.modules.setdefault("PIL", pil)

from game_board15 import router, storage, battle


def test_board_updates_accumulate(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")

    match = storage.create_match(1, 1, "A")
    match = storage.join_match(match.match_id, 2, 2, "B")
    match.status = "playing"
    storage.save_match(match)

    boards = []

    def fake_render_board(state, player_key=None):
        boards.append([row[:] for row in state.board])
        return BytesIO(b"board")

    monkeypatch.setattr(router, "render_board", fake_render_board)
    monkeypatch.setattr(router, "render_player_board", lambda board, player_key=None: BytesIO(b"own"))

    class DummyBot:
        def __init__(self):
            self.mid = 0
            self.send_photo = AsyncMock(side_effect=self._send_photo)
            self.edit_message_media = AsyncMock()
            self.send_message = AsyncMock(side_effect=self._send_message)
            self.edit_message_text = AsyncMock()

        async def _send_photo(self, *args, **kwargs):
            self.mid += 1
            return SimpleNamespace(message_id=self.mid)

        async def _send_message(self, *args, **kwargs):
            self.mid += 1
            return SimpleNamespace(message_id=self.mid)

    bot = DummyBot()
    context = SimpleNamespace(bot=bot, bot_data={})

    coord1 = (0, 0)
    res1 = battle.apply_shot(match.board, coord1)
    battle.update_history(match.history, match.board, match.cell_owner, coord1, {'B': res1})
    match.shots['A']['last_coord'] = coord1
    asyncio.run(router._send_state(context, match, 'A', 'msg'))
    assert boards[0][0][0] == 2

    coord2 = (1, 1)
    res2 = battle.apply_shot(match.board, coord2)
    battle.update_history(match.history, match.board, match.cell_owner, coord2, {'A': res2})
    match.shots['B']['last_coord'] = coord2
    asyncio.run(router._send_state(context, match, 'B', 'msg'))
    assert boards[1][0][0] == 2
    assert boards[1][1][1] == 2

    asyncio.run(router._send_state(context, match, 'A', 'msg'))
    assert boards[2][0][0] == 2
    assert boards[2][1][1] == 2

    assert bot.send_photo.await_count > 0
    assert bot.edit_message_media.await_count > 0
