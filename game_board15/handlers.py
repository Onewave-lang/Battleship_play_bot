from __future__ import annotations

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes
from urllib.parse import quote_plus

from .state import Board15State
from .renderer import render_board
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
from .utils import _phrase_or_joke, _get_cell_state, _get_cell_owner, _set_cell_state
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
    state = Board15State(chat_id=update.effective_chat.id)
    merged = [[_get_cell_state(cell) for cell in row] for row in match.history]
    own_grid = match.boards[player_key].grid
    for r in range(15):
        for c in range(15):
            cell = own_grid[r][c]
            if merged[r][c] == 0 and _get_cell_state(cell) == 1:
                merged[r][c] = 1
    state.board = merged
    state.player_key = player_key
    buf = render_board(state, player_key)
    msg = await update.message.reply_photo(
        buf, caption='Выберите клетку или введите ход текстом.'
    )
    state.message_id = msg.message_id
    context.bot_data.setdefault(STATE_KEY, {})[update.effective_chat.id] = state
    match.messages[player_key] = {
        'board': msg.message_id,
        'board_history': [],
        'text_history': [],
        'history_active': False,
    }
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

    async def _safe_send_state(player_key: str, message: str) -> None:
        try:
            await router_module._send_state(context, match, player_key, message)
        except asyncio.CancelledError:
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
                    msgs["text"] = msg.message_id
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
            await asyncio.sleep(delay)
            continue
        board = match.boards[current]
        adj = _adjacent_mask(board.grid)
        enemies = [k for k in alive if k != current]
        candidates = [
            (r, c)
            for r in range(15)
            for c in range(15)
            if _get_cell_state(match.history[r][c]) == 0
            and _get_cell_state(board.grid[r][c]) != 1
            and not adj[r][c]
        ]
        if not candidates:
            break
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
        for b in match.boards.values():
            if b.highlight:
                for rr, cc in b.highlight:
                    if _get_cell_state(match.history[rr][cc]) == 0:
                        _set_cell_state(match.history, rr, cc, 2)
            b.highlight = []
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
            if match.players[player_key].user_id != 0:
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
                await _safe_send_state(player_key, msg_text)

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


async def board15_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player test match with two dummy opponents."""
    name = getattr(update.effective_user, 'first_name', '') or ''
    match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
    match.players['B'] = Player(user_id=0, chat_id=update.effective_chat.id, name='B')
    match.players['C'] = Player(user_id=0, chat_id=update.effective_chat.id, name='C')
    match.status = 'playing'
    match.turn = 'A'
    # place fleets for all players ensuring that ships of different players do
    # not touch each other.  Build a mask of forbidden cells (occupied or
    # adjacent) and update it after each fleet is generated.
    mask = [[0] * 15 for _ in range(15)]
    for key in ('A', 'B', 'C'):
        board = placement.random_board_global(mask)
        match.players[key].ready = True
        match.boards[key] = board
    storage.save_match(match)
    state = Board15State(chat_id=update.effective_chat.id)
    merged = [[_get_cell_state(cell) for cell in row] for row in match.history]
    owners = [[_get_cell_owner(cell) for cell in row] for row in match.history]
    own_grid = match.boards['A'].grid
    for r in range(15):
        for c in range(15):
            cell = own_grid[r][c]
            if merged[r][c] == 0 and _get_cell_state(cell) == 1:
                merged[r][c] = 1
                owners[r][c] = _get_cell_owner(cell) or 'A'
    state.board = merged
    state.owners = owners
    state.player_key = 'A'

    await update.message.reply_text(
        'Тестовый матч начат. Вы — игрок A; два бота ходят автоматически.'
    )

    try:
        buf = render_board(state, 'A')
    except Exception:
        from io import BytesIO
        buf = BytesIO()

    reply_photo = getattr(update.message, "reply_photo", None)
    board_msg_id = None
    if reply_photo is not None:
        msg = await reply_photo(
            buf, caption='Выберите клетку или введите ход текстом.'
        )
        board_msg_id = msg.message_id
    else:
        msg = await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=buf,
            caption='Выберите клетку или введите ход текстом.',
        )
        board_msg_id = msg.message_id
    state.message_id = board_msg_id
    context.bot_data.setdefault(STATE_KEY, {})[update.effective_chat.id] = state
    match.messages['A'] = {
        'board': board_msg_id,
        'board_history': [],
        'text_history': [],
        'history_active': False,
    }
    storage.save_match(match)
    asyncio.create_task(
        _auto_play_bots(
            match, context, update.effective_chat.id, human='A', delay=5
        )
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
