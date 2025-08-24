from __future__ import annotations
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import logging
from pathlib import Path
from io import BytesIO
from contextlib import contextmanager
import base64
from urllib.parse import quote_plus

import storage
from logic.render import render_board_own, render_board_enemy


logger = logging.getLogger(__name__)

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / '48E5E3DF-C5DF-4DE3-B301-EFA71844B5CF.png'
_WELCOME_PLACEHOLDER = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADUlEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='
)


@contextmanager
def welcome_photo():
    if WELCOME_IMAGE.exists():
        with WELCOME_IMAGE.open('rb') as img:
            yield img
    else:
        yield BytesIO(_WELCOME_PLACEHOLDER)


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
            with welcome_photo() as img:
                await update.message.reply_photo(img, caption='Добро пожаловать в игру!')
            await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки кораблей.')
            await update.message.reply_text('Используйте @<ваше сообщение>, чтобы отправить сообщение сопернику.')
            msg_a = 'Соперник присоединился. '
            if match.players['A'].ready:
                msg_a += 'Ожидаем его расстановку.'
            else:
                msg_a += 'Отправьте "авто" для расстановки кораблей.'
            await context.bot.send_message(match.players['A'].chat_id, msg_a)
            if 'Отправьте "авто"' in msg_a:
                await context.bot.send_message(
                    match.players['A'].chat_id,
                    'Используйте @<ваше сообщение>, чтобы отправить сообщение сопернику.',
                )
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
    elif args and args[0].startswith('b15_'):
        match_id = args[0][4:]
        from game_board15 import storage as storage15
        match = storage15.join_match(match_id, update.effective_user.id, update.effective_chat.id)
        if match:
            with welcome_photo() as img:
                await update.message.reply_photo(img, caption='Добро пожаловать в игру!')
            await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки.')
            await update.message.reply_text('Используйте @<буква> <сообщение>, чтобы отправить сообщение сопернику.')
            for key, player in match.players.items():
                if player.user_id == update.effective_user.id:
                    continue
                msg = 'Соперник присоединился. '
                if getattr(player, 'ready', False):
                    msg += 'Ожидаем его расстановку.'
                else:
                    msg += 'Отправьте "авто" для расстановки.'
                await context.bot.send_message(player.chat_id, msg)
                if 'Отправьте "авто"' in msg:
                    await context.bot.send_message(
                        player.chat_id,
                        'Используйте @<буква> <сообщение>, чтобы отправить сообщение сопернику.',
                    )
        else:
            await update.message.reply_text('Матч не найден или заполнен.')
    else:
        await update.message.reply_text(
            'Привет! Используйте /newgame чтобы создать матч. '
            'Если вы переходили по ссылке-приглашению, отправьте её текст '
            'вручную: /start inv_<id>.'
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton('Игра вдвоем', callback_data='mode_2'),
                    InlineKeyboardButton('Игра втроем', callback_data='mode_3'),
                ]
            ]
        )
        await update.message.reply_text('Выберите режим игры:', reply_markup=keyboard)


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
    with welcome_photo() as img:
        await update.message.reply_photo(img, caption='Добро пожаловать в игру!')
    link = f"https://t.me/{username}?start=inv_{match.match_id}"
    share_url = f"https://t.me/share/url?url={quote_plus(link)}"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Из контактов', url=share_url),
                InlineKeyboardButton('Ссылка на игру', callback_data='get_link'),
            ]
        ]
    )
    await update.message.reply_text(
        'Выберите способ приглашения соперника:',
        reply_markup=keyboard,
    )
    await update.message.reply_text('Матч создан. Ожидаем подключения соперника.')


async def send_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send invitation link to the match creator."""
    query = update.callback_query
    await query.answer()
    match = storage.find_match_by_user(query.from_user.id)
    if not match:
        await query.message.reply_text('Матч не найден.')
        return
    username = (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=inv_{match.match_id}"
    await query.message.reply_text(f"Пригласите друга: {link}")


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


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle game mode selection from start menu."""
    query = update.callback_query
    await query.answer()
    if query.data == 'mode_2':
        await query.message.reply_text('Используйте /newgame для классической игры вдвоем.')
    elif query.data == 'mode_3':
        await query.message.reply_text('Используйте /board15 для игры втроем на поле 15×15.')
