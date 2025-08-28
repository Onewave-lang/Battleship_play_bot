from __future__ import annotations

import random
from typing import List, Union, Tuple

from logic.phrases import random_phrase, random_joke


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


def _get_cell_state(cell: Union[int, List[int], Tuple[int, str]]) -> int:
    """Return numeric state from history cell which may be a list or int."""
    return cell[0] if isinstance(cell, (list, tuple)) else cell


def _set_cell_state(grid: List[List[Union[int, List[int]]]], r: int, c: int, value: int) -> None:
    """Set numeric state on history cell preserving list structure."""
    cell = grid[r][c]
    if isinstance(cell, list):
        cell[0] = value
    else:
        grid[r][c] = value


__all__ = ["_phrase_or_joke", "_get_cell_state", "_set_cell_state"]
