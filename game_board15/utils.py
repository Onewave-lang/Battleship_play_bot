from __future__ import annotations

import random
from datetime import datetime
from typing import List, Union, Tuple, Optional, Dict, Any

from logic.phrases import random_phrase, random_joke


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот по этому поводу:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


def _get_cell_state(cell: Union[int, List[int], Tuple[int, str]]) -> int:
    """Return numeric state from history cell which may be a list or int."""
    return cell[0] if isinstance(cell, (list, tuple)) else cell


def _get_cell_owner(cell: Union[int, List[int], Tuple[int, str]]) -> Optional[str]:
    """Return owner from history cell if present."""
    return cell[1] if isinstance(cell, (list, tuple)) and len(cell) > 1 else None


def _set_cell_state(
    grid: List[List[Union[int, List[Union[int, Optional[str]]]]]],
    r: int,
    c: int,
    value: int,
    owner: Optional[str] = None,
) -> None:
    """Set state and optionally owner on history cell preserving list structure."""
    cell = grid[r][c]
    if isinstance(cell, list):
        if not cell:
            cell.extend([value, owner])
        else:
            cell[0] = value
            if owner is not None:
                if len(cell) > 1:
                    cell[1] = owner
                else:
                    cell.append(owner)
    else:
        grid[r][c] = [value, owner] if owner is not None else value


def record_snapshot(match, *, actor: Optional[str], coord: Optional[Tuple[int, int]]) -> dict:
    """Record immutable snapshot of the current match state."""

    def _copy_history(history: List[List[Union[int, List[Union[int, Optional[str]]]]]]) -> list[list[object]]:
        copied: list[list[object]] = []
        for row in history:
            copied_row: list[object] = []
            for cell in row:
                if isinstance(cell, list):
                    copied_row.append(cell.copy())
                elif isinstance(cell, tuple):
                    copied_row.append(list(cell))
                else:
                    copied_row.append(cell)
            copied.append(copied_row)
        return copied

    def _copy_board(board) -> Dict[str, Any]:
        grid_copy = [row.copy() for row in board.grid]
        ships_copy = [
            {
                "cells": [tuple(cell) for cell in ship.cells],
                "alive": ship.alive,
            }
            for ship in board.ships
        ]
        return {
            "grid": grid_copy,
            "ships": ships_copy,
            "alive_cells": board.alive_cells,
        }

    history_copy = _copy_history(match.history)
    boards_copy = {key: _copy_board(board) for key, board in match.boards.items()}
    snapshot = {
        "timestamp": datetime.utcnow().isoformat(),
        "move": len(getattr(match, "snapshots", [])),
        "actor": actor,
        "coord": tuple(coord) if coord is not None else None,
        "next_turn": match.turn,
        "history": history_copy,
        "last_highlight": [tuple(cell) for cell in getattr(match, "last_highlight", [])],
        "boards": boards_copy,
    }
    if not hasattr(match, "snapshots"):
        match.snapshots = []
    match.snapshots.append(snapshot)
    return snapshot


__all__ = [
    "_phrase_or_joke",
    "_get_cell_state",
    "_get_cell_owner",
    "_set_cell_state",
    "record_snapshot",
]
