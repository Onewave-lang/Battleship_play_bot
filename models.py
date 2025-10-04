from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import uuid
import random


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
    # cells to highlight (last shot or destroyed ship) for rendering
    highlight: List[Coord] = field(default_factory=list)
    # owner key ("A", "B" or "C") used for colouring
    owner: Optional[str] = None


@dataclass
class Player:
    user_id: int
    chat_id: int
    name: str = ""
    ready: bool = False


@dataclass
class Match:
    match_id: str
    status: str = "waiting"  # waiting|placing|playing|finished
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    players: Dict[str, Player] = field(default_factory=dict)
    turn: str = "A"
    boards: Dict[str, Board] = field(default_factory=dict)
    # global shot history for rendering target board
    history: List[List[int]] = field(
        default_factory=lambda: [[0] * 10 for _ in range(10)]
    )
    last_highlight: List[Coord] = field(default_factory=list)
    shots: Dict[str, Dict[str, object]] = field(
        default_factory=lambda: {
            k: {
                "history": [],
                "last_result": None,
                "move_count": 0,
                "joke_start": random.randint(1, 10),
            }
            for k in ("A", "B", "C")
        }
    )
    # stores ids of service messages per player: e.g. last board or keyboard
    # also maintains chronological history of all board and text messages
    messages: Dict[str, Dict[str, object]] = field(
        default_factory=lambda: {
            k: {
                "board_history": [],
                "text_history": [],
                "history_active": False,
            }
            for k in ("A", "B", "C")
        }
    )

    @staticmethod
    def new(a_user_id: int, a_chat_id: int, a_name: str = "") -> 'Match':
        match_id = uuid.uuid4().hex
        match = Match(match_id=match_id)
        match.players["A"] = Player(
            user_id=a_user_id,
            chat_id=a_chat_id,
            name=a_name.strip(),
        )
        for k in ("A", "B", "C"):
            match.boards[k] = Board(owner=k)
        match.history = [[0] * 10 for _ in range(10)]
        return match
