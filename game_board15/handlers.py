"""Handlers and helpers for the 15×15 mode."""
from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import quote_plus
from typing import Dict, Iterable, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.commands import (
    ADMIN_ID,
    NAME_HINT_BOARD15,
    get_player_name,
    set_waiting_for_name,
)

from . import storage
from .battle import HIT, KILL, MISS, ShotResult, advance_turn, apply_shot
from .models import Field15, Match15, Player, PLAYER_ORDER
from .render import render_board
from .router import STATE_KEY
from . import router

logger = logging.getLogger(__name__)

PENDING_BOARD15_CREATE = "board15_create"
PENDING_BOARD15_TEST = "board15_test"

Coord = Tuple[int, int]
BOARD_SIZE = 15


def _normalize_coord_value(value: object) -> Optional[Coord]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _is_adjacent(a: Coord, b: Coord) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def _orthogonal_neighbors(coord: Coord) -> List[Coord]:
    r, c = coord
    neighbours: List[Coord] = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
            neighbours.append((nr, nc))
    return neighbours


def _normalize_target_hits(entry: Dict[str, object], field: Field15) -> List[Coord]:
    raw_hits = entry.get("target_hits") or []
    normalized: List[Coord] = []
    seen: set[Coord] = set()
    for item in raw_hits:
        coord = _normalize_coord_value(item)
        if coord is None or coord in seen:
            continue
        if field.state_at(coord) == 3:
            normalized.append(coord)
            seen.add(coord)
    entry["target_hits"] = normalized
    if not normalized:
        entry["target_owner"] = None
    return normalized


def _is_available_target(field: Field15, shooter: str, coord: Coord) -> bool:
    owner = field.owner_at(coord)
    if owner == shooter:
        return False
    state = field.state_at(coord)
    return state not in (2, 3, 4, 5)


def _collect_line_candidates(
    field: Field15,
    shooter: str,
    hits: List[Coord],
) -> List[Coord]:
    if not hits:
        return []
    rows = {r for r, _ in hits}
    cols = {c for _, c in hits}
    candidates: List[Coord] = []
    seen: set[Coord] = set()
    if len(rows) == 1:
        ordered = sorted(hits, key=lambda item: item[1])
        endpoints = [ordered[0], ordered[-1]]
        for r, c in endpoints:
            for delta in (-1, 1):
                candidate = (r, c + delta)
                if candidate in seen:
                    continue
                seen.add(candidate)
                if _is_available_target(field, shooter, candidate):
                    candidates.append(candidate)
    elif len(cols) == 1:
        ordered = sorted(hits, key=lambda item: item[0])
        endpoints = [ordered[0], ordered[-1]]
        for r, c in endpoints:
            for delta in (-1, 1):
                candidate = (r + delta, c)
                if candidate in seen:
                    continue
                seen.add(candidate)
                if _is_available_target(field, shooter, candidate):
                    candidates.append(candidate)
    return candidates


def _collect_neighbor_candidates(
    field: Field15,
    shooter: str,
    hits: List[Coord],
) -> List[Coord]:
    candidates: List[Coord] = []
    seen: set[Coord] = set()
    for hit in hits:
        for candidate in _orthogonal_neighbors(hit):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _is_available_target(field, shooter, candidate):
                candidates.append(candidate)
    return candidates


def _choose_bot_target(
    field: Field15,
    shooter: str,
    entry: Dict[str, object],
    rng: random.Random,
) -> Optional[Coord]:
    hits = _normalize_target_hits(entry, field)
    if hits:
        if len(hits) == 1:
            neighbors = _collect_neighbor_candidates(field, shooter, hits)
            if neighbors:
                rng.shuffle(neighbors)
                return neighbors[0]
        else:
            line_candidates = _collect_line_candidates(field, shooter, hits)
            if line_candidates:
                rng.shuffle(line_candidates)
                return line_candidates[0]
            neighbors = _collect_neighbor_candidates(field, shooter, hits)
            if neighbors:
                rng.shuffle(neighbors)
                return neighbors[0]

    coords = [(r, c) for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)]
    rng.shuffle(coords)
    for coord in coords:
        if _is_available_target(field, shooter, coord):
            return coord
    return None


