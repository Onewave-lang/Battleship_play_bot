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
from .utils import (
    _phrase_or_joke,
    _get_cell_state,
    _get_cell_owner,
    _set_cell_state,
    _persist_highlight_to_history,
    record_snapshot,
)


logger = logging.getLogger(__name__)


CHAT_PREFIXES = ("@", "!")


def _compose_move_message(
    result_line: str, humor: str | None, next_line: str | None
) -> str:
    """Return formatted message with blank lines between sections."""

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

    def _grid_value(grid: list[list[int]], r: int, c: int) -> int:
        if r < len(grid):
            row = grid[r]
            if c < len(row):
                return _get_cell_state(row[c])
        return 0

    def _copy_grid(grid: list[list[int]]) -> list[list[int]]:
        return [row.copy() for row in grid]

    board_sources: dict[str, list[list[int]]] = {}
    snapshot_boards = snapshot.get("boards", {}) if snapshot else {}
    if snapshot:
        boards_section = snapshot.setdefault("boards", {})
    else:
        boards_section = {}

    for owner_key, board in match.boards.items():
        live_grid = board.grid
        if snapshot:
            board_entry = boards_section.setdefault(owner_key, {})
            snapshot_grid = board_entry.get("grid")
            mismatch_coord: tuple[int | None, int | None] | None = None
            if snapshot_grid is None:
                mismatch_coord = (None, None)
            else:
                for rr in range(15):
                    for cc in range(15):
                        if _grid_value(live_grid, rr, cc) == 1 and _grid_value(
                            snapshot_grid, rr, cc
                        ) != 1:
                            mismatch_coord = (rr, cc)
                            break
                    if mismatch_coord:
                        break
            if mismatch_coord:
                rr, cc = mismatch_coord
                if rr is not None and cc is not None:
                    logger.warning(
                        "Snapshot grid mismatch for player %s at (%s, %s); refreshing",
                        owner_key,
                        rr,
                        cc,
                    )
                else:
                    logger.warning(
                        "Snapshot grid missing ship data for player %s; refreshing",
                        owner_key,
                    )
                fresh_grid = _copy_grid(live_grid)
                board_entry["grid"] = fresh_grid
                snapshot_grid = fresh_grid
            board_sources[owner_key] = board_entry.get("grid", [])
        else:
            board_sources[owner_key] = live_grid

    for owner_key, board_data in snapshot_boards.items():
        if owner_key not in board_sources:
            board_sources[owner_key] = board_data.get("grid", [])

    shared_view = any(
        other_key != player_key
        and getattr(other_player, "chat_id", None) == chat_id
        for other_key, other_player in match.players.items()
    )
    reuse_snapshot_enemy_ships = not include_all_ships and not shared_view

    for owner_key, grid in board_sources.items():
        if not grid:
            continue
        snapshot_grid = None
        if snapshot:
            owner_snapshot = snapshot_boards.get(owner_key)
            if owner_snapshot:
                snapshot_grid = owner_snapshot.get("grid")
        for r in range(min(len(grid), 15)):
            row = grid[r]
            for c in range(min(len(row), 15)):
                cell_state = _get_cell_state(row[c])
                if cell_state != 1:
                    if owners[r][c] is None and cell_state in {3, 4, 5}:
                        owners[r][c] = owner_key
                    continue
                if owner_key != player_key:
                    if include_all_ships:
                        pass
                    else:
                        snapshot_cell_has_ship = (
                            snapshot_grid is not None
                            and _grid_value(snapshot_grid, r, c) == 1
                        )
                        if not (reuse_snapshot_enemy_ships and snapshot_cell_has_ship):
                            logger.debug(
                                "Hiding ship at (%s, %s) for viewer %s owned by %s; "
                                "reuse_snapshot=%s snapshot_has_ship=%s include_all_ships=%s shared_view=%s",
                                r,
                                c,
                                player_key,
                                owner_key,
                                reuse_snapshot_enemy_ships,
                                snapshot_cell_has_ship,
                                include_all_ships,
                                shared_view,
                            )
                            continue
                        cell_state = 1
                if merged_states[r][c] == 0:
                    merged_states[r][c] = 1
                if owners[r][c] is None:
                    owners[r][c] = owner_key
    if reveal_ships:
        own_grid = board_sources.get(player_key, match.boards[player_key].grid)
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

    if text.startswith(CHAT_PREFIXES):
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
    enemy_msgs: dict[str, tuple[int, str, str]] = {}
    targets: list[str] = []
    player_obj = match.players.get(player_key)
    player_label = getattr(player_obj, "name", "") or player_key
    eliminated: list[str] = []
    for enemy, res in results.items():
        enemy_obj = match.players.get(enemy)
        enemy_label = getattr(enemy_obj, "name", "") or enemy
        if res == battle.HIT:
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT).strip()
            parts_self.append(f"корабль игрока {enemy_label} ранен.")
            watch_parts.append(
                f"игрок {player_label} поразил корабль игрока {enemy_label}."
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} - ваш корабль ранен.",
                phrase_enemy,
            )
            targets.append(enemy)
        elif res == battle.KILL:
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL).strip()
            parts_self.append(f"уничтожен корабль игрока {enemy_label}!")
            watch_parts.append(
                f"игрок {player_label} поразил корабль игрока {enemy_label}."
            )
            enemy_msgs[enemy] = (
                res,
                f"Ход игрока {player_label}: {coord_str} - ваш корабль уничтожен.",
                phrase_enemy,
            )
            targets.append(enemy)
            if match.boards[enemy].alive_cells == 0:
                eliminated.append(enemy)

    if any(res == battle.KILL for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_KILL).strip()
    elif any(res == battle.HIT for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_HIT).strip()
    elif any(res == battle.REPEAT for res in results.values()):
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()
    else:
        phrase_self = _phrase_or_joke(match, player_key, SELF_MISS).strip()

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
        for enemy, (_, result_line_enemy, humor_enemy) in enemy_msgs.items():
            if match.players[enemy].user_id != 0:
                message_enemy = _compose_move_message(
                    result_line_enemy,
                    humor_enemy,
                    f"Следующим ходит {next_name}.",
                )
                await _send_state(context, match, enemy, message_enemy)
    if others and not same_chat:
        for other in others:
            if match.players[other].user_id != 0:
                watch_body = msg_watch.rstrip()
                if not watch_body.endswith(('.', '!', '?')):
                    watch_body += '.'
                watch_message = _compose_move_message(
                    f"Ход игрока {player_label}: {coord_str} - {watch_body}",
                    phrase_self,
                    f"Следующим ходит {next_name}.",
                )
                await _send_state(context, match, other, watch_message)
    msg_body = ' '.join(parts_self) if parts_self else 'мимо'
    body_self = msg_body.rstrip()
    if not body_self.endswith(('.', '!', '?')):
        body_self += '.'
    save_before_send = any(res == battle.KILL for res in results.values())
    shared_text = _compose_move_message(
        f"Ход игрока {player_label}: {coord_str} - {body_self}",
        phrase_self,
        f"Следующим ходит {next_name}.",
    )
    personal_text = _compose_move_message(
        f"Ваш ход: {coord_str} - {body_self}",
        phrase_self,
        f"Следующим ходит {next_name}.",
    )
    if save_before_send:
        storage.save_match(match)
    if same_chat:
        watch_body = msg_watch.rstrip()
        if not watch_body.endswith((".", "!", "?")):
            watch_body += "."
        watch_message = _compose_move_message(
            f"Ход игрока {player_label}: {coord_str} - {watch_body}",
            phrase_self,
            f"Следующим ходит {next_name}.",
        )
        enemy_personal_texts: dict[str, str] = {}
        for enemy, (_, result_line_enemy, humor_enemy) in enemy_msgs.items():
            enemy_personal_texts[enemy] = _compose_move_message(
                result_line_enemy,
                humor_enemy,
                f"Следующим ходит {next_name}.",
            )

        for key, participant in match.players.items():
            if key == player_key:
                message_text = personal_text
            elif key in enemy_personal_texts:
                message_text = enemy_personal_texts[key]
            elif key in others:
                message_text = watch_message
            else:
                message_text = shared_text

            await _send_state(
                context,
                match,
                key,
                message_text,
                reveal_ships=True,
                include_all_ships=False,
            )
    elif single_user:
        await _send_state(context, match, player_key, shared_text)
    else:
        await _send_state(context, match, player_key, personal_text)

    if not save_before_send:
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
