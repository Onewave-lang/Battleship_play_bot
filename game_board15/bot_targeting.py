"""Helpers for bot targeting logic in the 15×15 mode."""
from __future__ import annotations

import random
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .battle import HIT, KILL, ShotResult
from .models import Field15, Match15, Ship

Coord = Tuple[int, int]
BOARD_SIZE = 15


def _normalize_coord_value(value: object) -> Optional[Coord]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _is_adjacent(a: Coord, b: Coord) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def _has_diagonal_wounded(field: Field15, coord: Coord) -> bool:
    r, c = coord
    for dr in (-1, 1):
        for dc in (-1, 1):
            nr, nc = r + dr, c + dc
            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                if field.state_at((nr, nc)) == 3:
                    return True
    return False


def _orthogonal_neighbors(coord: Coord) -> List[Coord]:
    r, c = coord
    neighbours: List[Coord] = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
            neighbours.append((nr, nc))
    return neighbours


def _normalize_target_hits(entry: Dict[str, object], field: Field15) -> List[Coord]:
    raw_hits = entry.get("target_hits") or []
    normalized: List[Coord] = []
    seen: Set[Coord] = set()
    for item in raw_hits:
        coord = _normalize_coord_value(item)
        if coord is None or coord in seen:
            continue
        if field.state_at(coord) == 3:
            normalized.append(coord)
            seen.add(coord)
    entry["target_hits"] = normalized
    if not normalized:
        entry["target_owner"] = None
    return normalized


def _is_available_target(field: Field15, shooter: str, coord: Coord) -> bool:
    owner = field.owner_at(coord)
    if owner == shooter:
        return False
    if _has_diagonal_wounded(field, coord):
        return False
    state = field.state_at(coord)
    return state not in (2, 3, 4, 5)


def _find_ship_cells(
    field: Field15,
    owner: Optional[str],
    reference_hits: Sequence[Coord],
    extra_coord: Optional[Coord] = None,
) -> Optional[List[Coord]]:
    if owner is None:
        return None
    ships: List[Ship] = field.ships.get(owner, []) if field and hasattr(field, "ships") else []
    coords_to_check: List[Coord] = list(reference_hits)
    if extra_coord is not None:
        coords_to_check.append(extra_coord)
    for ship in ships:
        ship_cells = [tuple(cell) for cell in ship.cells]
        if any(hit in ship_cells for hit in coords_to_check):
            return ship_cells
    return None


def _collect_line_candidates(
    field: Field15,
    shooter: str,
    hits: List[Coord],
    owner: Optional[str] = None,
) -> List[Coord]:
    if not hits:
        return []
    ship_cells = _find_ship_cells(field, owner, hits)
    if ship_cells:
        remaining = [
            coord
            for coord in ship_cells
            if coord not in hits and _is_available_target(field, shooter, coord)
        ]
        if remaining:
            return remaining

    rows = {r for r, _ in hits}
    cols = {c for _, c in hits}
    candidates: List[Coord] = []
    seen: Set[Coord] = set()
    if len(rows) == 1:
        ordered = sorted(hits, key=lambda item: item[1])
        endpoints = [ordered[0], ordered[-1]]
        for r, c in endpoints:
            for delta in (-1, 1):
                candidate = (r, c + delta)
                if candidate in seen:
                    continue
                seen.add(candidate)
                if _is_available_target(field, shooter, candidate):
                    candidates.append(candidate)
    elif len(cols) == 1:
        ordered = sorted(hits, key=lambda item: item[0])
        endpoints = [ordered[0], ordered[-1]]
        for r, c in endpoints:
            for delta in (-1, 1):
                candidate = (r + delta, c)
                if candidate in seen:
                    continue
                seen.add(candidate)
                if _is_available_target(field, shooter, candidate):
                    candidates.append(candidate)
    return candidates


def _collect_neighbor_candidates(
    field: Field15,
    shooter: str,
    hits: List[Coord],
) -> List[Coord]:
    candidates: List[Coord] = []
    seen: Set[Coord] = set()
    for hit in hits:
        for candidate in _orthogonal_neighbors(hit):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _is_available_target(field, shooter, candidate):
                candidates.append(candidate)
    return candidates


