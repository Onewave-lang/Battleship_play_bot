from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes

import storage


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].startswith('inv_'):
        match_id = context.args[0][4:]
        match = storage.join_match(match_id, update.effective_user.id, update.effective_chat.id)
        if match:
            await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки кораблей.')
        else:
            await update.message.reply_text('Не удалось присоединиться к матчу.')
    else:
        await update.message.reply_text('Привет! Используйте /newgame чтобы создать матч.')


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    match = storage.create_match(update.effective_user.id, update.effective_chat.id)
    username = (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=inv_{match.match_id}"
    await update.message.reply_text(f"Пригласите друга: {link}")
    await update.message.reply_text('Отправьте "авто" для расстановки кораблей.')
