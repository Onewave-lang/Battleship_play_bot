from __future__ import annotations
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes
from types import SimpleNamespace

import logging
from pathlib import Path
from io import BytesIO
from contextlib import contextmanager
from urllib.parse import quote_plus
import os

from PIL import Image, ImageDraw, ImageFont

import storage
from logic.render import render_board_own, render_board_enemy
from .board_test import board_test_two
from app.config import BOARD15_ENABLED, BOARD15_TEST_ENABLED


logger = logging.getLogger(__name__)

WELCOME_IMAGE = (
    Path(__file__).resolve().parent.parent / 'assets' / 'images' / 'IMG_6309.jpeg'
)
_WELCOME_PLACEHOLDER_CACHE: bytes | None = None


def _generate_welcome_placeholder() -> bytes:
    global _WELCOME_PLACEHOLDER_CACHE
    if _WELCOME_PLACEHOLDER_CACHE is not None:
        return _WELCOME_PLACEHOLDER_CACHE

    width, height = 640, 360
    background_color = (9, 23, 46)
    panel_color = (16, 53, 96)
    title_color = (255, 255, 255)
    caption_color = (192, 214, 255)

    image = Image.new('RGB', (width, height), color=background_color)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    title = 'Battleship'
    subtitle = 'Добро пожаловать в игру!'
    caption = 'Соберите флот и вступайте в бой.'

    title_bbox = draw.textbbox((0, 0), title, font=font)
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font)
    caption_bbox = draw.textbbox((0, 0), caption, font=font)

    content_height = (
        (title_bbox[3] - title_bbox[1])
        + (subtitle_bbox[3] - subtitle_bbox[1])
        + (caption_bbox[3] - caption_bbox[1])
        + 32
    )
    top = (height - content_height) // 2

    panel_margin_x = 48
    panel_margin_y = max(top - 40, 24)
    draw.rounded_rectangle(
        (
            panel_margin_x,
            panel_margin_y,
            width - panel_margin_x,
            height - panel_margin_y,
        ),
        radius=36,
        fill=panel_color,
    )

    current_y = top
    title_x = (width - (title_bbox[2] - title_bbox[0])) // 2
    draw.text((title_x, current_y), title, fill=title_color, font=font)
    current_y += (title_bbox[3] - title_bbox[1]) + 12

    subtitle_x = (width - (subtitle_bbox[2] - subtitle_bbox[0])) // 2
    draw.text((subtitle_x, current_y), subtitle, fill=title_color, font=font)
    current_y += (subtitle_bbox[3] - subtitle_bbox[1]) + 20

    caption_x = (width - (caption_bbox[2] - caption_bbox[0])) // 2
    draw.text((caption_x, current_y), caption, fill=caption_color, font=font)

    buffer = BytesIO()
    image.save(buffer, format='PNG')
    _WELCOME_PLACEHOLDER_CACHE = buffer.getvalue()
    return _WELCOME_PLACEHOLDER_CACHE

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
            yield InputFile(img, filename=WELCOME_IMAGE.name)
    else:
        yield InputFile(_generate_welcome_placeholder(), filename='welcome.png')


NAME_KEY = "player_name"
NAME_STATE_KEY = "name_state"
NAME_HINT_NEWGAME = "newgame"
NAME_HINT_AUTO = "auto"
NAME_HINT_BOARD15 = "board15"
NAME_PENDING_BOARD15_JOIN = "board15_join"


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


