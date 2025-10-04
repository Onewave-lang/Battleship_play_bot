from __future__ import annotations
import copy
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
from .utils import (
    _phrase_or_joke,
    _get_cell_state,
    _get_cell_owner,
    _set_cell_state,
    _persist_highlight_to_history,
    record_snapshot,
)


logger = logging.getLogger(__name__)


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
    *,
    reveal_ships: bool = True,
    snapshot_override: dict | None = None,
    include_all_ships: bool = False,
) -> None:
    """Render and send main board image followed by text message."""

    chat_id = match.players[player_key].chat_id
    states = context.bot_data.setdefault(STATE_KEY, {})
    state: Board15State | None = states.get(chat_id)
    if not state:
        state = Board15State(chat_id=chat_id)
        states[chat_id] = state

    snapshot = snapshot_override
    if snapshot is None:
        snapshot = match.snapshots[-1] if getattr(match, "snapshots", []) else None
    history_source = snapshot.get("history") if snapshot else None
    if not history_source:
        history_source = match.history
    merged_states = [[_get_cell_state(cell) for cell in row] for row in history_source]
    owners = [[_get_cell_owner(cell) for cell in row] for row in history_source]
    if include_all_ships:
        board_sources: dict[str, list[list[int]]] = {}
        if snapshot:
            board_sources = {
                key: board_data.get("grid", [])
                for key, board_data in snapshot.get("boards", {}).items()
            }
        else:
            board_sources = {key: board.grid for key, board in match.boards.items()}
        for owner_key, grid in board_sources.items():
            if not grid:
                continue
            is_recipient_board = owner_key == player_key
            for r in range(min(len(grid), 15)):
                row = grid[r]
                for c in range(min(len(row), 15)):
                    if row[c] != 1:
                        continue
                    history_state = merged_states[r][c]
                    if history_state not in {0, 1}:
                        if owners[r][c] is None:
                            owners[r][c] = owner_key
                        continue
                    if not (is_recipient_board and reveal_ships):
                        continue
                    merged_states[r][c] = 1
                    owners[r][c] = owner_key
    if reveal_ships:
        if snapshot and player_key in snapshot.get("boards", {}):
            own_grid = snapshot["boards"][player_key]["grid"]
            live_grid = match.boards[player_key].grid
            mismatch_found = False
            max_rows = min(len(live_grid), len(own_grid))
            for r in range(max_rows):
                live_row = live_grid[r]
                snapshot_row = own_grid[r]
                max_cols = min(len(live_row), len(snapshot_row))
                for c in range(max_cols):
                    if live_row[c] == 1 and snapshot_row[c] != 1:
                        logger.warning(
                            "Snapshot grid missing ship cell for player %s at (%s, %s); refreshing",
                            player_key,
                            r,
                            c,
                        )
                        mismatch_found = True
                        break
                if mismatch_found:
                    break
                if len(live_row) > max_cols:
                    for c in range(max_cols, len(live_row)):
                        if live_row[c] == 1:
                            logger.warning(
                                "Snapshot grid missing ship cell for player %s at (%s, %s); refreshing",
                                player_key,
                                r,
                                c,
                            )
                            mismatch_found = True
                            break
                if mismatch_found:
                    break
            if not mismatch_found and len(live_grid) > max_rows:
                for r in range(max_rows, len(live_grid)):
                    row = live_grid[r]
                    for c, value in enumerate(row):
                        if value == 1:
                            logger.warning(
                                "Snapshot grid missing ship cell for player %s at (%s, %s); refreshing",
                                player_key,
                                r,
                                c,
                            )
                            mismatch_found = True
                            break
                    if mismatch_found:
                        break
            if mismatch_found:
                fresh_grid = copy.deepcopy(live_grid)
                own_grid = fresh_grid
                if snapshot:
                    snapshot["boards"][player_key]["grid"] = fresh_grid
        else:
            own_grid = match.boards[player_key].grid
        for r in range(15):
            for c in range(15):
                cell = own_grid[r][c]
                if _get_cell_state(cell) != 1:
                    continue
                history_state = merged_states[r][c]
                history_owner = owners[r][c]
                if history_state in {3, 4} and history_owner == player_key:
                    continue
                if history_state in {2, 5}:
                    logger.warning(
                        "Correcting state %s for player %s at (%s, %s)",
                        history_state,
                        player_key,
                        r,
                        c,
                    )
                merged_states[r][c] = 1
                owners[r][c] = player_key
    state.board = merged_states
    state.owners = owners
    state.player_key = player_key
    if snapshot:
        state.highlight = [tuple(cell) for cell in snapshot.get("last_highlight", [])]
    else:
        state.highlight = getattr(match, "last_highlight", []).copy()
    buf = render_board(state, player_key)
    if buf.getbuffer().nbytes == 0:
        logger.warning("render_board returned empty buffer for chat %s", chat_id)
        return

    msgs = match.messages.setdefault(player_key, {})

    # send main board image with caption text
    try:
        buf.seek(0)
        msg = await context.bot.send_photo(chat_id, buf, caption=message)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to send board image for chat %s", chat_id)
        return
    state.message_id = msg.message_id
    msgs["board"] = msg.message_id
    msgs.pop("text", None)
    board_hist = msgs.setdefault("board_history", [])
    text_hist = msgs.setdefault("text_history", [])
    if msgs.get("history_active"):
        board_hist.append(msg.message_id)
        text_hist.append(msg.message_id)


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
    if _get_cell_state(match.boards[player_key].grid[r][c]) == 1:
        await update.message.reply_text('Здесь ваш корабль')
        return

    # Persist previous highlights before clearing so that red marks remain
    # as permanent dots on the board history.
    _persist_highlight_to_history(match)

    state = _get_cell_state(match.history[r][c])
    if state in {2, 3, 4, 5}:
        await update.message.reply_text('Эта клетка уже обстреляна')
        return

    if not single_user and match.turn != player_key:
        await update.message.reply_text('Сейчас ход другого игрока.')
        return

    enemy_cell_states = {
        enemy: _get_cell_state(match.boards[enemy].grid[r][c])
        for enemy in enemy_keys
    }
    if any(state in {2, 3, 4, 5} for state in enemy_cell_states.values()):
        await update.message.reply_text('Эта клетка уже обстреляна')
        return

    results = {}
    repeat = False
    for enemy in enemy_keys:
        res = battle.apply_shot(match.boards[enemy], coord)
        results[enemy] = res
        if res == battle.REPEAT:
            repeat = True
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
    after_history = [[_get_cell_state(cell) for cell in row] for row in match.history]
    history_unchanged = after_history == before_history
    history_empty = all(all(state == 0 for state in row) for row in after_history)
    if history_unchanged:
        logger.warning("History unchanged after shot %s", coord_str)
    if history_empty:
        logger.warning("History is empty after shot %s", coord_str)
    cell_state = _get_cell_state(match.history[r][c])
    if cell_state == 0:
        logger.warning(
            "History cell %s is still empty after shot %s; applying fallback",
            (r, c),
            coord_str,
        )
        if any(res == battle.KILL for res in results.values()):
            best_value = 4
            owner = next(
                (enemy for enemy, res in results.items() if res == battle.KILL),
                None,
            )
        elif any(res == battle.HIT for res in results.values()):
            best_value = 3
            owner = next(
                (enemy for enemy, res in results.items() if res == battle.HIT),
                None,
            )
        else:
            best_value = 2
            owner = None
        if owner is None:
            owner = _get_cell_owner(match.history[r][c])
        _set_cell_state(match.history, r, c, best_value, owner)
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

    match.shots[player_key]["last_coord"] = coord
    shot_hist = match.shots[player_key].setdefault("history", [])
    for enemy, res in results.items():
        shot_hist.append({"coord": coord, "enemy": enemy, "result": res})
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
    hit_any = any(
        res in (battle.HIT, battle.KILL, battle.REPEAT) for res in results.values()
    )
    order = [
        k
        for k in ('A', 'B', 'C')
        if k in match.players and match.boards[k].alive_cells > 0
    ]
    idx = order.index(player_key)
    if hit_any:
        next_player = player_key
    else:
        next_player = order[(idx + 1) % len(order)]
    match.turn = next_player
    record_snapshot(match, actor=player_key, coord=coord)
    next_obj = match.players.get(next_player)
    next_name = getattr(next_obj, 'name', '') or next_player
    chat_counts: dict[int, int] = {}
    for participant in match.players.values():
        chat_counts[participant.chat_id] = chat_counts.get(participant.chat_id, 0) + 1
    same_chat = len(chat_counts) == 1
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
    shared_text = (
        f"Ход игрока {player_label}: {coord_str} - {body_self} {phrase_self} Следующим ходит {next_name}."
    )
    personal_text = (
        f"Ваш ход: {coord_str} - {body_self} {phrase_self} Следующим ходит {next_name}."
    )
    if same_chat:
        latest_snapshot = match.snapshots[-1] if getattr(match, "snapshots", []) else None
        await _send_state(
            context,
            match,
            player_key,
            shared_text,
            snapshot_override=latest_snapshot,
            include_all_ships=True,
        )
        private_receivers = [
            key
            for key, participant in match.players.items()
            if chat_counts.get(participant.chat_id, 0) == 1 and participant.user_id != 0
        ]
        for key in private_receivers:
            if key == player_key:
                await _send_state(
                    context,
                    match,
                    key,
                    personal_text,
                    reveal_ships=True,
                )
            elif key in enemy_msgs:
                _, msg_body_enemy = enemy_msgs[key]
                next_phrase = f" Следующим ходит {next_name}."
                await _send_state(
                    context,
                    match,
                    key,
                    f"Ход игрока {player_label}: {coord_str} - {msg_body_enemy}{next_phrase}",
                    reveal_ships=True,
                )
            elif key in others:
                next_phrase = f" Следующим ходит {next_name}."
                watch_body = msg_watch.rstrip()
                if not watch_body.endswith((".", "!", "?")):
                    watch_body += "."
                await _send_state(
                    context,
                    match,
                    key,
                    f"Ход игрока {player_label}: {coord_str} - {watch_body} {phrase_self}{next_phrase}",
                    reveal_ships=True,
                )
    elif single_user:
        await _send_state(context, match, player_key, shared_text)
    else:
        await _send_state(context, match, player_key, personal_text)

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