def _update_bot_target_state(
    match: Match15,
    shooter: str,
    result: ShotResult,
) -> None:
    entry = match.shots.setdefault(shooter, {})
    hits_raw = entry.get("target_hits") or []
    normalized_hits: List[Coord] = []
    seen: set[Coord] = set()
    for item in hits_raw:
        coord = _normalize_coord_value(item)
        if coord is None or coord in seen:
            continue
        normalized_hits.append(coord)
        seen.add(coord)

    if result.result == KILL:
        entry["target_hits"] = []
        entry["target_owner"] = None
        return

    if result.result != HIT:
        entry["target_hits"] = normalized_hits
        if not normalized_hits:
            entry["target_owner"] = None
        return

    coord = result.coord
    owner = result.owner
    if owner is None:
        entry["target_hits"] = normalized_hits
        if not normalized_hits:
            entry["target_owner"] = None
        return

    if entry.get("target_owner") not in (None, owner):
        normalized_hits = []

    if normalized_hits and not any(_is_adjacent(hit, coord) for hit in normalized_hits):
        normalized_hits = []

    if coord not in normalized_hits:
        normalized_hits.append(coord)

    entry["target_hits"] = normalized_hits
    entry["target_owner"] = owner


async def _prompt_for_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pending_action: str,
) -> None:
    message = update.message
    if not message:
        return
    set_waiting_for_name(
        context,
        hint=NAME_HINT_BOARD15,
        pending={"action": pending_action},
    )
    await message.reply_text(
        "Перед созданием матча напишите, как вас представить соперникам."
    )
    await message.reply_text(
        "Введите имя одним сообщением (например: Иван)."
    )


async def _create_board15_match(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    test_mode: bool = False,
) -> Optional[Match15]:
    message = update.message
    if not message:
        return None
    user = update.effective_user
    chat = update.effective_chat

    existing = storage.find_match_by_user(user.id, chat.id)
    if existing:
        await message.reply_text("Вы уже участвуете в матче 15×15.")
        return existing

    name = get_player_name(context)
    if not name:
        # Should not happen because we prompt beforehand, but guard just in case.
        await _prompt_for_name(
            update,
            context,
            pending_action=PENDING_BOARD15_TEST if test_mode else PENDING_BOARD15_CREATE,
        )
        return None

    match = storage.create_match(user.id, chat.id, name)

    if test_mode:
        match.messages.setdefault("_flags", {})["board15_test"] = True
        context.bot_data.setdefault(STATE_KEY, {})
        for key in PLAYER_ORDER:
            if key == "A":
                continue
            if key not in match.players:
                match.players[key] = Player(
                    user_id=0,
                    chat_id=0,
                    name=f"Бот {key}",
                    color=match.color_map.get(key, key),
                )
        match.status = "playing"
        storage.append_snapshot(match)
        await message.reply_text(
            "Тестовый матч 15×15 создан. Боты будут ходить автоматически."
        )
        await _auto_play_bots(context, match, "A", delay=3.0)
        logger.info("MATCH3_TEST_CREATE | match_id=%s owner=%s", match.match_id, user.id)
    else:
        bot_username = getattr(await context.bot.get_me(), "username", None)
        if bot_username:
            deep_link = f"https://t.me/{bot_username}?start=b15_{match.match_id}"
            share_url = f"https://t.me/share/url?url={quote_plus(deep_link)}"
        else:
            deep_link = f"/start b15_{match.match_id}"
            share_url = f"https://t.me/share/url?text={quote_plus(deep_link)}"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Из контактов",
                        url=share_url,
                    ),
                    InlineKeyboardButton(
                        "Ссылка на игру",
                        callback_data="b15_get_link",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Пригласить соперник-бота",
                        callback_data="b15_add_bot",
                    )
                ],
            ]
        )
        await message.reply_text(
            "Матч создан. Пригласите ещё двух игроков по ссылке.",
            reply_markup=keyboard,
        )
        logger.info("MATCH3_CREATE | match_id=%s owner=%s", match.match_id, user.id)
    return match


