import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from models import Board, Ship
from handlers import router
import storage

from game_board15 import router as router15, storage as storage15
from game_board15.models import Board15, Ship as Ship15
from tests.utils import _new_grid


def test_router_clears_player_highlight(monkeypatch):
    async def run_test():
        board_self = Board()
        board_self.highlight = [(5, 5)]
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
            shots={"A": {"history": [], "move_count": 0, "joke_start": 10}, "B": {}},
            messages={"A": {}, "B": {}},
        )

        monkeypatch.setattr(storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage, "save_match", lambda m: None)
        monkeypatch.setattr(router, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router, "_send_state", AsyncMock())

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

        await router.router_text(update, context)

        assert board_self.highlight == []

    asyncio.run(run_test())


def test_board15_router_clears_player_highlight(monkeypatch):
    async def run_test():
        board_self = Board15()
        board_self.highlight = [(5, 5)]
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
            shots={"A": {"history": [], "last_result": None, "move_count": 0, "joke_start": 10, "last_coord": None}, "B": {}},
            messages={"A": {}, "B": {}},
            cell_history=_new_grid(15),
            history=[],
            alive_cells={"A": 20, "B": 1, "C": 0},
            order=["A", "B", "C"],
            turn_idx=0,
            snapshots=[],
        )

        monkeypatch.setattr(storage15, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(storage15, "save_match", lambda m: None)
        monkeypatch.setattr(
            storage15,
            "append_snapshot",
            lambda m, *_, **__: SimpleNamespace(
                field=getattr(m, "field", board_enemy),
                cell_history=[
                    [list(cell) for cell in row]
                    for row in getattr(m, "cell_history", _new_grid(15))
                ],
                shot_history=list(getattr(m, "history", [])),
                last_move=getattr(m.field, "last_move", None),
                status=m.status,
                turn_idx=getattr(m, "turn_idx", 0),
                alive_cells=getattr(m, "alive_cells", {}),
            ),
        )
        monkeypatch.setattr(router15.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router15.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router15, "_send_state", AsyncMock())

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=10),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={}, chat_data={})

        await router15.router_text(update, context)

        assert board_self.highlight == []

    asyncio.run(run_test())
