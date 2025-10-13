import asyncio
from types import SimpleNamespace

from unittest.mock import AsyncMock

from game_board15 import router as router15
from game_board15.battle import MISS, ShotResult
from game_board15.models import Field15, PLAYER_ORDER, empty_history


def test_router_text_skips_dummy_chat_notifications(monkeypatch):
    async def run():
        field = Field15()
        players = {
            "A": SimpleNamespace(user_id=1, chat_id=101, name="Admin"),
            "B": SimpleNamespace(user_id=2, chat_id=0, name="BotB"),
            "C": SimpleNamespace(user_id=3, chat_id=0, name="BotC"),
        }
        shots = {
            key: {"history": [], "last_result": None, "move_count": 0, "joke_start": None}
            for key in PLAYER_ORDER
        }
        match = SimpleNamespace(
            status="playing",
            players=players,
            field=field,
            boards={key: field for key in PLAYER_ORDER},
            turn="A",
            order=list(PLAYER_ORDER),
            turn_idx=0,
            messages={key: {} for key in PLAYER_ORDER},
            shots=shots,
            cell_history=empty_history(15),
            history=[],
            alive_cells={key: 20 for key in PLAYER_ORDER},
            snapshots=[],
        )

        monkeypatch.setattr(
            router15.storage,
            "find_match_by_user",
            lambda uid, chat_id=None: match,
        )
        monkeypatch.setattr(router15.storage, "save_match", lambda match_obj: None)

        def fake_append_snapshot(match_obj, *_, **__):
            snapshot = SimpleNamespace(
                field=match_obj.field,
                cell_history=match_obj.cell_history,
                shot_history=list(match_obj.history),
                last_move=getattr(match_obj.field, "last_move", None),
                status=match_obj.status,
                turn_idx=getattr(match_obj, "turn_idx", 0),
                alive_cells=dict(match_obj.alive_cells),
            )
            match_obj.snapshots.append(snapshot)
            return snapshot

        monkeypatch.setattr(router15.storage, "append_snapshot", fake_append_snapshot)
        monkeypatch.setattr(router15.parser, "parse_coord", lambda text: (0, 0))
        monkeypatch.setattr(router15.parser, "format_coord", lambda coord: "a1")
        monkeypatch.setattr(
            router15,
            "apply_shot",
            lambda *args, **kwargs: ShotResult(result=MISS, owner=None, coord=(0, 0)),
        )
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router15, "random_phrase", lambda phrases: "")

        send_state = AsyncMock()
        monkeypatch.setattr(router15, "_send_state", send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=101),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router15.router_text(update, context)

        assert send_state.await_count == 1
        call = send_state.await_args_list[0]
        assert call.args[2] == "A"

    asyncio.run(run())
