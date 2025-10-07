from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple, Any

import httpx

from models import Match, Player, Board, Ship


logger = logging.getLogger(__name__)


USE_SUPABASE = os.getenv("USE_SUPABASE") == "1"
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or ""
SUPABASE_TABLE10 = os.getenv("SUPABASE_TABLE10", "matches10")

DATA_FILE = Path(os.getenv("DATA_FILE_PATH", "data.json"))

_lock = Lock()


def _sb_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    base = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    }
    if extra:
        base.update(extra)
    return base


def _require_supabase() -> None:
    if not (SUPABASE_URL and SUPABASE_KEY):
        raise RuntimeError("Supabase credentials are not configured")


def _sb_get_all() -> Dict[str, dict]:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE10}?select=id,payload"
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=_sb_headers())
        response.raise_for_status()
        rows = response.json()
    return {row["id"]: row["payload"] for row in rows}


def _sb_get_one(match_id: str) -> Optional[dict]:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE10}?id=eq.{match_id}&select=id,payload"
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=_sb_headers())
        response.raise_for_status()
        rows = response.json()
    if not rows:
        return None
    return rows[0]["payload"]


def _sb_upsert_one(match_id: str, payload: dict) -> None:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE10}?on_conflict=id"
    body = [{"id": match_id, "payload": payload}]
    headers = _sb_headers({
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    })
    with httpx.Client(timeout=30) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()


def _sb_delete_one(match_id: str) -> None:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE10}?id=eq.{match_id}"
    with httpx.Client(timeout=30) as client:
        response = client.delete(url, headers=_sb_headers({"Prefer": "return=representation"}))
        response.raise_for_status()


def _file_load_all() -> Dict[str, dict]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            logger.warning("DATA_FILE is corrupted or empty, returning {}")
            return {}
    return {}


