from __future__ import annotations

import asyncio
import random
import logging
from telegram import Update
from telegram.ext import ContextTypes

import storage
from models import Player
from logic import placement, parser
from logic import battle_test as battle
from logic.battle import apply_shot, MISS, HIT, KILL, REPEAT
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


def _cell_state(cell):
    """Return state value for a possibly annotated board cell."""
    return cell[0] if isinstance(cell, (list, tuple)) else cell


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
    """Format move outcome with spacing between sections."""

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


async def _auto_play_bots(
    match,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    human: str = "A",
    delay: float = 0.0,
) -> None:
    """Automatically let bot players make moves until the game ends."""

    logger = logging.getLogger(__name__)

    async def _safe_send_state(player_key: str, message: str) -> None:
        from . import router as router_module

        try:
            await router_module._send_state_board_test(context, match, player_key, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send state to %s", player_key)

    async def _safe_send_message(chat_id_: int, text: str) -> None:
        try:
            await context.bot.send_message(chat_id_, text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send message to chat %s", chat_id_)

    coords = [(r, c) for r in range(10) for c in range(10)]
    order = ["A", "B", "C"]

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
                        msg = "Вы победили!🏆"
                    else:
                        msg = f"Игрок {winner_label} победил!"
                    await _safe_send_message(p.chat_id, msg)
            break

        if match.turn == human:
            await asyncio.sleep(0.5)
            continue

        if delay:
            await asyncio.sleep(delay)

        current = match.turn
        coord = None
        for pt in coords:
            r, c = pt
            if match.history[r][c] == 0 and _cell_state(match.boards[current].grid[r][c]) != 1:
                coord = pt
                break
        if coord is None:
            break

        enemies = [k for k in alive if k != current]
        for b in match.boards.values():
            b.highlight = []
        enemy_boards = {k: match.boards[k] for k in enemies}
        results = battle.apply_shot_multi(coord, enemy_boards, match.history)
        match.shots[current]["last_coord"] = coord
        eliminated: list[str] = []
        if any(res == battle.KILL for res in results.values()):
            cells: list[tuple[int, int]] = []
            for enemy, res in results.items():
                if res == battle.KILL:
                    cells.extend(match.boards[enemy].highlight)
                    if match.boards[enemy].alive_cells == 0:
                        eliminated.append(enemy)
            match.last_highlight = cells.copy()
            match.shots[current]["last_result"] = "kill"
        elif any(res == battle.HIT for res in results.values()):
            match.last_highlight = [coord]
            match.shots[current]["last_result"] = "hit"
        else:
            match.last_highlight = [coord]
            match.shots[current]["last_result"] = "miss"
        for k in match.shots:
            shots = match.shots[k]
            shots.setdefault("move_count", 0)
            shots.setdefault("joke_start", random.randint(1, 10))
            shots["move_count"] += 1
        coord_str = parser.format_coord(coord)
        hit_any = any(
            res in (battle.HIT, battle.KILL, battle.REPEAT)
            for res in results.values()
        )

        if not hit_any:
            alive_order = [k for k in order if k in alive]
            idx_next = alive_order.index(current)
            next_player = alive_order[(idx_next + 1) % len(alive_order)]
        else:
            next_player = current
        match.turn = next_player

        parts_self = []
        enemy_msgs: dict[str, tuple[str, str]] = {}
        priority = {battle.MISS: 0, battle.REPEAT: 1, battle.HIT: 2, battle.KILL: 3}
        overall_res = battle.MISS
        for enemy, res in results.items():
            if priority[res] > priority[overall_res]:
                overall_res = res
            if res == battle.MISS:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).strip()
                parts_self.append(f"{enemy}: мимо.")
                enemy_msgs[enemy] = (
                    f"Ход игрока {current}: {coord_str} - Соперник промахнулся.",
                    phrase_enemy,
                )
            elif res == battle.HIT:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT).strip()
                parts_self.append(f"{enemy}: ранил.")
                enemy_msgs[enemy] = (
                    f"Ход игрока {current}: {coord_str} - Соперник ранил ваш корабль.",
                    phrase_enemy,
                )
            elif res == battle.KILL:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL).strip()
                parts_self.append(f"{enemy}: уничтожен!")
                enemy_msgs[enemy] = (
                    f"Ход игрока {current}: {coord_str} - Соперник уничтожил ваш корабль.",
                    phrase_enemy,
                )
            elif res == battle.REPEAT:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).strip()
                parts_self.append(f"{enemy}: клетка уже обстреляна.")
                enemy_msgs[enemy] = (
                    f"Ход игрока {current}: {coord_str} - Соперник стрелял по уже обстрелянной клетке.",
                    phrase_enemy,
                )

        phrase_map = {
            battle.KILL: SELF_KILL,
            battle.HIT: SELF_HIT,
            battle.REPEAT: SELF_MISS,
            battle.MISS: SELF_MISS,
        }
        phrase_self = _phrase_or_joke(match, current, phrase_map[overall_res]).strip()

        next_name = next_player
        storage.save_match(match)
        if enemy_msgs:
            for enemy, (result_line_enemy, humor_enemy) in enemy_msgs.items():
                if enemy == human:
                    continue
                if match.players[enemy].user_id != 0:
                    message_enemy = _compose_move_message(
                        result_line_enemy,
                        humor_enemy,
                        f"Следующим ходит {next_name}.",
                    )
                    await _safe_send_state(enemy, message_enemy)

        if (
            current != human
            and human in enemy_msgs
            and match.players[human].user_id != 0
        ):
            result_line_human, humor_human = enemy_msgs[human]
            message_human = _compose_move_message(
                result_line_human,
                humor_human,
                f"Следующим ходит {next_name}.",
            )
            await _safe_send_state(human, message_human)

        parts_text = ' '.join(parts_self)
        parts_text = parts_text.strip()
        result_line_self = (
            f"Ваш ход: {coord_str} - {parts_text}" if parts_text else f"Ваш ход: {coord_str}"
        )
        result_self = _compose_move_message(
            result_line_self,
            phrase_self,
            f"Следующим ходит {next_name}.",
        )
        if match.players[current].user_id != 0:
            await _safe_send_state(current, result_self)

        finished = False
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


