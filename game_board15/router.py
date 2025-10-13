"""Text router for the 15×15 three-player mode."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set, Tuple

from telegram import Update
from telegram.ext import ContextTypes

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

from . import storage
from .battle import (
    AdvanceOutcome,
    KILL,
    MISS,
    HIT,
    ShotResult,
    advance_turn,
    apply_shot,
)
from .models import (
    Field15,
    Match15,
    Snapshot15,
    PLAYER_ORDER,
    Ship,
    ShotLogEntry,
    normalize_history_cell,
    normalize_history_grid,
)
from .parser import ParseError, format_coord, parse_coord
from . import parser as parser_module
from .render import RenderState, render_board

logger = logging.getLogger(__name__)

STATE_KEY = "board15_state"
parser = parser_module


def collect_expected_changes(
    previous: Snapshot15 | None, result: ShotResult
) -> Set[Tuple[int, int]]:
    """Return coordinates that are expected to change after a shot."""

    expected: Set[Tuple[int, int]] = set()
    if previous is not None:
        for r, row in enumerate(previous.cell_history):
            for c, cell in enumerate(row):
                normalized = normalize_history_cell(cell)
                age = normalized[2] if len(normalized) > 2 else 1
                if age == 0:
                    expected.add((r, c))
    expected.add(result.coord)
    if result.killed_ship:
        expected.update(result.killed_ship.cells)
    if result.contour:
        expected.update(result.contour)
    return expected


def _ensure_field(match) -> Field15:
    field = getattr(match, "field", None)
    if isinstance(field, Field15):
        return field
    boards = getattr(match, "boards", {})
    new_field = Field15()
    for key, board in boards.items():
        if not isinstance(board, Field15):
            continue
        owner_key = getattr(board, "owner", None) or (key if key in PLAYER_ORDER else None)
        ships_value = getattr(board, "ships", [])
        if isinstance(ships_value, dict):
            ship_iterable = []
            for items in ships_value.values():
                ship_iterable.extend(items)
        else:
            ship_iterable = ships_value
        for ship in ship_iterable:
            if not isinstance(ship, Ship):
                continue
            ship_owner = ship.owner or owner_key or key
            clone = Ship(cells=list(ship.cells), owner=ship_owner, alive=ship.alive)
            new_field.ships.setdefault(ship_owner, []).append(clone)
            for r, c in ship.cells:
                new_field.grid[r][c] = 1
                new_field.owners[r][c] = ship_owner
        for r in range(15):
            for c in range(15):
                value = board.grid[r][c]
                if value:
                    new_field.grid[r][c] = value
                    owner = board.owners[r][c] or owner_key
                    new_field.owners[r][c] = owner
    alive_counts = {key: 0 for key in PLAYER_ORDER}
    for r in range(15):
        for c in range(15):
            owner = new_field.owners[r][c]
            if owner in alive_counts and new_field.grid[r][c] == 1:
                alive_counts[owner] += 1
    if hasattr(match, "alive_cells") and isinstance(match.alive_cells, dict):
        for key, value in alive_counts.items():
            if value:
                match.alive_cells[key] = value
    setattr(match, "field", new_field)
    return new_field


def _ensure_history(match) -> List[List[List[int | None]]]:
    try:
        history_source = getattr(match, "cell_history")
    except AttributeError:
        history_source = getattr(match, "history", None)
    setattr(match, "_history_pre_coerce", history_source)
    history = normalize_history_grid(history_source)
    setattr(match, "cell_history", history)
    return history


def _decay_last_marks(history: List[List[List[int | None]]]) -> None:
    for r in range(15):
        row = history[r]
        for c in range(15):
            cell = normalize_history_cell(row[c])
            if len(cell) < 3:
                cell.append(1)
            if cell[2] == 0:
                cell[2] = 1
            row[c] = cell


def _set_history_cell(
    history: List[List[List[int | None]]],
    coord: Tuple[int, int],
    state: int,
    owner: Optional[str],
    *,
    fresh: bool,
) -> None:
    value = normalize_history_cell([state, owner, 0 if fresh else 1], default_owner=owner)
    r, c = coord
    history[r][c] = value


def _player_key(match, user_id: int) -> Optional[str]:
    players = getattr(match, "players", {})
    for key, player in players.items():
        if getattr(player, "user_id", None) == user_id:
            return key
    return None


def _player_label(match, player_key: str) -> str:
    player = getattr(match, "players", {}).get(player_key)
    if not player:
        return player_key
    name = getattr(player, "name", "") or ""
    return name.strip() or player_key


def _iter_real_players(match):
    players = getattr(match, "players", {})
    for key, player in players.items():
        chat_id = getattr(player, "chat_id", 0)
        if not chat_id:
            continue
        yield key, player


def _meta(match) -> dict:
    messages = getattr(match, "messages", None)
    if not isinstance(messages, dict):
        match.messages = {}
        messages = match.messages
    return messages.setdefault("_meta", {})


def _record_eliminations(match, eliminated: List[str]) -> List[str]:
    meta = _meta(match)
    order: List[str] = meta.setdefault("elimination_order", [])
    for key in eliminated:
        if key not in order:
            order.append(key)
    return order


async def _broadcast_elimination(
    context: ContextTypes.DEFAULT_TYPE, match, player_key: str
) -> None:
    label = _player_label(match, player_key)
    text = f"⛔ Игрок {label} выбыл (флот уничтожен)"
    for _, player in _iter_real_players(match):
        try:
            await context.bot.send_message(player.chat_id, text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to send elimination notice for player %s", player_key
            )


def _final_ranking(match, winner: Optional[str], elimination_order: List[str]) -> List[str]:
    ranking: List[str] = []
    if winner and winner not in ranking:
        ranking.append(winner)
    for key in reversed(elimination_order):
        if key not in ranking and key in getattr(match, "players", {}):
            ranking.append(key)
    for key in PLAYER_ORDER:
        if key not in ranking and key in getattr(match, "players", {}):
            ranking.append(key)
    return ranking


async def _send_final_summaries(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    ranking: List[str],
    winner: Optional[str],
) -> None:
    meta = _meta(match)
    if meta.get("final_summary_sent"):
        return

    placements = {key: idx + 1 for idx, key in enumerate(ranking)}
    lines_template = ["Итоги матча:"]
    for pos, key in enumerate(ranking, start=1):
        label = _player_label(match, key)
        marker = " 🏆" if winner and key == winner else ""
        lines_template.append(f"{pos}. {label}{marker}")

    for key, player in _iter_real_players(match):
        placement = placements.get(key)
        header = "🏁 Игра завершена!"
        if winner and key == winner:
            header += " Вы победили!🏆"
        elif placement:
            header += f" Вы заняли {placement} место."
        else:
            header += " Матч завершён."
        message_lines = [header, ""] + lines_template
        try:
            await context.bot.send_message(player.chat_id, "\n".join(message_lines))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send final summary to player %s", key)

    meta["final_summary_sent"] = True


def _phrase_or_joke(match, player_key: str, phrases: List[str]) -> str:
    shots = match.shots.setdefault(player_key, {})
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if isinstance(start, int) and count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот по этому поводу:\n{random_joke()}"
    return random_phrase(phrases)


async def _send_state(
    context: ContextTypes.DEFAULT_TYPE,
    match,
    player_key: str,
    message: str,
    *,
    reveal_ships: bool = False,
    snapshot: "Snapshot15" | None = None,
) -> None:
    player = match.players[player_key]
    chat_id = player.chat_id
    field = _ensure_field(match)
    if snapshot is None:
        snapshots = getattr(match, "snapshots", [])
        if snapshots:
            snapshot = snapshots[-1]
        elif hasattr(match, "create_snapshot"):
            snapshot = match.create_snapshot()
    if snapshot is not None:
        field = snapshot.field
        history_grid = snapshot.cell_history
        last_move = snapshot.last_move
    else:
        history_grid = _ensure_history(match)
        last_move = getattr(field, "last_move", None)
    flags = (
        match.messages.get("_flags", {})
        if isinstance(getattr(match, "messages", None), dict)
        else {}
    )
    if not reveal_ships and isinstance(flags, dict):
        reveal_ships = bool(flags.get("board15_reveal_ships"))
    state_store = context.bot_data.setdefault(STATE_KEY, {})
    match_id = getattr(match, "match_id", "unknown")
    footer = f"match={match_id} • player={player_key} • sh_disp=20"
    render_state = RenderState(
        field=field,
        history=history_grid,
        footer_label=footer,
        reveal_ships=reveal_ships,
        last_move=last_move,
    )
    buffer = render_board(render_state, player_key)
    visible = render_state.rendered_ship_cells
    if visible != 20:
        retry_footer = f"{footer} • retry sh_disp={visible}"
        retry_state = render_state.clone_for_retry(attempt=2, footer_label=retry_footer)
        buffer_retry = render_board(retry_state, player_key)
        second_visible = retry_state.rendered_ship_cells
        if second_visible != visible:
            logger.critical(
                "RENDER_GUARD_FAIL_OWN20 | match=%s player=%s first=%s second=%s",
                match.match_id,
                player_key,
                visible,
                second_visible,
            )
            state_store[chat_id] = retry_state
            return
        buffer = buffer_retry
        render_state = retry_state
    caption = message.strip()
    try:
        sent = await context.bot.send_photo(
            chat_id,
            photo=buffer,
            caption=caption or None,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to send state to player %s", player_key)
        raise
    state_store[chat_id] = render_state
    msgs = match.messages.setdefault(player_key, {})
    board_hist = msgs.setdefault("board_history", [])
    board_hist.append(getattr(sent, "message_id", None))
    msgs["board"] = getattr(sent, "message_id", None)
    if caption:
        msgs.setdefault("text_history", []).append(caption)


def _update_history(match, shooter: str, result: ShotResult) -> bool:
    r, c = result.coord
    owner = result.owner
    raw_source = getattr(match, "_history_pre_coerce", None)
    if raw_source is None:
        raw_source = getattr(match, "cell_history", [])
    raw_cell = None
    if isinstance(raw_source, (list, tuple)) and len(raw_source) > r:
        row = raw_source[r]
        if isinstance(row, (list, tuple)) and len(row) > c:
            raw_cell = row[c]
    original_was_scalar = not isinstance(raw_cell, (list, tuple))

    history = _ensure_history(match)
    setattr(match, "_history_pre_coerce", None)
    _decay_last_marks(history)

    boards = getattr(match, "boards", {})

    if result.result == MISS:
        _set_history_cell(history, (r, c), 2, owner, fresh=True)
        for board in boards.values():
            if hasattr(board, "grid"):
                board.grid[r][c] = 2
    elif result.result == HIT:
        _set_history_cell(history, (r, c), 3, owner, fresh=True)
        target = boards.get(owner)
        if target and hasattr(target, "grid"):
            target.grid[r][c] = 3
    elif result.result == KILL:
        _set_history_cell(history, (r, c), 4, owner, fresh=True)
        if result.killed_ship:
            target = boards.get(owner)
            for cell in result.killed_ship.cells:
                rr, cc = cell
                _set_history_cell(history, (rr, cc), 4, owner, fresh=True)
                if target and hasattr(target, "grid"):
                    target.grid[rr][cc] = 4
        for contour_cell in result.contour:
            rr, cc = contour_cell
            _set_history_cell(history, (rr, cc), 5, None, fresh=False)
            for board in boards.values():
                if hasattr(board, "grid"):
                    board.grid[rr][cc] = 5
    log_entry = ShotLogEntry(
        by_player=shooter,
        coord=result.coord,
        result=result.result,
        target=result.owner,
    )
    history_log = getattr(match, "history", None)
    if isinstance(history_log, list):
        history_log.append(log_entry)
    else:
        match.history = [log_entry]
    return original_was_scalar


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    match = storage.find_match_by_user(user_id, chat_id)
    if not match:
        return
    if not hasattr(match, "alive_cells") or not isinstance(getattr(match, "alive_cells"), dict):
        match.alive_cells = {key: 20 for key in PLAYER_ORDER}
    if not hasattr(match, "order"):
        match.order = list(PLAYER_ORDER)
    if not hasattr(match, "turn_idx"):
        match.turn_idx = 0
    if not hasattr(match, "messages"):
        match.messages = {key: {} for key in PLAYER_ORDER}
    if not hasattr(match, "shots"):
        match.shots = {key: {} for key in PLAYER_ORDER}
    _ensure_history(match)
    field = _ensure_field(match)
    if not hasattr(match, "boards"):
        match.boards = {key: field for key in PLAYER_ORDER}
    player_key = _player_key(match, user_id)
    if not player_key:
        return
    if match.status not in {"placing", "playing"}:
        await message.reply_text("Игра ещё не началась.")
        return
    text = message.text.strip()
    try:
        coord = parse_coord(text)
    except ParseError as exc:
        await message.reply_text(str(exc))
        return

    board_self = match.boards.get(player_key)
    if board_self and hasattr(board_self, "highlight"):
        board_self.highlight.clear()

    prev_alive = {key: match.alive_cells.get(key, 0) for key in PLAYER_ORDER}

    try:
        shot_result = apply_shot(match, player_key, coord)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return

    needs_presave = _update_history(match, player_key, shot_result)

    shots = match.shots.setdefault(player_key, {})
    shots.setdefault("history", []).append(coord)
    shots["last_result"] = shot_result.result
    shots["move_count"] = shots.get("move_count", 0) + 1
    shots["last_coord"] = coord

    if needs_presave:
        storage.save_match(match)

    if shot_result.result == MISS:
        phrase = _phrase_or_joke(match, player_key, SELF_MISS)
        enemy_phrase = random_phrase(ENEMY_MISS)
    elif shot_result.result == HIT:
        phrase = _phrase_or_joke(match, player_key, SELF_HIT)
        enemy_phrase = random_phrase(ENEMY_HIT)
    else:
        phrase = _phrase_or_joke(match, player_key, SELF_KILL)
        enemy_phrase = random_phrase(ENEMY_KILL)

    coord_text = format_coord(coord)
    message_self = f"Ваш ход: {coord_text}. {phrase}".strip()
    player_label = _player_label(match, player_key)

    outcome = advance_turn(match, shot_result, previous_alive=prev_alive)
    elimination_order = _record_eliminations(match, outcome.eliminated)

    previous_snapshot = match.snapshots[-1] if getattr(match, "snapshots", []) else None
    expected_cells = collect_expected_changes(previous_snapshot, shot_result)
    snapshot = storage.append_snapshot(
        match,
        expected_changes=expected_cells,
    )

    await _send_state(
        context,
        match,
        player_key,
        message_self,
        snapshot=snapshot,
    )

    for other_key in PLAYER_ORDER:
        if other_key == player_key:
            continue
        player = match.players.get(other_key)
        if not player or match.alive_cells.get(other_key, 0) <= 0:
            continue
        try:
            await _send_state(
                context,
                match,
                other_key,
                f"Ход {player_label}: {coord_text}. {enemy_phrase}",
                snapshot=snapshot,
            )
        except Exception:
            logger.exception("Failed to notify player %s", other_key)

    for eliminated_key in outcome.eliminated:
        await _broadcast_elimination(context, match, eliminated_key)

    if outcome.finished:
        ranking = _final_ranking(match, outcome.winner, elimination_order)
        await _send_final_summaries(context, match, ranking, outcome.winner)


__all__ = ["router_text", "_send_state", "STATE_KEY", "collect_expected_changes"]
