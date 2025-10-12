from __future__ import annotations
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from types import SimpleNamespace

import logging
from pathlib import Path
from io import BytesIO
from contextlib import contextmanager
import base64
from urllib.parse import quote_plus
import os

import storage
from logic.render import render_board_own, render_board_enemy
from .board_test import board_test_two


logger = logging.getLogger(__name__)

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / '48E5E3DF-C5DF-4DE3-B301-EFA71844B5CF.png'
_WELCOME_PLACEHOLDER = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADUlEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='
)

BOARD15_TEST_ENABLED = os.getenv("BOARD15_TEST_ENABLED") == "1"
_ADMIN_ID_RAW = os.getenv("ADMIN_ID")
try:
    ADMIN_ID = int(_ADMIN_ID_RAW) if _ADMIN_ID_RAW is not None else None
except (TypeError, ValueError):
    logger.warning("Invalid ADMIN_ID provided: %s", _ADMIN_ID_RAW)
    ADMIN_ID = None


@contextmanager
def welcome_photo():
    if WELCOME_IMAGE.exists():
        with WELCOME_IMAGE.open('rb') as img:
            yield img
    else:
        yield BytesIO(_WELCOME_PLACEHOLDER)


NAME_KEY = "player_name"
NAME_STATE_KEY = "name_state"
NAME_HINT_NEWGAME = "newgame"
NAME_HINT_AUTO = "auto"
NAME_HINT_BOARD15 = "board15"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    data = getattr(context, "user_data", None)
    if data is None:
        data = {}
        setattr(context, "user_data", data)
    return data


def get_player_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return _user_data(context).get(NAME_KEY, "")


def _name_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return _user_data(context).setdefault(NAME_STATE_KEY, {})


def set_waiting_for_name(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    hint: str,
    pending: dict | None = None,
) -> None:
    state = _name_state(context)
    state["waiting"] = True
    state["hint"] = hint
    if pending is not None:
        state["pending"] = pending
    else:
        state.pop("pending", None)