async def finalize_board15_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    match_id: str,
) -> bool:
    from game_board15 import router as router15
    from game_board15 import storage as storage15
    from game_board15.models import PLAYER_ORDER as PLAYER_ORDER15

    name = get_player_name(context)
    match = storage15.join_match(
        match_id,
        update.effective_user.id,
        update.effective_chat.id,
        name,
    )
    if not match:
        return False

    joiner_key = None
    joiner = None
    for key, player in match.players.items():
        if getattr(player, "user_id", None) == update.effective_user.id:
            joiner_key = key
            joiner = player
            break

    joiner_name = (getattr(joiner, "name", "") or name).strip() or "Игрок"

    with welcome_photo() as img:
        await update.message.reply_photo(img, caption='Добро пожаловать в игру!')

    joined_count = sum(
        1 for player in match.players.values() if getattr(player, 'user_id', 0)
    )
    total_required = len(PLAYER_ORDER15)
    waiting_for_more = joined_count < total_required

    joiner_message_parts = [
        'Вы присоединились к матчу 15×15.',
        'Флот расставлен автоматически.',
    ]
    if waiting_for_more:
        joiner_message_parts.append('Ожидайте подключения остальных игроков.')
    else:
        current_turn = getattr(match, "turn", None)
        current_label = router15._player_label(match, current_turn) if current_turn else ''
        if joiner_key and joiner_key == current_turn:
            joiner_message_parts.append('Игра начинается — Ваш ход.')
        elif current_label:
            joiner_message_parts.append(f'Игра начинается — ходит {current_label}.')
        else:
            joiner_message_parts.append('Игра начинается — ждите своего хода.')

    await update.message.reply_text(' '.join(joiner_message_parts))
    await update.message.reply_text(
        'Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.'
    )

    current_turn = getattr(match, "turn", None)
    current_label = router15._player_label(match, current_turn) if current_turn else ''

    for key, player in match.players.items():
        if player.user_id == update.effective_user.id:
            continue
        msg_parts = [
            f'Игрок {joiner_name} присоединился.',
            'Флот расставлен автоматически.',
        ]
        if waiting_for_more:
            msg_parts.append('Ждём остальных игроков.')
        else:
            if key == current_turn:
                msg_parts.append('Игра начинается — Ваш ход.')
            elif current_label:
                msg_parts.append(f'Игра начинается — ходит {current_label}.')
            else:
                msg_parts.append('Игра начинается.')
        msg = ' '.join(msg_parts)
        await context.bot.send_message(player.chat_id, msg)
        await context.bot.send_message(
            player.chat_id,
            'Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
        )

    if not waiting_for_more:
        snapshot = match.snapshots[-1] if getattr(match, "snapshots", []) else None
        for key, player in match.players.items():
            chat_id = getattr(player, "chat_id", 0)
            if not chat_id:
                continue
            if key == current_turn:
                caption = 'Все участники подключены. Ваш ход.'
            elif current_label:
                caption = f'Все участники подключены. Ходит {current_label}.'
            else:
                caption = 'Все участники подключены. Игра начинается.'
            try:
                await router15._send_state(
                    context,
                    match,
                    key,
                    caption,
                    snapshot=snapshot,
                )
            except Exception:
                logger.exception('Failed to send initial board to player %s', key)

    return True


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

        name = get_player_name(context)
        if not name:
            set_waiting_for_name(
                context,
                hint=NAME_HINT_BOARD15,
                pending={"action": NAME_PENDING_BOARD15_JOIN, "match_id": match_id},
            )
            await update.message.reply_text(
                'Перед присоединением к матчу напишите, как вас представить соперникам.'
            )
            await update.message.reply_text('Введите имя одним сообщением (например: Иван).')
            return

        success = await finalize_board15_join(update, context, match_id)
        if not success:
            existing = storage15.get_match(match_id)
            reason = 'match not found'
            msg = 'Матч не найден или заполнен.'
            if existing:
                if any(player.user_id == update.effective_user.id for player in existing.players.values()):
                    reason = 'already joined'
                    msg = 'Вы уже участвуете в этом матче.'
            logger.info(
                'Failed board15 join: match_id=%s user_id=%s reason=%s',
                match_id,
                update.effective_user.id,
                reason,
            )
            await update.message.reply_text(msg)
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
            buttons.append([InlineKeyboardButton('[адм.] Тест 2 игроков', callback_data='mode_test2')])
            if BOARD15_TEST_ENABLED:
                buttons.append([
                    InlineKeyboardButton('[адм.] Тест 3 игроков', callback_data='mode_test3')
                ])
                buttons.append([
                    InlineKeyboardButton(
                        '[адм.] Тест 3 игроков (ускор.)',
                        callback_data='mode_test3_fast',
                    )
                ])
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
    if not match and BOARD15_ENABLED:
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
        from game_board15.handlers import board15_test  # Local import to avoid circular deps.

        message = query.message
        fake_update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=query.from_user,
            effective_chat=getattr(message, 'chat', None),
        )
        await board15_test(fake_update, context)
    elif query.data == 'mode_test3_fast':
        if ADMIN_ID is None or not query.from_user or query.from_user.id != ADMIN_ID:
            logger.info(
                'Unauthorized mode_test3_fast selection: user_id=%s admin_id=%s',
                getattr(query.from_user, 'id', None),
                ADMIN_ID,
            )
            return
        from game_board15.handlers import board15_test_fast  # Local import to avoid circular deps.

        message = query.message
        fake_update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=query.from_user,
            effective_chat=getattr(message, 'chat', None),
        )
        await board15_test_fast(fake_update, context)
