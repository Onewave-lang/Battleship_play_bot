import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_board15 import handlers, router, storage
from game_board15.models import Board15, Ship, Match15
from game_board15.state import Board15State


def test_board15_test_manual(monkeypatch):
    async def run():
        # prepare deterministic boards: A has ship at o15, B at a1, C at b1
        def build_board(pattern):
            board = Board15()
            board.grid = [[0] * 15 for _ in range(15)]
            board.ships = []
            for cells in pattern:
                ship_cells = [tuple(cell) for cell in cells]
                board.ships.append(Ship(cells=ship_cells))
                for r, c in ship_cells:
                    board.grid[r][c] = 1
            board.alive_cells = sum(len(cells) for cells in pattern)
            return board

        board_a_pattern = [
            [(10, 10), (10, 11), (10, 12), (10, 13)],
            [(6, 12), (7, 12), (8, 12)],
            [(6, 14), (7, 14), (8, 14)],
            [(12, 8), (12, 9)],
            [(13, 6), (13, 7)],
            [(8, 6), (9, 6)],
            [(14, 14)],
            [(12, 12)],
            [(14, 12)],
            [(12, 14)],
        ]
        board_b_pattern = [
            [(0, 2), (0, 3), (0, 4), (0, 5)],
            [(2, 0), (3, 0), (4, 0)],
            [(2, 6), (3, 6), (4, 6)],
            [(6, 0), (6, 1)],
            [(6, 3), (6, 4)],
            [(8, 1), (9, 1)],
            [(0, 0)],
            [(2, 4)],
            [(4, 4)],
            [(8, 4)],
        ]
        board_c_pattern = [
            [(0, 9), (0, 10), (0, 11), (0, 12)],
            [(2, 9), (3, 9), (4, 9)],
            [(2, 11), (3, 11), (4, 11)],
            [(6, 9), (6, 10)],
            [(6, 12), (6, 13)],
            [(8, 10), (9, 10)],
            [(0, 1)],
            [(2, 13)],
            [(4, 13)],
            [(8, 13)],
        ]

        boards = iter([
            build_board(board_a_pattern),
            build_board(board_b_pattern),
            build_board(board_c_pattern),
        ])
        monkeypatch.setattr(handlers.placement, "random_board_global", lambda mask: next(boards))

        # in-memory match handling
        match = Match15.new(1, 100, "Tester")
        monkeypatch.setattr(storage, "create_match", lambda uid, cid, name: match)
        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        finished = {}
        def fake_finish(m, w):
            finished["winner"] = w
        monkeypatch.setattr(storage, "finish", fake_finish)

        # renderers
        if hasattr(handlers, "render_board"):
            monkeypatch.setattr(handlers, "render_board", lambda *a, **k: BytesIO())
        monkeypatch.setattr(router, "render_board", lambda *a, **k: BytesIO())

        # capture background tasks
        tasks = []

        orig_sleep = handlers.asyncio.sleep

        async def fast_sleep(delay):
            await orig_sleep(0)

        monkeypatch.setattr(handlers.asyncio, "sleep", fast_sleep)

        async def fake_schedule_auto_play(match_obj, context_obj, chat_id, *, human, delay):
            match_obj.turn = 'B'
            match_obj.boards['B'].alive_cells = 0
            match_obj.boards['C'].alive_cells = 0
            match_obj.status = 'finished'
            finished['winner'] = human
            await context_obj.bot.send_message(
                chat_id,
                "Флот игрока B потоплен! B выбывает.",
            )
            await context_obj.bot.send_message(
                chat_id,
                "Флот игрока C потоплен! C занял 2 место. Вы победили!🏆",
            )
            match_obj.turn = 'A'

        monkeypatch.setattr(handlers, "_schedule_auto_play", fake_schedule_auto_play)

        calls: list[tuple[str, str]] = []

        async def reply_text(msg):
            calls.append(("text", msg))
            return SimpleNamespace()

        async def reply_photo(buf, caption=None):
            calls.append(("photo", caption))
            return SimpleNamespace(message_id=1)

        update = SimpleNamespace(
            message=SimpleNamespace(
                reply_text=reply_text,
                reply_photo=reply_photo,
                text="",
            ),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=100),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=3)),
            ),
            bot_data={},
        )

        sent_to: list[str] = []

        original_send_state = router._send_state

        async def fake_send_state(
            context,
            match_obj,
            player_key,
            message,
            *,
            reveal_ships=True,
            snapshot_override=None,
            include_all_ships=False,
        ):
            sent_to.append(player_key)
            return await original_send_state(
                context,
                match_obj,
                player_key,
                message,
                reveal_ships=reveal_ships,
                snapshot_override=snapshot_override,
                include_all_ships=include_all_ships,
            )

        monkeypatch.setattr(router, "_send_state", fake_send_state)

        await handlers.board15_test(update, context)

        # ensure start text sent before any board output
        assert calls[0][0] == "text"

        state = context.bot_data[handlers.STATE_KEY][update.effective_chat.id]
        assert state.owners[14][14] == "A"
        assert state.footer_label.startswith("match=")
        assert "player=A" in state.footer_label
        expected_ships = sum(
            1
            for r in range(15)
            for c in range(15)
            if match.boards['A'].grid[r][c] in {1, 3, 4}
        )
        assert f"ships={expected_ships}" in state.footer_label
        expected_sh_disp = sum(
            1
            for r in range(15)
            for c in range(15)
            if state.owners[r][c] == 'A' and state.board[r][c] in {1, 3, 4}
        )
        assert f"sh_disp={expected_sh_disp}" in state.footer_label

        # first human move: miss at c3
        update.message.reply_text = AsyncMock()
        update.message.text = "c3"
        await router.router_text(update, context)
        assert match.turn == "B"
        assert update.message.reply_text.call_count == 0

        # wait for bots to play until our turn again
        while match.turn != "A":
            await asyncio.sleep(0.05)

        # second human move: sink B at a1
        update.message.reply_text.reset_mock()
        update.message.text = "a1"
        await router.router_text(update, context)
        assert update.message.reply_text.call_count == 0

        # allow background tasks to finish
        await asyncio.gather(*tasks)

        assert finished.get("winner") == "A"
        messages = [c.args[1] for c in context.bot.send_message.call_args_list]
        assert any("B выбывает" in m for m in messages)
        assert any("C занял 2 место" in m for m in messages)
        assert any("Вы победили!🏆" in m for m in messages)
        assert set(sent_to) == {"A"}

    asyncio.run(run())
