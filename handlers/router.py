from __future__ import annotations
import random
import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

import storage
from logic.parser import parse_coord, format_coord
from logic.placement import random_board
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
from logic.battle_test import apply_shot_multi
from logic.render import render_board_own, render_board_enemy
from models import Board
from handlers.commands import (
    newgame,
    get_name_state,
    store_player_name,
    finalize_pending_join,
    finalize_board15_join,
    NAME_HINT_NEWGAME,
    NAME_HINT_AUTO,
    NAME_PENDING_BOARD15_JOIN,
)
from .board_test import board_test, board_test_two
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
from app.config import BOARD15_ENABLED


logger = logging.getLogger(__name__)


CHAT_PREFIXES = ("@", "!")


STATE_DELAY = float(os.getenv("STATE_DELAY", "0"))


def _log_router_skip(
    reason: str,
    *,
    match,
    user_id: int,
    text_raw: str,
    level: str = "info",
) -> None:
    log_method = getattr(logger, level, logger.info)
    context = {
        "user_id": user_id,
        "text_raw": text_raw,
        "match_id": getattr(match, "match_id", None),
        "match_status": getattr(match, "status", None),
        "match_turn": getattr(match, "turn", None),
    }
    log_method("%s | context=%s", reason, context)


def _cell_state(cell):
    """Return numerical state from a board cell.

    Cells may store a plain integer or a ``(state, owner)`` tuple. This
    helper extracts the state value so that comparisons work regardless of the
    underlying representation.
    """
    return cell[0] if isinstance(cell, (list, tuple)) else cell


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
) -> None:
    """Send the board and the textual result as a single message."""
    enemy_key = "B" if player_key == "A" else "A"
    chat_id = match.players[player_key].chat_id
    msgs = match.messages.setdefault(player_key, {})

    own = render_board_own(match.boards[player_key])
    enemy = render_board_enemy(match.boards[enemy_key])
    message = message.lstrip('\n')
    if message:
        board_text = f"Поле соперника:\n{enemy}\nВаше поле:\n{own}\n{message}"
    else:
        board_text = f"Поле соперника:\n{enemy}\nВаше поле:\n{own}"

    board_msg = await context.bot.send_message(
        chat_id,
        board_text,
        parse_mode="HTML",
    )

    new_id = board_msg.message_id

    msgs["board"] = new_id
    board_hist = msgs.setdefault("board_history", [])
    board_hist.append(new_id)
    msgs.pop("text", None)

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

    merged = [row[:] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(10):
        for c in range(10):
            cell = own_grid[r][c]
            if merged[r][c] == 0 and _cell_state(cell) == 1:
                # Preserve owner information by copying the full cell value
                merged[r][c] = cell
    board = Board(grid=merged, highlight=getattr(match, "last_highlight", []).copy())
    message = message.lstrip('\n')
    board_body = render_board_own(board)
    if message:
        board_text = f"Ваше поле:\n{board_body}\n{message}"
    else:
        board_text = f"Ваше поле:\n{board_body}"

    new_id = None
    if board_id:
        try:
            edited = await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=board_id,
                text=board_text,
                parse_mode="HTML",
            )
            new_id = getattr(edited, "message_id", board_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await context.bot.delete_message(chat_id, board_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
    if new_id is None:
        board_msg = await context.bot.send_message(
            chat_id,
            board_text,
            parse_mode="HTML",
        )
        new_id = board_msg.message_id

    msgs["board"] = new_id
    msgs.pop("text", None)

    storage.save_match(match)


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот по этому поводу:\n{random_joke()}"
    return random_phrase(phrases)


def _compose_move_message(
    result_line: str, humor: str | None, next_line: str | None
) -> str:
    """Format move summary with optional humor and next-turn line."""

    lines: list[str] = [result_line.strip()]
    humor_text = (humor or "").strip()
    if humor_text:
        lines.append("")
        lines.append(humor_text)
    if next_line:
        if humor_text:
            lines.append("")
        lines.append(next_line.strip())
    return "\n".join(lines)


async def _handle_board_test_two(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    match=None,
) -> bool:
    """Handle two-player test mode turns. Return ``True`` when processed."""

    message = update.message
    if not message:
        return False

    user_id = update.effective_user.id
    text_raw = message.text or ""
    if text_raw.startswith("/"):
        return False

    for entity in getattr(message, "entities", []) or []:
        if getattr(entity, "type", "") == "bot_command" and getattr(entity, "offset", 0) == 0:
            return False

    text = text_raw.strip()
    if match is None:
        match = storage.find_match_by_user(user_id, update.effective_chat.id)
    if not match:
        return False
    flags = match.messages.get("_flags", {}) if isinstance(match.messages, dict) else {}
    if not flags.get("mode_test2"):
        return False

    player_key = "A"
    enemy_key = "B"

    if match.status != "playing":
        return False

    if match.turn != player_key:
        await _send_state(context, match, player_key, "Сейчас ход соперника.")
        return True

    coord = parse_coord(text)
    if coord is None:
        await _send_state(context, match, player_key, "Не понял клетку. Пример: е5 или д10.")
        return True

    for b in match.boards.values():
        b.highlight = []

    result = apply_shot(match.boards[enemy_key], coord)
    match.shots[player_key]["history"].append(text)
    match.shots[player_key]["last_result"] = result
    match.shots[player_key]["last_coord"] = coord
    for key in (player_key, enemy_key):
        shots = match.shots.setdefault(key, {})
        shots.setdefault("move_count", 0)
        shots.setdefault("joke_start", random.randint(1, 10))
        shots["move_count"] += 1

    coord_str = format_coord(coord)
    player_label = getattr(match.players[player_key], "name", "") or player_key
    enemy_label = getattr(match.players[enemy_key], "name", "") or enemy_key

    if result == MISS:
        match.turn = enemy_key
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Мимо.",
            phrase_self,
            "Следующим ходит соперник.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник промахнулся.",
            phrase_enemy,
            "Следующим ходит соперник.",
        )
    elif result == HIT:
        match.turn = player_key
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_HIT).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Ранил корабль игрока {enemy_label}.",
            phrase_self,
            "Следующим ходите вы.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник ранил ваш корабль.",
            phrase_enemy,
            "Следующим ходит соперник.",
        )
    elif result == REPEAT:
        match.turn = player_key
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Клетка уже обстреляна.",
            phrase_self,
            "Следующим ходите вы.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник стрелял по уже обстрелянной клетке.",
            phrase_enemy,
            "Следующим ходит соперник.",
        )
    elif result == KILL:
        phrase_self = _phrase_or_joke(match, player_key, SELF_KILL).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_KILL).strip()
        result_line_self = (
            f"Ваш ход: {coord_str} — Корабль игрока {enemy_label} уничтожен!"
        )
        result_line_enemy = (
            f"Ход игрока {player_label}: {coord_str} — Соперник уничтожил ваш корабль."
        )
        if match.boards[enemy_key].alive_cells == 0:
            storage.finish(match, player_key)
            result_self = _compose_move_message(
                result_line_self,
                phrase_self,
                "Вы победили!🏆",
            )
            result_enemy = _compose_move_message(
                result_line_enemy,
                phrase_enemy,
                "Все ваши корабли уничтожены. Игрок A победил!",
            )
        else:
            match.turn = player_key
            result_self = _compose_move_message(
                result_line_self,
                phrase_self,
                "Следующим ходите вы.",
            )
            result_enemy = _compose_move_message(
                result_line_enemy,
                phrase_enemy,
                "Следующим ходит соперник.",
            )
    else:
        match.turn = enemy_key
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Ошибка.",
            None,
            "Следующим ходит соперник.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Техническая ошибка.",
            None,
            "Следующим ходит соперник.",
        )

    storage.save_match(match)
    await _send_state(context, match, player_key, result_self)
    if match.players[enemy_key].user_id != 0:
        await _send_state(context, match, enemy_key, result_enemy)
    else:
        match.messages.setdefault(enemy_key, {})["last_bot_message"] = result_enemy

    if match.status == "finished":
        await context.bot.send_message(
            match.players[player_key].chat_id,
            "Игра завершена! Используйте /newgame, чтобы начать новую партию.",
        )
    return True


