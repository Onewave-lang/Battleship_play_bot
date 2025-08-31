from __future__ import annotations
import logging
import random
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from . import storage
from . import battle, parser
from .handlers import STATE_KEY
from .renderer import render_board
from .state import Board15State
from logic.phrases import (
    ENEMY_HIT,
    ENEMY_KILL,
    ENEMY_MISS,
    SELF_HIT,
    SELF_KILL,
    SELF_MISS,
)
from .utils import _phrase_or_joke, _get_cell_state, _get_cell_owner, _set_cell_state


logger = logging.getLogger(__name__)


async def _send_state(context: ContextTypes.DEFAULT_TYPE, match, player_key: str, message: str) -> None:
    """Render and send main board image followed by text message."""

    chat_id = match.players[player_key].chat_id
    states = context.bot_data.setdefault(STATE_KEY, {})
    state: Board15State | None = states.get(chat_id)
    if not state:
        state = Board15State(chat_id=chat_id)
        states[chat_id] = state

    # prepare board images
    merged_states = [[_get_cell_state(cell) for cell in row] for row in match.history]
    owners = [[_get_cell_owner(cell) for cell in row] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(15):
        for c in range(15):
            if merged_states[r][c] == 0 and own_grid[r][c] == 1:
                merged_states[r][c] = 1
                owners[r][c] = player_key
    state.board = merged_states
    state.owners = owners
    state.player_key = player_key
    state.highlight = getattr(match, "last_highlight", []).copy()
    buf = render_board(state, player_key)
    if buf.getbuffer().nbytes == 0:
        logger.warning("render_board returned empty buffer for chat %s", chat_id)
        return

    msgs = match.messages.setdefault(player_key, {})

    # always send main board image
    try:
        buf.seek(0)
        msg_board = await context.bot.send_photo(chat_id, buf)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to send board image for chat %s", chat_id)
        return
    state.message_id = msg_board.message_id
    msgs["board"] = msg_board.message_id
    board_hist = msgs.setdefault("board_history", [])
    if msgs.get("history_active"):
        board_hist.append(msg_board.message_id)

    # send result text message
    try:
        msg_text = await context.bot.send_message(chat_id, message)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to send text message for chat %s", chat_id)
        return
    msgs["text"] = msg_text.message_id
    text_hist = msgs.setdefault("text_history", [])
    if msgs.get("history_active"):
        text_hist.append(msg_text.message_id)


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

    coord = parser.parse_coord(text)
    if coord is None:
        await update.message.reply_text('Не понял клетку. Пример: e5.')
        return
    r, c = coord
    if match.boards[player_key].grid[r][c] == 1:
        await update.message.reply_text('Здесь ваш корабль')
        return

    # Persist previous highlights before clearing so that red marks remain
    # as permanent dots on the board history.
    for b in match.boards.values():
        if b.highlight:
            for rr, cc in b.highlight:
                if _get_cell_state(match.history[rr][cc]) == 0:
                    _set_cell_state(match.history, rr, cc, 2)
        b.highlight = []

    state = _get_cell_state(match.history[r][c])
    if state in {2, 3, 4, 5}:
        await update.message.reply_text('Эта клетка уже обстреляна')
        return

    if not single_user and match.turn != player_key:
        await update.message.reply_text('Сейчас ход другого игрока.')
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
        await update.message.reply_text('Эта клетка уже обстреляна')
        return

    if match.players[player_key].user_id != 0:
        msgs = match.messages.setdefault(player_key, {})
        if not msgs.get("history_active"):
            msgs["history_active"] = True
    coord_str = parser.format_coord(coord)
    before_history = [[_get_cell_state(cell) for cell in row] for row in match.history]
    battle.update_history(match.history, match.boards, coord, results)
    if [[_get_cell_state(cell) for cell in row] for row in match.history] == before_history:
        logger.warning("History unchanged after shot %s", coord_str)
    if all(
        all(_get_cell_state(cell) == 0 for cell in row)
        for row in match.history
    ):
        logger.warning("History is empty after shot %s", coord_str)
    match.shots[player_key]["last_coord"] = coord
    shot_hist = match.shots[player_key].setdefault("history", [])
    for enemy, res in results.items():
        shot_hist.append({"coord": coord, "enemy": enemy, "result": res})
    if any(res == battle.KILL for res in results.values()):
        cells: list[tuple[int, int]] = []
        for enemy, res in results.items():
            if res == battle.KILL:
                cells.extend(match.boards[enemy].highlight)
        match.last_highlight = [coord] + [c for c in cells if c != coord]
        match.shots[player_key]["last_result"] = "kill"
    elif any(res == battle.HIT for res in results.values()):
        match.last_highlight = [coord]
        match.shots[player_key]["last_result"] = "hit"
    else:
        match.last_highlight = [coord]
        match.shots[player_key]["last_result"] = "miss"
    storage.save_match(match)
    for k in match.shots:
        shots = match.shots[k]
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1

    parts_self: list[str] = []
    watch_parts: list[str] = []
    # keep both the original result value and the message body for each enemy
    # so that the result (miss/hit/kill) is not lost for later processing
    enemy_msgs: dict[str, tuple[str, str]] = {}
    targets: list[str] = []
    next_player = player_key
    player_obj = match.players.get(player_key)
    player_label = getattr(player_obj, "name", "") or player_key
    eliminated: list[str] = []
    for enemy, res in results.items():
        enemy_obj = match.players.get(enemy)
        enemy_label = getattr(enemy_obj, "name", "") or enemy
        if res == battle.HIT:
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
            parts_self.append(f"корабль игрока {enemy_label} ранен.")
            watch_parts.append(
                f"игрок {player_label} поразил корабль игрока {enemy_label}."
            )
            enemy_msgs[enemy] = (res, f"ваш корабль ранен. {phrase_enemy}")
            targets.append(enemy)
        elif res == battle.KILL:
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
            parts_self.append(f"уничтожен корабль игрока {enemy_label}!")
            watch_parts.append(
                f"игрок {player_label} поразил корабль игрока {enemy_label}."
            )
            enemy_msgs[enemy] = (res, f"ваш корабль уничтожен. {phrase_enemy}")
            targets.append(enemy)
            if match.boards[enemy].alive_cells == 0:
                eliminated.append(enemy)

    if any(res == battle.KILL for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
    elif any(res == battle.HIT for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
    elif any(res == battle.REPEAT for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
    else:
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)

    msg_watch = ' '.join(watch_parts).strip() or 'мимо'
    others = [
        k
        for k in match.players
        if k not in enemy_msgs and k != player_key and match.boards[k].alive_cells > 0
    ]
    order = [
        k
        for k in ('A', 'B', 'C')
        if k in match.players and match.boards[k].alive_cells > 0
    ]
    idx = order.index(player_key)
    next_player = order[(idx + 1) % len(order)]
    match.turn = next_player
    next_obj = match.players.get(next_player)
    next_name = getattr(next_obj, 'name', '') or next_player
    same_chat = len({p.chat_id for p in match.players.values()}) == 1
    if enemy_msgs and not same_chat:
        for enemy, (res_enemy, msg_body_enemy) in enemy_msgs.items():
            if match.players[enemy].user_id != 0:
                next_phrase = f" Следующим ходит {next_name}."
                await _send_state(
                    context,
                    match,
                    enemy,
                    f"Ход игрока {player_label}: {coord_str} - {msg_body_enemy}{next_phrase}",
                )
    if others and not same_chat:
        for other in others:
            next_phrase = f" Следующим ходит {next_name}."
            if match.players[other].user_id != 0:
                watch_body = msg_watch.rstrip()
                if not watch_body.endswith(('.', '!', '?')):
                    watch_body += '.'
                await _send_state(
                    context,
                    match,
                    other,
                    f"Ход игрока {player_label}: {coord_str} - {watch_body} {phrase_self}{next_phrase}",
                )
    msg_body = ' '.join(parts_self) if parts_self else 'мимо'
    body_self = msg_body.rstrip()
    if not body_self.endswith(('.', '!', '?')):
        body_self += '.'
    if same_chat or single_user:
        result_self = (
            f"Ход игрока {player_label}: {coord_str} - {body_self} {phrase_self} Следующим ходит {next_name}."
        )
        view_key = player_key
    else:
        result_self = f"Ваш ход: {coord_str} - {body_self} {phrase_self} Следующим ходит {next_name}."
        view_key = player_key
    await _send_state(context, match, view_key, result_self)

    storage.save_match(match)

    for enemy in eliminated:
        enemy_label = getattr(match.players[enemy], "name", "") or enemy
        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
        if len(alive_players) == 1:
            winner = alive_players[0]
            winner_label = getattr(match.players[winner], "name", "") or winner
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
