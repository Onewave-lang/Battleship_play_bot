from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes

import logging

import storage
from logic.render import render_board_own, render_board_enemy


logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    logger.info(
        '/start called: user_id=%s args=%s',
        update.effective_user.id,
        args,
    )
    if args and args[0].startswith('inv_'):
        match_id = args[0][4:]
        match = storage.join_match(match_id, update.effective_user.id, update.effective_chat.id)
        if match:
            await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки кораблей.')
            msg_a = 'Соперник присоединился. '
            if match.players['A'].ready:
                msg_a += 'Ожидаем его расстановку.'
            else:
                msg_a += 'Отправьте "авто" для расстановки кораблей.'
            await context.bot.send_message(match.players['A'].chat_id, msg_a)
        else:
            existing = storage.get_match(match_id)
            reason = 'match not found'
            msg = 'Матч не найден.'
            if existing:
                if 'B' in existing.players:
                    reason = 'already has B'
                    msg = 'В матче уже есть второй игрок.'
                elif existing.players['A'].user_id == update.effective_user.id:
                    reason = 'self-join'
                    msg = 'Вы не можете присоединиться к собственному матчу.'
            logger.info(
                'Failed match join: match_id=%s user_id=%s reason=%s',
                match_id,
                update.effective_user.id,
                reason,
            )
            await update.message.reply_text(msg)
    else:
        await update.message.reply_text(
            'Привет! Используйте /newgame чтобы создать матч. '
            'Если вы переходили по ссылке-приглашению, отправьте её текст '
            'вручную: /start inv_<id>.'
        )


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    logger.info(
        '/newgame called: user_id=%s args=%s',
        update.effective_user.id,
        args,
    )
    await update.message.reply_text('Подождите, подготавливаем игровую среду...')
    match = storage.create_match(update.effective_user.id, update.effective_chat.id)
    username = (await context.bot.get_me()).username
    await update.message.reply_text('Среда игры готова.')
    link = f"https://t.me/{username}?start=inv_{match.match_id}"
    await update.message.reply_text(f"Пригласите друга: {link}")
    await update.message.reply_text('Матч создан. Ожидаем подключения соперника.')


async def board(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    logger.info(
        '/board called: user_id=%s args=%s',
        update.effective_user.id,
        args,
    )
    match = storage.find_match_by_user(update.effective_user.id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return
    player_key = 'A' if match.players['A'].user_id == update.effective_user.id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'
    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    await update.message.reply_text(
        f"Ваше поле:\n{own}\nПоле соперника:\n{enemy}",
        parse_mode='HTML',
    )
