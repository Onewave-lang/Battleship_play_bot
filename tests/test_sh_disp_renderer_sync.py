import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.handlers import STATE_KEY
from game_board15.models import Match15, Ship

def test_send_state_rerenders_footer_when_ship_count_differs(monkeypatch):
    async def run():
        match = Match15.new(1, 101, "Tester")
        match.match_id = "abcd1234"
        match.messages.setdefault("_flags", {})["board15_test"] = True

        board = match.boards["A"]
        board.grid = [[0] * 15 for _ in range(15)]
        board.ships = []
        ship_cells = [
            (0, 0), (0, 1), (0, 2), (0, 3),
            (2, 0), (3, 0), (4, 0),
            (2, 2), (3, 2), (4, 2),
            (6, 0), (6, 1),
            (6, 3), (6, 4),
            (8, 1), (9, 1),
            (10, 10),
            (12, 12),
            (13, 6),
            (14, 14),
        ]
        for cell in ship_cells:
            r, c = cell
            board.grid[r][c] = 1
            board.ships.append(Ship(cells=[cell]))
        board.alive_cells = len(ship_cells)

        render_calls: list[str] = []

        def fake_render(state, player_key):
            render_calls.append(state.footer_label)
            state.rendered_ship_cells = 19
            buf = BytesIO()
            buf.write(b"png")
            buf.seek(0)
            return buf

        monkeypatch.setattr(router, "render_board", fake_render)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=42))
            ),
            bot_data={},
        )

        await router._send_state(context, match, "A", "test message")

        assert len(render_calls) == 2
        assert any("sh_disp=20" in call for call in render_calls[:1])
        assert "sh_disp=19" in render_calls[-1]

        state = context.bot_data[STATE_KEY][match.players["A"].chat_id]
        assert "sh_disp=19" in state.footer_label
        assert state.rendered_ship_cells == 19

        context.bot.send_photo.assert_awaited_once()

    asyncio.run(run())


def test_send_state_aborts_on_persistent_ship_count_mismatch(monkeypatch):
    async def run():
        match = Match15.new(1, 101, "Tester")
        match.match_id = "abcd1234"
        match.messages.setdefault("_flags", {})["board15_test"] = True

        board = match.boards["A"]
        board.grid = [[0] * 15 for _ in range(15)]
        board.ships = []
        ship_cells = [
            (0, 0), (0, 1), (0, 2), (0, 3),
            (2, 0), (3, 0), (4, 0),
            (2, 2), (3, 2), (4, 2),
            (6, 0), (6, 1),
            (6, 3), (6, 4),
            (8, 1), (9, 1),
            (10, 10),
            (12, 12),
            (13, 6),
            (14, 14),
        ]
        for coord in ship_cells:
            r, c = coord
            board.grid[r][c] = 1
            board.ships.append(Ship(cells=[coord]))
        board.alive_cells = len(ship_cells)

        render_calls: list[str] = []
        counts = [19, 20]

        def fake_render(state, player_key):
            render_calls.append(state.footer_label)
            idx = min(len(render_calls), len(counts)) - 1
            state.rendered_ship_cells = counts[idx]
            buf = BytesIO()
            buf.write(b"png")
            buf.seek(0)
            return buf

        monkeypatch.setattr(router, "render_board", fake_render)

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=42))
            ),
            bot_data={},
        )

        await router._send_state(context, match, "A", "test message")

        assert len(render_calls) == 2
        context.bot.send_photo.assert_not_awaited()

    asyncio.run(run())
