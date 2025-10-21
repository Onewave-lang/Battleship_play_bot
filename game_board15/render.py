"""Rendering utilities for the 15×15 shared board."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field as dc_field
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import Field15, PLAYER_DARK_COLORS, PLAYER_LIGHT_COLORS, PLAYER_ORDER

Coord = Tuple[int, int]

CELL_SIZE = 42
# Margins around the playable field. We keep generous padding on the top/left to
# accommodate axis labels, while the bottom/right margins can be smaller so the
# caption in Telegram hugs the image tighter.
MARGIN_TOP = 60
MARGIN_LEFT = 60
MARGIN_BOTTOM = 30
MARGIN_RIGHT = 40
AXIS_FONT_SIZE = 21
AXIS_LETTER_PADDING = 18
AXIS_NUMBER_PADDING = 14
GRID_COLOR = (120, 120, 120)
BG_COLOR = (255, 255, 255)
AXIS_COLOR = (50, 50, 50)
MISS_STALE_COLOR = (40, 40, 40)
MISS_RECENT_COLOR = (220, 68, 68)
MISS_DOT_RADIUS = 4
HIT_HIGHLIGHT_FACTOR = 0.7
KILL_HIGHLIGHT_FACTOR = 0.6
KILL_OUTLINE = (0, 0, 0)
TARGET_OUTLINE_COLOR = (210, 32, 32)
TARGET_FILL_COLOR = (210, 32, 32)
TARGET_OUTER_RADIUS = 12
TARGET_INNER_RADIUS = 4
CROSS_COLOR = (40, 40, 40)
CROSS_WIDTH = 3
CROSS_MARGIN = 6
REPO_ROOT = Path(__file__).resolve().parent.parent

TEXT_FONT_PATHS: Sequence[Path | str] = (
    REPO_ROOT / "assets/fonts/DejaVuSans.ttf",
    "DejaVuSans.ttf",
)

EMOJI_FONT_PATHS: Sequence[Path | str] = (
    REPO_ROOT / "assets/fonts/NotoColorEmoji-Regular.ttf",
    REPO_ROOT / "NotoColorEmoji-Regular.ttf",
    "NotoColorEmoji-Regular.ttf",
)

COLS = "ABCDEFGHIJKLMNO"


@dataclass
class RenderState:
    field: Field15
    history: List[List[List[int | None]]]
    footer_label: str
    reveal_ships: bool = True
    rendered_ship_cells: int = 20
    last_move: Optional[Coord] = None
    attempt: int = 1
    color_map: Dict[str, str] = dc_field(
        default_factory=lambda: {key: key for key in PLAYER_ORDER}
    )

    def clone_for_retry(self, *, attempt: int, footer_label: str) -> "RenderState":
        return RenderState(
            field=self.field,
            history=self.history,
            footer_label=footer_label,
            reveal_ships=self.reveal_ships,
            rendered_ship_cells=self.rendered_ship_cells,
            last_move=self.last_move,
            attempt=attempt,
            color_map=dict(self.color_map),
        )


def _load_font(
    size: int,
    *,
    paths: Sequence[Path | str] = TEXT_FONT_PATHS,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in paths:
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _cell_rect(r: int, c: int) -> Tuple[int, int, int, int]:
    x0 = MARGIN_LEFT + c * CELL_SIZE
    y0 = MARGIN_TOP + r * CELL_SIZE
    x1 = x0 + CELL_SIZE
    y1 = y0 + CELL_SIZE
    return x0, y0, x1, y1


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    """Render the cell grid including the outer border."""

    field_width = CELL_SIZE * 15
    field_height = CELL_SIZE * 15

    for r in range(16):
        y = MARGIN_TOP + r * CELL_SIZE
        draw.line(
            [(MARGIN_LEFT, y), (MARGIN_LEFT + field_width, y)],
            fill=GRID_COLOR,
            width=1,
        )
    for c in range(16):
        x = MARGIN_LEFT + c * CELL_SIZE
        draw.line(
            [(x, MARGIN_TOP), (x, MARGIN_TOP + field_height)],
            fill=GRID_COLOR,
            width=1,
        )


def _draw_axes(
    draw: ImageDraw.ImageDraw,
    *,
    draw_top: bool = True,
    draw_bottom: bool = False,
    draw_left: bool = True,
    draw_right: bool = False,
) -> None:
    """Render axis labels around the board."""

    font = _load_font(AXIS_FONT_SIZE)
    col_centers = [
        MARGIN_LEFT + idx * CELL_SIZE + CELL_SIZE // 2 for idx in range(15)
    ]
    row_centers = [MARGIN_TOP + idx * CELL_SIZE + CELL_SIZE // 2 for idx in range(15)]

    if draw_top:
        top_y = MARGIN_TOP - AXIS_LETTER_PADDING
        for x, letter in zip(col_centers, COLS):
            draw.text((x, top_y), letter, anchor="mm", font=font, fill=AXIS_COLOR)

    if draw_bottom:
        bottom_y = MARGIN_TOP + CELL_SIZE * 15 + AXIS_LETTER_PADDING
        for x, letter in zip(col_centers, COLS):
            draw.text((x, bottom_y), letter, anchor="mm", font=font, fill=AXIS_COLOR)

    if draw_left:
        left_x = MARGIN_LEFT - AXIS_NUMBER_PADDING
        for idx, y in enumerate(row_centers):
            draw.text((left_x, y), str(idx + 1), anchor="rm", font=font, fill=AXIS_COLOR)

    if draw_right:
        right_x = MARGIN_LEFT + CELL_SIZE * 15 + AXIS_NUMBER_PADDING
        for idx, y in enumerate(row_centers):
            draw.text((right_x, y), str(idx + 1), anchor="lm", font=font, fill=AXIS_COLOR)

def _mix(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    r, g, b = color
    return (
        int(r * factor + (1 - factor) * 255),
        int(g * factor + (1 - factor) * 255),
        int(b * factor + (1 - factor) * 255),
    )


def _shade(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    """Darken ``color`` while preserving its hue to avoid muddy tones."""

    r, g, b = color
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    new_l = max(0.0, min(1.0, l * factor))
    new_r, new_g, new_b = colorsys.hls_to_rgb(h, new_l, s)
    return (
        int(round(new_r * 255)),
        int(round(new_g * 255)),
        int(round(new_b * 255)),
    )


def _draw_target_symbol(draw: ImageDraw.ImageDraw, rect: Tuple[int, int, int, int]) -> None:
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    draw.ellipse(
        [
            cx - TARGET_OUTER_RADIUS,
            cy - TARGET_OUTER_RADIUS,
            cx + TARGET_OUTER_RADIUS,
            cy + TARGET_OUTER_RADIUS,
        ],
        outline=TARGET_OUTLINE_COLOR,
        width=3,
    )
    draw.ellipse(
        [
            cx - TARGET_INNER_RADIUS,
            cy - TARGET_INNER_RADIUS,
            cx + TARGET_INNER_RADIUS,
            cy + TARGET_INNER_RADIUS,
        ],
        fill=TARGET_FILL_COLOR,
    )


def _draw_cross(draw: ImageDraw.ImageDraw, rect: Tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = rect
    draw.line(
        [(x0 + CROSS_MARGIN, y0 + CROSS_MARGIN), (x1 - CROSS_MARGIN, y1 - CROSS_MARGIN)],
        fill=CROSS_COLOR,
        width=CROSS_WIDTH,
    )
    draw.line(
        [(x0 + CROSS_MARGIN, y1 - CROSS_MARGIN), (x1 - CROSS_MARGIN, y0 + CROSS_MARGIN)],
        fill=CROSS_COLOR,
        width=CROSS_WIDTH,
    )


def render_board(state: RenderState, player_key: str) -> BytesIO:
    field_width = CELL_SIZE * 15
    field_height = CELL_SIZE * 15
    image_width = MARGIN_LEFT + field_width + MARGIN_RIGHT
    image_height = MARGIN_TOP + field_height + MARGIN_BOTTOM
    image = Image.new("RGBA", (image_width, image_height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(image)

    _draw_axes(draw, draw_top=True, draw_left=True, draw_bottom=False, draw_right=False)

    visible_own = 0
    color_map = state.color_map or {}
    player_color_key = color_map.get(player_key, player_key)
    default_light = PLAYER_LIGHT_COLORS.get(
        player_color_key,
        PLAYER_LIGHT_COLORS.get("A"),
    )
    default_dark = PLAYER_DARK_COLORS.get(
        player_color_key,
        PLAYER_DARK_COLORS.get("A"),
    )

    def light_color(owner: Optional[str]) -> Tuple[int, int, int]:
        if owner:
            color_id = color_map.get(owner, owner)
        else:
            color_id = player_color_key
        return PLAYER_LIGHT_COLORS.get(color_id, default_light)

    def dark_color(owner: Optional[str]) -> Tuple[int, int, int]:
        if owner:
            color_id = color_map.get(owner, owner)
        else:
            color_id = player_color_key
        return PLAYER_DARK_COLORS.get(color_id, default_dark)

    for r in range(15):
        for c in range(15):
            rect = _cell_rect(r, c)
            cell_value = state.history[r][c]
            if isinstance(cell_value, (list, tuple)):
                state_value = int(cell_value[0]) if cell_value else 0
                owner = cell_value[1] if len(cell_value) > 1 else None
                try:
                    age = int(cell_value[2]) if len(cell_value) > 2 else 1
                except (TypeError, ValueError):
                    age = 1
            else:
                state_value = int(cell_value)
                owner = None
                age = 1
            fresh = age == 0
            field_state = state.field.grid[r][c]
            field_owner = state.field.owners[r][c]
            owner = owner if owner is not None else field_owner
            if field_state == 1:
                if field_owner == player_key:
                    visible_own += 1
                    draw.rectangle(
                        rect,
                        fill=light_color(player_key),
                    )
                elif state.reveal_ships and owner:
                    draw.rectangle(
                        rect,
                        fill=light_color(owner),
                    )

            if state_value == 2 or field_state == 2:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                color = MISS_RECENT_COLOR if fresh and state_value == 2 else MISS_STALE_COLOR
                radius = MISS_DOT_RADIUS
                draw.ellipse(
                    [cx - radius, cy - radius, cx + radius, cy + radius],
                    fill=color,
                )
            if state_value == 3 or field_state == 3:
                if owner == player_key:
                    visible_own += 1
                fill_color = dark_color(owner or player_key)
                draw.rectangle(rect, fill=fill_color)
                if fresh and state_value == 3:
                    _draw_target_symbol(draw, rect)
                else:
                    _draw_cross(draw, rect)
            if state_value == 4 or field_state == 4:
                if owner == player_key:
                    visible_own += 1
                fill_color = dark_color(owner or player_key)
                draw.rectangle(rect, fill=fill_color)
                if fresh and state_value == 4:
                    _draw_target_symbol(draw, rect)
                else:
                    _draw_cross(draw, rect)
                draw.rectangle(rect, outline=KILL_OUTLINE, width=3)
            if state_value == 5 or field_state == 5:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                radius = MISS_DOT_RADIUS
                draw.ellipse(
                    [cx - radius, cy - radius, cx + radius, cy + radius],
                    fill=MISS_STALE_COLOR,
                )

    _draw_grid(draw)

    if state.last_move:
        lr, lc = state.last_move
        rect = _cell_rect(lr, lc)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        draw.ellipse(
            [cx - 10, cy - 10, cx + 10, cy + 10],
            outline=(220, 0, 0),
            width=2,
        )

    state.rendered_ship_cells = visible_own

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


__all__ = ["RenderState", "render_board"]
