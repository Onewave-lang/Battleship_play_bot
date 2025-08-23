from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes

import storage
from logic.parser import parse_coord
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from logic.render import render_board_own, render_board_enemy


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


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    match = storage.find_match_by_user(user_id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return

    player_key = 'A' if match.players['A'].user_id == user_id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'

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

    if result == MISS:
        match.turn = enemy_key
        result_self = 'Мимо. Ход соперника.'
        result_enemy = 'Соперник промахнулся. Ваш ход.'
    elif result == HIT:
        result_self = 'Ранил. Ваш ход.'
        result_enemy = 'Соперник ранил ваш корабль. Ход соперника.'
    elif result == REPEAT:
        result_self = 'Клетка уже обстреляна. Ваш ход.'
        result_enemy = 'Соперник стрелял по уже обстрелянной клетке. Ход соперника.'
    else:
        if match.boards[enemy_key].alive_cells == 0:
            storage.finish(match, player_key)
            result_self = 'Убил! Вы победили.'
            result_enemy = 'Все ваши корабли потоплены. Игра окончена.'
        else:
            result_self = 'Убил! Ваш ход.'
            result_enemy = 'Соперник уничтожил ваш корабль. Ход соперника.'

    storage.save_match(match)

    await _send_state(context, match, player_key, result_self)
    await _send_state(context, match, enemy_key, result_enemy)