def _file_save_all(data: Dict[str, dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def _file_get_one(match_id: str) -> Optional[dict]:
    with _lock:
        data = _file_load_all()
        return data.get(match_id)


def _file_upsert_one(match_id: str, payload: dict) -> None:
    with _lock:
        data = _file_load_all()
        data[match_id] = payload
        _file_save_all(data)


def _file_delete_one(match_id: str) -> None:
    with _lock:
        data = _file_load_all()
        if match_id in data:
            del data[match_id]
            _file_save_all(data)


# ---------------------------------------------------------------------------
# Helpers for serialising matches
# ---------------------------------------------------------------------------

def _coord_to_list(coord: Tuple[int, int] | List[int] | None) -> Optional[List[int]]:
    if coord is None:
        return None
    if isinstance(coord, tuple):
        return [int(coord[0]), int(coord[1])]
    if isinstance(coord, list):
        if len(coord) >= 2:
            return [int(coord[0]), int(coord[1])]
        return coord
    return [int(coord), 0]


def _coord_from_value(value: Any) -> Tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    raise ValueError(f"Invalid coordinate value: {value!r}")


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, set):
        return [_json_ready(v) for v in value]
    return value


def _ship_to_payload(ship: Ship) -> dict:
    return {
        "cells": [_coord_to_list(cell) for cell in ship.cells],
        "alive": ship.alive,
    }


def _ship_from_payload(data: dict) -> Ship:
    cells = [
        _coord_from_value(cell)
        for cell in data.get("cells", [])
    ]
    return Ship(cells=cells, alive=bool(data.get("alive", True)))


def _board_to_payload(board: Board) -> dict:
    payload = {
        "grid": _json_ready(board.grid),
        "ships": [_ship_to_payload(ship) for ship in board.ships],
        "alive_cells": board.alive_cells,
        "highlight": [
            _coord_to_list(coord) for coord in getattr(board, "highlight", [])
        ],
        "owner": board.owner,
    }
    return payload


def _board_from_payload(owner: str, data: dict) -> Board:
    board = Board(owner=owner)
    grid = data.get("grid")
    if grid is not None:
        board.grid = deepcopy(grid)
    ships = data.get("ships") or []
    board.ships = [_ship_from_payload(item) for item in ships]
    board.alive_cells = int(data.get("alive_cells", board.alive_cells))
    board.highlight = [
        _coord_from_value(coord) for coord in data.get("highlight", [])
    ]
    board.owner = data.get("owner", owner)
    return board


def _match_to_payload(match: Match) -> dict:
    players_payload = {
        key: {
            "user_id": player.user_id,
            "chat_id": player.chat_id,
            "name": player.name,
            "ready": player.ready,
        }
        for key, player in match.players.items()
    }

    boards_payload = {
        key: _board_to_payload(board)
        for key, board in match.boards.items()
    }

    shots_payload: Dict[str, dict] = {}
    for key, data in match.shots.items():
        entry = _json_ready(data)
        last_coord = entry.get("last_coord")
        if last_coord is not None:
            entry["last_coord"] = _coord_to_list(last_coord)  # type: ignore[arg-type]
        shots_payload[key] = entry

    messages_payload = _json_ready(match.messages)

    payload: Dict[str, Any] = {
        "match_id": match.match_id,
        "status": match.status,
        "created_at": getattr(match, "created_at", datetime.utcnow().isoformat()),
        "turn": match.turn,
        "players": players_payload,
        "boards": boards_payload,
        "history": _json_ready(match.history),
        "last_highlight": [
            _coord_to_list(coord) for coord in getattr(match, "last_highlight", [])
        ],
        "shots": shots_payload,
        "messages": messages_payload,
    }

    if hasattr(match, "updated_at"):
        payload["updated_at"] = getattr(match, "updated_at")
    if hasattr(match, "winner"):
        payload["winner"] = getattr(match, "winner")
    if hasattr(match, "snapshots"):
        payload["snapshots"] = _json_ready(getattr(match, "snapshots"))

    return payload


def _payload_to_match(payload: dict) -> Match:
    match = Match(
        match_id=payload.get("match_id", ""),
        status=payload.get("status", "waiting"),
        created_at=payload.get("created_at", datetime.utcnow().isoformat()),
    )
    match.turn = payload.get("turn", match.turn)

    players_data = payload.get("players") or {}
    players: Dict[str, Player] = {}
    for key, info in players_data.items():
        try:
            user_id = int(info.get("user_id", 0))
        except (TypeError, ValueError):
            user_id = 0
        try:
            chat_id = int(info.get("chat_id", 0))
        except (TypeError, ValueError):
            chat_id = 0
        players[key] = Player(
            user_id=user_id,
            chat_id=chat_id,
            name=str(info.get("name", "")),
            ready=bool(info.get("ready", False)),
        )
    match.players = players

    boards_data = payload.get("boards") or {}
    boards: Dict[str, Board] = {}
    for key in ("A", "B", "C"):
        board_payload = boards_data.get(key)
        if board_payload:
            boards[key] = _board_from_payload(key, board_payload)
        else:
            boards[key] = Board(owner=key)
    for key, board_payload in boards_data.items():
        if key not in boards:
            boards[key] = _board_from_payload(key, board_payload)
    match.boards = boards

    history = payload.get("history")
    match.history = deepcopy(history) if history is not None else [[0] * 10 for _ in range(10)]
    match.last_highlight = [
        _coord_from_value(coord) for coord in payload.get("last_highlight", [])
    ]

    raw_shots = payload.get("shots") or {}
    default_shots = match.shots
    for key, defaults in default_shots.items():
        data = deepcopy(raw_shots.get(key, {}))
        merged = {**defaults, **data}
        last_coord = merged.get("last_coord")
        if last_coord is not None:
            try:
                merged["last_coord"] = _coord_from_value(last_coord)
            except ValueError:
                merged["last_coord"] = None
        match.shots[key] = merged
    for key, data in raw_shots.items():
        if key not in match.shots:
            merged = deepcopy(data)
            last_coord = merged.get("last_coord")
            if last_coord is not None:
                try:
                    merged["last_coord"] = _coord_from_value(last_coord)
                except ValueError:
                    merged["last_coord"] = None
            match.shots[key] = merged

    default_messages = match.messages
    messages_data = payload.get("messages")
    if isinstance(messages_data, dict):
        for key, defaults in list(default_messages.items()):
            data = messages_data.get(key)
            if data is None:
                continue
            combined = deepcopy(defaults)
            combined.update(deepcopy(data))
            match.messages[key] = combined
        for key, value in messages_data.items():
            if key not in match.messages:
                match.messages[key] = deepcopy(value)
    match.messages.setdefault("_flags", {})

    if "updated_at" in payload:
        match.updated_at = payload["updated_at"]
    if "winner" in payload:
        match.winner = payload["winner"]
    if "snapshots" in payload:
        match.snapshots = deepcopy(payload["snapshots"])

    return match


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_matches() -> Dict[str, dict]:
    if USE_SUPABASE:
        try:
            return _sb_get_all()
        except Exception:
            logger.exception("Failed to list matches from Supabase; falling back to empty {}")
            return {}
    return _file_load_all()


def get_match(match_id: str) -> Optional[Match]:
    if USE_SUPABASE:
        try:
            payload = _sb_get_one(match_id)
        except Exception:
            logger.exception("Failed to get match from Supabase")
            payload = None
    else:
        payload = _file_get_one(match_id)
    if not payload:
        return None
    try:
        return _payload_to_match(payload)
    except Exception:
        logger.exception("Failed to deserialize match %s", match_id)
        return None


def _persist_payload(match_id: str, payload: dict) -> Optional[str]:
    try:
        if USE_SUPABASE:
            _sb_upsert_one(match_id, payload)
        else:
            _file_upsert_one(match_id, payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to persist match %s", match_id)
        return str(exc)
    return None


def create_match(a_user_id: int, a_chat_id: int, a_name: str = "") -> Match:
    match = Match.new(a_user_id, a_chat_id, a_name)
    payload = _match_to_payload(match)
    now = datetime.utcnow().isoformat()
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    match.created_at = payload["created_at"]
    match.updated_at = now
    error = _persist_payload(match.match_id, payload)
    if error:
        logger.error("Failed to create match %s: %s", match.match_id, error)
    return match


def save_match(match: Match) -> Optional[str]:
    payload = _match_to_payload(match)
    now = datetime.utcnow().isoformat()
    payload["updated_at"] = now
    match.updated_at = now
    return _persist_payload(match.match_id, payload)


def delete_match(match_id: str) -> None:
    if USE_SUPABASE:
        try:
            _sb_delete_one(match_id)
        except Exception:
            logger.exception("Failed to delete match %s from Supabase", match_id)
    else:
        _file_delete_one(match_id)


def join_match(match_id: str, user_id: int, chat_id: int, name: str = "") -> Optional[Match]:
    match = get_match(match_id)
    if not match:
        return None

    for player in match.players.values():
        if player.user_id == user_id:
            player.chat_id = chat_id
            if name:
                player.name = name
            save_match(match)
            return match

    slot = None
    for key in ("B", "A", "C"):
        player = match.players.get(key)
        if player is None or player.user_id in (0, None):
            slot = key
            break
    if slot is None:
        return None

    match.players[slot] = Player(user_id=user_id, chat_id=chat_id, name=name or "", ready=False)
    match.boards.setdefault(slot, Board(owner=slot))
    if match.status == "waiting":
        match.status = "placing"
    save_match(match)
    return match


def save_board(match: Match, player_key: str, board: Optional[Board] = None) -> Optional[str]:
    if board is not None:
        board.owner = player_key
        match.boards[player_key] = board
    match.players.setdefault(player_key, Player(user_id=0, chat_id=0, name="", ready=False))
    match.players[player_key].ready = True

    if match.status == "waiting":
        match.status = "placing"

    ready_state = {
        key: bool(match.players.get(key) and match.players[key].ready)
        for key in ("A", "B")
    }

    if not all(ready_state.values()):
        latest = get_match(match.match_id)
        if latest:
            for key in ("A", "B"):
                latest_player = latest.players.get(key)
                if not latest_player:
                    continue
                existing = match.players.get(key)
                combined_ready = bool(existing and existing.ready) or latest_player.ready
                if key == player_key:
                    match.players[key].ready = combined_ready
                else:
                    match.players[key] = Player(
                        user_id=latest_player.user_id,
                        chat_id=latest_player.chat_id,
                        name=latest_player.name,
                        ready=combined_ready,
                    )
                ready_state[key] = combined_ready
                if key != player_key and (
                    key not in match.boards or not getattr(match.boards[key], "ships", None)
                ):
                    match.boards[key] = latest.boards.get(key, match.boards.get(key))

    if all(ready_state.values()):
        match.status = "playing"
        if match.turn not in ("A", "B"):
            match.turn = "A"

    error = save_match(match)
    if error:
        return error

    latest = get_match(match.match_id)
    if latest and latest.status != "playing":
        if all(
            latest.players.get(key) and latest.players[key].ready
            for key in ("A", "B")
        ):
            latest.status = "playing"
            if latest.turn not in ("A", "B"):
                latest.turn = "A"
            save_match(latest)

    return None


def close_match(match: Match) -> Optional[str]:
    match.status = "finished"
    return save_match(match)


def finish(match: Match, winner: str) -> Optional[str]:
    match.status = "finished"
    match.turn = winner
    match.winner = winner
    return save_match(match)


def find_match_by_user(
    user_id: int,
    chat_id: Optional[int] = None,
    active_statuses: Optional[List[str]] = None,
) -> Optional[Match]:
    active = set(active_statuses or ["active", "placing", "in_progress", "waiting", "playing"])
    candidates: List[dict] = []
    any_chat: List[dict] = []
    for payload in list_matches().values():
        status = payload.get("status", "waiting")
        if status not in active:
            continue
        players = payload.get("players") or {}
        for info in players.values():
            try:
                pid = int(info.get("user_id", 0))
            except (TypeError, ValueError):
                continue
            if pid != int(user_id):
                continue
            if chat_id is not None:
                try:
                    cid = int(info.get("chat_id", 0))
                except (TypeError, ValueError):
                    continue
                if cid != int(chat_id):
                    any_chat.append(payload)
                    continue
            candidates.append(payload)
            any_chat.append(payload)
            break
    if not candidates:
        if chat_id is not None and any_chat:
            candidates = any_chat
        else:
            return None

    def _ts(data: dict) -> str:
        return data.get("updated_at") or data.get("created_at") or "1970-01-01T00:00:00"

    latest = max(candidates, key=_ts)
    return _payload_to_match(latest)
