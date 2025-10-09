from __future__ import annotations

import asyncio
import logging
import random
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
    ensure_ship_owners,
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
    for owner_key, board in match.boards.items():
        ensure_ship_owners(match.history, board, owner_key)

    history_source = snapshot.get("history") if snapshot else None
    if not history_source:
        history_source = match.history
    history_states = [[_get_cell_state(cell) for cell in row] for row in history_source]
    combined_board = [row.copy() for row in history_states]
    combined_owners = [[_get_cell_owner(cell) for cell in row] for row in history_source]

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
        # ``board.grid`` is the single source of truth for live ship cells when
        # composing the shared view.  If anything in the previous processing
        # pipeline accidentally wiped a ship segment (sets state to ``0``), the
        # viewer would later see an empty cell instead of their own ship.  That
        # scenario was observed in production and must be considered invalid.
        #
        # We therefore enforce that every alive ship cell remains marked as
        # ``1`` in the live grid before further merging.  In addition to
        # restoring the values we also keep track of the corrections so that
        # the root cause can be investigated via logs.
        if getattr(board, "ships", None):
            restored: list[tuple[int, int, int]] = []
            for ship in board.ships:
                if not getattr(ship, "alive", True):
                    continue
                for rr, cc in ship.cells:
                    if not (0 <= rr < 15 and 0 <= cc < 15):
                        continue
                    current_state = _get_cell_state(board.grid[rr][cc])
                    if current_state != 0:
                        continue
                    board.grid[rr][cc] = 1
                    restored.append((rr, cc, current_state))
            if restored:
                logger.critical(
                    "Restored %d live ship cells for %s before rendering: %s",
                    len(restored),
                    owner_key,
                    restored,
                )
        live_grid = board.grid
        if snapshot:
            board_entry = boards_section.setdefault(owner_key, {})
            snapshot_grid = board_entry.get("grid")
            mismatch_coord: tuple[int | None, int | None] | None = None
            prefer_snapshot = False
            original_snapshot_grid = snapshot_grid
            if snapshot_grid is None:
                mismatch_coord = (None, None)
            else:
                for rr in range(15):
                    for cc in range(15):
                        live_state = _grid_value(live_grid, rr, cc)
                        if live_state != _grid_value(snapshot_grid, rr, cc):
                            mismatch_coord = (rr, cc)
                            break
                    if mismatch_coord:
                        break
                if mismatch_coord:
                    rr, cc = mismatch_coord
                    snapshot_state = (
                        _grid_value(original_snapshot_grid, rr, cc)
                        if original_snapshot_grid is not None
                        else 0
                    )
                    live_state = _grid_value(live_grid, rr, cc)
                    if live_state == 0 and snapshot_state != 0:
                        prefer_snapshot = True
                    elif snapshot_state == 0 and live_state != 0:
                        prefer_snapshot = False
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
            if mismatch_coord and prefer_snapshot and original_snapshot_grid is not None:
                board_sources[owner_key] = original_snapshot_grid
            else:
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
    for owner_key, grid in board_sources.items():
        if not grid:
            continue
        for r in range(min(len(grid), 15)):
            row = grid[r]
            for c in range(min(len(row), 15)):
                cell_state = _get_cell_state(row[c])
                if cell_state == 0:
                    continue
                existing_state = combined_board[r][c]
                if cell_state != 1:
                    # не даём "чужим" 3/4/5 затирать нашу живую 1
                    if existing_state == 0 or (
                        existing_state == 1 and cell_state in {3, 4, 5}
                        and combined_owners[r][c] == owner_key
                    ):
                        combined_board[r][c] = cell_state
                        if cell_state in {3, 4, 5}:
                            combined_owners[r][c] = owner_key
                if cell_state == 1:
                    if owner_key == player_key:
                        # свои палубы ВСЕГДА поверх базы/следов (0/2/5/1 любого владельца)
                        combined_board[r][c] = 1
                        combined_owners[r][c] = owner_key
                    elif existing_state == 0:
                        # чужие '1' кладём только на пустую базу
                        combined_board[r][c] = 1
                        combined_owners[r][c] = owner_key
                    continue

    view_board = [row.copy() for row in combined_board]
    view_owners = [[owner for owner in row] for row in combined_owners]

    own_live_grid = match.boards[player_key].grid

    if not include_all_ships:
        for r in range(15):
            for c in range(15):
                owner = view_owners[r][c]
                if owner == player_key:
                    continue
                if _get_cell_state(own_live_grid[r][c]) == 1:
                    # ✅ не скрываем свои корабли, даже если ключ отличается
                    continue
                if owner is None:
                    continue
                if view_board[r][c] != 1:
                    continue
                history_state = history_states[r][c]
                history_owner = _get_cell_owner(history_source[r][c])
                if history_owner == owner and history_state != 0:
                    continue
                if history_state in {3, 4, 5}:
                    continue
                logger.debug(
                    "Hiding ship at (%s, %s) for viewer %s owned by %s; "
                    "include_all_ships=%s shared_view=%s",
                    r,
                    c,
                    player_key,
                    owner,
                    include_all_ships,
                    shared_view,
                )
                view_board[r][c] = 0
                view_owners[r][c] = None

    if reveal_ships:
        own_grid = match.boards[player_key].grid
        restored_cells: list[tuple[int, int]] = []
        for r in range(15):
            for c in range(15):
                own_state = _get_cell_state(own_grid[r][c])
                if own_state == 0:
                    continue
                if own_state in {3, 4}:
                    # попадания/убийства по своим кораблям всегда отражаем
                    view_board[r][c] = own_state
                    view_owners[r][c] = player_key
                    continue
                if own_state == 1:
                    # безусловно кладём свои палубы поверх всего
                    if view_board[r][c] != 1 or view_owners[r][c] != player_key:
                        restored_cells.append((r, c))
                    view_board[r][c] = 1
                    view_owners[r][c] = player_key
                    continue
                if own_state == 2:
                    if view_board[r][c] == 0:
                        view_board[r][c] = 2
                    continue
                if own_state == 5:
                    if view_board[r][c] == 0:
                        view_board[r][c] = 5
        if restored_cells:
            logger.debug(
                "Force-restored %d own ship cells for %s: %s",
                len(restored_cells),
                player_key,
                restored_cells,
            )

    state.board = view_board
    state.owners = view_owners
    state.player_key = player_key
    if snapshot:
        state.highlight = [tuple(cell) for cell in snapshot.get("last_highlight", [])]
    else:
        state.highlight = getattr(match, "last_highlight", []).copy()
    buf = render_board(state, player_key)
    if buf.getbuffer().nbytes == 0:
        logger.warning("render_board returned empty buffer for chat %s", chat_id)
        return

    if getattr(state, "_shared_skip_next", False):
        msgs = match.messages.setdefault(player_key, {})
        if state.message_id is not None:
            msgs["board"] = state.message_id
        msgs.setdefault("board_history", [])
        msgs.setdefault("text_history", [])
        msgs.setdefault("history_active", False)
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


