from __future__ import annotations
import random
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

import storage
from logic.parser import parse_coord, format_coord
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from logic.render import render_board_own, render_board_enemy
from handlers.commands import newgame
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


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
) -> None:
    """Send current boards and message to the given player."""
    enemy_key = "B" if player_key == "A" else "A"
    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    await context.bot.send_message(
        match.players[player_key].chat_id,
        f"Ваше поле:\n{own}\nПоле соперника:\n{enemy}\n{message}",
        parse_mode="HTML",
    )


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
    match = storage.find_match_by_user(user_id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return

    player_key = 'A' if match.players['A'].user_id == user_id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'

    if text.startswith('@'):
        msg = text[1:].strip()
        await context.bot.send_message(match.players[enemy_key].chat_id, msg)
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
                    'Используйте @<ваше сообщение>, чтобы отправить сообщение сопернику.',
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

    if result == MISS:
        match.turn = enemy_key
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS)
        result_self = f"{coord_str} - Мимо. {phrase_self}Ход соперника."
        result_enemy = f"{coord_str} - Соперник промахнулся. {phrase_enemy}Ваш ход."
        error = storage.save_match(match)
    elif result == HIT:
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_HIT)
        result_self = f"{coord_str} - Ранил. {phrase_self}Ваш ход."
        result_enemy = f"{coord_str} - Соперник ранил ваш корабль. {phrase_enemy}Ход соперника."
        error = storage.save_match(match)
    elif result == REPEAT:
        result_self = f'{coord_str} - Клетка уже обстреляна. Ваш ход.'
        result_enemy = f'{coord_str} - Соперник стрелял по уже обстрелянной клетке. Ход соперника.'
        error = storage.save_match(match)
    elif result == KILL:
        if match.boards[enemy_key].alive_cells == 0:
            error = storage.finish(match, player_key)
            result_self = f"{coord_str} - Корабль соперника уничтожен! Вы победили. 🏆🎉"
            result_enemy = (
                f"{coord_str} - Все ваши корабли уничтожены. Соперник победил. "
                "Не сдавайтесь, капитан! ⚓"
            )
        else:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
            phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_KILL)
            result_self = f"{coord_str} - Корабль соперника уничтожен! {phrase_self}Ваш ход."
            result_enemy = (
                f"{coord_str} - Соперник уничтожил ваш корабль. {phrase_enemy}Ход соперника."
            )
            error = storage.save_match(match)
    else:
        result_self = f'{coord_str} - Ошибка. Ваш ход.'
        result_enemy = f'{coord_str} - Техническая ошибка. Ход соперника.'

    if error:
        msg = 'Произошла техническая ошибка. Ход прерван.'
        await context.bot.send_message(match.players[player_key].chat_id, msg)
        await context.bot.send_message(match.players[enemy_key].chat_id, msg)
        return

    await _send_state(context, match, player_key, result_self)
    await _send_state(context, match, enemy_key, result_enemy)

    if match.status == 'finished':
        keyboard = ReplyKeyboardMarkup([["Начать новую игру"]], one_time_keyboard=True, resize_keyboard=True)
        await context.bot.send_message(match.players[player_key].chat_id, 'Игра завершена!', reply_markup=keyboard)
        await context.bot.send_message(match.players[enemy_key].chat_id, 'Игра завершена!', reply_markup=keyboard)
