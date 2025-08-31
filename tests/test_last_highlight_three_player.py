from types import SimpleNamespace
import asyncio
from io import BytesIO
from unittest.mock import AsyncMock

from game_board15 import router, storage
from game_board15.models import Match15, Player, Ship


def test_last_highlight_three_player(monkeypatch):
    async def run_test():
        match = Match15.new(1, 10, "A")
        match.status = "playing"
        match.players["B"] = Player(user_id=2, chat_id=20, name="B")
        match.players["C"] = Player(user_id=3, chat_id=30, name="C")

        board_b = match.boards["B"]
        ship_b = Ship(cells=[(0, 0), (0, 1)])
        board_b.ships = [ship_b]
        board_b.grid[0][0] = 3
        board_b.grid[0][1] = 1
        board_b.alive_cells = 1

        board_c = match.boards["C"]
        ship_c = Ship(cells=[(5, 5)])
        board_c.ships = [ship_c]
        board_c.grid[5][5] = 1
        board_c.alive_cells = 1

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")

        highlights = []

        def fake_render_board(state, player_key):
            highlights.append(state.highlight.copy())
            return BytesIO(b"img")

        monkeypatch.setattr(router, "render_board", fake_render_board)

        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
        )
        context = SimpleNamespace(bot=bot, bot_data={})
        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )

        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (0, 1))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "a1")
        await router.router_text(update, context)
        highlights.clear()
        await router._send_state(context, match, "A", "msg")
        assert highlights[-1][0] == (0, 1)

        match.turn = "A"

        monkeypatch.setattr(router.parser, "parse_coord", lambda text: (2, 2))
        monkeypatch.setattr(router.parser, "format_coord", lambda coord: "c3")
        update.message.text = "c3"
        await router.router_text(update, context)
        highlights.clear()
        await router._send_state(context, match, "A", "msg")
        assert highlights[-1] == [(2, 2)]

    asyncio.run(run_test())
