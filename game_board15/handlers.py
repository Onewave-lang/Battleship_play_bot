from __future__ import annotations

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes
from urllib.parse import quote_plus

from . import storage, parser, battle, placement
from .models import Player
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
import random
import asyncio
import logging

WELCOME_TEXT = 'Выберите способ приглашения соперников:'

STATE_KEY = "board15_states"


async def board15(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, 'args', None)
    name = getattr(update.effective_user, 'first_name', '') or ''
    if args:
        match_id = args[0]
        match = storage.join_match(match_id, update.effective_user.id, update.effective_chat.id, name)
        if not match:
            await update.message.reply_text('Матч не найден или заполнен.')
            return
        await update.message.reply_text('Вы присоединились к матчу. Отправьте "авто" для расстановки.')
    else:
        match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
        username = (await context.bot.get_me()).username
        link = f"https://t.me/{username}?start=b15_{match.match_id}"
        share_url = f"https://t.me/share/url?url={quote_plus(link)}"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton('Из контактов', url=share_url),
                    InlineKeyboardButton('Ссылка на игру', callback_data='b15_get_link'),
                ]
            ]
        )
        await update.message.reply_text(WELCOME_TEXT, reply_markup=keyboard)
        await update.message.reply_text('Матч создан. Ожидаем подключения соперников.')
    player_key = next(k for k, p in match.players.items() if p.user_id == update.effective_user.id)
    player = match.players[player_key]
    if not getattr(player, 'name', ''):
        player.name = name
        storage.save_match(match)
    from . import router as router_module

    await router_module._send_state(
        context,
        match,
        player_key,
        'Выберите клетку или введите ход текстом.',
        reveal_ships=True,
    )
    storage.save_match(match)


