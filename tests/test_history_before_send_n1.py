from unittest.mock import AsyncMock
import asyncio
from types import SimpleNamespace

from game_board15 import router as router15
from game_board15.models import Board15, Ship as Ship15
from handlers import router as router_std
from models import Board, Ship
import storage


def test_board15_router_updates_history_before_send_n1(monkeypatch):
    async def run():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship15(cells=[(0, 13)], owner="B")
        board_enemy.ships = [ship]
        board_enemy.grid[0][13] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            messages={"A": {}, "B": {}},
            shots={"A": {"history": []}, "B": {}},
            cell_history=[[0] * 15 for _ in range(15)],
            history=[],
            alive_cells={"A": 20, "B": 1, "C": 0},
            order=["A", "B", "C"],
            turn_idx=0,
            snapshots=[],
            last_highlight=[],
        )
        saved = False

        def fake_save_match(m):
            nonlocal saved
            saved = True

        def fake_append_snapshot(match_obj):
            snapshot = SimpleNamespace(
                field=getattr(match_obj, "field", board_enemy),
                cell_history=[
                    [list(cell) for cell in row]
                    for row in match_obj.cell_history
                ],
                shot_history=list(match_obj.history),
                last_move=getattr(match_obj.field, "last_move", None),
                status=match_obj.status,
                turn_idx=getattr(match_obj, "turn_idx", 0),
                alive_cells=getattr(match_obj, "alive_cells", {}),
            )
            match_obj.snapshots.append(snapshot)
            fake_save_match(match_obj)
            return snapshot

        monkeypatch.setattr(router15.storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router15.storage, "save_match", fake_save_match)
        monkeypatch.setattr(router15.storage, "append_snapshot", fake_append_snapshot)
        monkeypatch.setattr(router15.parser, "parse_coord", lambda text: (0, 13))
        monkeypatch.setattr(router15.parser, "format_coord", lambda coord: "n1")
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")

        captured = {}

        async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True, snapshot=None):
            captured["cell"] = snapshot.cell_history[0][13][0]
            captured["saved"] = saved
            captured["history_len"] = len(match_obj.history)

        monkeypatch.setattr(router15, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="n1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router15.router_text(update, context)

        assert captured["cell"] == 4
        assert captured["saved"]
        assert captured["history_len"] == 1

    asyncio.run(run())


def test_router_updates_board_before_send(monkeypatch):
    async def run():
        board_self = Board()
        board_enemy = Board()
        ship = Ship(cells=[(0, 0)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.alive_cells = 1
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            messages={"A": {}, "B": {}},
            shots={"A": {"history": []}, "B": {}},
        )
        saved = False

        def fake_save_match(m):
            nonlocal saved
            saved = True

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", fake_save_match)
        monkeypatch.setattr(router_std, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router_std, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router_std, "_phrase_or_joke", lambda m, pk, ph: "")

        captured = {}

        async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True):
            captured["cell"] = match_obj.boards["B"].grid[0][0]
            captured["saved"] = saved

        monkeypatch.setattr(router_std, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router_std.router_text(update, context)

        assert captured["cell"] == 4
        assert captured["saved"]

    asyncio.run(run())
