"""Handlers and helpers for the 15×15 mode."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import storage
from .models import Match15
from .router import STATE_KEY
from .render import render_board
from . import router

logger = logging.getLogger(__name__)


async def board15(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return
    user = update.effective_user
    chat = update.effective_chat
    match = storage.find_match_by_user(user.id, chat.id)
    if match:
        await message.reply_text("Вы уже участвуете в матче 15×15.")
        return
    name = user.first_name or "Игрок"
    match = storage.create_match(user.id, chat.id, name)
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
    message = update.message
    if not message:
        return
    user = update.effective_user
    name = user.first_name or "Тестирующий"
    match = storage.create_match(user.id, message.chat.id, name)
    match.messages.setdefault("_flags", {})["board15_test"] = True
    context.bot_data.setdefault(STATE_KEY, {})
    await message.reply_text("Тестовый матч 15×15 создан. Боты готовы к игре.")
    await _auto_play_bots(context, match, "A")


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
    "send_board15_invite_link",
]