def is_waiting_for_name(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(_name_state(context).get("waiting"))


def get_name_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return _name_state(context)


def store_player_name(context: ContextTypes.DEFAULT_TYPE, name: str) -> str:
    cleaned = name.strip()
    data = _user_data(context)
    data[NAME_KEY] = cleaned
    state = _name_state(context)
    state["waiting"] = False
    state.pop("pending", None)
    state.pop("hint", None)
    return cleaned


async def _send_join_success(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    reply_photo,
    reply_text,
) -> None:
    with welcome_photo() as img:
        await reply_photo(img, caption='Добро пожаловать в игру!')
    await reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки кораблей.')
    await reply_text('Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.')

    initiator = match.players.get('A')
    joiner = match.players.get('B')
    if not initiator or not joiner:
        return

    joiner_name = joiner.name or 'Соперник'
    msg_a = f'Игрок {joiner_name} присоединился. '
    if initiator.ready:
        msg_a += 'Ожидаем его расстановку.'
    else:
        msg_a += 'Отправьте "авто" для расстановки кораблей.'
    await context.bot.send_message(initiator.chat_id, msg_a)
    if 'Отправьте "авто"' in msg_a:
        await context.bot.send_message(
            initiator.chat_id,
            'Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
        )


async def finalize_pending_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    match_id: str,
) -> bool:
    name = get_player_name(context)
    match = storage.join_match(
        match_id,
        update.effective_user.id,
        update.effective_chat.id,
        name,
    )
    if match:
        await _send_join_success(
            context,
            match,
            update.message.reply_photo,
            update.message.reply_text,
        )
        return True
    await update.message.reply_text('Матч не найден или заполнен.')
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    logger.info(
        '/start called: user_id=%s args=%s',
        update.effective_user.id,
        args,
    )
    if args and args[0].startswith('inv_'):
        match_id = args[0][4:]
        existing = storage.find_match_by_user(update.effective_user.id)
        if existing and existing.match_id != match_id:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('Да', callback_data=f'join_yes|{existing.match_id}|{match_id}'),
                    InlineKeyboardButton('Нет', callback_data='join_no'),
                ]
            ])
            await update.message.reply_text(
                'У вас уже есть незавершенный матч. Завершить его и присоединиться к новому?',
                reply_markup=keyboard,
            )
            return
        name = get_player_name(context)
        if not name:
            set_waiting_for_name(
                context,
                hint=NAME_HINT_AUTO,
                pending={"action": "join", "match_id": match_id},
            )
            await update.message.reply_text(
                'Перед присоединением к матчу напишите, как вас представить сопернику.'
            )
            await update.message.reply_text('Введите имя одним сообщением (например: Иван).')
            return
        match = storage.join_match(
            match_id,
            update.effective_user.id,
            update.effective_chat.id,
            name,
        )
        if match:
            await _send_join_success(
                context,
                match,
                update.message.reply_photo,
                update.message.reply_text,
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
        name = getattr(update.effective_user, 'first_name', '') or ''
        match = storage15.join_match(match_id, update.effective_user.id, update.effective_chat.id, name)
        if match:
            with welcome_photo() as img:
                await update.message.reply_photo(img, caption='Добро пожаловать в игру!')
            await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки.')
            await update.message.reply_text('Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.')
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
                        'Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
                    )
        else:
            await update.message.reply_text('Матч не найден или заполнен.')
    else:
        with welcome_photo() as img:
            await update.message.reply_photo(img, caption='Добро пожаловать в игру!')
        buttons = [
            [
                InlineKeyboardButton('Игра вдвоем', callback_data='mode_2'),
                InlineKeyboardButton('Игра втроем', callback_data='mode_3'),
            ]
        ]
        if ADMIN_ID is not None and update.effective_user and update.effective_user.id == ADMIN_ID:
            buttons.append([InlineKeyboardButton('Тест 2 игроков', callback_data='mode_test2')])
            if BOARD15_TEST_ENABLED:
                buttons.append([InlineKeyboardButton('Тест 3 игроков', callback_data='mode_test3')])
        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text('Выберите режим игры:', reply_markup=keyboard)


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    logger.info(
        '/newgame called: user_id=%s args=%s',
        update.effective_user.id,
        args,
    )
    name = get_player_name(context)
    state = get_name_state(context)
    if not name:
        if state.get('waiting'):
            await update.message.reply_text('Сначала напишите ваше имя и отправьте его одним сообщением.')
        else:
            set_waiting_for_name(
                context,
                hint=NAME_HINT_NEWGAME,
                pending=None,
            )
            await update.message.reply_text(
                'Перед созданием матча напишите, как вас представить сопернику.'
            )
            await update.message.reply_text('Введите имя одним сообщением (например: Иван).')
        return
    existing = storage.find_match_by_user(update.effective_user.id)
    if existing:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton('Да', callback_data=f'ng_yes|{existing.match_id}'),
                InlineKeyboardButton('Нет', callback_data='ng_no'),
            ]
        ])
        await update.message.reply_text(
            'У вас уже есть незавершенный матч. Завершить его и начать новый?',
            reply_markup=keyboard,
        )
        return
    await update.message.reply_text('Подождите, подготавливаем игровую среду...')
    match = storage.create_match(
        update.effective_user.id,
        update.effective_chat.id,
        name,
    )
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