async def _auto_play_bot(
    match,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    human: str = "A",
    bot: str = "B",
    delay: float = 0.0,
) -> None:
    """Automatically perform moves for the bot opponent in two-player tests."""

    logger = logging.getLogger(__name__)

    async def _safe_send_state(player_key: str, message: str) -> None:
        from . import router as router_module

        try:
            await router_module._send_state(context, match, player_key, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send state to %s", player_key)

    async def _safe_send_message(chat_id_: int, text: str, **kwargs) -> None:
        try:
            await context.bot.send_message(chat_id_, text, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send message to chat %s", chat_id_)

    game_started = False

    while True:
        refreshed = storage.get_match(match.match_id)
        if refreshed is not None:
            match = refreshed
        if bot not in match.players:
            break
        if match.status == "finished":
            break
        if not game_started:
            if match.status != "playing":
                await asyncio.sleep(0.5)
                continue
            game_started = True
            continue
        if match.boards[human].alive_cells <= 0:
            break
        if match.turn != bot:
            await asyncio.sleep(0.5)
            continue
        if delay:
            await asyncio.sleep(delay)

        board = match.boards[human]
        available_cells = [
            (r, c)
            for r, row in enumerate(board.grid)
            for c, cell in enumerate(row)
            if _cell_state(cell) not in (2, 3, 4, 5)
        ]
        if not available_cells:
            break
        coord = random.choice(available_cells)

        for b in match.boards.values():
            b.highlight = []

        result = apply_shot(board, coord)
        coord_str = parser.format_coord(coord)
        bot_shots = match.shots.setdefault(bot, {})
        bot_shots.setdefault("history", []).append(coord_str)
        bot_shots["last_coord"] = coord
        bot_shots["last_result"] = result
        for key in (human, bot):
            shots = match.shots.setdefault(key, {})
            shots.setdefault("move_count", 0)
            shots.setdefault("joke_start", random.randint(1, 10))
            shots["move_count"] += 1

        if result == MISS:
            match.turn = human
            phrase_enemy = _phrase_or_joke(match, human, ENEMY_MISS).strip()
            message = _compose_move_message(
                f"Ход соперника: {coord_str} — Промах.",
                phrase_enemy,
                "Следующим ходите вы.",
            )
        elif result == HIT:
            match.turn = bot
            phrase_enemy = _phrase_or_joke(match, human, ENEMY_HIT).strip()
            message = _compose_move_message(
                f"Ход соперника: {coord_str} — Ваш корабль ранен.",
                phrase_enemy,
                "Следующим ходит соперник.",
            )
        elif result == REPEAT:
            match.turn = bot
            phrase_enemy = _phrase_or_joke(match, human, ENEMY_MISS).strip()
            message = _compose_move_message(
                f"Ход соперника: {coord_str} — Клетка уже обстреляна.",
                phrase_enemy,
                "Следующим ходит соперник.",
            )
        elif result == KILL:
            phrase_enemy = _phrase_or_joke(match, human, ENEMY_KILL).strip()
            if board.alive_cells == 0:
                message = _compose_move_message(
                    f"Ход соперника: {coord_str} — Ваш корабль уничтожен.",
                    phrase_enemy,
                    "Все ваши корабли уничтожены. Бот победил!",
                )
                storage.finish(match, bot)
                await _safe_send_state(human, message)
                await _safe_send_message(
                    match.players[human].chat_id,
                    "Игра завершена! Используйте /newgame, чтобы начать новую партию.",
                )
                break
            match.turn = bot
            message = _compose_move_message(
                f"Ход соперника: {coord_str} — Ваш корабль уничтожен.",
                phrase_enemy,
                "Следующим ходит соперник.",
            )
        else:
            match.turn = human
            message = _compose_move_message(
                f"Ход соперника: {coord_str} — Техническая ошибка.",
                None,
                "Следующим ходите вы.",
            )

        storage.save_match(match)
        await _safe_send_state(human, message)

        if match.status == "finished":
            break


async def board_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player test match with two dummy opponents."""

    name = getattr(update.effective_user, "first_name", "") or getattr(
        update.effective_user, "username", ""
    )
    match = storage.create_match(update.effective_user.id, update.effective_chat.id, name)
    match.players["B"] = Player(user_id=0, chat_id=update.effective_chat.id)
    match.players["C"] = Player(user_id=0, chat_id=update.effective_chat.id)
    match.status = "playing"
    match.turn = "A"

    mask = [[0] * 10 for _ in range(10)]
    for key in ("A", "B", "C"):
        board = placement.random_board_global(mask)
        board.owner = key
        match.players[key].ready = True
        match.boards[key] = board
    storage.save_match(match)

    from . import router as router_module

    await update.message.reply_text(
        "Тестовый матч начат. Вы — игрок A; два бота ходят автоматически."
    )

    await router_module._send_state_board_test(
        context,
        match,
        "A",
        "Выберите клетку или введите ход текстом.",
    )
    asyncio.create_task(
        _auto_play_bots(
            match, context, update.effective_chat.id, human="A", delay=5
        )
    )


async def board_test_two(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a two-player test match against a bot opponent."""

    message = getattr(update, "message", None)
    if message is None and getattr(update, "callback_query", None):
        message = update.callback_query.message
    if message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    name = getattr(user, "first_name", "") or getattr(user, "username", "")
    match = storage.create_match(user.id, chat.id, name)
    match.players["B"] = Player(user_id=0, chat_id=chat.id)
    match.players["B"].ready = True
    match.status = "placing"
    match.turn = "A"

    board_b = placement.random_board()
    board_b.owner = "B"
    match.boards["B"] = board_b

    flags = match.messages.setdefault("_flags", {})
    flags["mode_test2"] = True

    storage.save_match(match)

    await message.reply_text(
        'Тестовый матч начат. Отправьте "авто" для расстановки кораблей.'
    )
    await message.reply_text(
        "Используйте @ или ! в начале сообщения, чтобы отправить сообщение соперникам в чат игры."
    )

    asyncio.create_task(
        _auto_play_bot(
            match,
            context,
            chat.id,
            human="A",
            bot="B",
            delay=3,
        )
    )
