import asyncio
import logging
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_board15 import handlers, router
from game_board15.models import Match15, Player


def _make_cell(value):
    return (lambda: value).__closure__[0]


def _get_safe_send_state(context, match, human):
    code = next(
        c
        for c in handlers._auto_play_bots.__code__.co_consts
        if isinstance(c, types.CodeType) and c.co_name == "_safe_send_state"
    )
    logger = logging.getLogger("test")
    return types.FunctionType(
        code,
        handlers._auto_play_bots.__globals__,
        name="_safe_send_state",
        argdefs=None,
        closure=(
            _make_cell(context),
            _make_cell(human),
            _make_cell(logger),
            _make_cell(match),
            _make_cell(router),
        ),
    )


def test_render_failure(monkeypatch):
    async def run():
        match = Match15.new(1, 1, "A")
        match.players["B"] = Player(user_id=0, chat_id=2, name="B")
        context = SimpleNamespace(
            bot=SimpleNamespace(
                send_photo=AsyncMock(),
                send_message=AsyncMock(),
            ),
            bot_data={},
        )

        def fail_render(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(handlers, "render_board", fail_render)
        monkeypatch.setattr(router, "render_board", fail_render)

        safe_send_state = _get_safe_send_state(context, match, "A")
        await safe_send_state("B", "msg")

        assert context.bot.send_photo.call_count == 0
        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args[0][1]
        assert "Не удалось отправить обновление" in text

    asyncio.run(run())
