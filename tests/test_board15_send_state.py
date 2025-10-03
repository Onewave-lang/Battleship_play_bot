import asyncio
from types import SimpleNamespace

from game_board15 import router, storage, placement

class DummyBot:
    async def send_message(self, *args, **kwargs):
        pass
    async def send_photo(self, *args, **kwargs):
        pass
    async def edit_message_media(self, *args, **kwargs):
        pass
    async def edit_message_text(self, *args, **kwargs):
        pass

class DummyMessage:
    def __init__(self, text):
        self.text = text
    async def reply_text(self, *args, **kwargs):
        pass

async def run_router(update):
    context = SimpleNamespace(bot=DummyBot(), chat_data={}, bot_data={})
    await router.router_text(update, context)


def test_send_state_for_all_players(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")

    match = storage.create_match(1, 1, "A")
    storage.join_match(match.match_id, 2, 2, "B")
    storage.join_match(match.match_id, 3, 3, "C")
    storage.save_board(match, "A", placement.random_board())
    storage.save_board(match, "B", placement.random_board())
    storage.save_board(match, "C", placement.random_board())

    called = []
    async def fake_send_state(context, match_obj, player_key, message, *, reveal_ships=True):
        called.append(player_key)
    monkeypatch.setattr(router, "_send_state", fake_send_state)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=DummyMessage("a1"),
        effective_chat=SimpleNamespace(id=1),
    )

    asyncio.run(run_router(update))

    assert set(called) == {"A", "B", "C"}
