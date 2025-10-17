"""Data models for the 15×15 three-player mode."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import uuid

Coord = Tuple[int, int]


PLAYER_ORDER = ["A", "B", "C"]

# Six fixed ship colors used across all three-player modes.
# "light" colors render intact ships while "dark" colors highlight
# damaged or destroyed segments.  The palette deliberately contains only
# these six values to avoid visual ambiguity between fleets.
PLAYER_COLOR_SCHEMES = {
    "A": {"light": (173, 216, 230), "dark": (0, 115, 255)},  # light/bright blue
    "B": {"light": (255, 213, 153), "dark": (255, 140, 0)},  # light/bright orange
    "C": {"light": (204, 239, 204), "dark": (46, 176, 75)},  # light/bright green
}

# Backwards compatibility mapping preserved for modules that expect the
# legacy ``PLAYER_COLORS`` constant to provide the "active" (dark) shade.
PLAYER_COLORS = {key: value["dark"] for key, value in PLAYER_COLOR_SCHEMES.items()}
PLAYER_LIGHT_COLORS = {key: value["light"] for key, value in PLAYER_COLOR_SCHEMES.items()}
PLAYER_DARK_COLORS = PLAYER_COLORS


def _coerce_age(value: Any) -> int:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return 1
    return 0 if age == 0 else 1


def normalize_history_cell(cell: Any, *, default_owner: Optional[str] = None) -> List[int | None]:
    """Return a normalized ``[state, owner, age]`` triple for history cells."""

    if isinstance(cell, (list, tuple)):
        state = int(cell[0]) if len(cell) > 0 and cell[0] is not None else 0
        owner = cell[1] if len(cell) > 1 else default_owner
        age = _coerce_age(cell[2] if len(cell) > 2 else 1)
    else:
        state = int(cell)
        owner = default_owner
        age = 1
    return [state, owner, age]


def empty_history(size: int = 15) -> List[List[List[int | None]]]:
    return [[[0, None, 1] for _ in range(size)] for _ in range(size)]


def normalize_history_grid(grid: Any, *, size: int = 15) -> List[List[List[int | None]]]:
    normalized: List[List[List[int | None]]] = []
    rows: List[Any] = list(grid) if isinstance(grid, (list, tuple)) else []
    for r in range(size):
        row_data = rows[r] if r < len(rows) else []
        row: List[List[int | None]] = []
        cells = list(row_data) if isinstance(row_data, (list, tuple)) else []
        for c in range(size):
            cell = cells[c] if c < len(cells) else [0, None, 1]
            row.append(normalize_history_cell(cell))
        normalized.append(row)
    return normalized


@dataclass
class ShotLogEntry:
    """Single entry describing a shot that happened in the match."""

    by_player: str
    coord: Coord
    result: str
    target: Optional[str] = None
    created_at: str = dc_field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_payload(self) -> Dict[str, Any]:
        return {
            "by_player": self.by_player,
            "coord": list(self.coord),
            "result": self.result,
            "target": self.target,
            "created_at": self.created_at,
        }

    @classmethod
    def from_payload(cls, data: Any) -> "ShotLogEntry":
        if not isinstance(data, dict):
            raise TypeError("Shot log payload must be a dict")
        coord_value = data.get("coord")
        if isinstance(coord_value, (list, tuple)) and len(coord_value) >= 2:
            coord = (int(coord_value[0]), int(coord_value[1]))
        else:
            coord = (0, 0)
        return cls(
            by_player=str(data.get("by_player", "")),
            coord=coord,
            result=str(data.get("result", "")),
            target=data.get("target"),
            created_at=str(data.get("created_at", datetime.utcnow().isoformat())),
        )

    def clone(self) -> "ShotLogEntry":
        return ShotLogEntry(
            by_player=self.by_player,
            coord=self.coord,
            result=self.result,
            target=self.target,
            created_at=self.created_at,
        )


@dataclass
class Player:
    """Representation of a participant of the 15×15 match."""

    user_id: int
    chat_id: int
    name: str
    color: str = ""
    eliminated: bool = False


@dataclass
class Ship:
    """Ship on the shared field."""

    cells: List[Coord]
    owner: str = ""
    alive: bool = True

    def contains(self, coord: Coord) -> bool:
        return coord in self.cells

    def mark_hit(self, coord: Coord) -> None:
        if coord in self.cells:
            # no separate state per cell is stored here; ``alive`` is updated by the
            # battle logic when all segments are destroyed.
            return


@dataclass
class Field15:
    """Unified 15×15 field shared between all players."""

    grid: List[List[int]] = dc_field(
        default_factory=lambda: [[0 for _ in range(15)] for _ in range(15)]
    )
    owners: List[List[Optional[str]]] = dc_field(
        default_factory=lambda: [[None for _ in range(15)] for _ in range(15)]
    )
    ships: Dict[str, List[Ship]] = dc_field(
        default_factory=lambda: {key: [] for key in PLAYER_ORDER}
    )
    highlight: List[Coord] = dc_field(default_factory=list)
    last_move: Optional[Coord] = None

    def clone(self) -> "Field15":
        clone = Field15()
        clone.grid = [row[:] for row in self.grid]
        clone.owners = [row[:] for row in self.owners]
        clone.ships = {key: [Ship(cells=list(ship.cells), owner=ship.owner, alive=ship.alive) for ship in ships]
                       for key, ships in self.ships.items()}
        clone.highlight = list(self.highlight)
        clone.last_move = self.last_move
        return clone

    def owner_at(self, coord: Coord) -> Optional[str]:
        r, c = coord
        if 0 <= r < 15 and 0 <= c < 15:
            return self.owners[r][c]
        return None

    def state_at(self, coord: Coord) -> int:
        r, c = coord
        if 0 <= r < 15 and 0 <= c < 15:
            return self.grid[r][c]
        return 0

    def set_state(self, coord: Coord, state: int, owner: Optional[str]) -> None:
        r, c = coord
        self.grid[r][c] = state
        self.owners[r][c] = owner


Board15 = Field15


@dataclass
class Snapshot15:
    """Immutable snapshot of a 3-player match state."""

    status: str
    turn_idx: int
    turn: str
    order: List[str]
    players: Dict[str, Player]
    field: Field15
    alive_cells: Dict[str, int]
    cell_history: List[List[List[int | None]]]
    shot_history: List[ShotLogEntry]
    last_move: Optional[Coord]
    messages: Dict[str, Dict[str, Any]]
    shots: Dict[str, Dict[str, Any]]

    @classmethod
    def from_match(cls, match: "Match15") -> "Snapshot15":
        field_copy = match.field.clone()
        history_copy = [
            [normalize_history_cell(cell) for cell in row]
            for row in match.cell_history
        ]
        players_copy = {
            key: Player(
                user_id=player.user_id,
                chat_id=player.chat_id,
                name=player.name,
                color=player.color,
                eliminated=player.eliminated,
            )
            for key, player in match.players.items()
        }
        return cls(
            status=match.status,
            turn_idx=match.turn_idx,
            turn=getattr(match, "turn", match.order[match.turn_idx]),
            order=list(getattr(match, "order", PLAYER_ORDER)),
            players=players_copy,
            field=field_copy,
            alive_cells={k: v for k, v in match.alive_cells.items()},
            cell_history=history_copy,
            shot_history=[entry.clone() for entry in match.history],
            last_move=match.field.last_move,
            messages=deepcopy(getattr(match, "messages", {})),
            shots=deepcopy(getattr(match, "shots", {})),
        )

    def to_record(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "turn_idx": self.turn_idx,
            "turn": self.turn,
            "order": list(self.order),
            "players": {
                key: {
                    "user_id": player.user_id,
                    "chat_id": player.chat_id,
                    "name": player.name,
                    "color": player.color,
                    "eliminated": player.eliminated,
                }
                for key, player in self.players.items()
            },
            "alive_cells": dict(self.alive_cells),
            "last_move": list(self.last_move) if self.last_move else None,
            "field": {
                "grid": [row[:] for row in self.field.grid],
                "owners": [row[:] for row in self.field.owners],
                "highlight": [list(coord) for coord in self.field.highlight],
                "last_move": list(self.field.last_move) if self.field.last_move else None,
                "ships": {
                    key: [
                        {
                            "cells": [list(cell) for cell in ship.cells],
                            "owner": ship.owner,
                            "alive": ship.alive,
                        }
                        for ship in ships
                    ]
                    for key, ships in self.field.ships.items()
                },
            },
            "cell_history": [
                [list(cell) for cell in row]
                for row in self.cell_history
            ],
            "history": [entry.to_payload() for entry in self.shot_history],
            "messages": deepcopy(self.messages),
            "shots": {
                key: {
                    "history": [
                        list(item) if isinstance(item, (list, tuple)) else item
                        for item in data.get("history", [])
                    ],
                    "last_result": data.get("last_result"),
                    "move_count": data.get("move_count", 0),
                    "joke_start": data.get("joke_start"),
                    "last_coord": (
                        list(data.get("last_coord"))
                        if isinstance(data.get("last_coord"), (list, tuple))
                        else data.get("last_coord")
                    ),
                }
                for key, data in self.shots.items()
            },
        }


@dataclass
class Match15:
    """Match descriptor for the 15×15 three-player game."""

    match_id: str
    status: str = "waiting"
    created_at: str = dc_field(default_factory=lambda: datetime.utcnow().isoformat())
    players: Dict[str, Player] = dc_field(default_factory=dict)
    field: Field15 = dc_field(default_factory=Field15)
    boards: Dict[str, Field15] = dc_field(
        default_factory=lambda: {key: Field15() for key in PLAYER_ORDER}
    )
    order: List[str] = dc_field(default_factory=lambda: PLAYER_ORDER.copy())
    turn_idx: int = 0
    alive_cells: Dict[str, int] = dc_field(
        default_factory=lambda: {key: 20 for key in PLAYER_ORDER}
    )
    cell_history: List[List[List[int | None]]] = dc_field(default_factory=empty_history)
    history: List[ShotLogEntry] = dc_field(default_factory=list)
    messages: Dict[str, Dict[str, object]] = dc_field(
        default_factory=lambda: {key: {} for key in PLAYER_ORDER}
    )
    shots: Dict[str, Dict[str, object]] = dc_field(
        default_factory=lambda: {
            key: {
                "history": [],
                "last_result": None,
                "move_count": 0,
                "joke_start": None,
                "last_coord": None,
            }
            for key in PLAYER_ORDER
        }
    )
    snapshots: List[Snapshot15] = dc_field(default_factory=list)

    @staticmethod
    def new(user_id: int, chat_id: int, name: str) -> "Match15":
        match_id = uuid.uuid4().hex
        player_a = Player(
            user_id=user_id,
            chat_id=chat_id,
            name=name.strip() or "Игрок A",
            color="A",
        )
        match = Match15(match_id=match_id)
        match.players["A"] = player_a

        # Auto-generate full fleets for all players as required by the
        # specification. The placement logic lives in ``placement`` and is
        # imported lazily here to avoid circular imports at module load time.
        from .placement import generate_field  # local import

        field, fleets = generate_field()
        match.field = field
        match.boards = {key: match.field for key in PLAYER_ORDER}
        match.field.ships = fleets
        match.alive_cells = {
            owner: sum(len(ship.cells) for ship in ships)
            for owner, ships in fleets.items()
        }
        match.snapshots.append(Snapshot15.from_match(match))
        return match

    @property
    def turn(self) -> str:
        return self.order[self.turn_idx]

    def set_turn(self, player_key: str) -> None:
        if player_key not in self.order:
            raise ValueError(f"Unknown player key: {player_key}")
        self.turn_idx = self.order.index(player_key)

    def active_players(self) -> List[str]:
        return [key for key in self.order if self.alive_cells.get(key, 0) > 0]

    def next_turn(self) -> None:
        alive = self.active_players()
        if len(alive) <= 1:
            self.status = "finished"
            return
        current = self.turn
        idx = alive.index(current)
        next_idx = (idx + 1) % len(alive)
        self.turn_idx = self.order.index(alive[next_idx])

    def create_snapshot(self) -> Snapshot15:
        snapshot = Snapshot15.from_match(self)
        self.snapshots.append(snapshot)
        return snapshot

    def to_payload(self) -> dict:
        return {
            "match_id": self.match_id,
            "status": self.status,
            "created_at": self.created_at,
            "players": {
                key: {
                    "user_id": player.user_id,
                    "chat_id": player.chat_id,
                    "name": player.name,
                    "color": player.color,
                    "eliminated": player.eliminated,
                }
                for key, player in self.players.items()
            },
            "field": {
                "grid": [row[:] for row in self.field.grid],
                "owners": [row[:] for row in self.field.owners],
                "ships": {
                    key: [
                        {"cells": list(ship.cells), "owner": ship.owner, "alive": ship.alive}
                        for ship in ships
                    ]
                    for key, ships in self.field.ships.items()
                },
                "highlight": list(self.field.highlight),
                "last_move": list(self.field.last_move) if self.field.last_move else None,
            },
            "order": list(self.order),
            "turn_idx": self.turn_idx,
            "alive_cells": dict(self.alive_cells),
            "cell_history": [
                [normalize_history_cell(cell) for cell in row]
                for row in self.cell_history
            ],
            "history": [entry.to_payload() for entry in self.history],
            "messages": {key: dict(value) for key, value in self.messages.items()},
            "shots": {
                key: {
                    "history": [list(item) if isinstance(item, tuple) else item for item in data.get("history", [])],
                    "last_result": data.get("last_result"),
                    "move_count": data.get("move_count", 0),
                    "joke_start": data.get("joke_start"),
                    "last_coord": list(data.get("last_coord")) if data.get("last_coord") else None,
                }
                for key, data in self.shots.items()
            },
        }

    @staticmethod
    def from_payload(data: dict) -> "Match15":
        match = Match15(match_id=data["match_id"])
        match.status = data.get("status", "waiting")
        match.created_at = data.get("created_at", match.created_at)
        match.players = {
            key: Player(
                user_id=player_data.get("user_id", 0),
                chat_id=player_data.get("chat_id", 0),
                name=player_data.get("name", ""),
                color=player_data.get("color", key),
                eliminated=player_data.get("eliminated", False),
            )
            for key, player_data in data.get("players", {}).items()
        }
        field_data = data.get("field", {})
        match.field.grid = [list(row) for row in field_data.get("grid", match.field.grid)]
        match.field.owners = [list(row) for row in field_data.get("owners", match.field.owners)]
        ships_data = field_data.get("ships", {})
        for key, ships in ships_data.items():
            match.field.ships[key] = [
                Ship(cells=[tuple(cell) for cell in ship.get("cells", [])], owner=ship.get("owner", key), alive=ship.get("alive", True))
                for ship in ships
            ]
        match.field.highlight = [tuple(coord) for coord in field_data.get("highlight", [])]
        last_move = field_data.get("last_move")
        if last_move is not None:
            match.field.last_move = (last_move[0], last_move[1])
        match.order = list(data.get("order", PLAYER_ORDER))
        match.turn_idx = int(data.get("turn_idx", 0))
        match.alive_cells = {key: int(value) for key, value in data.get("alive_cells", {}).items()}
        raw_cell_history = data.get("cell_history")
        if raw_cell_history is not None:
            match.cell_history = normalize_history_grid(raw_cell_history)
        else:
            legacy_history = data.get("history")
            if legacy_history and isinstance(legacy_history, list) and legacy_history and isinstance(legacy_history[0], dict):
                # Already in the new log format.
                match.cell_history = normalize_history_grid(empty_history())
            else:
                match.cell_history = normalize_history_grid(legacy_history)
        raw_log = data.get("history") or []
        if raw_log and isinstance(raw_log, list) and raw_log and isinstance(raw_log[0], dict):
            entries = []
            for item in raw_log:
                try:
                    entries.append(ShotLogEntry.from_payload(item))
                except Exception:
                    continue
            match.history = entries
        else:
            match.history = []
        match.messages = {
            key: dict(value)
            for key, value in data.get("messages", {}).items()
        }
        match.shots = {
            key: {
                "history": [tuple(item) if isinstance(item, (list, tuple)) else item for item in value.get("history", [])],
                "last_result": value.get("last_result"),
                "move_count": value.get("move_count", 0),
                "joke_start": value.get("joke_start"),
                "last_coord": tuple(value.get("last_coord")) if value.get("last_coord") else None,
            }
            for key, value in data.get("shots", {}).items()
        }
        match.boards = {key: match.field for key in PLAYER_ORDER}
        return match


__all__ = [
    "Board15",
    "Field15",
    "Match15",
    "Player",
    "Ship",
    "ShotLogEntry",
    "Snapshot15",
    "Coord",
    "empty_history",
    "normalize_history_cell",
    "normalize_history_grid",
    "PLAYER_COLOR_SCHEMES",
    "PLAYER_DARK_COLORS",
    "PLAYER_LIGHT_COLORS",
    "PLAYER_COLORS",
    "PLAYER_ORDER",
]
