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


def _phrase_or_joke(match, player_key: str, phrases: list[str]) -> str:
    shots = match.shots[player_key]
    start = shots.get("joke_start")
    if start is None:
        start = shots["joke_start"] = random.randint(1, 10)
    count = shots.get("move_count", 0)
    if count >= start and (count - start) % 10 == 0:
        return f"Слушай анекдот по этому поводу:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


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
        except Exception:
            logger.exception("Failed to send state to %s", player_key)

    async def _safe_send_message(chat_id_: int, text: str) -> None:
        try:
            await context.bot.send_message(chat_id_, text)
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
            storage.finish(match, winner)
            if match.players[winner].user_id != 0:
                await _safe_send_message(match.players[winner].chat_id, "Вы победили!")
            for k in match.players:
                if k != winner and match.players[k].user_id != 0:
                    await _safe_send_message(match.players[k].chat_id, "Игра окончена. Победил соперник.")
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
            if match.history[r][c] == 0 and match.boards[current].grid[r][c] != 1:
                coord = pt
                break
        if coord is None:
            break

        enemies = [k for k in alive if k != current]
        enemy_boards = {k: match.boards[k] for k in enemies}
        results = battle.apply_shot_multi(coord, enemy_boards, match.history)
        match.shots[current]["last_coord"] = coord
        if any(res == battle.KILL for res in results.values()):
            cells: list[tuple[int, int]] = []
            for enemy, res in results.items():
                if res == battle.KILL:
                    cells.extend(match.boards[enemy].highlight)
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
        enemy_msgs: dict[str, str] = {}
        priority = {battle.MISS: 0, battle.REPEAT: 1, battle.HIT: 2, battle.KILL: 3}
        overall_res = battle.MISS
        for enemy, res in results.items():
            if priority[res] > priority[overall_res]:
                overall_res = res
            if res == battle.MISS:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).rstrip()
                parts_self.append(f"{enemy}: мимо.")
                enemy_msgs[enemy] = f"соперник промахнулся. {phrase_enemy}".rstrip()
            elif res == battle.HIT:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT).rstrip()
                parts_self.append(f"{enemy}: ранил.")
                enemy_msgs[enemy] = f"ваш корабль ранен. {phrase_enemy}".rstrip()
            elif res == battle.KILL:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL).rstrip()
                parts_self.append(f"{enemy}: уничтожен!")
                enemy_msgs[enemy] = f"ваш корабль уничтожен. {phrase_enemy}".rstrip()
                if match.boards[enemy].alive_cells == 0 and match.players[enemy].user_id != 0:
                    await _safe_send_message(
                        match.players[enemy].chat_id,
                        f"⛔ Игрок {enemy} выбыл (флот уничтожен)",
                    )
            elif res == battle.REPEAT:
                phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS).rstrip()
                parts_self.append(f"{enemy}: клетка уже обстреляна.")
                enemy_msgs[enemy] = (
                    f"соперник стрелял по уже обстрелянной клетке. {phrase_enemy}"
                ).rstrip()

        phrase_map = {
            battle.KILL: SELF_KILL,
            battle.HIT: SELF_HIT,
            battle.REPEAT: SELF_MISS,
            battle.MISS: SELF_MISS,
        }
        phrase_self = _phrase_or_joke(match, current, phrase_map[overall_res]).rstrip()

        next_name = next_player
        if enemy_msgs:
            for enemy, msg_body in enemy_msgs.items():
                if enemy == human:
                    continue
                if match.players[enemy].user_id != 0:
                    next_phrase = f" Следующим ходит {next_name}."
                    await _safe_send_state(
                        enemy,
                        f"Ход игрока {current}: {coord_str} - {msg_body}{next_phrase}",
                    )

        if (
            current != human
            and human in enemy_msgs
            and match.players[human].user_id != 0
        ):
            next_phrase = f" Следующим ходит {next_name}."
            await _safe_send_state(
                human,
                f"Ход игрока {current}: {coord_str} - {enemy_msgs[human]}{next_phrase}",
            )

        storage.save_match(match)
        parts_text = ' '.join(parts_self)
        base_self = (
            f"Ваш ход: {coord_str} - {parts_text} {phrase_self}"
            if parts_text
            else f"Ваш ход: {coord_str} - {phrase_self}"
        ).rstrip()
        result_self = base_self + f" Следующим ходит {next_name}."
        if match.players[current].user_id != 0:
            await _safe_send_state(current, result_self)

        alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0 and k in match.players]
        if len(alive_players) == 1:
            winner = alive_players[0]
            storage.finish(match, winner)
            if match.players[winner].user_id != 0:
                await _safe_send_message(match.players[winner].chat_id, "Вы победили!")
            for k in match.players:
                if k != winner and match.players[k].user_id != 0:
                    await _safe_send_message(
                        match.players[k].chat_id,
                        "Игра окончена. Победил соперник.",
                    )
            break


async def board_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a three-player test match with two dummy opponents."""

    match = storage.create_match(update.effective_user.id, update.effective_chat.id)
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
            match, context, update.effective_chat.id, human="A", delay=6
        )
    )
