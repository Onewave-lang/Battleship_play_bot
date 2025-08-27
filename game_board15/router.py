from __future__ import annotations
import logging
import random
import copy
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes

from . import storage
from . import battle, parser
from .handlers import STATE_KEY
from .renderer import render_board, render_player_board
from .state import Board15State
from logic.phrases import (
    ENEMY_HIT,
    ENEMY_KILL,
    ENEMY_MISS,
    SELF_HIT,
    SELF_KILL,
    SELF_MISS,
)
from .utils import _phrase_or_joke


logger = logging.getLogger(__name__)


async def _send_state(context: ContextTypes.DEFAULT_TYPE, match, player_key: str, message: str) -> None:
    """Render player's board and send board image followed by text message."""

    chat_id = match.players[player_key].chat_id
    states = context.bot_data.setdefault(STATE_KEY, {})
    state: Board15State | None = states.get(chat_id)
    if not state:
        state = Board15State(chat_id=chat_id)
        states[chat_id] = state

    # prepare board images
    merged = copy.deepcopy(match.history)
    own_grid = match.boards[player_key].grid
    for r in range(15):
        for c in range(15):
            if merged[r][c] == 0 and own_grid[r][c] == 1:
                merged[r][c] = 1
    state.board = merged
    state.player_key = player_key
    state.highlight = match.boards[player_key].highlight.copy()
    shots = getattr(match, "shots", {})
    last = shots.get(player_key, {}).get("last_coord")
    if last is not None:
        if isinstance(last, list):
            last = tuple(last)
        state.highlight.append(last)
    buf = render_board(state, player_key)
    if buf.getbuffer().nbytes == 0:
        logger.warning("render_board returned empty buffer for chat %s", chat_id)
        return
    player_buf = render_player_board(match.boards[player_key], player_key)
    if player_buf.getbuffer().nbytes == 0:
        logger.warning("render_player_board returned empty buffer for chat %s", chat_id)
        return

    msgs = match.messages.setdefault(player_key, {})
    board_id = msgs.get("board")
    player_id = msgs.get("player")

    # update player's own board with ships
    if player_id:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=player_id,
                media=InputMediaPhoto(player_buf),
            )
        except Exception:
            logger.exception("Failed to update player's board for chat %s", chat_id)
            try:
                await context.bot.delete_message(chat_id, player_id)
            except Exception:
                pass
            player_buf.seek(0)
            msg = await context.bot.send_photo(chat_id, player_buf)
            msgs["player"] = msg.message_id
    else:
        msg = await context.bot.send_photo(chat_id, player_buf)
        msgs["player"] = msg.message_id

    # update main board image
    if board_id:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=board_id,
                media=InputMediaPhoto(buf),
            )
            state.message_id = board_id
        except Exception:
            logger.exception("Failed to update board image for chat %s", chat_id)
            try:
                await context.bot.delete_message(chat_id, board_id)
            except Exception:
                pass
            buf.seek(0)
            msg = await context.bot.send_photo(chat_id, buf)
            board_id = msg.message_id
            state.message_id = board_id
    else:
        msg = await context.bot.send_photo(chat_id, buf)
        board_id = msg.message_id
        state.message_id = board_id
    msgs["board"] = board_id

    # update or send text message only when it changes
    last_text = msgs.get("text")
    text_id = msgs.get("text_id")
    history = msgs.setdefault("text_history", [])

    if last_text == message and text_id:
        # avoid sending duplicate text message
        return

    if text_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=text_id,
                text=message,
            )
        except Exception:
            logger.exception("Failed to update text message for chat %s", chat_id)
            try:
                await context.bot.delete_message(chat_id, text_id)
            except Exception:
                pass
            try:
                msg_text = await context.bot.send_message(chat_id, message)
            except Exception:
                logger.exception("Failed to send text message for chat %s", chat_id)
                return
            else:
                text_id = msg_text.message_id
                history.append(text_id)
        else:
            if not history:
                history.append(text_id)
    else:
        try:
            msg_text = await context.bot.send_message(chat_id, message)
        except Exception:
            logger.exception("Failed to send text message for chat %s", chat_id)
            return
        else:
            text_id = msg_text.message_id
            history.append(text_id)

    msgs["text"] = message
    msgs["text_id"] = text_id


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

    if not hasattr(match, "shots"):
        match.shots = {k: {} for k in match.players}
    else:
        for k in match.players:
            match.shots.setdefault(k, {})

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
    r, c = coord
    if match.boards[player_key].grid[r][c] == 1:
        await update.message.reply_text('Здесь ваш корабль')
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
    coord_str = parser.format_coord(coord)
    before_history = [row[:] for row in match.history]
    battle.update_history(match.history, match.boards, coord, results)
    if match.history == before_history:
        logger.warning("History unchanged after shot %s", coord_str)
    if all(all(cell == 0 for cell in row) for row in match.history):
        logger.warning("History is empty after shot %s", coord_str)
    match.shots[player_key]["last_coord"] = coord
    for k in match.shots:
        shots = match.shots[k]
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1

    parts_self: list[str] = []
    enemy_msgs: dict[str, str] = {}
    targets: list[str] = []
    next_player = player_key
    player_obj = match.players.get(player_key)
    player_label = getattr(player_obj, "name", "") or player_key
    for enemy, res in results.items():
        enemy_obj = match.players.get(enemy)
        enemy_label = getattr(enemy_obj, "name", "") or enemy
        if res == battle.MISS:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
            parts_self.append(f"{enemy_label}: мимо. {phrase_self}")
            enemy_msgs[enemy] = f"соперник промахнулся. {phrase_enemy}"
        elif res == battle.HIT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
            parts_self.append(f"{enemy_label}: ранил. {phrase_self}")
            enemy_msgs[enemy] = f"ваш корабль ранен. {phrase_enemy}"
            targets.append(enemy)
        elif res == battle.KILL:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
            parts_self.append(f"{enemy_label}: уничтожен! {phrase_self}")
            enemy_msgs[enemy] = f"ваш корабль уничтожен. {phrase_enemy}"
            targets.append(enemy)
            if (
                match.boards[enemy].alive_cells == 0
                and match.players[enemy].user_id != 0
            ):
                await context.bot.send_message(
                    match.players[enemy].chat_id,
                    f"⛔ Игрок {enemy_label} выбыл (флот уничтожен)",
                )

    others = [
        k
        for k in match.players
        if k not in targets and k != player_key and match.boards[k].alive_cells > 0
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
    else:
        match.turn = player_key
    next_obj = match.players.get(next_player)
    next_name = getattr(next_obj, 'name', '') or next_player
    if enemy_msgs:
        for enemy, msg_body_enemy in enemy_msgs.items():
            if match.players[enemy].user_id != 0:
                next_phrase = ' Ваш ход.' if match.turn == enemy else f" Ход {next_name}."
                await _send_state(
                    context,
                    match,
                    enemy,
                    f"Ход игрока {player_label}: {coord_str} - {msg_body_enemy}{next_phrase}",
                )
    if others:
        msg_body = ' '.join(parts_self) if parts_self else 'мимо'
        for other in others:
            next_phrase = ' Ваш ход.' if match.turn == other else f" Ход {next_name}."
            if match.players[other].user_id != 0:
                await _send_state(
                    context,
                    match,
                    other,
                    f"Ход игрока {player_label}: {coord_str} - {msg_body}{next_phrase}",
                )
    result_self = f"Ваш ход: {coord_str} - {' '.join(parts_self)}" + (
        ' Ваш ход.' if match.turn == player_key else f" Ход {next_name}."
    )
    view_key = match.turn if single_user else player_key
    await _send_state(context, match, view_key, result_self)

    storage.save_match(match)

    alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
    if len(alive_players) == 1:
        winner = alive_players[0]
        storage.finish(match, winner)
        if match.players[winner].user_id != 0:
            await context.bot.send_message(
                match.players[winner].chat_id, 'Вы победили!'
            )
        for k in match.players:
            if k != winner and match.players[k].user_id != 0:
                await context.bot.send_message(
                    match.players[k].chat_id,
                    'Игра окончена. Победил соперник.',
                )
