from __future__ import annotations
import random
import os
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

import storage
from logic.parser import parse_coord, format_coord
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from logic.battle_test import apply_shot_multi
from logic.render import render_board_own, render_board_enemy
from models import Board
from handlers.commands import newgame
from .move_keyboard import move_keyboard
from .board_test import board_test
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


# Delay after sending the board and before sending/editing the result text.
# Can be tuned with the ``STATE_DELAY`` environment variable.
STATE_DELAY = float(os.getenv("STATE_DELAY", "0.2"))


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
) -> None:
    """Send boards first, then a separate text message with the result."""
    enemy_key = "B" if player_key == "A" else "A"
    chat_id = match.players[player_key].chat_id
    msgs = match.messages.setdefault(player_key, {})

    board_id = msgs.get("board")
    text_id = msgs.get("text")

    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    kb = move_keyboard()

    # send a fresh board message with keyboard and remove the old one
    board_text = f"Ваше поле:\n{own}\nПоле соперника:\n{enemy}"
    if board_id:
        try:
            await context.bot.delete_message(chat_id, board_id)
        except Exception:
            pass
    board_msg = await context.bot.send_message(
        chat_id,
        board_text,
        parse_mode="HTML",
        reply_markup=kb,
    )
    msgs["board"] = board_msg.message_id

    await asyncio.sleep(STATE_DELAY)

    # update text message with result
    if text_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=text_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception:
            try:
                await context.bot.delete_message(chat_id, text_id)
            except Exception:
                pass
            text_msg = await context.bot.send_message(
                chat_id,
                message,
                parse_mode="HTML",
            )
            text_id = text_msg.message_id
    else:
        text_msg = await context.bot.send_message(
            chat_id,
            message,
            parse_mode="HTML",
        )
        text_id = text_msg.message_id
    msgs["text"] = text_id

    storage.save_match(match)


