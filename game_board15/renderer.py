from __future__ import annotations

import logging
import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from constants import BOMB
from .state import Board15State
from .models import Board15


logger = logging.getLogger(__name__)

TILE_PX = int(os.getenv("BOARD15_TILE_PX", "44"))
DEFAULT_FONT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "assets", "fonts", "NotoColorEmoji-Regular.ttf"
    )
)
FONT_PATH = os.getenv("BOARD15_FONT_PATH", DEFAULT_FONT)
THEME = os.getenv("BOARD15_THEME", "light")

COLORS = {
    "light": {
        "bg": (255, 255, 255, 255),
        "grid": (200, 200, 200, 255),
        "mark": (220, 0, 0, 255),
        "ship": (0, 0, 0, 255),
        "miss": (0, 0, 0, 255),
        "hit": (139, 0, 0, 255),
        "destroyed": (139, 0, 0, 255),
        "contour": (120, 120, 120, 255),
    },
    "dark": {
        "bg": (0, 0, 0, 255),
        "grid": (80, 80, 80, 255),
        "mark": (255, 0, 0, 255),
        "ship": (220, 220, 220, 255),
        "miss": (255, 255, 255, 255),
        "hit": (139, 0, 0, 255),
        "destroyed": (255, 100, 100, 255),
        "contour": (160, 160, 160, 255),
    },
}

PLAYER_SHIP_COLORS = {
    "light": {
        "A": (173, 216, 230, 255),  # light blue
        "B": (144, 238, 144, 255),  # light green
        "C": (255, 200, 140, 255),  # light orange
    },
    "dark": {
        "A": (173, 216, 230, 255),
        "B": (144, 238, 144, 255),
        "C": (255, 200, 140, 255),
    },
}

PLAYER_SHIP_COLORS_DARK = {
    "light": {
        "A": (0, 0, 139, 255),  # dark blue
        "B": (34, 139, 34, 255),  # dark green
        "C": (255, 140, 0, 255),  # dark orange
    },
    "dark": {
        "A": (0, 0, 139, 255),
        "B": (34, 139, 34, 255),
        "C": (255, 140, 0, 255),
    },
}

PLAYER_SHIP_COLORS_LIGHT = {
    "light": {
        "A": (224, 255, 255, 255),  # very light blue
        "B": (204, 255, 204, 255),  # very light green
        "C": (255, 235, 204, 255),  # very light orange
    },
    "dark": {
        "A": (224, 255, 255, 255),
        "B": (204, 255, 204, 255),
        "C": (255, 235, 204, 255),
    },
}


CELL_STYLE = {
    1: ("square", "ship"),
    2: ("dot", "miss"),
    3: ("square", "hit"),
    4: ("square", "destroyed"),
    # Cells adjacent to a destroyed ship are marked as a dot so they look
    # the same as already shot cells on the board.
    5: ("dot", "miss"),
}


