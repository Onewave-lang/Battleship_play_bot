from __future__ import annotations

from telegram import (
    Update,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes
from urllib.parse import quote_plus

from .state import Board15State
from .renderer import render_board, VIEW
from . import storage, parser, battle, placement
from .models import Player
from logic.phrases import (
    ENEMY_HIT,
    ENEMY_KILL,
    ENEMY_MISS,
    SELF_HIT,
    SELF_KILL,
    SELF_MISS,
    random_phrase,
    random_joke,
)
import random

WELCOME_TEXT = 'Выберите способ приглашения соперников:'

STATE_KEY = "board15_state"


def _keyboard() -> InlineKeyboardMarkup:
    arrows = [
        [
            InlineKeyboardButton("◀️", callback_data="b15|mv|-1|0"),
            InlineKeyboardButton("▲", callback_data="b15|mv|0|-1"),
            InlineKeyboardButton("▼", callback_data="b15|mv|0|1"),
            InlineKeyboardButton("▶️", callback_data="b15|mv|1|0"),
        ]
    ]
    matrix = []
    for r in range(VIEW):
        row = []
        for c in range(VIEW):
            row.append(InlineKeyboardButton("·", callback_data=f"b15|pick|{r}|{c}"))
        matrix.append(row)
    actions = [
        [
            InlineKeyboardButton("✅", callback_data="b15|act|confirm"),
            InlineKeyboardButton("↩️", callback_data="b15|act|cancel"),
        ]
    ]
    return InlineKeyboardMarkup(arrows + matrix + actions)


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


async def board15(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    name = getattr(update.effective_user, 'first_name', '') or ''
    if args:
        match_id = args[0]
        match = storage.join_match(match_id, update.effective_user.id, update.effective_chat.id, name)
        if not match:
            await update.message.reply_text('Матч не найден или заполнен.')
            return
        await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки.')
    else:
        match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
        username = (await context.bot.get_me()).username
        link = f"https://t.me/{username}?start=b15_{match.match_id}"
        share_url = f"https://t.me/share/url?url={quote_plus(link)}"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton('Из контактов', url=share_url),
                    InlineKeyboardButton('Ссылка на игру', callback_data='b15_get_link'),
                ]
            ]
        )
        await update.message.reply_text(WELCOME_TEXT, reply_markup=keyboard)
        await update.message.reply_text('Матч создан. Ожидаем подключения соперников.')
    player_key = next(k for k, p in match.players.items() if p.user_id == update.effective_user.id)
    player = match.players[player_key]
    if not getattr(player, 'name', ''):
        player.name = name
        storage.save_match(match)
    state = Board15State(chat_id=update.effective_chat.id)
    state.board = [row[:] for row in match.boards[player_key].grid]
    buf = render_board(state)
    msg = await update.message.reply_photo(buf, reply_markup=_keyboard())
    status = await update.message.reply_text('Выберите клетку или введите ход текстом.')
    state.message_id = msg.message_id
    state.status_message_id = status.message_id
    context.chat_data[STATE_KEY] = state
    match.messages[player_key] = {
        'board': msg.message_id,
        'status': status.message_id,
    }
    storage.save_match(match)


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player match where one user controls all players."""
    name = getattr(update.effective_user, 'first_name', '') or ''
    match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
    match.players['B'] = Player(user_id=update.effective_user.id, chat_id=update.effective_chat.id, name='B')
    match.players['C'] = Player(user_id=update.effective_user.id, chat_id=update.effective_chat.id, name='C')
    match.status = 'playing'
    match.turn = 'A'
    for key in ('A', 'B', 'C'):
        match.players[key].ready = True
        match.boards[key] = placement.random_board()
    storage.save_match(match)
    state = Board15State(chat_id=update.effective_chat.id)
    state.board = [row[:] for row in match.boards['A'].grid]
    buf = render_board(state)
    msg = await update.message.reply_photo(buf, reply_markup=_keyboard())
    status = await update.message.reply_text('Тестовый матч начат. Ход игрока A.')
    state.message_id = msg.message_id
    state.status_message_id = status.message_id
    context.chat_data[STATE_KEY] = state
    match.messages = {
        'A': {'board': msg.message_id, 'status': status.message_id},
        'B': {'board': msg.message_id, 'status': status.message_id},
        'C': {'board': msg.message_id, 'status': status.message_id},
    }
    storage.save_match(match)


async def send_board15_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send invitation link for 15x15 mode."""
    query = update.callback_query
    await query.answer()
    match = storage.find_match_by_user(query.from_user.id)
    if not match:
        await query.message.reply_text('Матч не найден.')
        return
    username = (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=b15_{match.match_id}"
    await query.message.reply_text(f"Пригласите друга: {link}")


async def board15_on_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data.split("|")
    state: Board15State = context.chat_data.get(STATE_KEY)
    if not state:
        await query.answer()
        return
    if data[1] == "mv":
        dx, dy = int(data[2]), int(data[3])
        state.window_left = max(0, min(15 - VIEW, state.window_left + dx))
        state.window_top = max(0, min(15 - VIEW, state.window_top + dy))
    elif data[1] == "pick":
        r, c = int(data[2]), int(data[3])
        state.selected = (state.window_top + r, state.window_left + c)
    elif data[1] == "act" and data[2] == "confirm":
        if state.selected is None:
            await query.answer("Клетка не выбрана")
            return
        match = storage.find_match_by_user(query.from_user.id)
        if not match:
            await query.answer("Матч не найден")
            return
        if all(p.user_id == query.from_user.id for p in match.players.values()):
            player_key = match.turn
            single_user = True
        else:
            single_user = False
            player_key = next(k for k, p in match.players.items() if p.user_id == query.from_user.id)
            if match.turn != player_key:
                await query.answer("Не ваш ход")
                return
        coord = state.selected
        enemies = [k for k in match.players if k != player_key]
        results = {}
        hit_any = False
        for enemy in enemies:
            res = battle.apply_shot(match.boards[enemy], coord)
            results[enemy] = res
            if res in (battle.HIT, battle.KILL):
                hit_any = True
        for k in match.shots:
            shots = match.shots[k]
            shots.setdefault('move_count', 0)
            shots.setdefault('joke_start', random.randint(1, 10))
            shots['move_count'] += 1
        coord_str = parser.format_coord(coord)
        parts_self = []
        next_player = player_key
        for enemy, res in results.items():
            if res == battle.MISS:
                phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
                enemy_name = match.players.get(enemy)
                enemy_label = getattr(enemy_name, 'name', '') or enemy
                parts_self.append(f"{enemy_label}: мимо. {phrase_self}")
                await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - соперник промахнулся. {phrase_enemy}")
            elif res == battle.HIT:
                phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
                enemy_name = match.players.get(enemy)
                enemy_label = getattr(enemy_name, 'name', '') or enemy
                parts_self.append(f"{enemy_label}: ранил. {phrase_self}")
                await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - ваш корабль ранен. {phrase_enemy}")
            elif res == battle.KILL:
                phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
                enemy_name = match.players.get(enemy)
                enemy_label = getattr(enemy_name, 'name', '') or enemy
                parts_self.append(f"{enemy_label}: уничтожен! {phrase_self}")
                await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - ваш корабль уничтожен. {phrase_enemy}")
                if match.boards[enemy].alive_cells == 0:
                    await context.bot.send_message(match.players[enemy].chat_id, 'Все ваши корабли уничтожены. Вы выбыли.')
        if not hit_any:
            order = [k for k in ('A', 'B', 'C') if k in match.players and match.boards[k].alive_cells > 0]
            idx = order.index(player_key)
            next_player = order[(idx + 1) % len(order)]
            match.turn = next_player
            await context.bot.send_message(match.players[next_player].chat_id, 'Ваш ход.')
        else:
            match.turn = player_key
        storage.save_match(match)
        next_label = match.players.get(next_player)
        next_name = getattr(next_label, 'name', '') or next_player
        result_self = f"{coord_str} - {' '.join(parts_self)}" + (' Ваш ход.' if match.turn == player_key else f" Ход {next_name}.")
        msg_ids = match.messages.get(player_key, {})
        status_id = msg_ids.get('status')
        if status_id:
            try:
                await context.bot.edit_message_text(
                    result_self,
                    chat_id=state.chat_id,
                    message_id=status_id,
                )
            except Exception:
                status_msg = await context.bot.send_message(state.chat_id, result_self)
                msg_ids['status'] = status_msg.message_id
                storage.save_match(match)
            else:
                state.status_message_id = status_id
        else:
            status_msg = await context.bot.send_message(state.chat_id, result_self)
            msg_ids['status'] = status_msg.message_id
            state.status_message_id = status_msg.message_id
            storage.save_match(match)
        view_key = match.turn if single_user else player_key
        state.board = [row[:] for row in match.boards[view_key].grid]
        state.selected = None
        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
        if len(alive_players) == 1:
            winner = alive_players[0]
            storage.finish(match, winner)
            await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
            for k in match.players:
                if k != winner:
                    await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
    elif data[1] == "act" and data[2] == "cancel":
        state.selected = None
    buf = render_board(state)
    try:
        await query.edit_message_media(InputMediaPhoto(buf))
    except Exception:
        pass
    await query.edit_message_reply_markup(_keyboard())
    await query.answer()