async def _send_text_update(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
    *,
    message_id: int | None = None,
) -> int | None:
    """Send a plain text notification and track it in match messages."""

    participant = match.players[player_key]
    if message_id is None:
        try:
            msg = await context.bot.send_message(participant.chat_id, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send text update for %s", player_key)
            return None
        message_id = getattr(msg, "message_id", None)
        if message_id is None:
            return None

    msgs = match.messages.setdefault(player_key, {})
    msgs["text"] = message_id
    text_hist = msgs.setdefault("text_history", [])
    text_hist.append(message_id)
    return message_id


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
    watch_body = msg_watch.rstrip()
    if not watch_body.endswith((".", "!", "?")):
        watch_body += "."
    watch_message = _compose_move_message(
        f"Ход игрока {player_label}: {coord_str} - {watch_body}",
        phrase_self,
        f"Следующим ходит {next_name}.",
    )
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
        board_targets: list[str] = []
        for other in others:
            participant = match.players.get(other)
            if not participant or participant.user_id == 0:
                continue
            board_targets.append(other)
        for other in board_targets:
            if other in enemy_msgs or other == player_key:
                continue
            participant = match.players.get(other)
            if not participant or participant.user_id == 0:
                continue
            await _send_state(
                context,
                match,
                other,
                watch_message,
            )
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
        states = context.bot_data.setdefault(STATE_KEY, {})
        chat_id = match.players[player_key].chat_id
        shared_state = states.get(chat_id)
        if shared_state is not None:
            shared_state._shared_skip_next = False
        for idx, (key, participant) in enumerate(match.players.items()):
            if shared_state is not None and idx > 0:
                shared_state._shared_skip_next = True
            await _send_state(
                context,
                match,
                key,
                shared_text,
                reveal_ships=True,
            )
            if idx == 0:
                shared_state = states.get(chat_id)
        if shared_state is not None:
            shared_state._shared_skip_next = False
        shared_entry = match.messages.get(player_key, {})
        shared_board = shared_entry.get("board")
        shared_history_active = shared_entry.get("history_active", False)
        for key in match.players:
            msgs = match.messages.setdefault(key, {})
            if shared_board is not None:
                msgs["board"] = shared_board
            msgs.setdefault("board_history", [])
            msgs.setdefault("text_history", [])
            msgs["history_active"] = shared_history_active
        # все участники видят общий борт и подпись, поэтому отдельные текстовые
        # уведомления не рассылаем
    elif single_user:
        await _send_state(
            context,
            match,
            player_key,
            shared_text,
        )
    else:
        await _send_state(
            context,
            match,
            player_key,
            personal_text,
        )

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
