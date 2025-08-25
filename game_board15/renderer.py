from __future__ import annotations

import os
from io import BytesIO
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

from .state import Board15State
from .models import Board15

TILE_PX = int(os.getenv("BOARD15_TILE_PX", "44"))
VIEW = int(os.getenv("BOARD15_VIEW", "5"))
FONT_PATH = os.getenv(
    "BOARD15_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
THEME = os.getenv("BOARD15_THEME", "light")

COLORS = {
    "light": {
        "bg": (255, 255, 255, 255),
        "grid": (200, 200, 200, 255),
        "window": (0, 120, 215, 80),
        "mark": (0, 0, 0, 255),
        "selected": (255, 0, 0, 255),
    },
    "dark": {
        "bg": (0, 0, 0, 255),
        "grid": (80, 80, 80, 255),
        "window": (0, 120, 215, 120),
        "mark": (220, 220, 220, 255),
        "selected": (255, 0, 0, 255),
    },
}


def render_board(state: Board15State) -> BytesIO:
    """Render the 15x15 board into a PNG image.

    Only a 5x5 window is highlighted to guide the user's current view.
    """

    margin = TILE_PX
    size = 15 * TILE_PX
    width = margin * 2 + size
    height = margin * 2 + size
    img = Image.new("RGBA", (width, height), COLORS[THEME]["bg"])
    draw = ImageDraw.Draw(img)

    # grid
    for i in range(16):
        offset = margin + i * TILE_PX
        draw.line((margin, offset, margin + size, offset), fill=COLORS[THEME]["grid"])
        draw.line((offset, margin, offset, margin + size), fill=COLORS[THEME]["grid"])

    # marks
    for r in range(15):
        for c in range(15):
            if state.board[r][c]:
                x0 = margin + c * TILE_PX
                y0 = margin + r * TILE_PX
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=COLORS[THEME]["mark"],
                )

    # window rectangle
    wt, wl = state.window_top, state.window_left
    draw.rectangle(
        (
            margin + wl * TILE_PX,
            margin + wt * TILE_PX,
            margin + (wl + VIEW) * TILE_PX,
            margin + (wt + VIEW) * TILE_PX,
        ),
        outline=COLORS[THEME]["window"],
        width=3,
    )

    # selected cell
    if state.selected is not None:
        sr, sc = state.selected
        x0 = margin + sc * TILE_PX
        y0 = margin + sr * TILE_PX
        draw.ellipse(
            (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
            outline=COLORS[THEME]["selected"],
            width=3,
        )

    # axis labels
    try:
        font = ImageFont.truetype(FONT_PATH, int(TILE_PX * 0.6))
    except OSError:
        font = ImageFont.load_default()

    letters = [chr(ord("A") + i) for i in range(15)]
    for idx, ch in enumerate(letters):
        x = margin + idx * TILE_PX + TILE_PX // 2
        draw.text((x, margin // 2), ch, fill=COLORS[THEME]["grid"], anchor="mm", font=font)
    for idx in range(15):
        y = margin + idx * TILE_PX + TILE_PX // 2
        draw.text((margin // 2, y), str(idx + 1), fill=COLORS[THEME]["grid"], anchor="mm", font=font)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def render_player_board(board: Board15) -> BytesIO:
    """Render player's own board with their ships.

    Unlike :func:`render_board`, this version shows the full board without a
    movable window and marks every non-zero cell which represents the player's
    fleet and any shots made by the opponent.
    """

    margin = TILE_PX
    size = 15 * TILE_PX
    width = margin * 2 + size
    height = margin * 2 + size
    img = Image.new("RGBA", (width, height), COLORS[THEME]["bg"])
    draw = ImageDraw.Draw(img)

    # grid
    for i in range(16):
        offset = margin + i * TILE_PX
        draw.line((margin, offset, margin + size, offset), fill=COLORS[THEME]["grid"])
        draw.line((offset, margin, offset, margin + size), fill=COLORS[THEME]["grid"])

    # ship and shot markers
    for r in range(15):
        for c in range(15):
            if board.grid[r][c]:
                x0 = margin + c * TILE_PX
                y0 = margin + r * TILE_PX
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=COLORS[THEME]["mark"],
                )

    # axis labels
    try:
        font = ImageFont.truetype(FONT_PATH, int(TILE_PX * 0.6))
    except OSError:
        font = ImageFont.load_default()

    letters = [chr(ord("A") + i) for i in range(15)]
    for idx, ch in enumerate(letters):
        x = margin + idx * TILE_PX + TILE_PX // 2
        draw.text((x, margin // 2), ch, fill=COLORS[THEME]["grid"], anchor="mm", font=font)
    for idx in range(15):
        y = margin + idx * TILE_PX + TILE_PX // 2
        draw.text((margin // 2, y), str(idx + 1), fill=COLORS[THEME]["grid"], anchor="mm", font=font)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
