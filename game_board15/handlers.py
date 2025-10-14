"""Handlers and helpers for the 15×15 mode."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.commands import (
    ADMIN_ID,
    NAME_HINT_BOARD15,
    get_player_name,
    set_waiting_for_name,
)

from . import storage
from .battle import HIT, KILL, MISS, advance_turn, apply_shot
from .models import Match15, Player, PLAYER_ORDER
from .render import render_board
from .router import STATE_KEY
from . import router

logger = logging.getLogger(__name__)

PENDING_BOARD15_CREATE = "board15_create"
PENDING_BOARD15_TEST = "board15_test"


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
                    color=key,
                )
        match.status = "playing"
        storage.append_snapshot(match)
        await message.reply_text(
            "Тестовый матч 15×15 создан. Боты будут ходить автоматически."
        )
        await _auto_play_bots(context, match, "A", delay=3.0)
        logger.info("MATCH3_TEST_CREATE | match_id=%s owner=%s", match.match_id, user.id)
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Получить ссылку-приглашение",
                        callback_data="b15_get_link",
                    )
                ]
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
    human_key: str,
    *,
    delay: float = 3.0,
) -> None:
    logger = logging.getLogger(__name__)
    router_ref = router

    async def _safe_send_state(player_key: str, message: str) -> None:
        try:
            await router_ref._send_state(context, match, player_key, message)
        except Exception:
            logger.exception("Failed to render board15 state for player %s", player_key)
            player = match.players.get(player_key)
            if player:
                if player_key == human_key:
                    suffix = " для вашего чата"
                else:
                    suffix = f" для игрока {human_key}"
                await context.bot.send_message(
                    player.chat_id,
                    "Не удалось отправить обновление. Попробуйте позже." + suffix,
                )

    match_ref = match
    rng = random.Random(match_ref.match_id)

    async def _send_initial(match_obj: Match15) -> None:
        player = match_obj.players.get(human_key)
        if player and getattr(player, "chat_id", 0):
            await _safe_send_state(
                human_key, "Игра готова. Сделайте ход, отправив координату."
            )

    def _pick_coord(active_match: Match15, shooter: str) -> tuple[int, int] | None:
        field = router_ref._ensure_field(active_match)
        coords = [(r, c) for r in range(15) for c in range(15)]
        rng.shuffle(coords)
        for coord in coords:
            owner = field.owner_at(coord)
            if owner == shooter:
                continue
            state = field.state_at(coord)
            if state in (2, 3, 4, 5):
                continue
            return coord
        return None

    async def _loop() -> None:
        nonlocal match_ref
        try:
            while True:
                refreshed = storage.get_match(match_ref.match_id)
                if refreshed is None:
                    break
                match_ref = refreshed
                if match_ref.status != "playing":
                    break
                player = match_ref.players.get(human_key)
                if not player or not getattr(player, "chat_id", 0):
                    break

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
                if current == human_key:
                    await asyncio.sleep(0.5)
                    continue
                if match_ref.alive_cells.get(current, 0) <= 0:
                    match_ref.next_turn()
                    storage.save_match(match_ref)
                    await asyncio.sleep(0)
                    continue

                await asyncio.sleep(delay)
                coord = _pick_coord(match_ref, current)
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

                shots = match_ref.shots.setdefault(current, {})
                shots.setdefault("history", []).append(coord)
                shots["last_result"] = shot_result.result
                shots["last_coord"] = coord

                player_keys = list(getattr(match_ref, "players", {}).keys())
                for key in player_keys:
                    entry = match_ref.shots.setdefault(key, {})
                    entry.setdefault("move_count", 0)
                    entry.setdefault("joke_start", random.randint(1, 10))

                for key in player_keys:
                    entry = match_ref.shots.setdefault(key, {})
                    entry["move_count"] = entry.get("move_count", 0) + 1

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
                    phrase_self = router_ref._phrase_or_joke(
                        match_ref, current, router.SELF_HIT
                    ).strip()
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — Ранил.",
                        phrase_self,
                        next_line_default,
                    )
                    for other_key, _player in router_ref._iter_real_players(match_ref):
                        if other_key == current:
                            continue
                        humor_enemy = router_ref._phrase_or_joke(
                            match_ref, other_key, router.ENEMY_HIT
                        ).strip()
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            f"Ход игрока {player_label}: {coord_text} — Соперник ранил ваш корабль.",
                            humor_enemy,
                            next_line_default,
                        )
                elif shot_result.result == KILL:
                    phrase_self = router_ref._phrase_or_joke(
                        match_ref, current, router.SELF_KILL
                    ).strip()
                    if outcome.finished and outcome.winner == current:
                        next_line_self = "Вы победили!🏆"
                    else:
                        next_line_self = next_line_default
                    message_self = router_ref._compose_move_message(
                        f"Ваш ход: {coord_text} — Корабль соперника уничтожен!",
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
                        enemy_messages[other_key] = router_ref._compose_move_message(
                            f"Ход игрока {player_label}: {coord_text} — Соперник уничтожил ваш корабль.",
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
    "send_board15_invite_link",
]
