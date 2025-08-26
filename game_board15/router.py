from __future__ import annotations
import random
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes

from . import storage
from . import battle, parser
from .handlers import _keyboard, STATE_KEY
from .renderer import render_board, render_player_board
from .state import Board15State
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


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


async def _send_state(context: ContextTypes.DEFAULT_TYPE, match, player_key: str, message: str) -> None:
    """Render player's board and update their messages."""

    chat_id = match.players[player_key].chat_id
    states = context.bot_data.setdefault(STATE_KEY, {})
    state: Board15State | None = states.get(chat_id)
    if not state:
        state = Board15State(chat_id=chat_id)
        states[chat_id] = state
    merged = [row[:] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(15):
        for c in range(15):
            if merged[r][c] == 0 and own_grid[r][c] == 1:
                merged[r][c] = 1
    state.board = merged
    state.player_key = player_key
    buf = render_board(state, player_key)
    msgs = match.messages.setdefault(player_key, {})
    board_id = msgs.get('board')
    status_id = msgs.get('status')
    if board_id:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=board_id,
                media=InputMediaPhoto(buf),
            )
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=board_id,
                reply_markup=_keyboard(),
            )
        except Exception:
            msg = await context.bot.send_photo(chat_id, buf, reply_markup=_keyboard())
            board_id = msg.message_id
            msgs['board'] = board_id
        else:
            state.message_id = board_id
    else:
        msg = await context.bot.send_photo(chat_id, buf, reply_markup=_keyboard())
        board_id = msg.message_id
        msgs['board'] = board_id
        state.message_id = board_id

    # player's own board with ships
    player_buf = render_player_board(match.boards[player_key], player_key)
    player_id = msgs.get('player')
    if player_id:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=player_id,
                media=InputMediaPhoto(player_buf),
            )
        except Exception:
            msg = await context.bot.send_photo(chat_id, player_buf)
            msgs['player'] = msg.message_id
    else:
        msg = await context.bot.send_photo(chat_id, player_buf)
        msgs['player'] = msg.message_id

    if status_id:
        try:
            await context.bot.edit_message_text(
                message,
                chat_id=chat_id,
                message_id=status_id,
            )
        except Exception:
            status = await context.bot.send_message(chat_id, message)
            msgs['status'] = status.message_id
        else:
            state.status_message_id = status_id
    else:
        status = await context.bot.send_message(chat_id, message)
        msgs['status'] = status.message_id
        state.status_message_id = status.message_id
    storage.save_match(match)


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    match = storage.find_match_by_user(user_id, update.effective_chat.id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /board15 <id>.')
        return
    if all(p.user_id == user_id for p in match.players.values()):
        player_key = match.turn
        single_user = True
    else:
        single_user = False
        for key, p in match.players.items():
            if p.user_id == user_id:
                player_key = key
                break

    if text.startswith('@'):
        msg = text[1:].strip()
        for key, player in match.players.items():
            if key != player_key:
                await context.bot.send_message(player.chat_id, msg)
        return

    if match.status == 'placing':
        if text.lower() == 'авто':
            storage.save_board(match, player_key)
            if match.status == 'playing':
                for k in match.players:
                    msg = (
                        'Корабли расставлены. Бой начинается! '
                        if k == player_key
                        else 'Соперник готов. Бой начинается! '
                    )
                    msg += 'Ваш ход.' if match.turn == k else 'Ход соперника.'
                    await _send_state(context, match, k, msg)
            else:
                await _send_state(context, match, player_key, 'Корабли расставлены. Ожидаем остальных.')
            return
        await update.message.reply_text('Введите "авто" для расстановки.')
        return

    if match.status != 'playing':
        await update.message.reply_text('Матч ещё не начался.')
        return

    enemy_keys = [
        k for k in match.players
        if k != player_key and match.boards[k].alive_cells > 0
    ]

    if not single_user and match.turn != player_key:
        await update.message.reply_text('Сейчас ход другого игрока.')
        return

    coord = parser.parse_coord(text)
    if coord is None:
        await update.message.reply_text('Не понял клетку. Пример: e5.')
        return

    results = {}
    hit_any = False
    repeat = False
    for enemy in enemy_keys:
        res = battle.apply_shot(match.boards[enemy], coord)
        results[enemy] = res
        if res == battle.REPEAT:
            repeat = True
        elif res in (battle.HIT, battle.KILL):
            hit_any = True
    if repeat:
        await update.message.reply_text('Эта клетка уже открыта')
        return
    battle.update_history(match.history, match.boards, coord, results)
    for k in match.shots:
        shots = match.shots[k]
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1
    storage.save_match(match)

    coord_str = parser.format_coord(coord)
    parts_self: list[str] = []
    parts_others: list[str] = []
    victims: list[str] = []
    next_player = player_key
    for enemy, res in results.items():
        enemy_obj = match.players.get(enemy)
        enemy_label = getattr(enemy_obj, "name", "") or enemy
        if res == battle.MISS:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
            parts_self.append(f"{enemy_label}: мимо. {phrase_self}")
        elif res == battle.HIT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
            parts_self.append(f"{enemy_label}: ранил. {phrase_self}")
            parts_others.append(f"корабль игрока {enemy_label} ранен")
            victims.append(enemy)
            await _send_state(
                context,
                match,
                enemy,
                f"{coord_str} - ваш корабль ранен. {phrase_enemy}",
            )
        elif res == battle.KILL:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
            parts_self.append(f"{enemy_label}: уничтожен! {phrase_self}")
            parts_others.append(f"корабль игрока {enemy_label} уничтожен")
            victims.append(enemy)
            await _send_state(
                context,
                match,
                enemy,
                f"{coord_str} - ваш корабль уничтожен. {phrase_enemy}",
            )
            if match.boards[enemy].alive_cells == 0:
                await context.bot.send_message(
                    match.players[enemy].chat_id,
                    "Все ваши корабли уничтожены. Вы выбыли.",
                )

    others = [
        k
        for k in match.players
        if k not in victims and k != player_key and match.boards[k].alive_cells > 0
    ]
    if not hit_any:
        order = [
            k
            for k in ('A', 'B', 'C')
            if k in match.players and match.boards[k].alive_cells > 0
        ]
        idx = order.index(player_key)
        next_player = order[(idx + 1) % len(order)]
        match.turn = next_player
        storage.save_match(match)
        await _send_state(context, match, next_player, 'Ваш ход.')
    else:
        match.turn = player_key
        storage.save_match(match)
    others = [k for k in others if k != next_player]
    if others:
        if parts_others:
            msg_others = f"{coord_str} - {', '.join(parts_others)}"
        else:
            msg_others = f"{coord_str} - мимо"
        for other in others:
            await _send_state(context, match, other, msg_others)
    next_obj = match.players.get(next_player)
    next_name = getattr(next_obj, 'name', '') or next_player
    result_self = f"{coord_str} - {' '.join(parts_self)}" + (' Ваш ход.' if match.turn == player_key else f" Ход {next_name}.")
    view_key = match.turn if single_user else player_key
    await _send_state(context, match, view_key, result_self)

    alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
    if len(alive_players) == 1:
        winner = alive_players[0]
        storage.finish(match, winner)
        await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
        for k in match.players:
            if k != winner:
                await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
