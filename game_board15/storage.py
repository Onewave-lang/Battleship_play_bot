from __future__ import annotations
import json
from pathlib import Path
import logging
from threading import Lock
from typing import Dict
from datetime import datetime

from .models import Match15, Board15, Player, Ship
from . import placement

DATA_FILE = Path("data15.json")
_lock = Lock()
logger = logging.getLogger(__name__)


def _load_all() -> Dict[str, dict]:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def _save_all(data: Dict[str, dict]) -> str | None:
    tmp = DATA_FILE.with_suffix('.tmp')
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(DATA_FILE)
    except OSError as e:
        logger.exception("Failed to save data15")
        return str(e)
    return None


def create_match(a_user_id: int, a_chat_id: int, a_name: str = "") -> Match15:
    match = Match15.new(a_user_id, a_chat_id, a_name)
    save_match(match)
    return match


def get_match(match_id: str) -> Match15 | None:
    with _lock:
        data = _load_all()
    m = data.get(match_id)
    if not m:
        return None
    match = Match15(match_id=m['match_id'], status=m['status'], created_at=m['created_at'])
    match.turn = m.get('turn', 'A')
    match.players = {k: Player(**p) for k, p in m.get('players', {}).items()}
    match.boards = {}
    for key, b in m.get('boards', {}).items():
        ships = [Ship(cells=[tuple(cell) for cell in s.get('cells', [])], alive=s.get('alive', True)) for s in b.get('ships', [])]
        match.boards[key] = Board15(grid=b.get('grid', [[0]*15 for _ in range(15)]), ships=ships, alive_cells=b.get('alive_cells', 20))
    match.history = m.get('history', [[0] * 15 for _ in range(15)])
    match.shots = m.get('shots', match.shots)
    match.messages = m.get('messages', {})
    return match


def join_match(match_id: str, user_id: int, chat_id: int, name: str = "") -> Match15 | None:
    match = get_match(match_id)
    if not match:
        return None
    if user_id in [p.user_id for p in match.players.values()]:
        return None
    if 'B' not in match.players:
        match.players['B'] = Player(user_id=user_id, chat_id=chat_id, name=name)
    elif 'C' not in match.players:
        match.players['C'] = Player(user_id=user_id, chat_id=chat_id, name=name)
    else:
        return None
    if len(match.players) == 3:
        match.status = 'placing'
    save_match(match)
    return match


def save_board(match: Match15,
               player_key: str,
               board: Board15 | None = None) -> None:
    """Save player's board and update match state safely.

    Similar to the two-player version, we need to avoid race conditions when
    several players send the ``авто`` command simultaneously.  The previous
    implementation called :func:`get_match` while holding the global lock,
    which attempted to acquire the same lock again and caused a deadlock.
    Instead we reconstruct the latest state manually based on the data stored
    on disk.
    """

    with _lock:
        data = _load_all()
        m_dict = data.get(match.match_id)
        if m_dict:
            # Reconstruct current match state without calling get_match (to
            # avoid re-acquiring the lock)
            current = Match15(
                match_id=m_dict['match_id'],
                status=m_dict['status'],
                created_at=m_dict['created_at'],
            )
            current.turn = m_dict.get('turn', 'A')
            current.players = {k: Player(**p) for k, p in m_dict.get('players', {}).items()}
            current.boards = {}
            for key, b in m_dict.get('boards', {}).items():
                ships = [
                    Ship(cells=[tuple(cell) for cell in s.get('cells', [])],
                         alive=s.get('alive', True))
                    for s in b.get('ships', [])
                ]
                current.boards[key] = Board15(
                    grid=b.get('grid', [[0] * 15 for _ in range(15)]),
                    ships=ships,
                    alive_cells=b.get('alive_cells', 20),
                )
            current.shots = m_dict.get('shots', current.shots)
            current.messages = m_dict.get('messages', {})
            current.history = m_dict.get('history', [[0] * 15 for _ in range(15)])
        else:
            current = match

        # build a mask of cells occupied or surrounded by other fleets
        mask = [[0] * 15 for _ in range(15)]
        for k, b in current.boards.items():
            if k == player_key:
                continue
            for ship in b.ships:
                for r, c in ship.cells:
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < 15 and 0 <= nc < 15:
                                mask[nr][nc] = 1

        # generate board if not provided, taking into account the mask
        if board is None:
            board = placement.random_board(mask)

        current.boards[player_key] = board
        current.players[player_key].ready = True
        if (
            len(current.players) == 3
            and all(p.ready for p in current.players.values())
            and current.status != 'playing'
        ):
            current.status = 'playing'
            current.turn = 'A'

        # persist updated match
        data[current.match_id] = {
            'match_id': current.match_id,
            'status': current.status,
            'created_at': current.created_at,
            'players': {k: vars(p) for k, p in current.players.items()},
            'turn': current.turn,
            'boards': {
                k: {
                    'grid': b.grid,
                    'ships': [{'cells': s.cells, 'alive': s.alive} for s in b.ships],
                    'alive_cells': b.alive_cells,
                }
                for k, b in current.boards.items()
            },
            'shots': current.shots,
            'messages': current.messages,
            'history': current.history,
        }
        _save_all(data)

    # update caller's object with latest state
    match.status = current.status
    match.turn = current.turn
    match.players = current.players
    match.boards = current.boards
    match.shots = current.shots
    match.history = current.history
    match.messages = current.messages


def save_match(match: Match15) -> str | None:
    with _lock:
        data = _load_all()
        data[match.match_id] = {
            'match_id': match.match_id,
            'status': match.status,
            'created_at': match.created_at,
            'players': {k: vars(p) for k, p in match.players.items()},
            'turn': match.turn,
            'boards': {k: {'grid': b.grid, 'ships': [{'cells': s.cells, 'alive': s.alive} for s in b.ships], 'alive_cells': b.alive_cells} for k, b in match.boards.items()},
            'shots': match.shots,
            'messages': match.messages,
            'history': match.history,
        }
        return _save_all(data)


def finish(match: Match15, winner: str) -> str | None:
    match.status = 'finished'
    match.shots[winner]['last_result'] = 'win'
    return save_match(match)


def find_match_by_user(user_id: int, chat_id: int | None = None) -> Match15 | None:
    """Return the latest active match for ``user_id``.

    When ``chat_id`` is provided, prefer matches where the user participates in
    the specified chat.  If no such match exists, fall back to the most recent
    active match regardless of chat.
    """
    with _lock:
        data = _load_all()
    active = {'waiting', 'placing', 'playing'}
    all_candidates: list[dict] = []
    chat_candidates: list[dict] = []
    for m in data.values():
        if m.get('status') not in active:
            continue
        players = m.get('players', {})
        for p in players.values():
            if p.get('user_id') == user_id:
                all_candidates.append(m)
                if chat_id is not None and p.get('chat_id') == chat_id:
                    chat_candidates.append(m)
                break
    candidates = chat_candidates if chat_candidates else all_candidates
    if not candidates:
        return None
    latest = max(candidates, key=lambda m: datetime.fromisoformat(m['created_at']))
    return get_match(latest['match_id'])