async def _auto_play_bots(
    match: storage.Match15,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    human: str = 'A',
    delay: float = 0.0,
) -> None:
    """Automatically let bot players make moves until the game ends."""
    logger = logging.getLogger(__name__)

    async def _safe_send_state(
        player_key: str,
        message: str,
        *positional,
        **keyword,
    ) -> None:
        snapshot_override = keyword.pop("snapshot_override", None)
        if positional:
            snapshot_override = positional[0]
        try:
            kwargs = dict(keyword)
            if snapshot_override is not None:
                kwargs["snapshot_override"] = snapshot_override
            await router_module._send_state(
                context,
                match,
                player_key,
                message,
                **kwargs,
            )
        except asyncio.CancelledError:
            raise
        except TypeError as exc:
            if (
                snapshot_override is not None
                and "snapshot_override" in str(exc)
            ):
                await router_module._send_state(
                    context,
                    match,
                    player_key,
                    message,
                    **keyword,
                )
            else:
                raise
        except Exception:
            logger.exception("Failed to send state to %s", player_key)
            human_player = match.players.get(human)
            if (
                human_player
                and human_player.user_id != 0
                and player_key != human
            ):
                try:
                    msg = await context.bot.send_message(
                        human_player.chat_id,
                        f"Не удалось отправить обновление игроку {player_key}",
                    )
                    msgs = match.messages.setdefault(human, {})
                    hist = msgs.setdefault("text_history", [])
                    hist.append(msg.message_id)
                    msgs.setdefault("service_messages", []).append(msg.message_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to notify human about state send failure"
                    )

    async def _safe_send_message(chat_id: int, text: str) -> None:
        try:
            await context.bot.send_message(chat_id, text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send message to chat %s", chat_id)
            human_player = match.players.get(human)
            if human_player and human_player.user_id != 0 and chat_id != human_player.chat_id:
                try:
                    await context.bot.send_message(
                        human_player.chat_id,
                        "Не удалось отправить сообщение участнику",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to notify human about message send failure"
                    )
    def _adjacent_mask(grid: list[list[int]]) -> list[list[bool]]:
        mask = [[False] * 15 for _ in range(15)]
        for r in range(15):
            for c in range(15):
                if _get_cell_state(grid[r][c]) == 1:
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < 15 and 0 <= nc < 15:
                                mask[nr][nc] = True
        return mask

    order = ['A', 'B', 'C']
    from . import router as router_module

    while True:
        refreshed = storage.get_match(match.match_id)
        if refreshed is not None:
            match = refreshed
        alive = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
        if len(alive) == 1:
            winner = alive[0]
            winner_label = getattr(match.players[winner], 'name', '') or winner
            storage.finish(match, winner)
            for k, p in match.players.items():
                if p.user_id != 0:
                    if k == winner:
                        msg = 'Вы победили!🏆'
                    else:
                        msg = f'Игрок {winner_label} победил!'
                    await _safe_send_message(p.chat_id, msg)
            break

        if delay:
            await asyncio.sleep(delay)

        current = match.turn
        player = match.players.get(current)
        if player is None or player.user_id != 0:
            await asyncio.sleep(delay or 0)
            refreshed = storage.get_match(match.match_id)
            if refreshed is not None:
                match = refreshed
            continue
        board = match.boards[current]
        adj = _adjacent_mask(board.grid)
        enemies = [k for k in alive if k != current]
        primary_candidates = [
            (r, c)
            for r in range(15)
            for c in range(15)
            if _get_cell_state(match.history[r][c]) == 0
            and _get_cell_state(board.grid[r][c]) != 1
            and not adj[r][c]
        ]
        if primary_candidates:
            candidates = primary_candidates
        else:
            fallback_candidates = [
                (r, c)
                for r in range(15)
                for c in range(15)
                if _get_cell_state(match.history[r][c]) == 0
            ]
            if not fallback_candidates:
                logger.warning(
                    "No available coordinates left for bot %s in match %s; closing",
                    current,
                    match.match_id,
                )
                storage.close_match(match)
                for key, participant in match.players.items():
                    if participant.user_id != 0:
                        await _safe_send_message(
                            participant.chat_id,
                            "Матч завершён: отсутствуют доступные клетки для выстрелов.",
                        )
                break
            candidates = fallback_candidates
        if len(enemies) == 1:
            enemy_board = match.boards[enemies[0]]
            target = next(
                (
                    (r, c)
                    for r in range(15)
                    for c in range(15)
                    if _get_cell_state(enemy_board.grid[r][c]) == 1
                ),
                None,
            )
            coord = target if target else random.choice(candidates)
        else:
            coord = random.choice(candidates)
        # Persist previous highlights before clearing them so that temporary
        # red marks become permanent dots on the history grid.
        _persist_highlight_to_history(match)
        results = {}
        hit_any = False
        eliminated: list[str] = []
        for enemy in enemies:
            res = battle.apply_shot(match.boards[enemy], coord)
            results[enemy] = res
            if res in (battle.HIT, battle.KILL):
                hit_any = True
            if res == battle.KILL and match.boards[enemy].alive_cells == 0:
                eliminated.append(enemy)
        # record detailed shot history including attacked players
        shot_hist = match.shots[current].setdefault("history", [])
        for enemy, res in results.items():
            shot_hist.append({"coord": coord, "enemy": enemy, "result": res})
        battle.update_history(match.history, match.boards, coord, results)
        match.shots[current]["last_coord"] = coord
        if any(res == battle.KILL for res in results.values()):
            cells: list[tuple[int, int]] = []
            for enemy, res in results.items():
                if res == battle.KILL:
                    cells.extend(match.boards[enemy].highlight)
            match.last_highlight = [coord] + [c for c in cells if c != coord]
        else:
            match.last_highlight = [coord]
        for k in match.shots:
            shots = match.shots[k]
            shots.setdefault('move_count', 0)
            shots.setdefault('joke_start', random.randint(1, 10))
            shots['move_count'] += 1
        coord_str = parser.format_coord(coord)

        if not hit_any:
            alive_order = [k for k in order if k in alive]
            idx_next = alive_order.index(current)
            next_player = alive_order[(idx_next + 1) % len(alive_order)]
        else:
            next_player = current
        match.turn = next_player

        snapshot = record_snapshot(match, actor=current, coord=coord)

        parts_self: list[str] = []
        watch_parts: list[str] = []
        enemy_msgs: dict[str, str] = {}
        player_label = getattr(match.players.get(current), 'name', '') or current
        for enemy, res in results.items():
            enemy_name = match.players.get(enemy)
            enemy_label = getattr(enemy_name, 'name', '') or enemy
            if res == battle.HIT:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
                parts_self.append(f"корабль игрока {enemy_label} ранен.")
                watch_parts.append(
                    f"игрок {player_label} поразил корабль игрока {enemy_label}."
                )
                enemy_msgs[enemy] = f"ваш корабль ранен. {phrase_enemy}"
            elif res == battle.KILL:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
                parts_self.append(f"уничтожен корабль игрока {enemy_label}!")
                watch_parts.append(
                    f"игрок {player_label} поразил корабль игрока {enemy_label}."
                )
                enemy_msgs[enemy] = f"ваш корабль уничтожен. {phrase_enemy}"
        enemy_msgs[current] = ' '.join(parts_self) if parts_self else 'мимо'
        watch_msg = ' '.join(watch_parts).strip() or 'мимо'
        for pk in match.players:
            enemy_msgs.setdefault(pk, watch_msg)

        if any(res == battle.KILL for res in results.values()):
            phrase_self = _phrase_or_joke(match, current, SELF_KILL)
        elif any(res == battle.HIT for res in results.values()):
            phrase_self = _phrase_or_joke(match, current, SELF_HIT)
        elif any(res == battle.REPEAT for res in results.values()):
            phrase_self = _phrase_or_joke(match, current, SELF_MISS)
        else:
            phrase_self = _phrase_or_joke(match, current, SELF_MISS)

        next_label = match.players.get(next_player)
        next_name = getattr(next_label, 'name', '') or next_player

        storage.save_match(match)

        for player_key, msg_body in enemy_msgs.items():
            participant = match.players[player_key]
            if participant.user_id == 0:
                continue
            next_phrase = f" Следующим ходит {next_name}."
            body = msg_body.rstrip()
            if not body.endswith(('.', '!', '?')):
                body += '.'
            if player_key == current:
                msg_text = f"Ваш ход: {coord_str} - {body} {phrase_self}{next_phrase}"
            else:
                msg_text = (
                    f"Ход игрока {player_label}: {coord_str} - {body} {phrase_self}{next_phrase}"
                )

            if player_key == human and current != human:
                human_participant = match.players.get(human)
                if not human_participant or human_participant.user_id == 0:
                    continue
                await _safe_send_state(
                    player_key,
                    msg_text,
                    snapshot_override=snapshot,
                )
            else:
                await _safe_send_state(
                    player_key,
                    msg_text,
                    snapshot_override=snapshot,
                )

        finished = False
        for enemy in eliminated:
            enemy_label = getattr(match.players[enemy], 'name', '') or enemy
            alive_players = [
                k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players
            ]
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
                        await _safe_send_message(p.chat_id, msg)
                finished = True
            else:
                for k, p in match.players.items():
                    if p.user_id != 0:
                        await _safe_send_message(
                            p.chat_id,
                            f"Флот игрока {enemy_label} потоплен! {enemy_label} выбывает.",
                        )
        if finished:
            break


def _schedule_auto_play(
    match: storage.Match15,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    human: str,
    delay: float,
) -> asyncio.Task:
    """Launch auto play ensuring moves run sequentially per chat."""

    if not hasattr(context, "chat_data") or context.chat_data is None:
        context.chat_data = {}
    if not hasattr(context, "bot_data") or context.bot_data is None:
        context.bot_data = {}
    locks = context.bot_data.setdefault("_board15_auto_locks", {})
    lock: asyncio.Lock = locks.setdefault(chat_id, asyncio.Lock())

    async def runner() -> None:
        async with lock:
            await _auto_play_bots(
                match, context, chat_id, human=human, delay=delay
            )

    application = getattr(context, "application", None)
    if application and hasattr(application, "create_task"):
        task: asyncio.Task = application.create_task(runner())
    else:
        task = asyncio.create_task(runner())

    tasks = context.chat_data.setdefault("_board15_auto_tasks", set())
    tasks.add(task)

    def _cleanup(_: object) -> None:
        tasks.discard(task)

    task.add_done_callback(_cleanup)
    return task


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player test match with two dummy opponents."""
    name = getattr(update.effective_user, 'first_name', '') or ''
    match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
    match.players['B'] = Player(user_id=0, chat_id=update.effective_chat.id, name='B')
    match.players['C'] = Player(user_id=0, chat_id=update.effective_chat.id, name='C')
    match.status = 'playing'
    match.turn = 'A'
    flags = match.messages.setdefault('_flags', {})
    flags['board15_test'] = True
    # place fleets for all players ensuring that ships of different players do
    # not touch each other.  Build a mask of forbidden cells (occupied or
    # adjacent) and update it after each fleet is generated.
    mask = [[0] * 15 for _ in range(15)]
    for key in ('A', 'B', 'C'):
        board = placement.random_board_global(mask)
        match.players[key].ready = True
        match.boards[key] = board
        ensure_ship_owners(match.history, board, key)
    storage.save_match(match)
    await update.message.reply_text(
        'Тестовый матч начат. Вы — игрок A; два бота ходят автоматически.'
    )

    from . import router as router_module

    await router_module._send_state(
        context,
        match,
        'A',
        'Выберите клетку или введите ход текстом.',
        reveal_ships=True,
    )
    storage.save_match(match)
    _schedule_auto_play(
        match, context, update.effective_chat.id, human='A', delay=3
    )


async def send_board15_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send invitation link for 15x15 mode."""
    query = update.callback_query
    await query.answer()
    match = storage.find_match_by_user(query.from_user.id, update.effective_chat.id)
    if not match:
        await query.message.reply_text('Матч не найден.')
        return
    username = (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=b15_{match.match_id}"
    await query.message.reply_text(f"Пригласите друга: {link}")
