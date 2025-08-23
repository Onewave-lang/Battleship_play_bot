from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes

import storage
from logic.parser import parse_coord
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL
from logic.render import render_board_own, render_board_enemy


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
                await update.message.reply_text('Корабли расставлены. Бой начинается!')
            else:
                await update.message.reply_text('Корабли расставлены. Ожидаем соперника.')
        else:
            await update.message.reply_text('Введите "авто" для автоматической расстановки.')
        return

    if match.status != 'playing':
        await update.message.reply_text('Матч ещё не начался.')
        return

    if match.turn != player_key:
        await update.message.reply_text('Сейчас ход соперника.')
        return

    coord = parse_coord(text)
    if coord is None:
        await update.message.reply_text('Не понял клетку. Пример: е5 или д10.')
        return

    result = apply_shot(match.boards[enemy_key], coord)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_result'] = result

    if result == MISS:
        match.turn = enemy_key
        result_msg = 'Мимо. Ход соперника.'
    elif result == HIT:
        result_msg = 'Ранил. Ваш ход.'
    else:
        if match.boards[enemy_key].alive_cells == 0:
            storage.finish(match, player_key)
            result_msg = 'Убил! Вы победили.'
        else:
            result_msg = 'Убил! Ваш ход.'

    storage.save_match(match)

    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    await context.bot.send_message(match.players[player_key].chat_id,
                                   f"Ваше поле:\n{own}\nПоле соперника:\n{enemy}\n{result_msg}",
                                   parse_mode='HTML')
    if match.status == 'playing':
        own_e = render_board_own(match.boards[enemy_key])
        enemy_e = render_board_enemy(match.boards[player_key])
        await context.bot.send_message(match.players[enemy_key].chat_id,
                                       f"Ваше поле:\n{own_e}\nПоле соперника:\n{enemy_e}\n{result_msg}",
                                       parse_mode='HTML')
    else:
        await context.bot.send_message(match.players[enemy_key].chat_id,
                                       'Все корабли потоплены. Игра окончена.',
                                       parse_mode='HTML')
