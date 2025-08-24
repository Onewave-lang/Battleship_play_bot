from __future__ import annotations
import random
from telegram import Update
from telegram.ext import ContextTypes

from . import storage
from . import placement, battle, parser
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
        return f"Слушай анекдот:\n{random_joke()}\n\n"
    return f"{random_phrase(phrases)} "


async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    match = storage.find_match_by_user(user_id)
    if not match:
        await update.message.reply_text('Вы не участвуете в матче. Используйте /board15 <id>.')
        return
    for key, p in match.players.items():
        if p.user_id == user_id:
            player_key = key
            break
    enemy_keys = [k for k in match.players if k != player_key]

    if text.startswith('@'):
        parts = text[1:].split(maxsplit=1)
        if len(parts) == 2:
            target, msg = parts
            target = target.upper()[0]
            if target in match.players and target != player_key:
                await context.bot.send_message(match.players[target].chat_id, msg)
        return

    if match.status == 'placing':
        if text.lower() == 'авто':
            board = placement.random_board()
            storage.save_board(match, player_key, board)
            if match.status == 'playing':
                for k in match.players:
                    await context.bot.send_message(
                        match.players[k].chat_id,
                        'Все готовы. Бой начинается! ' + ('Ваш ход.' if match.turn == k else 'Ждём хода соперника.'),
                    )
            else:
                await update.message.reply_text('Корабли расставлены. Ожидаем остальных.')
            return
        await update.message.reply_text('Введите "авто" для расстановки.')
        return

    if match.status != 'playing':
        await update.message.reply_text('Матч ещё не начался.')
        return

    if match.turn != player_key:
        await update.message.reply_text('Сейчас ход другого игрока.')
        return

    coord = parser.parse_coord(text)
    if coord is None:
        await update.message.reply_text('Не понял клетку. Пример: e5.')
        return

    results = {}
    hit_any = False
    for enemy in enemy_keys:
        res = battle.apply_shot(match.boards[enemy], coord)
        results[enemy] = res
        if res in (battle.HIT, battle.KILL):
            hit_any = True
    for k in match.shots:
        shots = match.shots[k]
        shots.setdefault('move_count', 0)
        shots.setdefault('joke_start', random.randint(1, 10))
        shots['move_count'] += 1
    storage.save_match(match)

    coord_str = parser.format_coord(coord)
    parts_self = []
    next_player = player_key
    for enemy, res in results.items():
        if res == battle.MISS:
            phrase_self = _phrase_or_joke(match, player_key, SELF_MISS)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_MISS)
            parts_self.append(f"{enemy}: мимо. {phrase_self}")
            await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - соперник промахнулся. {phrase_enemy}")
        elif res == battle.HIT:
            phrase_self = _phrase_or_joke(match, player_key, SELF_HIT)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_HIT)
            parts_self.append(f"{enemy}: ранил. {phrase_self}")
            await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - ваш корабль ранен. {phrase_enemy}")
        elif res == battle.KILL:
            phrase_self = _phrase_or_joke(match, player_key, SELF_KILL)
            phrase_enemy = _phrase_or_joke(match, enemy, ENEMY_KILL)
            parts_self.append(f"{enemy}: уничтожен! {phrase_self}")
            await context.bot.send_message(match.players[enemy].chat_id, f"{coord_str} - ваш корабль уничтожен. {phrase_enemy}")
            if match.boards[enemy].alive_cells == 0:
                await context.bot.send_message(match.players[enemy].chat_id, 'Все ваши корабли уничтожены. Вы выбыли.')
    if not hit_any:
        order = [k for k in ('A', 'B', 'C') if k in match.players and match.boards[k].alive_cells > 0]
        idx = order.index(player_key)
        next_player = order[(idx + 1) % len(order)]
        match.turn = next_player
        storage.save_match(match)
        await context.bot.send_message(match.players[next_player].chat_id, 'Ваш ход.')
    else:
        match.turn = player_key
        storage.save_match(match)
    result_self = f"{coord_str} - {' '.join(parts_self)}" + (' Ваш ход.' if match.turn == player_key else f" Ход {next_player}.")
    await update.message.reply_text(result_self)

    alive_players = [k for k, b in match.boards.items() if b.alive_cells > 0]
    if len(alive_players) == 1:
        winner = alive_players[0]
        storage.finish(match, winner)
        await context.bot.send_message(match.players[winner].chat_id, 'Вы победили!')
        for k in match.players:
            if k != winner:
                await context.bot.send_message(match.players[k].chat_id, 'Игра окончена. Победил соперник.')