async def router_text_board_test_two(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    handled = await _handle_board_test_two(update, context)
    if handled:
        raise ApplicationHandlerStop
    await router_text(update, context)


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text_raw = update.message.text
    text = text_raw.strip()
    text_lower = text.lower()
    state = get_name_state(context)
    if state.get("waiting"):
        if not text:
            await update.message.reply_text('Имя не может быть пустым. Попробуйте ещё раз.')
            return
        if text.startswith('/'):
            await update.message.reply_text('Введите имя без команд. Например: Иван.')
            return
        hint = state.get("hint", NAME_HINT_NEWGAME)
        pending = state.get("pending")
        cleaned = store_player_name(context, text)
        pending_action = pending.get("action") if pending else None
        if pending_action == "join":
            match_id = pending.get("match_id")
            if match_id:
                success = await finalize_pending_join(update, context, match_id)
                if success:
                    return
            await update.message.reply_text('Не удалось присоединиться к матчу. Попробуйте снова перейти по ссылке приглашения.')
            return
        if pending_action == NAME_PENDING_BOARD15_JOIN:
            match_id = pending.get("match_id")
            await update.message.reply_text(
                f'Имя сохранено: {cleaned}. Присоединяемся к матчу 15×15.'
            )
            if match_id:
                success = await finalize_board15_join(update, context, match_id)
                if success:
                    return
            await update.message.reply_text(
                'Не удалось присоединиться к матчу 15×15. Попробуйте снова перейти по ссылке приглашения.'
            )
            return
        if pending_action in {"board15_create", "board15_test", "board15_test_fast"}:
            if pending_action == "board15_test":
                ack = f'Имя сохранено: {cleaned}. Запускаем тестовый режим 15×15.'
            elif pending_action == "board15_test_fast":
                ack = (
                    f'Имя сохранено: {cleaned}. '
                    "Запускаем ускоренный тестовый режим 15×15."
                )
            else:
                ack = f'Имя сохранено: {cleaned}. Создаём матч 15×15.'
            await update.message.reply_text(ack)
            from game_board15.handlers import finalize_board15_pending

            success = await finalize_board15_pending(update, context, pending)
            if success:
                return
            await update.message.reply_text('Не удалось подготовить матч 15×15. Попробуйте снова команду /board15.')
            return
        if hint == NAME_HINT_AUTO:
            await update.message.reply_text(
                f'Имя сохранено: {cleaned}. Отправьте "авто" для расстановки кораблей.'
            )
        else:
            await update.message.reply_text(
                f'Имя сохранено: {cleaned}. Используйте /newgame, чтобы создать матч.'
            )
        return
    if text_lower == 'начать новую игру':
        await newgame(update, context)
        return
    match = storage.find_match_by_user(user_id, update.effective_chat.id)
    handled_test2 = await _handle_board_test_two(update, context, match)
    if handled_test2:
        return
    if not match and BOARD15_ENABLED:
        from game_board15 import storage as storage15, router as router15
        match15 = storage15.find_match_by_user(user_id, update.effective_chat.id)
        if match15:
            await router15.router_text(update, context)
            return
    if not match:
        _log_router_skip(
            "No active match for user",
            match=match,
            user_id=user_id,
            text_raw=text_raw,
        )
        await update.message.reply_text('Вы не участвуете в матче. Используйте /newgame.')
        return

    player_key = 'A' if match.players['A'].user_id == user_id else 'B'
    enemy_key = 'B' if player_key == 'A' else 'A'

    if text.startswith(CHAT_PREFIXES):
        msg = text[1:].strip()
        for key, player in match.players.items():
            if key != player_key:
                await context.bot.send_message(player.chat_id, msg)
        return

    if match.status == 'placing':
        if text == 'авто':
            board = random_board()
            board.owner = player_key
            storage.save_board(match, player_key, board)
            current_player = match.players.get(player_key)
            player_label = getattr(current_player, 'name', '') or f'Игрок {player_key}'
            if match.status == 'playing':
                message_self = (
                    'Корабли расставлены. Бой начинается! '
                    + ('Ваш ход.' if match.turn == player_key else 'Ход соперника.')
                )
                message_enemy = (
                    f'{player_label} готов. Бой начинается! '
                    + ('Ваш ход.' if match.turn == enemy_key else 'Ход соперника.')
                )
                await _send_state(
                    context,
                    match,
                    player_key,
                    message_self,
                )
                enemy_player = match.players.get(enemy_key)
                if enemy_player and enemy_player.user_id != 0:
                    await _send_state(
                        context,
                        match,
                        enemy_key,
                        message_enemy,
                    )
                else:
                    match.messages.setdefault(enemy_key, {})['last_bot_message'] = (
                        message_enemy
                    )
                    storage.save_match(match)
            else:
                message_self = 'Корабли расставлены. Ожидаем соперника.'
                message_enemy = (
                    f'{player_label} готов. Отправьте "авто" для расстановки кораблей.'
                )
                await _send_state(
                    context,
                    match,
                    player_key,
                    message_self,
                )
                enemy_player = match.players.get(enemy_key)
                if enemy_player and enemy_player.user_id != 0:
                    await _send_state(
                        context,
                        match,
                        enemy_key,
                        message_enemy,
                    )
                    await context.bot.send_message(
                        match.players[enemy_key].chat_id,
                        'Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры.',
                    )
                else:
                    match.messages.setdefault(enemy_key, {})['last_bot_message'] = (
                        message_enemy
                    )
                    storage.save_match(match)
        else:
            await update.message.reply_text('Введите "авто" для автоматической расстановки.')
            _log_router_skip(
                'User provided manual placement input while match in placing status',
                match=match,
                user_id=user_id,
                text_raw=text_raw,
                level="warning",
            )
        return

    if match.status != 'playing':
        if match.status == 'waiting':
            await update.message.reply_text('Матч ещё не начался. Ожидаем соперника.')
        else:
            await update.message.reply_text('Матч ещё не начался.')
        _log_router_skip(
            'Match not ready for playing state',
            match=match,
            user_id=user_id,
            text_raw=text_raw,
        )
        return

    if match.turn != player_key:
        await _send_state(context, match, player_key, 'Сейчас ход соперника.')
        _log_router_skip(
            "Player attempted move out of turn",
            match=match,
            user_id=user_id,
            text_raw=text_raw,
        )
        return

    coord = parse_coord(text)
    if coord is None:
        await _send_state(context, match, player_key, 'Не понял клетку. Пример: е5 или д10.')
        _log_router_skip(
            'Failed to parse coordinate from input',
            match=match,
            user_id=user_id,
            text_raw=text_raw,
            level="warning",
        )
        return

    for b in match.boards.values():
        b.highlight = []

    logger.info(
        "Preparing shot | context=%s",
        {
            "user_id": user_id,
            "text_raw": text_raw,
            "match_id": getattr(match, "match_id", None),
            "match_turn": getattr(match, "turn", None),
            "player_key": player_key,
            "enemy_key": enemy_key,
            "coord": coord,
        },
    )

    result = apply_shot(match.boards[enemy_key], coord)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_result'] = result
    match.shots[player_key]['last_coord'] = coord
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

    logger.info(
        "Shot resolved | context=%s",
        {
            "user_id": user_id,
            "match_id": getattr(match, "match_id", None),
            "coord": coord,
            "result": result,
        },
    )

    eliminated: list[str] = []
    if result == MISS:
        match.turn = enemy_key
        next_player = enemy_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Мимо.",
            phrase_self,
            f"Следующим ходит {next_label}.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник промахнулся.",
            phrase_enemy,
            f"Следующим ходит {next_label}.",
        )
        error = storage.save_match(match)
    elif result == HIT:
        next_player = player_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_HIT).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Ранил корабль игрока {enemy_label}.",
            phrase_self,
            f"Следующим ходит {next_label}.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник ранил ваш корабль.",
            phrase_enemy,
            f"Следующим ходит {next_label}.",
        )
        error = storage.save_match(match)
    elif result == REPEAT:
        next_player = player_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_MISS).strip()
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Клетка уже обстреляна.",
            phrase_self,
            f"Следующим ходит {next_label}.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Соперник стрелял по уже обстрелянной клетке.",
            phrase_enemy,
            f"Следующим ходит {next_label}.",
        )
        error = storage.save_match(match)
    elif result == KILL:
        phrase_self = _phrase_or_joke(match, player_key, SELF_KILL).strip()
        phrase_enemy = _phrase_or_joke(match, enemy_key, ENEMY_KILL).strip()
        result_line_self = (
            f"Ваш ход: {coord_str} — Корабль игрока {enemy_label} уничтожен!"
        )
        result_line_enemy = (
            f"Ход игрока {player_label}: {coord_str} — Соперник уничтожил ваш корабль."
        )
        if match.boards[enemy_key].alive_cells == 0:
            eliminated.append(enemy_key)
            result_self = _compose_move_message(
                result_line_self,
                phrase_self,
                "Вы победили!🏆",
            )
            result_enemy = _compose_move_message(
                result_line_enemy,
                phrase_enemy,
                f"Все ваши корабли уничтожены. Игрок {player_label} победил!",
            )
            error = storage.save_match(match)
        else:
            next_player = player_key
            next_label = getattr(match.players[next_player], 'name', '') or next_player
            result_self = _compose_move_message(
                result_line_self,
                phrase_self,
                f"Следующим ходит {next_label}.",
            )
            result_enemy = _compose_move_message(
                result_line_enemy,
                phrase_enemy,
                f"Следующим ходит {next_label}.",
            )
            error = storage.save_match(match)
    else:
        next_player = enemy_key
        next_label = getattr(match.players[next_player], 'name', '') or next_player
        result_self = _compose_move_message(
            f"Ваш ход: {coord_str} — Ошибка.",
            None,
            f"Следующим ходит {next_label}.",
        )
        result_enemy = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} — Техническая ошибка.",
            None,
            f"Следующим ходит {next_label}.",
        )

    logger.info(
        "Post-shot state | context=%s",
        {
            "user_id": user_id,
            "match_id": getattr(match, "match_id", None),
            "result": result,
            "match_turn": getattr(match, "turn", None),
            "next_player": next_player,
        },
    )

    if error:
        msg = 'Произошла техническая ошибка. Ход прерван.'
        await context.bot.send_message(match.players[player_key].chat_id, msg)
        await context.bot.send_message(match.players[enemy_key].chat_id, msg)
        return

    if match.players['A'].chat_id == match.players['B'].chat_id:
        chat_id = match.players[player_key].chat_id
        enemy_msgs = match.messages.get(enemy_key, {})
        for msg_id in (enemy_msgs.get('board'), enemy_msgs.get('text')):
            if msg_id:
                try:
                    await context.bot.delete_message(chat_id, msg_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
        result_shared = result_self.replace('Ваш ход:', f'Ход игрока {player_label}:')
        result_shared = result_shared.replace('Вы победили!🏆', f'Игрок {player_label} победил!')
        result_shared = result_shared.replace('Вы победили.', f'Игрок {player_label} победил!')
        await _send_state(context, match, player_key, result_shared)
        match.messages[enemy_key] = match.messages[player_key].copy()
        storage.save_match(match)
    else:
        await _send_state(context, match, player_key, result_self)
        await _send_state(context, match, enemy_key, result_enemy)

    for enemy in eliminated:
        enemy_label = getattr(match.players[enemy], 'name', '') or enemy
        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
        if len(alive_players) == 1:
            winner = alive_players[0]
            winner_label = getattr(match.players[winner], 'name', '') or winner
            storage.finish(match, winner)
            for k, p in match.players.items():
                if p.user_id != 0:
                    if k == winner:
                        msg = (
                            f"Флот игрока {enemy_label} потоплен! {enemy_label} занял 2 место. Вы победили!🏆"
                        )
                    else:
                        msg = (
                            f"Флот игрока {enemy_label} потоплен! {enemy_label} занял 2 место. Игрок {winner_label} победил!"
                        )
                    await context.bot.send_message(p.chat_id, msg)
        else:
            for k, p in match.players.items():
                if p.user_id != 0:
                    await context.bot.send_message(
                        p.chat_id,
                        f"Флот игрока {enemy_label} потоплен! {enemy_label} выбывает.",
                    )

    if match.status == 'finished':
        await context.bot.send_message(
            match.players[player_key].chat_id,
            'Игра завершена! Используйте /newgame, чтобы начать новую партию.',
        )
        await context.bot.send_message(
            match.players[enemy_key].chat_id,
            'Игра завершена! Используйте /newgame, чтобы начать новую партию.',
        )


async def router_text_board_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle moves for the three-player test mode."""

    user_id = update.effective_user.id
    text = update.message.text.strip()
    match = storage.find_match_by_user(user_id, update.effective_chat.id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /board_test.')
        return

    player_key = 'A'

    if text.startswith(CHAT_PREFIXES):
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
    for b in match.boards.values():
        b.highlight = []
    results = apply_shot_multi(coord, boards, match.history)
    match.shots[player_key]['history'].append(text)
    match.shots[player_key]['last_coord'] = coord
    if any(res == KILL for res in results.values()):
        cells: list[tuple[int, int]] = []
        for enemy, res in results.items():
            if res == KILL:
                cells.extend(match.boards[enemy].highlight)
        match.last_highlight = cells.copy()
        match.shots[player_key]['last_result'] = 'kill'
    elif any(res == HIT for res in results.values()):
        match.last_highlight = [coord]
        match.shots[player_key]['last_result'] = 'hit'
    else:
        match.last_highlight = [coord]
        match.shots[player_key]['last_result'] = 'miss'
    for k in match.shots:
        shots = match.shots.setdefault(k, {})
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1

    coord_str = format_coord(coord)
    hit_any = any(res in (HIT, KILL, REPEAT) for res in results.values())
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
    enemy_msgs: dict[str, tuple[str, str, str]] = {}
    for enemy, res in results.items():
        enemy_label = getattr(match.players[enemy], 'name', '') or enemy
        if res == MISS:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).strip()
            self_msgs[enemy] = (
                f"{enemy_label}: мимо. {phrase_self}" if phrase_self else f"{enemy_label}: мимо."
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} — соперник промахнулся.",
                phrase_enemy,
            )
        elif res == HIT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_HIT).strip()
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT).strip()
            self_msgs[enemy] = (
                f"{enemy_label}: ранил. {phrase_self}" if phrase_self else f"{enemy_label}: ранил."
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} — ваш корабль ранен.",
                phrase_enemy,
            )
        elif res == KILL:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL).strip()
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL).strip()
            self_msgs[enemy] = (
                f"{enemy_label}: уничтожен! {phrase_self}" if phrase_self else f"{enemy_label}: уничтожен!"
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} — ваш корабль уничтожен.",
                phrase_enemy,
            )
            if (
                match.boards[enemy].alive_cells == 0
                and match.players[enemy].user_id != 0
            ):
                await context.bot.send_message(
                    match.players[enemy].chat_id,
                    f"⛔ Игрок {enemy_label} выбыл (флот уничтожен)",
                )
        elif res == REPEAT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).strip()
            self_msgs[enemy] = (
                f"{enemy_label}: клетка уже обстреляна. {phrase_self}"
                if phrase_self
                else f"{enemy_label}: клетка уже обстреляна."
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} — соперник стрелял по уже обстрелянной клетке.",
                phrase_enemy,
            )

    next_label = getattr(match.players[next_player], 'name', '') or next_player
    next_phrase_self = f"Следующим ходит {next_label}."
    summary = random.choice(list(self_msgs.values())) if self_msgs else ''
    if summary:
        self_lines = [f"Ваш ход: {coord_str} — {summary}"]
    else:
        self_lines = [f"Ваш ход: {coord_str}"]
    self_lines.append(next_phrase_self)
    storage.save_match(match)
    await _send_state_board_test(
        context,
        match,
        player_key,
        "\n".join(self_lines),
    )

    for enemy, (res, result_line_enemy, humor_enemy) in enemy_msgs.items():
        if res not in (HIT, KILL):
            continue
        if match.players[enemy].user_id != 0:
            next_phrase = f"Следующим ходит {next_label}."
            message_enemy = _compose_move_message(
                result_line_enemy,
                humor_enemy,
                next_phrase,
            )
            await _send_state_board_test(
                context,
                match,
                enemy,
                message_enemy,
            )

    alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
    if len(alive_players) == 1:
        winner = alive_players[0]
        storage.finish(match, winner)
        if winner == player_key:
            await context.bot.send_message(match.players[player_key].chat_id, 'Вы победили!')
        else:
            await context.bot.send_message(match.players[player_key].chat_id, 'Игра окончена. Победил соперник.')
