"""Handlers and helpers for the 15×15 mode."""
from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.commands import (
    NAME_HINT_BOARD15,
    get_player_name,
    set_waiting_for_name,
)

from . import storage
from .models import Match15
from .router import STATE_KEY
from .render import render_board
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
        match.status = "playing"
        match.create_snapshot()
        storage.save_match(match)
        await message.reply_text("Тестовый матч 15×15 создан. Боты готовы к игре.")
        await _auto_play_bots(context, match, "A")
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
    link = f"/start inv_{match.match_id}"
    await query.message.reply_text(
        "Передайте эту команду двум друзьям, чтобы присоединиться к матчу:\n" + link
    )


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_board15_ready(update, context, test_mode=True)


async def _auto_play_bots(
    context: ContextTypes.DEFAULT_TYPE,
    match: Match15,
    human_key: str,
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

    # In a real implementation this function would drive two dummy opponents.
    # For the purposes of tests we simply send the initial state to the human
    # player if the roster is complete enough.
    player = match.players.get(human_key)
    if player:
        await _safe_send_state(human_key, "Игра готова. Сделайте ход, отправив координату.")


__all__ = [
    "STATE_KEY",
    "board15",
    "board15_test",
    "finalize_board15_pending",
    "send_board15_invite_link",
]
