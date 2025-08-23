from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import uuid


Coord = Tuple[int, int]  # row, col indexes


@dataclass
class Ship:
    cells: List[Coord]
    alive: bool = True


@dataclass
class Board:
    grid: List[List[int]] = field(default_factory=lambda: [[0]*10 for _ in range(10)])
    ships: List[Ship] = field(default_factory=list)
    alive_cells: int = 20


@dataclass
class Player:
    user_id: int
    chat_id: int
    ready: bool = False


@dataclass
class Match:
    match_id: str
    status: str = "waiting"  # waiting|placing|playing|finished
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    players: Dict[str, Player] = field(default_factory=dict)
    turn: str = "A"
    boards: Dict[str, Board] = field(default_factory=dict)
    shots: Dict[str, Dict[str, object]] = field(default_factory=lambda: {
        "A": {"history": [], "last_result": None},
        "B": {"history": [], "last_result": None}
    })
    messages: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @staticmethod
    def new(a_user_id: int, a_chat_id: int) -> 'Match':
        match_id = uuid.uuid4().hex
        match = Match(match_id=match_id)
        match.players["A"] = Player(user_id=a_user_id, chat_id=a_chat_id)
        match.boards["A"] = Board()
        match.boards["B"] = Board()
        return match