async def _ensure_board15_ready(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    test_mode: bool = False,
) -> Optional[Match15]:
    name = get_player_name(context)
    if not name:
        await _prompt_for_name(
            update,
            context,
            pending_action=PENDING_BOARD15_TEST if test_mode else PENDING_BOARD15_CREATE,
        )
        return None
    return await _create_board15_match(update, context, test_mode=test_mode)


async def finalize_board15_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict,
) -> bool:
    action = pending.get("action")
    test_mode = action == PENDING_BOARD15_TEST
    match = await _create_board15_match(update, context, test_mode=test_mode)
    return match is not None


async def board15(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_board15_ready(update, context)


async def send_board15_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat = query.message.chat
    match = storage.find_match_by_user(user.id, chat.id)
    if not match:
        await query.message.reply_text("Матч не найден.")
        return
    bot_username = getattr(await context.bot.get_me(), "username", None)
    deep_link: str
    if bot_username:
        deep_link = f"https://t.me/{bot_username}?start=b15_{match.match_id}"
    else:
        deep_link = f"/start b15_{match.match_id}"
    message = (
        "Передайте эту ссылку двум друзьям, чтобы присоединиться к матчу:\n"
        f"{deep_link}"
    )
    if bot_username:
        message += (
            "\nЕсли нужно поделиться текстом вручную, отправьте: "
            f"/start b15_{match.match_id}"
        )
    await query.message.reply_text(message)


async def add_board15_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    message = query.message
    if not message:
        return

    user = query.from_user
    chat = getattr(message, "chat", None)
    match = storage.find_match_by_user(user.id, getattr(chat, "id", None))
    if not match:
        await message.reply_text("Матч не найден.")
        return

    owner = match.players.get("A")
    if not owner or owner.user_id != user.id:
        await message.reply_text("Пригласить бота может только создатель матча.")
        return

    human_players = [
        key
        for key, player in match.players.items()
        if getattr(player, "chat_id", 0)
    ]
    if len(human_players) < 2:
        await message.reply_text("Дождитесь подключения второго игрока перед приглашением бота.")
        return

    available_slot = next((key for key in PLAYER_ORDER if key not in match.players), None)
    if available_slot is None:
        if any(player.user_id == 0 for player in match.players.values()):
            await message.reply_text("Бот уже участвует в матче.")
        else:
            await message.reply_text("Все места уже заняты.")
        return

    match.players[available_slot] = Player(
        user_id=0,
        chat_id=0,
        name=f"Бот {available_slot}",
        color=match.color_map.get(available_slot, available_slot),
    )
    match.status = "playing"
    if not hasattr(match, "order") or not match.order:
        match.order = list(PLAYER_ORDER)
    try:
        primary = match.order[0]
        match.turn_idx = match.order.index(primary)
    except (IndexError, ValueError):
        match.turn_idx = 0

    flags = match.messages.setdefault("_flags", {})
    flags["board15_bot"] = True

    storage.append_snapshot(match)

    label_turn = router._player_label(match, match.turn)
    info_text = (
        "Бот присоединился. "
        + ("Ваш ход." if match.turn == "A" else f"Ходит {label_turn}.")
    )
    await message.reply_text(info_text)

    for key in human_players:
        if key == "A":
            continue
        player = match.players.get(key)
        if not player or not getattr(player, "chat_id", 0):
            continue
        await context.bot.send_message(
            player.chat_id,
            "Бот присоединился к матчу. Игра начинается.",
        )

    if hasattr(message, "edit_reply_markup"):
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug(
                "Failed to clear bot invite keyboard for match %s", match.match_id
            )

    await _auto_play_bots(
        context,
        match,
        human_keys=human_players,
        delay=3.0,
    )


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    user_id = getattr(user, "id", None)
    if ADMIN_ID is None:
        logger.warning("BOARD15TEST invoked without ADMIN_ID configured; access denied")
        if message is not None:
            await message.reply_text("Команда доступна только администратору.")
        return
    if user_id != ADMIN_ID:
        logger.info(
            "Unauthorized board15test usage attempt: user_id=%s admin_id=%s",
            user_id,
            ADMIN_ID,
        )
        if message is not None:
            await message.reply_text("Команда доступна только администратору.")
        return
    await _ensure_board15_ready(update, context, test_mode=True)


async def _auto_play_bots(
    context: ContextTypes.DEFAULT_TYPE,
    match: Match15,
    human_keys: Iterable[str] | str | None = None,
    *,
    delay: float = 3.0,
) -> None:
    logger = logging.getLogger(__name__)
    router_ref = router

    if isinstance(human_keys, str):
        initial_humans = [human_keys]
    elif human_keys is None:
        initial_humans = [
            key
            for key, player in match.players.items()
            if getattr(player, "chat_id", 0)
        ]
    else:
        initial_humans = list(human_keys)

    human_key = initial_humans[0] if initial_humans else None
    async def _safe_send_state(player_key: str, message: str) -> None:
        try:
            await router_ref._send_state(context, match, player_key, message)
        except Exception:
            logger.exception("Failed to render board15 state for player %s", player_key)
            player = match.players.get(player_key)
            if player and getattr(player, "chat_id", 0):
                target = human_key or player_key
                suffix = (
                    " для вашего чата"
                    if player_key == target
                    else f" для игрока {target}"
                )
                await context.bot.send_message(
                    player.chat_id,
                    "Не удалось отправить обновление. Попробуйте позже." + suffix,
                )

    match_ref = match
    rng = random.Random(match_ref.match_id)

    async def _send_initial(match_obj: Match15) -> None:
        nonlocal human_key
        active = [
            key
            for key, player in match_obj.players.items()
            if getattr(player, "chat_id", 0)
        ]
        if not active:
            return
        human_key = active[0]
        current_turn = match_obj.turn
        current_label = router_ref._player_label(match_obj, current_turn)
        for key in active:
            if key == current_turn:
                text = "Игра готова. Сделайте ход, отправив координату."
            else:
                prefix = "Игра начинается. "
                if current_label:
                    text = f"{prefix}Ходит {current_label}. Ждите своего хода."
                else:
                    text = prefix + "Ждите своего хода."
            await _safe_send_state(key, text)

    async def _loop() -> None:
        nonlocal match_ref, human_key
        try:
            while True:
                refreshed = storage.get_match(match_ref.match_id)
                if refreshed is None:
                    break
                match_ref = refreshed
                if match_ref.status != "playing":
                    break

                active_humans = {
                    key
                    for key, player in match_ref.players.items()
                    if getattr(player, "chat_id", 0)
                }
                if not active_humans:
                    break
                human_key = next(iter(active_humans))

                if not isinstance(getattr(match_ref, "alive_cells", None), dict):
                    match_ref.alive_cells = {key: 20 for key in PLAYER_ORDER}
                if not hasattr(match_ref, "order"):
                    match_ref.order = list(PLAYER_ORDER)
                if not hasattr(match_ref, "turn_idx"):
                    match_ref.turn_idx = 0
                if not isinstance(getattr(match_ref, "messages", None), dict):
                    match_ref.messages = {key: {} for key in PLAYER_ORDER}
                if not isinstance(getattr(match_ref, "shots", None), dict):
                    match_ref.shots = {key: {} for key in PLAYER_ORDER}
                router_ref._ensure_history(match_ref)
                field = router_ref._ensure_field(match_ref)
                if not isinstance(getattr(match_ref, "boards", None), dict):
                    match_ref.boards = {key: field for key in PLAYER_ORDER}

                current = match_ref.turn
                if current in active_humans:
                    await asyncio.sleep(0.5)
                    continue
                if match_ref.alive_cells.get(current, 0) <= 0:
                    match_ref.next_turn()
                    storage.save_match(match_ref)
                    await asyncio.sleep(0)
                    continue

                player_keys = list(getattr(match_ref, "players", {}).keys())
                for key in player_keys:
                    entry = match_ref.shots.setdefault(key, {})
                    entry.setdefault("history", [])
                    entry.setdefault("last_result", None)
                    entry.setdefault("last_coord", None)
                    entry.setdefault("move_count", 0)
                    entry.setdefault("joke_start", random.randint(1, 10))
                    if entry.get("target_hits") is None:
                        entry["target_hits"] = []
                    entry.setdefault("target_owner", None)

                await asyncio.sleep(delay)
                shooter_entry = match_ref.shots.setdefault(current, {})
                coord = _choose_bot_target(field, current, shooter_entry, rng)
                if coord is None:
                    match_ref.next_turn()
                    storage.save_match(match_ref)
                    continue

                prev_alive = {
                    key: match_ref.alive_cells.get(key, 0) for key in PLAYER_ORDER
                }

                try:
                    shot_result = apply_shot(match_ref, current, coord)
                except ValueError:
                    logger.debug(
                        "Bot %s attempted invalid shot at %s in match %s",
                        current,
                        coord,
                        match_ref.match_id,
                    )
                    continue

                needs_presave = router_ref._update_history(match_ref, current, shot_result)

                shots = shooter_entry
                shots.setdefault("history", []).append(coord)
                shots["last_result"] = shot_result.result
                shots["last_coord"] = coord

                for key in player_keys:
                    entry = match_ref.shots.setdefault(key, {})
                    entry["move_count"] = entry.get("move_count", 0) + 1

                _update_bot_target_state(match_ref, current, shot_result)

                if needs_presave:
                    storage.save_match(match_ref)

                coord_text = router.format_coord(coord)
                player_label = router_ref._player_label(match_ref, current)

                outcome = advance_turn(
                    match_ref, shot_result, previous_alive=prev_alive
                )
                elimination_order = router_ref._record_eliminations(
                    match_ref, outcome.eliminated
                )

                next_line_default = router_ref._format_next_turn_line(
                    match_ref,
                    outcome.next_turn,
                    finished=outcome.finished,
                )

                enemy_messages: Dict[str, str] = {}

                if shot_result.result == MISS:
                    phrase_self = router_ref._phrase_or_joke(
                        match_ref, current, router.SELF_MISS
                    ).strip()
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — Мимо.",
                        phrase_self,
                        next_line_default,
                    )
                    for other_key, _player in router_ref._iter_real_players(match_ref):
                        if other_key == current:
                            continue
                        humor_enemy = router_ref._phrase_or_joke(
                            match_ref, other_key, router.ENEMY_MISS
                        ).strip()
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            f"Ход игрока {player_label}: {coord_text} — Соперник промахнулся.",
                            humor_enemy,
                            next_line_default,
                        )
                elif shot_result.result == HIT:
                    target_label = (
                        router_ref._player_label(match_ref, shot_result.owner)
                        if shot_result.owner is not None
                        else None
                    )
                    target_phrase = (
                        f"корабль игрока {target_label}"
                        if target_label
                        else "корабль соперника"
                    )
                    phrase_self = router_ref._phrase_or_joke(
                        match_ref, current, router.SELF_HIT
                    ).strip()
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — Ранил {target_phrase}.",
                        phrase_self,
                        next_line_default,
                    )
                    for other_key, _player in router_ref._iter_real_players(match_ref):
                        if other_key == current:
                            continue
                        humor_enemy = router_ref._phrase_or_joke(
                            match_ref, other_key, router.ENEMY_HIT
                        ).strip()
                        if shot_result.owner == other_key:
                            result_line_enemy = (
                                f"Ход игрока {player_label}: {coord_text} — Соперник ранил ваш корабль."
                            )
                        else:
                            result_line_enemy = (
                                f"Ход игрока {player_label}: {coord_text} — Соперник ранил {target_phrase}."
                            )
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            result_line_enemy,
                            humor_enemy,
                            next_line_default,
                        )
                elif shot_result.result == KILL:
                    target_label = (
                        router_ref._player_label(match_ref, shot_result.owner)
                        if shot_result.owner is not None
                        else None
                    )
                    target_phrase_self = (
                        f"Корабль игрока {target_label}"
                        if target_label
                        else "Корабль соперника"
                    )
                    target_phrase_enemy = (
                        f"корабль игрока {target_label}"
                        if target_label
                        else "корабль соперника"
                    )
                    phrase_self = router_ref._phrase_or_joke(
                        match_ref, current, router.SELF_KILL
                    ).strip()
                    if outcome.finished and outcome.winner == current:
                        next_line_self = "Вы победили!🏆"
                    else:
                        next_line_self = next_line_default
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — {target_phrase_self} уничтожен!",
                        phrase_self,
                        next_line_self,
                    )
                    for other_key, _player in router_ref._iter_real_players(match_ref):
                        if other_key == current:
                            continue
                        humor_enemy = router_ref._phrase_or_joke(
                            match_ref, other_key, router.ENEMY_KILL
                        ).strip()
                        if (
                            outcome.finished
                            and outcome.winner == current
                            and shot_result.owner == other_key
                        ):
                            next_line_enemy = (
                                f"Все ваши корабли уничтожены. Игрк {player_label} победил!"
                            )
                        else:
                            next_line_enemy = next_line_default
                        if shot_result.owner == other_key:
                            result_line_enemy = (
                                f"Ход игрока {player_label}: {coord_text} — Соперник уничтожил ваш корабль."
                            )
                        else:
                            result_line_enemy = (
                                f"Ход игрока {player_label}: {coord_text} — Соперник уничтожил {target_phrase_enemy}."
                            )
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            result_line_enemy,
                            humor_enemy,
                            next_line_enemy,
                        )
                else:
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — Ошибка.",
                        None,
                        next_line_default,
                    )
                    for other_key, _player in router_ref._iter_real_players(match_ref):
                        if other_key == current:
                            continue
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            f"Ход игрока {player_label}: {coord_text} — Техническая ошибка.",
                            None,
                            next_line_default,
                        )

                previous_snapshot = (
                    match_ref.snapshots[-1]
                    if getattr(match_ref, "snapshots", [])
                    else None
                )
                expected_cells = router.collect_expected_changes(
                    previous_snapshot,
                    shot_result,
                )
                snapshot = storage.append_snapshot(
                    match_ref,
                    expected_changes=expected_cells,
                )

                shooter = match_ref.players.get(current)
                if shooter and getattr(shooter, "chat_id", 0):
                    try:
                        await router_ref._send_state(
                            context,
                            match_ref,
                            current,
                            message_self,
                            snapshot=snapshot,
                        )
                    except Exception:
                        logger.exception("Failed to notify bot player %s", current)

                for other_key, other_player in router_ref._iter_real_players(match_ref):
                    if other_key == current:
                        continue
                    if match_ref.alive_cells.get(other_key, 0) <= 0:
                        continue
                    message_enemy = enemy_messages.get(other_key)
                    if not message_enemy:
                        continue
                    try:
                        await router_ref._send_state(
                            context,
                            match_ref,
                            other_key,
                            message_enemy,
                            snapshot=snapshot,
                        )
                    except Exception:
                        logger.exception("Failed to notify player %s", other_key)

                for eliminated_key in outcome.eliminated:
                    await router_ref._broadcast_elimination(
                        context, match_ref, eliminated_key
                    )

                if outcome.finished:
                    ranking = router_ref._final_ranking(
                        match_ref, outcome.winner, elimination_order
                    )
                    await router_ref._send_final_summaries(
                        context, match_ref, ranking, outcome.winner
                    )
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Auto-play loop failed for match %s", getattr(match_ref, "match_id", "?")
            )

    await _send_initial(match_ref)
    loop = getattr(context, "application", None)
    task = _loop()
    if loop and hasattr(loop, "create_task"):
        loop.create_task(task)
    else:
        asyncio.create_task(task)
    await asyncio.sleep(0)


__all__ = [
    "STATE_KEY",
    "board15",
    "board15_test",
    "finalize_board15_pending",
    "add_board15_bot",
    "send_board15_invite_link",
]
