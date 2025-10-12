"""Data models for the 15×15 three-player mode."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import uuid

Coord = Tuple[int, int]


PLAYER_ORDER = ["A", "B", "C"]
PLAYER_COLORS = {
    "A": (64, 115, 255),
    "B": (38, 178, 69),
    "C": (255, 136, 17),
}


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
    field: Field15
    alive_cells: Dict[str, int]
    history: List[List[List[int | None]]]
    last_move: Optional[Coord]

    @classmethod
    def from_match(cls, match: "Match15") -> "Snapshot15":
        field_copy = match.field.clone()
        history_copy = [
            [list(cell) if isinstance(cell, (list, tuple)) else [cell, None] for cell in row]
            for row in match.history
        ]
        return cls(
            status=match.status,
            turn_idx=match.turn_idx,
            field=field_copy,
            alive_cells={k: v for k, v in match.alive_cells.items()},
            history=history_copy,
            last_move=match.field.last_move,
        )


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
    history: List[List[List[int | None]]] = dc_field(
        default_factory=lambda: [[[0, None] for _ in range(15)] for _ in range(15)]
    )
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
            "history": [
                [list(cell) if isinstance(cell, (list, tuple)) else [cell, None] for cell in row]
                for row in self.history
            ],
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
        match.history = [
            [list(cell) if isinstance(cell, (list, tuple)) else [cell, None] for cell in row]
            for row in data.get("history", match.history)
        ]
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
    "Snapshot15",
    "Coord",
    "PLAYER_COLORS",
    "PLAYER_ORDER",
]
