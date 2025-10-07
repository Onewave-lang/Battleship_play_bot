import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from game_board15 import handlers, router, storage
from game_board15.models import Board15, Ship, Match15, Player


def test_three_player_match(monkeypatch):
    async def run():
        # deterministic boards far apart to avoid early hits
        def make_board(coord):
            b = Board15()
            r, c = coord
            b.grid = [[0] * 15 for _ in range(15)]
            b.grid[r][c] = 1
            b.ships = [Ship(cells=[(r, c)])]
            b.alive_cells = 1
            return b
        boards = iter([
            make_board((14, 14)),  # A
            make_board((13, 13)),  # B
            make_board((12, 12)),  # C
        ])
        monkeypatch.setattr(handlers.placement, "random_board_global", lambda mask: next(boards))

        match = Match15.new(1, 100, "Tester")
        monkeypatch.setattr(storage, "create_match", lambda uid, cid, name: match)
        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "finish", lambda m, w: None)
        monkeypatch.setattr(storage, "get_match", lambda mid: match)

        # non-empty renders
        monkeypatch.setattr(handlers, "render_board", lambda *a, **k: BytesIO(b"img"))
        monkeypatch.setattr(router, "render_board", lambda *a, **k: BytesIO(b"img"))

        async def assert_reply_photo(photo, *args, **kwargs):
            assert photo.getbuffer().nbytes > 0
            return SimpleNamespace(message_id=1)

        update = SimpleNamespace(
            message=SimpleNamespace(
                reply_text=AsyncMock(),
                reply_photo=AsyncMock(side_effect=assert_reply_photo),
                text="",
            ),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=100),
        )

        async def assert_send_photo(*args, **kwargs):
            buf = kwargs.get("photo") or (len(args) > 1 and args[1])
            assert buf.getbuffer().nbytes > 0
            return SimpleNamespace(message_id=3)

        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=2)),
            send_photo=AsyncMock(side_effect=assert_send_photo),
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(return_value=None),
            delete_message=AsyncMock(return_value=None),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        tasks = []
        orig_create_task = asyncio.create_task

        def fake_create_task(coro):
            t = orig_create_task(coro)
            tasks.append(t)
            return t

        monkeypatch.setattr(asyncio, "create_task", fake_create_task)

        # start test match
        await handlers.board15_test(update, context)

        # human move
        update.message.text = "a3"
        await router.router_text(update, context)

        # wait for bots to play until turn returns to human
        while match.turn != "A":
            await asyncio.sleep(0.05)

        for t in tasks:
            t.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert not any(
            isinstance(r, BadRequest) for r in results if not isinstance(r, asyncio.CancelledError)
        )

        # ensure board images were produced for each turn
        assert update.message.reply_photo.call_count == 1
        assert bot.send_photo.call_count >= 3

    asyncio.run(run())


def test_admin_turn_skips_unaffected_boards(monkeypatch):
    async def run():
        match = Match15.new(1, 101, "Admin")
        match.status = "playing"
        match.turn = "A"

        match.players["B"] = Player(user_id=2, chat_id=202, name="Beta", ready=True)
        match.players["C"] = Player(user_id=3, chat_id=303, name="Gamma", ready=True)

        board_b = match.boards["B"]
        board_b.grid = [[0] * 15 for _ in range(15)]
        board_b.grid[0][0] = 1
        board_b.ships = [Ship(cells=[(0, 0)])]
        board_b.alive_cells = 1

        board_c = match.boards["C"]
        board_c.grid = [[0] * 15 for _ in range(15)]
        board_c.grid[4][4] = 1
        board_c.ships = [Ship(cells=[(4, 4)])]
        board_c.alive_cells = 1

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(storage, "finish", lambda m, w: None)
        monkeypatch.setattr(storage, "get_match", lambda mid: match)

        monkeypatch.setattr(router, "render_board", lambda *a, **k: BytesIO(b"buf"))

        photo_chats: list[int] = []
        message_chats: list[int] = []

        async def fake_send_photo(chat_id, *args, **kwargs):
            photo_chats.append(chat_id)
            return SimpleNamespace(message_id=len(photo_chats))

        async def fake_send_message(chat_id, *args, **kwargs):
            message_chats.append(chat_id)
            return SimpleNamespace(message_id=len(message_chats))

        send_photo = AsyncMock(side_effect=fake_send_photo)
        send_message = AsyncMock(side_effect=fake_send_message)

        bot = SimpleNamespace(
            send_photo=send_photo,
            send_message=send_message,
            edit_message_media=AsyncMock(),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot, bot_data={}, chat_data={})

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=101),
        )

        await router.router_text(update, context)

        assert 202 in photo_chats
        assert 303 not in photo_chats

        assert 303 in message_chats

    asyncio.run(run())
