import asyncio
from io import BytesIO
from types import SimpleNamespace

from game_board15 import router, storage, placement
from game_board15.handlers import STATE_KEY
from game_board15.models import Match15, Player

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


def test_send_state_restores_player_ships(monkeypatch):
    async def _run():
        match = Match15.new(1, 1, "A")
        match.players["B"] = Player(user_id=2, chat_id=2, name="B")
        match.players["C"] = Player(user_id=3, chat_id=3, name="C")
        match.status = "playing"
        match.boards["A"].grid[0][0] = 1

        snapshot = {
            "history": [[0 for _ in range(15)] for _ in range(15)],
            "boards": {
                "A": {"grid": [[0 for _ in range(15)] for _ in range(15)]},
                "B": {"grid": [[0 for _ in range(15)] for _ in range(15)]},
                "C": {"grid": [[0 for _ in range(15)] for _ in range(15)]},
            },
            "last_highlight": [],
        }
        match.snapshots.append(snapshot)

        class _Bot:
            async def send_message(self, *args, **kwargs):
                return SimpleNamespace(message_id=101)

            async def send_photo(self, *args, **kwargs):
                return SimpleNamespace(message_id=202)

        monkeypatch.setattr(router, "render_board", lambda state, player_key=None: BytesIO(b"x"))

        context = SimpleNamespace(bot=_Bot(), bot_data={}, chat_data={})
        await router._send_state(context, match, "A", "test")

        state = context.bot_data[STATE_KEY][match.players["A"].chat_id]
        assert state.board[0][0] == 1
        assert state.owners[0][0] == "A"

    asyncio.run(_run())