def render_board(state: Board15State, player_key: str | None = None) -> BytesIO:
    """Render the 15x15 board into a PNG image."""

    debug_fleet_issue = False
    debug_fleet_cells: list[tuple[int, int]] = []
    if player_key and state.owners:
        owner_rows = state.owners
        for r in range(min(15, len(state.board))):
            row = state.board[r]
            owner_row = owner_rows[r] if r < len(owner_rows) else []
            for c in range(min(15, len(row))):
                if c >= len(owner_row):
                    continue
                if owner_row[c] != player_key:
                    continue
                if row[c] in {1, 3, 4}:
                    debug_fleet_cells.append((r, c))
        if len(debug_fleet_cells) < 20:
            debug_fleet_issue = True
            logger.error(
                "[B15] render_board fleet underflow for %s: cells=%d sample=%s",
                player_key,
                len(debug_fleet_cells),
                debug_fleet_cells[:40],
            )

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

    highlight = set(state.highlight)

    # marks
    for r in range(15):
        for c in range(15):
            val = state.board[r][c]
            if not val:
                continue
            x0 = margin + c * TILE_PX
            y0 = margin + r * TILE_PX
            coord = (r, c)
            owner = state.owners[r][c] if state.owners else None
            shape, color_key = CELL_STYLE.get(val, ("square", "ship"))
            if coord in highlight:
                if val in (2, 5):
                    color = COLORS[THEME]["mark"]
                elif val == 4:
                    shape = "bomb"
                    if owner:
                        color = PLAYER_SHIP_COLORS_LIGHT.get(
                            THEME, {}
                        ).get(owner, COLORS[THEME]["destroyed"])
                    else:
                        color = COLORS[THEME]["destroyed"]
                else:
                    color = COLORS[THEME]["mark"]
            else:
                if val == 1 and owner:
                    color = PLAYER_SHIP_COLORS.get(THEME, {}).get(owner, COLORS[THEME]["ship"])
                elif val == 3:
                    if owner:
                        color = PLAYER_SHIP_COLORS_DARK.get(THEME, {}).get(
                            owner, COLORS[THEME]["hit"]
                        )
                    else:
                        color = COLORS[THEME]["hit"]
                elif val == 4:
                    shape = "square"
                    if owner:
                        color = PLAYER_SHIP_COLORS_DARK.get(
                            THEME, {}
                        ).get(owner, COLORS[THEME]["destroyed"])
                    else:
                        color = COLORS[THEME]["destroyed"]
                elif val in (2, 5):
                    color = COLORS[THEME]["miss"]
                else:
                    color = COLORS[THEME][color_key]
            if shape == "square":
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                )
            elif shape == "cross":
                draw.line(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                    width=3,
                )
                draw.line(
                    (x0 + TILE_PX - 4, y0 + 4, x0 + 4, y0 + TILE_PX - 4),
                    fill=color,
                    width=3,
                )
            elif shape == "bomb":
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                )
                cx = x0 + TILE_PX // 2
                cy = y0 + TILE_PX // 2
                try:
                    bomb_font = ImageFont.truetype(FONT_PATH, int(TILE_PX * 0.8))
                except OSError:
                    bomb_font = ImageFont.load_default()
                draw.text((cx, cy), BOMB, fill=(0, 0, 0, 255), anchor="mm", font=bomb_font)
                draw.point((cx, cy), fill=(0, 0, 0, 255))
            elif shape == "dot":
                cx = x0 + TILE_PX // 2
                cy = y0 + TILE_PX // 2
                r = max(2, TILE_PX // 8)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

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

    if debug_fleet_issue:
        warn_text = "DEBUG: FLEET<20"
        try:
            warn_font = ImageFont.truetype(FONT_PATH, int(TILE_PX * 1.4))
        except OSError:
            warn_font = ImageFont.load_default()
        draw.text(
            (margin + size / 2, margin + size / 2),
            warn_text,
            fill=(255, 0, 0, 255),
            anchor="mm",
            font=warn_font,
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def render_player_board(board: Board15, player_key: str | None = None) -> BytesIO:
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
    highlight = set(board.highlight)

    # ship and shot markers
    for r in range(15):
        for c in range(15):
            val = board.grid[r][c]
            if not val:
                continue
            x0 = margin + c * TILE_PX
            y0 = margin + r * TILE_PX
            coord = (r, c)
            shape, color_key = CELL_STYLE.get(val, ("square", "ship"))
            if coord in highlight:
                if val in (2, 5):
                    color = COLORS[THEME]["mark"]
                elif val == 4:
                    shape = "bomb"
                    if player_key:
                        color = PLAYER_SHIP_COLORS_LIGHT.get(
                            THEME, {}
                        ).get(player_key, COLORS[THEME]["destroyed"])
                    else:
                        color = COLORS[THEME]["destroyed"]
                else:
                    color = COLORS[THEME]["mark"]
            else:
                if val == 1 and player_key:
                    color = PLAYER_SHIP_COLORS.get(THEME, {}).get(player_key, COLORS[THEME]["ship"])
                elif val == 3:
                    if player_key == "C":
                        color = PLAYER_SHIP_COLORS_DARK.get(THEME, {}).get("C", COLORS[THEME]["hit"])
                    else:
                        color = COLORS[THEME]["hit"]
                elif val == 4:
                    shape = "square"
                    if player_key:
                        color = PLAYER_SHIP_COLORS_DARK.get(
                            THEME, {}
                        ).get(player_key, COLORS[THEME]["destroyed"])
                    else:
                        color = COLORS[THEME]["destroyed"]
                elif val in (2, 5):
                    color = COLORS[THEME]["miss"]
                else:
                    color = COLORS[THEME][color_key]
            if shape == "square":
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                )
            elif shape == "cross":
                draw.line(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                    width=3,
                )
                draw.line(
                    (x0 + TILE_PX - 4, y0 + 4, x0 + 4, y0 + TILE_PX - 4),
                    fill=color,
                    width=3,
                )
            elif shape == "bomb":
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + TILE_PX - 4, y0 + TILE_PX - 4),
                    fill=color,
                )
                cx = x0 + TILE_PX // 2
                cy = y0 + TILE_PX // 2
                try:
                    bomb_font = ImageFont.truetype(FONT_PATH, int(TILE_PX * 0.8))
                except OSError:
                    bomb_font = ImageFont.load_default()
                draw.text((cx, cy), BOMB, fill=(0, 0, 0, 255), anchor="mm", font=bomb_font)
                draw.point((cx, cy), fill=(0, 0, 0, 255))
            elif shape == "dot":
                cx = x0 + TILE_PX // 2
                cy = y0 + TILE_PX // 2
                r = max(2, TILE_PX // 8)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

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
