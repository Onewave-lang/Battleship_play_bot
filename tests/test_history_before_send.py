import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router as router15
from game_board15.battle import HIT, KILL, MISS, ShotResult
from game_board15.models import Board15, Ship as Ship15, ShotLogEntry
from handlers import router as router_std
from models import Board, Ship
import storage
from tests.utils import _new_grid


def test_board15_router_updates_history_before_send(monkeypatch):
    async def run():
        board_self = Board15()
        board_enemy = Board15()
        ship = Ship15(cells=[(0, 0)], owner="B")
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
            cell_history=_new_grid(15),
            history=[],
            last_highlight=[],
            alive_cells={"A": 20, "B": 1, "C": 0},
            order=["A", "B", "C"],
            turn_idx=0,
            snapshots=[],
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
        monkeypatch.setattr(router15.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router15.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")

        captured = {}

        async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True, snapshot=None):
            captured["cell"] = snapshot.cell_history[0][0][0]
            captured["saved"] = saved
            captured["history_len"] = len(match_obj.history)
            captured["log_entry"] = match_obj.history[-1] if match_obj.history else None

        monkeypatch.setattr(router15, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router15.router_text(update, context)

        assert captured["cell"] == 4
        assert captured["saved"]
        assert saved
        assert captured["history_len"] == 1
        entry = captured["log_entry"]
        assert isinstance(entry, ShotLogEntry)
        assert entry.by_player == "A"
        assert entry.coord == (0, 0)
        assert entry.result == KILL

    asyncio.run(run())


def test_update_history_marks_last_move_and_decays():
    boards = {key: Board15() for key in ("A", "B", "C")}
    match = SimpleNamespace(cell_history=_new_grid(15), boards=boards, history=[])

    miss_result = ShotResult(result=MISS, owner=None, coord=(0, 0))
    router15._update_history(match, "A", miss_result)
    assert match.cell_history[0][0] == [2, None, 0]

    hit_result = ShotResult(result=HIT, owner="B", coord=(0, 1))
    router15._update_history(match, "A", hit_result)
    assert match.cell_history[0][0][2] == 1
    assert match.cell_history[0][1] == [3, "B", 0]

    ship = Ship15(cells=[(1, 1), (1, 2)], owner="C")
    kill_result = ShotResult(
        result=KILL,
        owner="C",
        coord=(1, 1),
        killed_ship=ship,
        contour=[(0, 2)],
    )
    router15._update_history(match, "B", kill_result)
    assert match.cell_history[1][1] == [4, "C", 0]
    assert match.cell_history[1][2] == [4, "C", 0]
    assert match.cell_history[0][1][2] == 1
    assert match.cell_history[0][2] == [5, None, 1]

    next_miss = ShotResult(result=MISS, owner=None, coord=(2, 2))
    router15._update_history(match, "C", next_miss)
    assert match.cell_history[1][1][2] == 1
    assert match.cell_history[2][2] == [2, None, 0]
    assert len(match.history) == 4
    assert isinstance(match.history[-1], ShotLogEntry)
    assert match.history[-1].by_player == "C"


def test_board_test_router_updates_history_before_send(monkeypatch):
    async def run():
        board_self = Board()
        board_enemy = Board()
        ship = Ship(cells=[(0, 0), (0, 1)])
        board_enemy.ships = [ship]
        board_enemy.grid[0][0] = 1
        board_enemy.grid[0][1] = 1
        board_enemy.alive_cells = 2
        match = SimpleNamespace(
            status="playing",
            players={
                "A": SimpleNamespace(user_id=1, chat_id=10, name="A"),
                "B": SimpleNamespace(user_id=2, chat_id=20, name="B"),
            },
            boards={"A": board_self, "B": board_enemy},
            turn="A",
            shots={"A": {"history": [], "move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
            history=[[0] * 10 for _ in range(10)],
            last_highlight=[],
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
            captured["cell"] = match_obj.history[0][0]
            captured["saved"] = saved

        monkeypatch.setattr(router_std, "_send_state_board_test", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router_std.router_text_board_test(update, context)

        assert captured["cell"] == 3
        assert captured["saved"]

    asyncio.run(run())
