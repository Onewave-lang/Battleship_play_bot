import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import game_board15.render as render_mod
from game_board15 import router as router15
from game_board15.models import Field15, Match15, PLAYER_LIGHT_COLORS


def _cell_center(row: int, col: int) -> tuple[int, int]:
    x = render_mod.MARGIN + col * render_mod.CELL_SIZE + render_mod.CELL_SIZE // 2
    y = render_mod.MARGIN + row * render_mod.CELL_SIZE + render_mod.CELL_SIZE // 2
    return x, y


def test_render_board_hides_enemy_ships_when_reveal_disabled():
    field = Field15()
    field.grid[0][0] = 1
    field.owners[0][0] = "A"
    field.grid[0][1] = 1
    field.owners[0][1] = "B"

    history = [[[0, None] for _ in range(15)] for _ in range(15)]
    state = render_mod.RenderState(
        field=field,
        history=history,
        footer_label="visibility", 
        reveal_ships=False,
    )

    buffer = render_mod.render_board(state, "A")
    image = render_mod.Image.open(buffer)
    try:
        own_center = _cell_center(0, 0)
        enemy_center = _cell_center(0, 1)

        own_pixel = image.getpixel(own_center)
        enemy_pixel = image.getpixel(enemy_center)

        expected_own = PLAYER_LIGHT_COLORS["A"] + (255,)
        expected_bg = render_mod.BG_COLOR + (255,)

        assert own_pixel == expected_own
        assert enemy_pixel == expected_bg
    finally:
        image.close()


def test_send_state_disables_enemy_reveal(monkeypatch):
    async def run():
        match = Match15.new(1, 101, "Tester")

        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=42))
            ),
            bot_data={},
        )

        reveal_values: list[bool] = []

        def fake_render(state, player_key):
            reveal_values.append(state.reveal_ships)
            buf = BytesIO()
            buf.write(b"png")
            buf.seek(0)
            return buf

        monkeypatch.setattr(router15, "render_board", fake_render)

        await router15._send_state(context, match, "A", "message")

        assert reveal_values == [False]

    asyncio.run(run())