def _choose_bot_target(
    field: Field15,
    shooter: str,
    entry: Dict[str, object],
    rng: random.Random,
) -> Optional[Coord]:
    hits = _normalize_target_hits(entry, field)
    owner = entry.get("target_owner")
    if hits:
        if len(hits) == 1:
            neighbors = _collect_neighbor_candidates(field, shooter, hits)
            if neighbors:
                rng.shuffle(neighbors)
                return neighbors[0]
        else:
            line_candidates = _collect_line_candidates(field, shooter, hits, owner=owner)
            if line_candidates:
                rng.shuffle(line_candidates)
                return line_candidates[0]
            neighbors = _collect_neighbor_candidates(field, shooter, hits)
            if neighbors:
                rng.shuffle(neighbors)
                return neighbors[0]

    coords = [(r, c) for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)]
    rng.shuffle(coords)
    for coord in coords:
        if _is_available_target(field, shooter, coord):
            return coord
    return None


def _clear_targets_for_owner(
    match: Match15,
    owner: Optional[str],
    *,
    exclude: Optional[str] = None,
) -> None:
    if owner is None:
        return
    for key, entry in list(match.shots.items()):
        if key == exclude:
            continue
        if entry.get("target_owner") == owner:
            entry["target_hits"] = []
            entry["target_owner"] = None


def _propagate_hit_to_other_entries(
    match: Match15,
    shooter: str,
    owner: str,
    coord: Coord,
) -> None:
    field = getattr(match, "field", None)
    if not isinstance(field, Field15):
        return
    ship_cells = _find_ship_cells(field, owner, [], extra_coord=coord)
    ship_cells_set: Optional[Set[Coord]] = set(ship_cells) if ship_cells else None

    for key, entry in list(match.shots.items()):
        if key == shooter:
            continue
        if entry.get("target_owner") != owner:
            continue
        hits_raw = entry.get("target_hits") or []
        normalized: List[Coord] = []
        seen: Set[Coord] = set()
        for item in hits_raw:
            value = _normalize_coord_value(item)
            if value is None or value in seen:
                continue
            if field.state_at(value) == 3:
                normalized.append(value)
                seen.add(value)
        if not normalized:
            continue
        if ship_cells_set is not None and not any(hit in ship_cells_set for hit in normalized):
            continue
        if coord not in normalized:
            normalized.append(coord)
        entry["target_hits"] = normalized
        entry["target_owner"] = owner


def _update_bot_target_state(
    match: Match15,
    shooter: str,
    result: ShotResult,
) -> None:
    entry = match.shots.setdefault(shooter, {})
    field = getattr(match, "field", None)
    hits_raw = entry.get("target_hits") or []
    normalized_hits: List[Coord] = []
    seen: Set[Coord] = set()
    for item in hits_raw:
        coord = _normalize_coord_value(item)
        if coord is None or coord in seen:
            continue
        if isinstance(field, Field15) and field.state_at(coord) != 3:
            continue
        normalized_hits.append(coord)
        seen.add(coord)

    if result.result == KILL:
        entry["target_hits"] = []
        entry["target_owner"] = None
        _clear_targets_for_owner(match, result.owner, exclude=shooter)
        return

    if result.result != HIT:
        entry["target_hits"] = normalized_hits
        if not normalized_hits:
            entry["target_owner"] = None
        return

    coord = result.coord
    owner = result.owner
    if owner is None:
        entry["target_hits"] = normalized_hits
        if not normalized_hits:
            entry["target_owner"] = None
        return

    if entry.get("target_owner") not in (None, owner):
        normalized_hits = []

    if normalized_hits and not any(_is_adjacent(hit, coord) for hit in normalized_hits):
        normalized_hits = []

    if coord not in normalized_hits:
        normalized_hits.append(coord)

    entry["target_hits"] = normalized_hits
    entry["target_owner"] = owner

    _propagate_hit_to_other_entries(match, shooter, owner, coord)


__all__ = [
    "BOARD_SIZE",
    "Coord",
    "_choose_bot_target",
    "_update_bot_target_state",
]
