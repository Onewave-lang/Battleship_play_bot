"""Persistence helpers for the 15×15 mode."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, Optional

from .models import (
    Match15,
    Player,
    Snapshot15,
    PLAYER_ORDER,
    normalize_history_cell,
)


class SnapshotDiffError(RuntimeError):
    """Raised when a snapshot differs from the previous one unexpectedly."""


def _fresh_cells(snapshot: Snapshot15) -> set[tuple[int, int]]:
    fresh: set[tuple[int, int]] = set()
    for r, row in enumerate(snapshot.cell_history):
        for c, cell in enumerate(row):
            normalized = normalize_history_cell(cell)
            age = normalized[2] if len(normalized) > 2 else 1
            if age == 0:
                fresh.add((r, c))
    return fresh


def _changed_cells(previous: Snapshot15, current: Snapshot15) -> set[tuple[int, int]]:
    changed: set[tuple[int, int]] = set()
    for r in range(15):
        for c in range(15):
            if previous.field.grid[r][c] != current.field.grid[r][c]:
                changed.add((r, c))
                continue
            if previous.field.owners[r][c] != current.field.owners[r][c]:
                changed.add((r, c))
                continue
            if normalize_history_cell(previous.cell_history[r][c]) != normalize_history_cell(
                current.cell_history[r][c]
            ):
                changed.add((r, c))
    return changed

logger = logging.getLogger(__name__)

DATA_FILE = Path(os.getenv("DATA15_FILE_PATH", "data15.json"))
SNAPSHOT_DIR = Path(os.getenv("DATA15_SNAPSHOTS", "snapshots15"))

_lock = RLock()
_cache: Dict[str, Match15] = {}


def _load_all() -> Dict[str, Match15]:
    if _cache:
        return _cache
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupted data15.json; starting with an empty store")
            data = {}
    else:
        data = {}
    for match_id, payload in data.items():
        try:
            _cache[match_id] = Match15.from_payload(payload)
        except Exception:
            logger.exception("Failed to load match %s from storage", match_id)
    return _cache


def _save_all(matches: Dict[str, Match15]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {match_id: match.to_payload() for match_id, match in matches.items()}
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def list_matches() -> Iterable[Match15]:
    with _lock:
        return list(_load_all().values())


def save_match(match: Match15) -> None:
    with _lock:
        matches = _load_all()
        matches[match.match_id] = match
        _save_all(matches)


def delete_match(match_id: str) -> None:
    with _lock:
        matches = _load_all()
        if match_id in matches:
            del matches[match_id]
            _save_all(matches)


def create_match(user_id: int, chat_id: int, name: str) -> Match15:
    match = Match15.new(user_id, chat_id, name)
    save_match(match)
    return match


def get_match(match_id: str) -> Optional[Match15]:
    with _lock:
        return _load_all().get(match_id)


def find_match_by_user(user_id: int, chat_id: int | None = None) -> Optional[Match15]:
    with _lock:
        for match in _load_all().values():
            for player in match.players.values():
                if player.user_id == user_id and (chat_id is None or player.chat_id == chat_id):
                    return match
    return None


def join_match(match_id: str, user_id: int, chat_id: int, name: str) -> Optional[Match15]:
    with _lock:
        match = _load_all().get(match_id)
        if not match:
            return None
        for key in PLAYER_ORDER:
            player = match.players.get(key)
            if player is None:
                match.players[key] = Player(
                    user_id=user_id,
                    chat_id=chat_id,
                    name=name.strip() or f"Игрок {key}",
                    color=key,
                )
                if all(match.players.get(player_key) for player_key in PLAYER_ORDER):
                    match.status = "playing"
                    try:
                        primary = match.order[0]
                        match.turn_idx = match.order.index(primary)
                    except (IndexError, ValueError):
                        match.turn_idx = 0
                    append_snapshot(match)
                else:
                    save_match(match)
                return match
        return None


def append_snapshot(
    match: Match15,
    snapshot: Snapshot15 | None = None,
    *,
    expected_changes: Iterable[tuple[int, int]] | None = None,
) -> Snapshot15:
    previous = match.snapshots[-1] if getattr(match, "snapshots", []) else None
    snap = snapshot or match.create_snapshot()
    if previous is not None and previous is not snap:
        changed = _changed_cells(previous, snap)
        allowed = set(expected_changes or [])
        allowed.update(_fresh_cells(previous))
        unexpected = changed - allowed
        if unexpected:
            raise SnapshotDiffError(
                "Snapshot diff has unexpected cells",
                {
                    "match_id": match.match_id,
                    "unexpected": sorted(unexpected),
                    "allowed": sorted(allowed),
                },
            )
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{match.match_id}.jsonl"
    record = snap.to_record()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    save_match(match)
    return snap


__all__ = [
    "append_snapshot",
    "create_match",
    "delete_match",
    "find_match_by_user",
    "get_match",
    "join_match",
    "list_matches",
    "save_match",
    "SnapshotDiffError",
]