async def _send_state_board_test(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
) -> None:
    """Send the shared board with global history to ``player_key``."""

    chat_id = match.players[player_key].chat_id
    msgs = match.messages.setdefault(player_key, {})

    board_id = msgs.get("board")
    text_id = msgs.get("text")

    merged = [row[:] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(10):
        for c in range(10):
            if merged[r][c] == 0 and own_grid[r][c] == 1:
                merged[r][c] = 1
    board = Board(grid=merged, highlight=match.boards[player_key].highlight.copy())
    shots = match.shots.get(player_key, {})
    last = shots.get("last_coord")
    if last is not None:
        if isinstance(last, list):
            last = tuple(last)
        board.highlight.append(last)
    board_text = f"Ваше поле:\n{render_board_own(board)}"
    kb = move_keyboard()

    if board_id:
        try:
            await context.bot.delete_message(chat_id, board_id)
        except Exception:
            pass
    board_msg = await context.bot.send_message(
        chat_id,
        board_text,
        parse_mode="HTML",
        reply_markup=kb,
    )
    msgs["board"] = board_msg.message_id

    await asyncio.sleep(STATE_DELAY)

    if text_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=text_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception:
            try:
                await context.bot.delete_message(chat_id, text_id)
            except Exception:
                pass
            text_msg = await context.bot.send_message(
                chat_id,
                message,
                parse_mode="HTML",
            )
            text_id = text_msg.message_id
    else:
        text_msg = await context.bot.send_message(
            chat_id,
            message,
            parse_mode="HTML",
        )
        text_id = text_msg.message_id
    msgs["text"] = text_id

    storage.save_match(match)


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот по этому поводу:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text_raw = update.message.text
    text = text_raw.strip()
    text_lower = text.lower()
    if text_lower == 'начать новую игру':
        await newgame(update, context)
        return
    match = storage.find_match_by_user(user_id, update.effective_chat.id)
    if not match and os.getenv("BOARD15_ENABLED") == "1":
        from game_board15 import storage as storage15, router as router15
        match15 = storage15.find_match_by_user(user_id, update.effective_chat.id)
        if match15:
            await router15.router_text(update, context)
            return
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return

    player_key = 'A' if match.players['A'].user_id == user_id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'

    if text.startswith('@'):
        msg = text[1:].strip()
        for key, player in match.players.items():
            if key != player_key:
                await context.bot.send_message(player.chat_id, msg)
        return

    if match.status == 'placing':
        if text == 'авто':
            board = random_board()
            storage.save_board(match, player_key, board)
            if match.status == 'playing':
                await _send_state(
                    context,
                    match,
                    player_key,
                    'Корабли расставлены. Бой начинается! '
                    + ('Ваш ход.' if match.turn == player_key else 'Ход соперника.'),
                )
                await _send_state(
                    context,
                    match,
                    enemy_key,
                    'Соперник готов. Бой начинается! '
                    + ('Ваш ход.' if match.turn == enemy_key else 'Ход соперника.'),
                )
            else:
                await _send_state(
                    context,
                    match,
                    player_key,
                    'Корабли расставлены. Ожидаем соперника.',
                )
                await _send_state(
                    context,
                    match,
                    enemy_key,
                    'Соперник готов. Отправьте "авто" для расстановки кораблей.',
                )
                await context.bot.send_message(
                    match.players[enemy_key].chat_id,
                    'Используйте @ в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
                )
        else:
            await update.message.reply_text('Введите "авто" для автоматической расстановки.')
        return

    if match.status != 'playing':
        if match.status == 'waiting':
            await update.message.reply_text('Матч ещё не начался. Ожидаем соперника.')
        else:
            await update.message.reply_text('Матч ещё не начался.')
        return

    if match.turn != player_key:
        await _send_state(context, match, player_key, 'Сейчас ход соперника.')
        return

    coord = parse_coord(text)
    if coord is None:
        await _send_state(context, match, player_key, 'Не понял клетку. Пример: е5 или д10.')
        return

    result = apply_shot(match.boards[enemy_key], coord)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_result'] = result
    for k in ('A', 'B'):
        shots = match.shots.setdefault(k, {})
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1
    error = None
    coord_str = format_coord(coord)
    player_label = getattr(match.players[player_key], 'name', '') or player_key
    enemy_label = getattr(match.players[enemy_key], 'name', '') or enemy_key
    next_player = None

    if result == MISS:
        match.turn = enemy_key
        next_player = enemy_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS)
        next_phrase_self = f"Ход {next_label}."
        next_phrase_enemy = 'Ваш ход.'
        result_self = f"Ваш ход: {coord_str} — Мимо. {phrase_self}{next_phrase_self}"
        result_enemy = (
            f"Ход игрока {player_label}: {coord_str} — Соперник промахнулся. {phrase_enemy}{next_phrase_enemy}"
        )
        error = storage.save_match(match)
    elif result == HIT:
        next_player = player_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_HIT)
        next_phrase_self = 'Ваш ход.'
        next_phrase_enemy = f"Ход {next_label}."
        result_self = f"Ваш ход: {coord_str} — Ранил. {phrase_self}{next_phrase_self}"
        result_enemy = (
            f"Ход игрока {player_label}: {coord_str} — Соперник ранил ваш корабль. {phrase_enemy}{next_phrase_enemy}"
        )
        error = storage.save_match(match)
    elif result == REPEAT:
        next_player = player_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS)
        next_phrase_self = 'Ваш ход.'
        next_phrase_enemy = f"Ход {next_label}."
        result_self = (
            f"Ваш ход: {coord_str} — Клетка уже обстреляна. {phrase_self}{next_phrase_self}"
        )
        result_enemy = (
            f"Ход игрока {player_label}: {coord_str} — Соперник стрелял по уже обстрелянной клетке. {phrase_enemy}{next_phrase_enemy}"
        )
        error = storage.save_match(match)
    elif result == KILL:
        phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_KILL)
        if match.boards[enemy_key].alive_cells == 0:
            error = storage.finish(match, player_key)
            result_self = (
                f"Ваш ход: {coord_str} — Корабль соперника уничтожен! {phrase_self}Вы победили. 🏆🎉"
            )
            result_enemy = (
                f"Ход игрока {player_label}: {coord_str} — Соперник уничтожил ваш корабль. {phrase_enemy}Все ваши корабли уничтожены. Соперник победил. Не сдавайтесь, капитан! ⚓"
            )
        else:
            next_player = player_key
            next_label = getattr(match.players[next_player], 'name', '') or next_player
            next_phrase_self = 'Ваш ход.'
            next_phrase_enemy = f"Ход {next_label}."
            result_self = (
                f"Ваш ход: {coord_str} — Корабль соперника уничтожен! {phrase_self}{next_phrase_self}"
            )
            result_enemy = (
                f"Ход игрока {player_label}: {coord_str} — Соперник уничтожил ваш корабль. {phrase_enemy}{next_phrase_enemy}"
            )
            error = storage.save_match(match)
    else:
        next_player = enemy_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        next_phrase_self = f"Ход {next_label}."
        next_phrase_enemy = 'Ваш ход.'
        result_self = f"Ваш ход: {coord_str} — Ошибка. {next_phrase_self}"
        result_enemy = f"Ход игрока {player_label}: {coord_str} — Техническая ошибка. {next_phrase_enemy}"

    if error:
        msg = 'Произошла техническая ошибка. Ход прерван.'
        await context.bot.send_message(match.players[player_key].chat_id, msg)
        await context.bot.send_message(match.players[enemy_key].chat_id, msg)
        return

    if match.players['A'].chat_id == match.players['B'].chat_id:
        if next_player == player_key:
            next_label = getattr(match.players[next_player], 'name', '') or next_player
            result_self = result_self.replace('Ваш ход.', f'Ход {next_label}.')
        await _send_state(context, match, player_key, result_self)
    else:
        await _send_state(context, match, player_key, result_self)
        await _send_state(context, match, enemy_key, result_enemy)

    if match.status == 'finished':
        keyboard = ReplyKeyboardMarkup([["Начать новую игру"]], one_time_keyboard=True, resize_keyboard=True)
        await context.bot.send_message(match.players[player_key].chat_id, 'Игра завершена!', reply_markup=keyboard)
        await context.bot.send_message(match.players[enemy_key].chat_id, 'Игра завершена!', reply_markup=keyboard)


