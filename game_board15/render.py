"""Rendering utilities for the 15×15 shared board."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import Field15, PLAYER_COLORS

Coord = Tuple[int, int]

CELL_SIZE = 42
MARGIN = 60
GRID_COLOR = (120, 120, 120)
BG_COLOR = (245, 246, 250)
AXIS_COLOR = (50, 50, 50)
MISS_COLOR = (40, 40, 40)
HIT_COLOR = (220, 68, 68)
KILL_OUTLINE = (0, 0, 0)
CONTOUR_COLOR = (0, 0, 0)
FONT_PATHS = [
    "NotoColorEmoji-Regular.ttf",
]

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

    def clone_for_retry(self, *, attempt: int, footer_label: str) -> "RenderState":
        return RenderState(
            field=self.field,
            history=self.history,
            footer_label=footer_label,
            reveal_ships=self.reveal_ships,
            rendered_ship_cells=self.rendered_ship_cells,
            last_move=self.last_move,
            attempt=attempt,
        )


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _cell_rect(r: int, c: int) -> Tuple[int, int, int, int]:
    x0 = MARGIN + c * CELL_SIZE
    y0 = MARGIN + r * CELL_SIZE
    x1 = x0 + CELL_SIZE
    y1 = y0 + CELL_SIZE
    return x0, y0, x1, y1


def _draw_axes(draw: ImageDraw.ImageDraw) -> None:
    font = _load_font(18)
    for idx, letter in enumerate(COLS):
        x = MARGIN + idx * CELL_SIZE + CELL_SIZE // 2
        draw.text((x, MARGIN - 35), letter, anchor="mm", font=font, fill=AXIS_COLOR)
    for idx in range(15):
        y = MARGIN + idx * CELL_SIZE + CELL_SIZE // 2
        draw.text((MARGIN - 35, y), str(idx + 1), anchor="mm", font=font, fill=AXIS_COLOR)


def _mix(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    r, g, b = color
    return (
        int(r * factor + (1 - factor) * 255),
        int(g * factor + (1 - factor) * 255),
        int(b * factor + (1 - factor) * 255),
    )


def render_board(state: RenderState, player_key: str) -> BytesIO:
    image_size = MARGIN * 2 + CELL_SIZE * 15
    image = Image.new("RGBA", (image_size, image_size), BG_COLOR + (255,))
    draw = ImageDraw.Draw(image)

    # background grid
    for r in range(16):
        y = MARGIN + r * CELL_SIZE
        draw.line([(MARGIN, y), (MARGIN + CELL_SIZE * 15, y)], fill=GRID_COLOR, width=1)
    for c in range(16):
        x = MARGIN + c * CELL_SIZE
        draw.line([(x, MARGIN), (x, MARGIN + CELL_SIZE * 15)], fill=GRID_COLOR, width=1)

    _draw_axes(draw)

    visible_own = 0

    for r in range(15):
        for c in range(15):
            rect = _cell_rect(r, c)
            cell_value = state.history[r][c]
            if isinstance(cell_value, (list, tuple)):
                state_value = int(cell_value[0]) if cell_value else 0
                owner = cell_value[1] if len(cell_value) > 1 else None
            else:
                state_value = int(cell_value)
                owner = None
            field_state = state.field.grid[r][c]
            field_owner = state.field.owners[r][c]
            owner = owner if owner is not None else field_owner
            if field_state == 1 and field_owner == player_key:
                visible_own += 1
                if state.reveal_ships:
                    draw.rectangle(rect, fill=_mix(PLAYER_COLORS[player_key], 0.25))
            elif field_state == 1 and state.reveal_ships and owner:
                draw.rectangle(rect, fill=_mix(PLAYER_COLORS.get(owner, (120, 120, 120)), 0.15))

            if state_value == 2 or field_state == 2:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                draw.ellipse(
                    [cx - 4, cy - 4, cx + 4, cy + 4],
                    fill=MISS_COLOR,
                )
            if state_value == 3 or field_state == 3:
                if owner == player_key:
                    visible_own += 1
                color = PLAYER_COLORS.get(owner or player_key, HIT_COLOR)
                draw.rectangle(rect, fill=_mix(color, 0.55))
            if state_value == 4 or field_state == 4:
                if owner == player_key:
                    visible_own += 1
                color = PLAYER_COLORS.get(owner or player_key, HIT_COLOR)
                draw.rectangle(rect, fill=_mix(color, 0.85))
                draw.rectangle(rect, outline=KILL_OUTLINE, width=2)
            if state_value == 5 or field_state == 5:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                draw.ellipse(
                    [cx - 3, cy - 3, cx + 3, cy + 3],
                    fill=CONTOUR_COLOR,
                )

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

    footer_font = _load_font(20)
    draw.text(
        (image_size // 2, image_size - MARGIN // 2),
        state.footer_label,
        anchor="mm",
        font=footer_font,
        fill=AXIS_COLOR,
    )

    state.rendered_ship_cells = visible_own

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


__all__ = ["RenderState", "render_board"]
