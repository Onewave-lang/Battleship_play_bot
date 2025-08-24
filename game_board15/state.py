from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Board15State:
    """State of a 15x15 board with a movable 5x5 window.

    This simplified state container keeps only the data required for
    rendering the board and tracking user interactions.  The board is a
    15x15 matrix of integers where ``0`` represents an empty cell.  Other
    values may be used by the game logic to indicate various markers.
    """

    board: List[List[int]] = field(
        default_factory=lambda: [[0] * 15 for _ in range(15)]
    )
    window_top: int = 0
    window_left: int = 0
    phase: str = "aim"
    last_img_hash: str = ""
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    selected: Optional[Tuple[int, int]] = None
