from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, List

from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

# =====================================================
# Конфигурация
# =====================================================
USE_SUPABASE = os.getenv("USE_SUPABASE") == "1"
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or ""
SUPABASE_TABLE15 = os.getenv("SUPABASE_TABLE15", "matches15")

# Fallback-файл для локальной отладки
DATA_FILE = Path(os.getenv("DATA15_FILE_PATH", "data15.json"))
_lock = Lock()


# =====================================================
# Вспомогательные утилиты
# =====================================================
def _sb_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    base = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    }
    if extra:
        base.update(extra)
    return base


def _require_supabase():
    if not (SUPABASE_URL and SUPABASE_KEY):
        raise RuntimeError("Supabase credentials are not configured")


# =====================================================
# SUPABASE BACKEND (построчные CRUD)
# =====================================================
def _sb_get_all() -> Dict[str, dict]:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE15}?select=id,payload"
    with httpx.Client(timeout=30) as cl:
        r = cl.get(url, headers=_sb_headers())
        r.raise_for_status()
        rows = r.json()
    return {row["id"]: row["payload"] for row in rows}


def _sb_get_one(match_id: str) -> Optional[dict]:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE15}?id=eq.{match_id}&select=id,payload"
    with httpx.Client(timeout=30) as cl:
        r = cl.get(url, headers=_sb_headers())
        r.raise_for_status()
        rows = r.json()
    if not rows:
        return None
    return rows[0]["payload"]


def _sb_upsert_one(match_id: str, payload: dict) -> None:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE15}?on_conflict=id"
    body = [{"id": match_id, "payload": payload}]
    headers = _sb_headers({"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"})
    with httpx.Client(timeout=30) as cl:
        r = cl.post(url, headers=headers, json=body)
        r.raise_for_status()


def _sb_delete_one(match_id: str) -> None:
    _require_supabase()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE15}?id=eq.{match_id}"
    with httpx.Client(timeout=30) as cl:
        r = cl.delete(url, headers=_sb_headers({"Prefer": "return=representation"}))
        r.raise_for_status()


# =====================================================
# FILE FALLBACK BACKEND (единый словарь в JSON-файле)
# =====================================================
def _file_load_all() -> Dict[str, dict]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            logger.warning("DATA15_FILE is corrupted or empty, returning {}")
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


# =====================================================
# Публичное API (совместимо с прежней логикой)
# =====================================================
def list_matches() -> Dict[str, dict]:
    """Вернёт все матчи 15×15 в виде словаря {match_id: payload}."""
    if USE_SUPABASE:
        try:
            return _sb_get_all()
        except Exception:
            logger.exception("Failed to list matches15 from Supabase; returning {}")
            return {}
    return _file_load_all()


def get_match(match_id: str) -> Optional[dict]:
    """Вернёт payload матча или None."""
    if USE_SUPABASE:
        try:
            return _sb_get_one(match_id)
        except Exception:
            logger.exception("Failed to get match15 from Supabase")
            return None
    return _file_get_one(match_id)


def create_match(match_id: str, payload: dict) -> None:
    """Создаёт/перезаписывает матч 15×15."""
    payload.setdefault("match_id", match_id)
    payload.setdefault("created_at", datetime.utcnow().isoformat())
    payload.setdefault("status", payload.get("status", "active"))
    if USE_SUPABASE:
        _sb_upsert_one(match_id, payload)
        return
    _file_upsert_one(match_id, payload)


def save_match(match_id: str, payload: dict) -> None:
    """Сохраняет изменения матча (upsert)."""
    payload.setdefault("match_id", match_id)
    payload["updated_at"] = datetime.utcnow().isoformat()
    if USE_SUPABASE:
        _sb_upsert_one(match_id, payload)
        return
    _file_upsert_one(match_id, payload)


def delete_match(match_id: str) -> None:
    """Удаляет матч."""
    if USE_SUPABASE:
        _sb_delete_one(match_id)
        return
    _file_delete_one(match_id)


def find_match_by_user(
    user_id: int,
    chat_id: Optional[int] = None,
    active_statuses: Optional[List[str]] = None,
) -> Optional[dict]:
    """
    Находит «последний» (по updated_at/created_at) активный матч пользователя.
    Ожидается структура в payload:
      payload["players"] = {
        "A": {"user_id": 123, "chat_id": 456, ...},
        "B": {"user_id": 999, "chat_id": 456, ...},
      }
    """
    active = set(active_statuses or ["active", "placing", "in_progress", "waiting"])

    matches = list_matches().values()
    if not matches:
        return None

    candidates: List[dict] = []
    for m in matches:
        if m.get("status") not in active:
            continue
        players = (m.get("players") or {}) if isinstance(m.get("players"), dict) else {}
        for p in players.values():
            try:
                if int(p.get("user_id")) == int(user_id):
                    if chat_id is None or int(p.get("chat_id")) == int(chat_id):
                        candidates.append(m)
                        break
            except Exception:
                continue

    if not candidates:
        return None

    def _ts(mm: dict) -> str:
        return mm.get("updated_at") or mm.get("created_at") or "1970-01-01T00:00:00"
    return max(candidates, key=_ts)


# =====================================================
# Удобные обёртки для работы c доской/снапшотами 15×15
# (если где-то в коде ты их вызываешь напрямую)
# =====================================================
def get_board(match_id: str) -> Optional[dict]:
    """
    Возвращает весь payload матча (там обычно и «доска»/board, и прочее состояние).
    Оставлено для совместимости с кодом, где понятие «board» = весь матч.
    """
    return get_match(match_id)


def save_board(match_id: str, payload: dict) -> None:
    """
    Сохраняет payload матча. Синоним save_match для совместимости.
    """
    save_match(match_id, payload)


def get_snapshots(match_id: str) -> List[dict]:
    """
    Возвращает список снапшотов из payload["snapshots"] (если используется).
    """
    m = get_match(match_id)
    if not m:
        return []
    snaps = m.get("snapshots")
    return snaps if isinstance(snaps, list) else []


def append_snapshot(match_id: str, snapshot: dict, limit: Optional[int] = None) -> None:
    """
    Добавляет снапшот в payload["snapshots"]. Можно ограничить длину.
    """
    m = get_match(match_id) or {"match_id": match_id}
    snaps = m.get("snapshots")
    if not isinstance(snaps, list):
        snaps = []
    snaps.append(snapshot)
    if isinstance(limit, int) and limit > 0 and len(snaps) > limit:
        snaps = snaps[-limit:]
    m["snapshots"] = snaps
    save_match(match_id, m)


def clear_snapshots(match_id: str) -> None:
    """Очищает payload["snapshots"]."""
    m = get_match(match_id)
    if not m:
        return
    m["snapshots"] = []
    save_match(match_id, m)