async def confirm_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation to terminate existing match and start a new one."""
    query = update.callback_query
    await query.answer()
    if query.data.startswith('ng_yes|'):
        old_id = query.data.split('|', 1)[1]
        old_match = storage.get_match(old_id)
        if old_match:
            storage.close_match(old_match)
        new_update = SimpleNamespace(
            message=query.message,
            effective_user=query.from_user,
            effective_chat=query.message.chat,
        )
        await newgame(new_update, context)
    else:
        await query.message.reply_text('Вы остались в текущем матче.')


async def confirm_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation to leave previous match and join a new one."""
    query = update.callback_query
    await query.answer()
    if query.data.startswith('join_yes|'):
        _, old_id, new_id = query.data.split('|', 2)
        old_match = storage.get_match(old_id)
        if old_match:
            storage.close_match(old_match)
        name = get_player_name(context)
        if not name:
            set_waiting_for_name(
                context,
                hint=NAME_HINT_AUTO,
                pending={"action": "join", "match_id": new_id},
            )
            await query.message.reply_text(
                'Перед присоединением к новому матчу напишите, как вас представить сопернику.'
            )
            await query.message.reply_text('Введите имя одним сообщением (например: Иван).')
            return
        match = storage.join_match(
            new_id,
            query.from_user.id,
            query.message.chat.id,
            name,
        )
        if match:
            await _send_join_success(
                context,
                match,
                query.message.reply_photo,
                query.message.reply_text,
            )
        else:
            await query.message.reply_text('Матч не найден или заполнен.')
    else:
        await query.message.reply_text('Вы остались в текущем матче.')


async def send_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send invitation link to the match creator."""
    query = update.callback_query
    await query.answer()
    match = storage.find_match_by_user(query.from_user.id, update.effective_chat.id)
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
    match = storage.find_match_by_user(update.effective_user.id, update.effective_chat.id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return
    player_key = 'A' if match.players['A'].user_id == update.effective_user.id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'
    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    await update.message.reply_text(
        f"Поле соперника:\n{enemy}\nВаше поле:\n{own}",
        parse_mode='HTML',
    )


async def quit_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Close the current match for the issuing user."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    match = storage.find_match_by_user(user_id, chat_id)
    if not match and os.getenv("BOARD15_ENABLED") == "1":
        from game_board15 import storage as storage15  # type: ignore
        match15 = storage15.find_match_by_user(user_id, chat_id)
        if match15:
            quitter = next((k for k, p in match15.players.items() if p.user_id == user_id), None)
            match15.status = 'finished'
            storage15.save_match(match15)
            for key, player in match15.players.items():
                if player.user_id == 0:
                    continue
                if key == quitter:
                    await update.message.reply_text('Матч завершен.')
                else:
                    await context.bot.send_message(player.chat_id, 'Соперник завершил матч.')
            return
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return
    player_key = 'A' if match.players['A'].user_id == user_id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'
    await update.message.reply_text('Матч завершен.')
    if enemy_key in match.players:
        await context.bot.send_message(match.players[enemy_key].chat_id, 'Соперник завершил матч.')
    storage.close_match(match)


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle game mode selection from start menu."""
    query = update.callback_query
    await query.answer()
    if query.data == 'mode_2':
        name = get_player_name(context)
        if name:
            await query.message.reply_text(
                'Используйте /newgame чтобы создать матч. '
                'Если вы переходили по ссылке-приглашению, отправьте её текст '
                'вручную: /start inv_<id>.'
            )
        else:
            set_waiting_for_name(
                context,
                hint=NAME_HINT_NEWGAME,
                pending=None,
            )
            await query.message.reply_text(
                'Перед началом игры напишите, как вас представить сопернику.'
            )
            await query.message.reply_text('Введите имя одним сообщением (например: Иван).')
    elif query.data == 'mode_3':
        await query.message.reply_text('Используйте /board15 для игры втроем на поле 15×15.')
    elif query.data == 'mode_test2':
        fake_update = SimpleNamespace(
            message=query.message,
            effective_user=query.from_user,
            effective_chat=query.message.chat,
        )
        await board_test_two(fake_update, context)
    elif query.data == 'mode_test3':
        if ADMIN_ID is None or not query.from_user or query.from_user.id != ADMIN_ID:
            logger.info(
                'Unauthorized mode_test3 selection: user_id=%s admin_id=%s',
                getattr(query.from_user, 'id', None),
                ADMIN_ID,
            )
            return
        await query.message.reply_text('Используйте /board15test для тестовой игры втроем.')
