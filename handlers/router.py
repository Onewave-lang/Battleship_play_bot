from __future__ import annotations
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio

import storage
from logic.parser import parse_coord, ROWS
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from logic.render import render_board_own, render_board_enemy


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
    *,
    blink_cells=None,
    blink_on="enemy",
    show_dot=False,
    blink_red=False,
    message_id=None,
):
    """Send current boards and message to the given player."""
    enemy_key = "B" if player_key == "A" else "A"
    if blink_on == "own" and blink_cells is not None:
        own = render_board_own(
            match.boards[player_key], blink_cells, show_dot, blink_red
        )
    else:
        own = render_board_own(match.boards[player_key])
    if blink_on == "enemy" and blink_cells is not None:
        enemy = render_board_enemy(
            match.boards[enemy_key], blink_cells, show_dot, blink_red
        )
    else:
        enemy = render_board_enemy(match.boards[enemy_key])
    text = f"Ваше поле:\n{own}\nПоле соперника:\n{enemy}\n{message}"
    if message_id:
        await context.bot.edit_message_text(
            text,
            match.players[player_key].chat_id,
            message_id,
            parse_mode="HTML",
        )
        return None
    return await context.bot.send_message(
        match.players[player_key].chat_id, text, parse_mode="HTML"
    )


async def _animate_shot(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    shooter_key: str,
    defender_key: str,
    result_self: str,
    result_enemy: str,
    cells,
    *,
    red=False,
):
    blink = set(cells)
    msg_self = await _send_state(
        context,
        match,
        shooter_key,
        result_self,
        blink_cells=blink,
        blink_on="enemy",
        blink_red=red,
    )
    msg_enemy = await _send_state(
        context,
        match,
        defender_key,
        result_enemy,
        blink_cells=blink,
        blink_on="own",
        blink_red=red,
    )
    show_dot = False
    for _ in range(8):
        await asyncio.sleep(0.5)
        show_dot = not show_dot
        await _send_state(
            context,
            match,
            shooter_key,
            result_self,
            blink_cells=blink,
            blink_on="enemy",
            show_dot=show_dot,
            blink_red=red,
            message_id=msg_self.message_id,
        )
        await _send_state(
            context,
            match,
            defender_key,
            result_enemy,
            blink_cells=blink,
            blink_on="own",
            show_dot=show_dot,
            blink_red=red,
            message_id=msg_enemy.message_id,
        )
    await _send_state(
        context,
        match,
        shooter_key,
        result_self,
        blink_cells=blink,
        blink_on="enemy",
        show_dot=False,
        blink_red=False,
        message_id=msg_self.message_id,
    )
    await _send_state(
        context,
        match,
        defender_key,
        result_enemy,
        blink_cells=blink,
        blink_on="own",
        show_dot=False,
        blink_red=False,
        message_id=msg_enemy.message_id,
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

    r, c = coord
    coord_str = f"{ROWS[r]}{c+1}"
    result = apply_shot(match.boards[enemy_key], coord)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_result'] = result
    error = None

    if result == MISS:
        match.turn = enemy_key
        result_self = f'{coord_str}: Мимо. Ход соперника.'
        result_enemy = f'{coord_str}: Соперник промахнулся. Ваш ход.'
        error = storage.save_match(match)
    elif result == HIT:
        result_self = f'{coord_str}: Ранил. Ваш ход.'
        result_enemy = f'{coord_str}: Соперник ранил ваш корабль. Ход соперника.'
        error = storage.save_match(match)
    elif result == REPEAT:
        result_self = f'{coord_str}: Клетка уже обстреляна. Ваш ход.'
        result_enemy = f'{coord_str}: Соперник стрелял по уже обстрелянной клетке. Ход соперника.'
        error = storage.save_match(match)
    else:
        if match.boards[enemy_key].alive_cells == 0:
            error = storage.finish(match, player_key)
            result_self = f'{coord_str}: Корабль уничтожен! Вы победили.'
            result_enemy = f'{coord_str}: Все ваши корабли потоплены.'
        else:
            result_self = f'{coord_str}: Корабль уничтожен! Ваш ход.'
            result_enemy = f'{coord_str}: Соперник уничтожил ваш корабль. Ход соперника.'
            error = storage.save_match(match)

    if error:
        msg = 'Произошла техническая ошибка. Ход прерван.'
        await context.bot.send_message(match.players[player_key].chat_id, msg)
        await context.bot.send_message(match.players[enemy_key].chat_id, msg)
        return

    cells = [coord]
    if result == KILL:
        for ship in match.boards[enemy_key].ships:
            if not ship.alive and coord in ship.cells:
                cells = ship.cells
                break

    if result == REPEAT:
        await _send_state(context, match, player_key, result_self)
        await _send_state(context, match, enemy_key, result_enemy)
    else:
        await _animate_shot(
            context,
            match,
            player_key,
            enemy_key,
            result_self,
            result_enemy,
            cells,
            red=result in (HIT, KILL),
        )

    if match.status == 'finished':
        kb = ReplyKeyboardMarkup([['/newgame']], one_time_keyboard=True)
        await context.bot.send_message(
            match.players[player_key].chat_id,
            '🎉 Победа! Вы разгромили флот соперника!',
        )
        await context.bot.send_message(
            match.players[enemy_key].chat_id,
            '⚓ Соперник одержал победу. Не сдавайтесь, удача улыбнётся в следующий раз.',
        )
        for key in (player_key, enemy_key):
            await context.bot.send_message(
                match.players[key].chat_id,
                'Игра завершена!',
                reply_markup=kb,
            )
