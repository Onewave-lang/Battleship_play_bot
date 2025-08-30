from __future__ import annotations
import json
from pathlib import Path
import logging
from threading import Lock
from typing import Dict
from datetime import datetime

from models import Match, Board

DATA_FILE = Path("data.json")
_lock = Lock()
logger = logging.getLogger(__name__)


def _load_all() -> Dict[str, dict]:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # corrupted or empty file
            return {}
    return {}


def _save_all(data: Dict[str, dict]) -> str | None:
    tmp_file = DATA_FILE.with_suffix('.tmp')
    try:
        with tmp_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(DATA_FILE)
    except OSError as e:
        logger.exception("Failed to save data file")
        return str(e)
    return None


def create_match(a_user_id: int, a_chat_id: int) -> Match:
    match = Match.new(a_user_id, a_chat_id)
    save_match(match)
    return match


def get_match(match_id: str) -> Match | None:
    with _lock:
        data = _load_all()
    m = data.get(match_id)
    if not m:
        return None
    # reconstruct Match
    match = Match(match_id=m['match_id'], status=m['status'], created_at=m['created_at'])
    # players
    from models import Player, Ship
    match.players = {
        key: Player(**p) for key, p in m['players'].items()
    }
    # boards
    match.boards = {}
    for key, b in m['boards'].items():
        ships = [
            Ship(cells=[tuple(cell) for cell in s.get('cells', [])],
                 alive=s.get('alive', True))
            for s in b.get('ships', [])
        ]
        match.boards[key] = Board(
            grid=b.get('grid', [[0] * 10 for _ in range(10)]),
            ships=ships,
            alive_cells=b.get('alive_cells', 20),
            owner=b.get('owner', key),
        )
    match.turn = m.get('turn', 'A')
    match.history = m.get('history', [[0] * 10 for _ in range(10)])
    match.last_highlight = [tuple(cell) for cell in m.get('last_highlight', [])]
    match.shots = m.get('shots', match.shots)
    match.messages = m.get('messages', {})
    return match


def join_match(match_id: str, b_user_id: int, b_chat_id: int) -> Match | None:
    match = get_match(match_id)
    if (
        not match
        or 'B' in match.players
        or match.players['A'].user_id == b_user_id
    ):
        return None
    from models import Player
    match.players['B'] = Player(user_id=b_user_id, chat_id=b_chat_id)
    match.status = 'placing'
    save_match(match)
    return match


def save_board(match: Match, player_key: str, board: Board) -> None:
    """Save player's board and update match state.

    The previous implementation performed a read-modify-write cycle without
    locking which led to a race condition: when both players sent the
    "авто" command almost simultaneously, the second write could overwrite the
    first player's ``ready`` flag.  As a result the match never transitioned to
    the ``playing`` state and both players kept waiting for each other.

    To avoid lost updates we perform the whole update while holding the global
    lock and base modifications on the latest data from storage.
    """
    with _lock:
        data = _load_all()
        # Reconstruct current match state from storage to avoid stale data
        m_dict = data.get(match.match_id)
        if m_dict:
            from models import Player, Ship
            current = Match(match_id=m_dict['match_id'],
                            status=m_dict['status'],
                            created_at=m_dict['created_at'])
            current.players = {key: Player(**p) for key, p in m_dict['players'].items()}
            current.boards = {}
            for key, b in m_dict['boards'].items():
                ships = [
                    Ship(cells=[tuple(cell) for cell in s.get('cells', [])],
                         alive=s.get('alive', True))
                    for s in b.get('ships', [])
                ]
                current.boards[key] = Board(
                    grid=b.get('grid', [[0] * 10 for _ in range(10)]),
                    ships=ships,
                    alive_cells=b.get('alive_cells', 20),
                    owner=b.get('owner', key),
                )
            current.turn = m_dict.get('turn', 'A')
            current.shots = m_dict.get('shots', current.shots)
            current.messages = m_dict.get('messages', {})
            current.history = m_dict.get('history', [[0] * 10 for _ in range(10)])
            current.last_highlight = [tuple(cell) for cell in m_dict.get('last_highlight', [])]
        else:
            current = match

        # apply board and readiness
        board.owner = player_key
        current.boards[player_key] = board
        current.players[player_key].ready = True
        if all(p.ready for p in current.players.values()) and current.status != 'playing':
            current.status = 'playing'
            current.turn = 'A'

        # persist updated match
        data[current.match_id] = {
            'match_id': current.match_id,
            'status': current.status,
            'created_at': current.created_at,
            'players': {k: vars(p) for k, p in current.players.items()},
            'turn': current.turn,
            'boards': {k: {'grid': b.grid,
                           'ships': [{'cells': s.cells, 'alive': s.alive} for s in b.ships],
                           'alive_cells': b.alive_cells,
                           'owner': b.owner}
                       for k, b in current.boards.items()},
            'shots': current.shots,
            'messages': current.messages,
            'history': current.history,
            'last_highlight': current.last_highlight,
        }
        _save_all(data)

    # update caller's object with the latest state
    match.status = current.status
    match.turn = current.turn
    match.players = current.players
    match.boards = current.boards
    match.shots = current.shots
    match.history = current.history
    match.messages = current.messages
    match.last_highlight = current.last_highlight


def finish(match: Match, winner: str) -> str | None:
    match.status = "finished"
    match.shots[winner]["last_result"] = "win"
    return save_match(match)


def close_match(match: Match) -> str | None:
    """Mark match as finished without declaring a winner."""
    match.status = "finished"
    return save_match(match)


def save_match(match: Match) -> str | None:
    with _lock:
        data = _load_all()
        data[match.match_id] = {
            "match_id": match.match_id,
            "status": match.status,
            "created_at": match.created_at,
            "players": {k: vars(p) for k, p in match.players.items()},
            "turn": match.turn,
            "boards": {
                k: {
                    "grid": b.grid,
                    "ships": [{"cells": s.cells, "alive": s.alive} for s in b.ships],
                    "alive_cells": b.alive_cells,
                    "owner": b.owner,
                }
                for k, b in match.boards.items()
            },
            "shots": match.shots,
            "messages": match.messages,
            "history": match.history,
            "last_highlight": match.last_highlight,
        }
        return _save_all(data)


def find_match_by_user(user_id: int, chat_id: int | None = None) -> Match | None:
    """Return the latest active match for ``user_id``.

    If ``chat_id`` is provided, a match is returned only if the user is a
    participant in that chat.  When no such match exists, the behaviour
    falls back to the previous implementation: return the most recent active
    match regardless of chat.

    Only matches in ``waiting``, ``placing`` or ``playing`` states are
    considered.  Matches in the ``finished`` state are ignored.
    """
    with _lock:
        data = _load_all()
    active_statuses = {"waiting", "placing", "playing"}
    all_candidates = []
    chat_candidates = []
    for m in data.values():
        if m.get("status") not in active_statuses:
            continue
        players = m.get("players", {})
        for p in players.values():
            if p.get("user_id") == user_id:
                all_candidates.append(m)
                if chat_id is not None and p.get("chat_id") == chat_id:
                    chat_candidates.append(m)
                break
    candidates = chat_candidates if chat_candidates else all_candidates
    if not candidates:
        return None
    latest = max(candidates, key=lambda m: datetime.fromisoformat(m["created_at"]))
    return get_match(latest["match_id"])
