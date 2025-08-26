from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Board15State:
    """State of a 15x15 board used for rendering and message tracking.

    Only the data necessary for creating board images and updating Telegram
    messages is stored.  The board itself is represented as a 15x15 matrix of
    integers where ``0`` denotes an empty cell and other values are produced by
    the game logic.
    """

    board: List[List[int]] = field(
        default_factory=lambda: [[0] * 15 for _ in range(15)]
    )
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    status_message_id: Optional[int] = None
    player_key: Optional[str] = None
