"""Helper script for producing preview renders of the 15×15 board."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .models import Field15, PLAYER_ORDER, empty_history
from .render import RenderState, render_board

Coord = Tuple[int, int]


def _fill_cells(field: Field15, cells: Iterable[Coord], owner: str, state: int) -> None:
    for r, c in cells:
        field.grid[r][c] = state
        field.owners[r][c] = owner


def _age_cell(history: List[List[List[int | None]]], coord: Coord, state: int, owner: str, age: int) -> None:
    r, c = coord
    history[r][c][0] = state
    history[r][c][1] = owner
    history[r][c][2] = 0 if age == 0 else 1


def build_preview_state() -> Tuple[Field15, List[List[List[int | None]]]]:
    """Create a synthetic board snapshot demonstrating visual states."""

    field = Field15()
    history = empty_history()

    # Base ships that remain intact for each player
    intact_layout: Sequence[Tuple[str, Sequence[Coord]]] = (
        ("A", [(1, 1), (1, 2), (1, 3)]),
        ("B", [(5, 10), (6, 10), (7, 10), (8, 10)]),
        ("C", [(11, 4), (11, 5)]),
    )
    for owner, cells in intact_layout:
        _fill_cells(field, cells, owner, 1)

    # Fresh and stale hits
    _fill_cells(field, [(4, 4)], "B", 3)
    _age_cell(history, (4, 4), 3, "B", age=0)
    _fill_cells(field, [(4, 6)], "B", 3)
    _age_cell(history, (4, 6), 3, "B", age=1)

    # Fresh and stale kills (bold outline + markers)
    sunk_ship_fresh = [(8, 3), (8, 4)]
    _fill_cells(field, sunk_ship_fresh, "C", 4)
    for coord in sunk_ship_fresh:
        _age_cell(history, coord, 4, "C", age=0)

    sunk_ship_stale = [(9, 6), (9, 7), (9, 8)]
    _fill_cells(field, sunk_ship_stale, "A", 4)
    for coord in sunk_ship_stale:
        _age_cell(history, coord, 4, "A", age=1)

    # Miss markers: fresh (red) and stale (black)
    history[2][9][0] = 2
    history[2][9][2] = 0
    history[12][12][0] = 2
    history[12][12][2] = 1

    # Contour markers around an older sunk ship
    contour_coords = [(10, 5), (10, 6), (10, 7), (9, 5), (9, 9)]
    for coord in contour_coords:
        r, c = coord
        field.grid[r][c] = 5
        history[r][c][0] = 5

    field.last_move = (4, 4)

    return field, history


def generate_preview(path: Path) -> Path:
    """Render the preview image to ``path`` and return it."""

    field, history = build_preview_state()
    state = RenderState(
        field=field,
        history=history,
        footer_label="Preview",
        reveal_ships=True,
        color_map={key: key for key in PLAYER_ORDER},
    )
    buffer = render_board(state, PLAYER_ORDER[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return path


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a preview render for the shared board.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/render_preview.png"),
        help="Where to store the generated PNG (default: artifacts/render_preview.png)",
    )
    args = parser.parse_args(argv)
    output_path = generate_preview(args.output)
    print(f"Preview image saved to {output_path}")


if __name__ == "__main__":
    main()

