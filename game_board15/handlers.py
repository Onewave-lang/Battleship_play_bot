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
)
from .utils import _phrase_or_joke
import random
import asyncio

WELCOME_TEXT = 'Выберите способ приглашения соперников:'

STATE_KEY = "board15_states"


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
    merged = [row[:] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(15):
        for c in range(15):
            if merged[r][c] == 0 and own_grid[r][c] == 1:
                merged[r][c] = 1
    state.board = merged
    state.player_key = player_key
    buf = render_board(state, player_key)
    msg = await update.message.reply_photo(buf, reply_markup=_keyboard())
    status = await update.message.reply_text('Выберите клетку или введите ход текстом.')
    state.message_id = msg.message_id
    state.status_message_id = status.message_id
    context.bot_data.setdefault(STATE_KEY, {})[update.effective_chat.id] = state
    match.messages[player_key] = {
        'board': msg.message_id,
        'status': status.message_id,
    }
    storage.save_match(match)


async def _auto_play_bots(
    match: storage.Match15,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    human: str = 'A',
) -> None:
    """Automatically let bot players make moves until the game ends."""
    coords = [(r, c) for r in range(15) for c in range(15)]
    order = ['A', 'B', 'C']
    from . import router as router_module

    while True:
        alive = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
        if len(alive) == 1:
            winner = alive[0]
            storage.finish(match, winner)
            await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
            for k in match.players:
                if k != winner:
                    await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
            break

        if match.turn == human:
            await asyncio.sleep(0.5)
            continue

        current = match.turn
        # find first untouched cell scanning from the start each time
        coord = None
        for pt in coords:
            r, c = pt
            if (
                match.history[r][c] == 0
                and match.boards[current].grid[r][c] != 1
            ):
                coord = pt
                break
        if coord is None:
            break
        enemies = [k for k in alive if k != current]
        results = {}
        hit_any = False
        for enemy in enemies:
            res = battle.apply_shot(match.boards[enemy], coord)
            results[enemy] = res
            if res in (battle.HIT, battle.KILL):
                hit_any = True
        battle.update_history(match.history, match.boards, coord, results)
        for k in match.shots:
            shots = match.shots[k]
            shots.setdefault('move_count', 0)
            shots.setdefault('joke_start', random.randint(1, 10))
            shots['move_count'] += 1
        coord_str = parser.format_coord(coord)

        if not hit_any:
            alive_order = [k for k in order if k in alive]
            idx_next = alive_order.index(current)
            next_player = alive_order[(idx_next + 1) % len(alive_order)]
        else:
            next_player = current
        match.turn = next_player

        parts_self = []
        for enemy, res in results.items():
            enemy_name = match.players.get(enemy)
            enemy_label = getattr(enemy_name, 'name', '') or enemy
            if res == battle.MISS:
                phrase_self = _phrase_or_joke(match, current, SELF_MISS)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
                parts_self.append(f"{enemy_label}: мимо. {phrase_self}")
                if match.players[enemy].user_id != 0:
                    msg = f"{coord_str} - соперник промахнулся. {phrase_enemy}"
                    if enemy == next_player:
                        msg += ' Ваш ход.'
                    await router_module._send_state(context, match, enemy, msg)
            elif res == battle.HIT:
                phrase_self = _phrase_or_joke(match, current, SELF_HIT)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
                parts_self.append(f"{enemy_label}: ранил. {phrase_self}")
                if match.players[enemy].user_id != 0:
                    await router_module._send_state(
                        context,
                        match,
                        enemy,
                        f"{coord_str} - ваш корабль ранен. {phrase_enemy}",
                    )
            elif res == battle.KILL:
                phrase_self = _phrase_or_joke(match, current, SELF_KILL)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
                parts_self.append(f"{enemy_label}: уничтожен! {phrase_self}")
                if match.players[enemy].user_id != 0:
                    await router_module._send_state(
                        context,
                        match,
                        enemy,
                        f"{coord_str} - ваш корабль уничтожен. {phrase_enemy}",
                    )
                if match.boards[enemy].alive_cells == 0:
                    enemy_label = getattr(match.players.get(enemy), 'name', '') or enemy
                    await context.bot.send_message(
                        match.players[enemy].chat_id,
                        f"⛔ Игрок {enemy_label} выбыл (флот уничтожен)",
                    )

        if current != human and human in match.players and match.players[human].user_id != 0:
            msg_self = f"{coord_str} - {' '.join(parts_self)}"
            if next_player == human:
                msg_self += ' Ваш ход.'
            await router_module._send_state(context, match, human, msg_self)

        storage.save_match(match)
        next_label = match.players.get(next_player)
        next_name = getattr(next_label, 'name', '') or next_player
        result_self = f"{coord_str} - {' '.join(parts_self)}" + (
            ' Ваш ход.' if next_player == current else f" Ход {next_name}."
        )
        if match.players[current].user_id != 0:
            await router_module._send_state(context, match, current, result_self)

        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
        if len(alive_players) == 1:
            winner = alive_players[0]
            storage.finish(match, winner)
            await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
            for k in match.players:
                if k != winner:
                    await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
            break


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player test match with two dummy opponents."""
    name = getattr(update.effective_user, 'first_name', '') or ''
    match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
    match.players['B'] = Player(user_id=0, chat_id=update.effective_chat.id, name='B')
    match.players['C'] = Player(user_id=0, chat_id=update.effective_chat.id, name='C')
    match.status = 'playing'
    match.turn = 'A'
    # place fleets for all players ensuring that ships of different players do
    # not touch each other.  Build a mask of forbidden cells (occupied or
    # adjacent) and update it after each fleet is generated.
    mask = [[0] * 15 for _ in range(15)]
    for key in ('A', 'B', 'C'):
        board = placement.random_board(mask)
        match.players[key].ready = True
        match.boards[key] = board
        for ship in board.ships:
            for r, c in ship.cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < 15 and 0 <= nc < 15:
                            mask[nr][nc] = 1
    storage.save_match(match)
    state = Board15State(chat_id=update.effective_chat.id)
    merged = [row[:] for row in match.history]
    own_grid = match.boards['A'].grid
    for r in range(15):
        for c in range(15):
            if merged[r][c] == 0 and own_grid[r][c] == 1:
                merged[r][c] = 1
    state.board = merged
    state.player_key = 'A'
    try:
        buf = render_board(state, 'A')
    except Exception:
        from io import BytesIO
        buf = BytesIO()
    reply_photo = getattr(update.message, "reply_photo", None)
    board_msg_id = None
    if reply_photo is not None:
        msg = await reply_photo(buf, reply_markup=_keyboard())
        board_msg_id = msg.message_id
    else:
        msg = await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=buf,
            reply_markup=_keyboard(),
        )
        board_msg_id = msg.message_id
    status = await update.message.reply_text('Выберите клетку или введите ход текстом.')
    state.message_id = board_msg_id
    state.status_message_id = status.message_id
    context.bot_data.setdefault(STATE_KEY, {})[update.effective_chat.id] = state
    match.messages['A'] = {
        'board': board_msg_id,
        'status': status.message_id,
    }
    storage.save_match(match)
    asyncio.create_task(_auto_play_bots(match, context, update.effective_chat.id, human='A'))
    await update.message.reply_text('Тестовый матч начат. Вы — игрок A; два бота ходят автоматически.')


async def send_board15_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send invitation link for 15x15 mode."""
    query = update.callback_query
    await query.answer()
    match = storage.find_match_by_user(query.from_user.id, update.effective_chat.id)
    if not match:
        await query.message.reply_text('Матч не найден.')
        return
    username = (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=b15_{match.match_id}"
    await query.message.reply_text(f"Пригласите друга: {link}")


async def board15_on_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data.split("|")
    states = context.bot_data.get(STATE_KEY, {})
    state: Board15State | None = states.get(update.effective_chat.id)
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
        buf = render_board(state, state.player_key)
        try:
            await query.edit_message_media(InputMediaPhoto(buf))
        except Exception:
            pass
        await query.edit_message_reply_markup(_keyboard())
        await query.answer()
        return
    elif data[1] == "act" and data[2] == "confirm":
        if state.selected is None:
            await query.answer("Клетка не выбрана")
            return
        match = storage.find_match_by_user(query.from_user.id, update.effective_chat.id)
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
        r, c = coord
        if match.boards[player_key].grid[r][c] == 1:
            await query.answer("Здесь ваш корабль")
            return
        enemies = [k for k in match.players if k != player_key]
        results = {}
        hit_any = False
        for enemy in enemies:
            res = battle.apply_shot(match.boards[enemy], coord)
            results[enemy] = res
            if res in (battle.HIT, battle.KILL):
                hit_any = True
        if battle.REPEAT in results.values():
            await query.answer("Эта клетка уже открыта")
            return
        battle.update_history(match.history, match.boards, coord, results)
        for k in match.shots:
            shots = match.shots[k]
            shots.setdefault('move_count', 0)
            shots.setdefault('joke_start', random.randint(1, 10))
            shots['move_count'] += 1
        coord_str = parser.format_coord(coord)
        if not hit_any:
            order = [k for k in ('A', 'B', 'C') if k in match.players and match.boards[k].alive_cells > 0]
            idx = order.index(player_key)
            next_player = order[(idx + 1) % len(order)]
        else:
            next_player = player_key
        match.turn = next_player

        parts_self = []
        from . import router as router_module
        for enemy, res in results.items():
            enemy_name = match.players.get(enemy)
            enemy_label = getattr(enemy_name, 'name', '') or enemy
            if res == battle.MISS:
                phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
                parts_self.append(f"{enemy_label}: мимо. {phrase_self}")
                if match.players[enemy].user_id != 0:
                    msg = f"{coord_str} - соперник промахнулся. {phrase_enemy}"
                    if enemy == next_player:
                        msg += ' Ваш ход.'
                    await router_module._send_state(context, match, enemy, msg)
            elif res == battle.HIT:
                phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
                parts_self.append(f"{enemy_label}: ранил. {phrase_self}")
                if match.players[enemy].user_id != 0:
                    await router_module._send_state(
                        context,
                        match,
                        enemy,
                        f"{coord_str} - ваш корабль ранен. {phrase_enemy}",
                    )
            elif res == battle.KILL:
                phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
                parts_self.append(f"{enemy_label}: уничтожен! {phrase_self}")
                if match.players[enemy].user_id != 0:
                    await router_module._send_state(
                        context,
                        match,
                        enemy,
                        f"{coord_str} - ваш корабль уничтожен. {phrase_enemy}",
                    )
                if match.boards[enemy].alive_cells == 0:
                    enemy_label = getattr(match.players.get(enemy), 'name', '') or enemy
                    target = enemy if match.players[enemy].user_id != 0 else player_key
                    await context.bot.send_message(
                        match.players[target].chat_id,
                        f"⛔ Игрок {enemy_label} выбыл (флот уничтожен)",
                    )

        storage.save_match(match)
        next_label = match.players.get(next_player)
        next_name = getattr(next_label, 'name', '') or next_player
        result_self = f"{coord_str} - {' '.join(parts_self)}" + (
            ' Ваш ход.' if next_player == player_key else f" Ход {next_name}."
        )
        view_key = match.turn if single_user else player_key
        merged = [row[:] for row in match.history]
        own_grid_view = match.boards[view_key].grid
        for r in range(15):
            for c in range(15):
                if merged[r][c] == 0 and own_grid_view[r][c] == 1:
                    merged[r][c] = 1
        state.board = merged
        state.selected = None
        if match.players[view_key].user_id != 0:
            await router_module._send_state(context, match, view_key, result_self)
        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
        if len(alive_players) == 1:
            winner = alive_players[0]
            storage.finish(match, winner)
            await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
            for k in match.players:
                if k != winner:
                    await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
        await query.answer()
        return
    elif data[1] == "act" and data[2] == "cancel":
        state.selected = None
    buf = render_board(state, state.player_key)
    try:
        await query.edit_message_media(InputMediaPhoto(buf))
    except Exception:
        pass
    await query.edit_message_reply_markup(_keyboard())
    await query.answer()
