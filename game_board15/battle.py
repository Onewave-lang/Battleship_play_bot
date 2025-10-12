"""Battle logic for the 15×15 three-player mode."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .models import Match15, Ship, PLAYER_ORDER

Coord = Tuple[int, int]

MISS = "miss"
HIT = "hit"
KILL = "kill"


@dataclass
class ShotResult:
    result: str
    owner: Optional[str]
    coord: Coord
    killed_ship: Optional[Ship] = None
    contour: List[Coord] | None = None

    def __post_init__(self) -> None:
        if self.contour is None:
            self.contour = []


@dataclass
class AdvanceOutcome:
    """Result of advancing the turn after a shot."""

    next_turn: Optional[str]
    eliminated: List[str]
    finished: bool
    winner: Optional[str]
    alive_players: List[str]


def _neighbors(coord: Coord) -> Iterable[Coord]:
    r, c = coord
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < 15 and 0 <= nc < 15:
                yield nr, nc


def _find_ship(match: Match15, owner: str, coord: Coord) -> Optional[Ship]:
    for ship in match.field.ships.get(owner, []):
        if ship.contains(coord):
            return ship
    return None


def _ship_cells_state(match: Match15, ship: Ship) -> List[int]:
    return [match.field.state_at(cell) for cell in ship.cells]


def _mark_contour(match: Match15, ship: Ship) -> List[Coord]:
    contour: List[Coord] = []
    for cell in ship.cells:
        for neighbor in _neighbors(cell):
            if match.field.state_at(neighbor) == 0:
                match.field.set_state(neighbor, 5, None)
                contour.append(neighbor)
    return contour


def apply_shot(match: Match15, shooter: str, coord: Coord) -> ShotResult:
    if match.status != "playing":
        raise ValueError("Match is not in playing state")
    if shooter != match.turn:
        raise ValueError("Not this player's turn")
    state = match.field.state_at(coord)
    owner = match.field.owner_at(coord)
    if state in (2, 3, 4, 5):
        raise ValueError("Cell already targeted")
    if owner == shooter:
        raise ValueError("Cannot shoot own ship")
    match.field.last_move = coord
    if owner is None and state == 0:
        match.field.set_state(coord, 2, None)
        return ShotResult(result=MISS, owner=None, coord=coord)
    if state != 1 or owner is None:
        match.field.set_state(coord, 2, None)
        return ShotResult(result=MISS, owner=None, coord=coord)

    ship = _find_ship(match, owner, coord)
    match.field.set_state(coord, 3, owner)
    if not ship:
        match.alive_cells[owner] = max(0, match.alive_cells.get(owner, 0) - 1)
        return ShotResult(result=HIT, owner=owner, coord=coord)

    states = _ship_cells_state(match, ship)
    if all(value in (3, 4) for value in states):
        ship.alive = False
        newly_destroyed: List[Coord] = []
        for cell in ship.cells:
            if match.field.state_at(cell) != 4:
                match.field.set_state(cell, 4, owner)
                newly_destroyed.append(cell)
        lost = len(newly_destroyed) or len(ship.cells)
        match.alive_cells[owner] = max(0, match.alive_cells.get(owner, 0) - lost)
        contour = _mark_contour(match, ship)
        return ShotResult(
            result=KILL,
            owner=owner,
            coord=coord,
            killed_ship=ship,
            contour=contour,
        )
    match.alive_cells[owner] = max(0, match.alive_cells.get(owner, 0) - 1)
    return ShotResult(result=HIT, owner=owner, coord=coord)


def advance_turn(
    match: Match15,
    last_result: ShotResult,
    *,
    previous_alive: Optional[Dict[str, int]] = None,
) -> AdvanceOutcome:
    prev_counts = previous_alive or {}
    eliminated: List[str] = []
    alive_counts: Dict[str, int] = {
        key: max(0, int(match.alive_cells.get(key, 0))) for key in PLAYER_ORDER
    }

    for key, current_count in alive_counts.items():
        was_alive = prev_counts.get(key, 0) > 0
        is_alive = current_count > 0
        if was_alive and not is_alive:
            eliminated.append(key)
            player = match.players.get(key) if hasattr(match, "players") else None
            if player is not None and hasattr(player, "eliminated"):
                player.eliminated = True

    alive_players = [key for key, count in alive_counts.items() if count > 0]
    finished = len(alive_players) <= 1
    winner = alive_players[0] if finished and alive_players else None

    if finished:
        match.status = "finished"
        if winner is not None:
            try:
                setattr(match, "winner", winner)
            except AttributeError:
                pass

    next_turn = getattr(match, "turn", None)

    if match.status != "playing":
        return AdvanceOutcome(
            next_turn=next_turn,
            eliminated=eliminated,
            finished=finished,
            winner=winner,
            alive_players=alive_players,
        )

    if last_result.result in (HIT, KILL):
        return AdvanceOutcome(
            next_turn=next_turn,
            eliminated=eliminated,
            finished=finished,
            winner=winner,
            alive_players=alive_players,
        )

    if not alive_players:
        return AdvanceOutcome(
            next_turn=next_turn,
            eliminated=eliminated,
            finished=finished,
            winner=winner,
            alive_players=alive_players,
        )

    current = next_turn if next_turn in alive_players else alive_players[0]
    idx = alive_players.index(current)
    next_key = alive_players[(idx + 1) % len(alive_players)]
    order = getattr(match, "order", PLAYER_ORDER)
    if hasattr(match, "turn_idx"):
        try:
            match.turn_idx = order.index(next_key)
        except ValueError:
            match.turn_idx = order.index(alive_players[0])
    descriptor = getattr(type(match), "turn", None)
    if not isinstance(descriptor, property):
        try:
            setattr(match, "turn", next_key)
        except AttributeError:
            pass
    next_turn = next_key

    return AdvanceOutcome(
        next_turn=next_turn,
        eliminated=eliminated,
        finished=finished,
        winner=winner,
        alive_players=alive_players,
    )


__all__ = [
    "AdvanceOutcome",
    "apply_shot",
    "advance_turn",
    "MISS",
    "HIT",
    "KILL",
    "ShotResult",
]