async def router_text_board_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle moves for the three-player test mode."""

    user_id = update.effective_user.id
    text = update.message.text.strip()
    match = storage.find_match_by_user(user_id, update.effective_chat.id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /board_test.')
        return

    player_key = 'A'

    if text.startswith('@'):
        msg = text[1:].strip()
        for key, player in match.players.items():
            if key != player_key and player.user_id != 0:
                await context.bot.send_message(player.chat_id, msg)
        return

    if match.status != 'playing':
        await update.message.reply_text('Матч ещё не начался.')
        return

    if match.turn != player_key:
        await _send_state_board_test(context, match, player_key, 'Сейчас ход соперника.')
        return

    coord = parse_coord(text)
    if coord is None:
        await _send_state_board_test(context, match, player_key, 'Не понял клетку. Пример: е5 или д10.')
        return

    enemies = [k for k in match.players.keys() if k != player_key and match.boards[k].alive_cells > 0]
    boards = {k: match.boards[k] for k in enemies}
    results = apply_shot_multi(coord, boards, match.history)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_coord'] = coord
    for k in match.shots:
        shots = match.shots.setdefault(k, {})
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1

    coord_str = format_coord(coord)
    hit_any = any(res in (HIT, KILL) for res in results.values())
    alive = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
    if not hit_any:
        alive_order = [k for k in ('A', 'B', 'C') if k in alive]
        idx_next = alive_order.index(player_key)
        next_player = alive_order[(idx_next + 1) % len(alive_order)]
    else:
        next_player = player_key
    match.turn = next_player

    player_label = getattr(match.players[player_key], 'name', '') or player_key
    self_msgs: dict[str, str] = {}
    enemy_msgs: dict[str, str] = {}
    for enemy, res in results.items():
        enemy_label = getattr(match.players[enemy], 'name', '') or enemy
        if res == MISS:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
            self_msgs[enemy] = f"{enemy_label}: мимо. {phrase_self}"
            enemy_msgs[enemy] = f"соперник промахнулся. {phrase_enemy}"
        elif res == HIT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
            self_msgs[enemy] = f"{enemy_label}: ранил. {phrase_self}"
            enemy_msgs[enemy] = f"ваш корабль ранен. {phrase_enemy}"
        elif res == KILL:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
            self_msgs[enemy] = f"{enemy_label}: уничтожен! {phrase_self}"
            enemy_msgs[enemy] = f"ваш корабль уничтожен. {phrase_enemy}"
            if (
                match.boards[enemy].alive_cells == 0
                and match.players[enemy].user_id != 0
            ):
                await context.bot.send_message(
                    match.players[enemy].chat_id,
                    f"⛔ Игрок {enemy_label} выбыл (флот уничтожен)",
                )

    storage.save_match(match)

    next_label = getattr(match.players[next_player], 'name', '') or next_player
    next_phrase_self = (
        'Ваш ход.' if next_player == player_key else f"Ход {next_label}."
    )
    self_lines = [
        f"Ваш ход: {coord_str} — {body}" for body in self_msgs.values()
    ]
    if not self_lines:
        self_lines = [f"Ваш ход: {coord_str}"]
    self_lines.append(next_phrase_self)
    await _send_state_board_test(
        context,
        match,
        player_key,
        "\n".join(self_lines),
    )

    for enemy, body in enemy_msgs.items():
        if match.players[enemy].user_id != 0:
            next_phrase = (
                'Ваш ход.' if next_player == enemy else f"Ход {next_label}."
            )
            await _send_state_board_test(
                context,
                match,
                enemy,
                f"Ход игрока {player_label}: {coord_str} — {body}\n{next_phrase}",
            )

    alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
    if len(alive_players) == 1:
        winner = alive_players[0]
        storage.finish(match, winner)
        if winner == player_key:
            await context.bot.send_message(match.players[player_key].chat_id, 'Вы победили!')
        else:
            await context.bot.send_message(match.players[player_key].chat_id, 'Игра окончена. Победил соперник.')
