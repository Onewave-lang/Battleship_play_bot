import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import router
from game_board15.models import Match15


def _stub_render(state, player_key):
    state.rendered_ship_cells = 20
    buffer = BytesIO()
    buffer.write(b"png")
    buffer.seek(0)
    return buffer


def test_snapshot_record_contains_field_and_metadata():
    match = Match15.new(1, 101, "Tester")
    snapshot = match.snapshots[-1]

    record = snapshot.to_record()

    assert record["turn"] in match.order
    assert record["turn_idx"] == match.turn_idx
    assert set(record["players"]) == set(match.players)
    field = record["field"]
    assert "grid" in field and len(field["grid"]) == 15
    assert "owners" in field and len(field["owners"]) == 15
    assert "ships" in field and all(field["ships"].get(key) for key in match.players)
    assert "history" in record
    assert isinstance(record["history"], list)
    assert "messages" in record
    assert "shots" in record


def test_send_state_blocks_unexpected_frame_changes(monkeypatch):
    monkeypatch.setattr(router, "render_board", _stub_render)

    async def run():
        match = Match15.new(1, 101, "Tester")
        match.match_id = "frame-guard"
        match.field.grid[0][0] = 2
        new_snapshot = match.create_snapshot()
        match._last_expected_changes = set()

        context = SimpleNamespace(
            bot=SimpleNamespace(send_photo=AsyncMock()),
            bot_data={},
        )

        await router._send_state(context, match, "A", "msg", snapshot=new_snapshot)

        context.bot.send_photo.assert_not_awaited()
        assert match.players["A"].chat_id not in context.bot_data.get(router.STATE_KEY, {})

    asyncio.run(run())


def test_send_state_allows_expected_frame_changes(monkeypatch):
    monkeypatch.setattr(router, "render_board", _stub_render)

    async def run():
        match = Match15.new(1, 101, "Tester")
        match.match_id = "frame-guard-allow"
        match.field.grid[0][1] = 2
        snapshot = match.create_snapshot()
        match._last_expected_changes = {(0, 1)}

        context = SimpleNamespace(
            bot=SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=42))),
            bot_data={},
        )

        await router._send_state(context, match, "A", "msg", snapshot=snapshot)

        context.bot.send_photo.assert_awaited_once()
        state_store = context.bot_data[router.STATE_KEY]
        assert match.players["A"].chat_id in state_store

    asyncio.run(run())
