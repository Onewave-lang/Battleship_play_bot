import asyncio
from types import SimpleNamespace

from unittest.mock import AsyncMock

from game_board15 import router as router15
from game_board15.models import Field15, Ship, PLAYER_ORDER, empty_history


def _setup_match():
    field = Field15()
    ship_b = Ship(cells=[(0, 0)], owner="B")
    ship_c = Ship(cells=[(1, 0)], owner="C")
    field.grid[0][0] = 1
    field.grid[1][0] = 1
    field.owners[0][0] = "B"
    field.owners[1][0] = "C"
    field.ships = {"A": [], "B": [ship_b], "C": [ship_c]}

    players = {
        "A": SimpleNamespace(user_id=1, chat_id=101, name="Alpha"),
        "B": SimpleNamespace(user_id=2, chat_id=202, name="Bravo"),
        "C": SimpleNamespace(user_id=3, chat_id=303, name="Charlie"),
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
        alive_cells={"A": 20, "B": 1, "C": 1},
        snapshots=[],
    )
    return match


def test_router_text_sends_elimination_and_final_summary(monkeypatch):
    async def run():
        match = _setup_match()

        coords = [(0, 0), (1, 0)]
        coord_labels = {(0, 0): "a1", (1, 0): "a2"}

        def fake_parse_coord(_text):
            return coords.pop(0)

        def fake_format_coord(coord):
            return coord_labels[coord]

        async def fake_send_state(context, match_obj, player_key, message, *, snapshot, reveal_ships=False):
            match_obj._last_sent = (player_key, message, snapshot)

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

        monkeypatch.setattr(router15.storage, "find_match_by_user", lambda uid, chat_id=None: match)
        monkeypatch.setattr(router15.storage, "save_match", lambda match_obj: None)
        monkeypatch.setattr(router15.storage, "append_snapshot", fake_append_snapshot)
        monkeypatch.setattr(router15.parser, "parse_coord", fake_parse_coord)
        monkeypatch.setattr(router15.parser, "format_coord", fake_format_coord)
        monkeypatch.setattr(router15, "_phrase_or_joke", lambda m, pk, ph: "")
        monkeypatch.setattr(router15, "random_phrase", lambda phrases: "")
        monkeypatch.setattr(router15, "_send_state", fake_send_state)

        update = SimpleNamespace(
            message=SimpleNamespace(text="a1", reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=101),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})

        await router15.router_text(update, context)

        # Second shot to finish the game
        update.message.text = "a2"
        await router15.router_text(update, context)

        calls = context.bot.send_message.await_args_list
        messages_by_chat = {}
        for call in calls:
            chat_id, text = call.args[:2]
            messages_by_chat.setdefault(chat_id, []).append(text)

        assert any("⛔ Игрок Bravo выбыл" in text for text in messages_by_chat[101])
        assert any("⛔ Игрок Bravo выбыл" in text for text in messages_by_chat[202])
        assert any("⛔ Игрок Bravo выбыл" in text for text in messages_by_chat[303])

        assert any("⛔ Игрок Charlie выбыл" in text for text in messages_by_chat[101])
        assert any("⛔ Игрок Charlie выбыл" in text for text in messages_by_chat[202])
        assert any("⛔ Игрок Charlie выбыл" in text for text in messages_by_chat[303])

        winner_summary = messages_by_chat[101][-1]
        assert "Вы победили!🏆" in winner_summary
        assert "1. Alpha" in winner_summary
        assert "2. Charlie" in winner_summary
        assert "3. Bravo" in winner_summary

        second_summary = messages_by_chat[303][-1]
        assert "Вы заняли 2 место." in second_summary
        assert "1. Alpha" in second_summary
        assert "3. Bravo" in second_summary

        third_summary = messages_by_chat[202][-1]
        assert "Вы заняли 3 место." in third_summary

    asyncio.run(run())
