import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _reload_board15(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA15_FILE_PATH", str(tmp_path / "data15.json"))
    monkeypatch.setenv("DATA15_SNAPSHOTS", str(tmp_path / "snapshots"))
    commands_module = importlib.import_module("handlers.commands")
    storage_module = importlib.import_module("game_board15.storage")
    handlers_module = importlib.import_module("game_board15.handlers")
    router_module = importlib.import_module("handlers.router")
    importlib.reload(commands_module)
    importlib.reload(storage_module)
    importlib.reload(handlers_module)
    importlib.reload(router_module)
    return commands_module, storage_module, handlers_module, router_module


def test_board15_prompts_for_name(monkeypatch, tmp_path):
    commands_module, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(user_data={}, bot_data={})

        await handlers15.board15(update, context)

        calls = [call.args[0] for call in reply_text.call_args_list]
        assert any("Перед созданием матча" in text for text in calls)
        assert any("Введите имя" in text for text in calls)
        state = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert state.get("waiting") is True
        assert state.get("hint") == commands_module.NAME_HINT_BOARD15
        assert storage15.find_match_by_user(1, 1) is None

    asyncio.run(run())


def test_board15_creates_match_after_name(monkeypatch, tmp_path):
    commands_module, storage15, handlers15, router_module = _reload_board15(monkeypatch, tmp_path)

    async def run():
        reply_text_cmd = AsyncMock()
        update_cmd = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text_cmd),
            effective_user=SimpleNamespace(id=1, first_name="Tester"),
            effective_chat=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(user_data={}, bot_data={}, bot=SimpleNamespace())

        await handlers15.board15(update_cmd, context)

        reply_text_name = AsyncMock()
        update_name = SimpleNamespace(
            message=SimpleNamespace(text="Иван", reply_text=reply_text_name),
            effective_user=update_cmd.effective_user,
            effective_chat=update_cmd.effective_chat,
        )

        await router_module.router_text(update_name, context)

        responses = [call.args[0] for call in reply_text_name.call_args_list]
        assert any("Имя сохранено" in text for text in responses)
        assert any("Матч создан" in text for text in responses)

        match = storage15.find_match_by_user(1, 1)
        assert match is not None
        assert match.players["A"].name == "Иван"
        assert match.status == "waiting"

        assert context.user_data.get(commands_module.NAME_KEY) == "Иван"
        state = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert not state.get("waiting")

    asyncio.run(run())


def test_board15_invite_link_uses_deep_link(monkeypatch, tmp_path):
    _, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        match = storage15.create_match(1, 1, "Игрок A")
        reply_text = AsyncMock()
        bot_mock = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(username="TestBot"))
        )
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=1),
                reply_text=reply_text,
            ),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={}, bot_data={}, bot=bot_mock)

        await handlers15.send_board15_invite_link(update, context)

        assert query.answer.call_count == 1
        texts = [record.args[0] for record in reply_text.call_args_list]
        expected_link = f"https://t.me/TestBot?start=b15_{match.match_id}"
        assert any(expected_link in text for text in texts)
        assert any(f"/start b15_{match.match_id}" in text for text in texts)
        bot_mock.get_me.assert_awaited()

    asyncio.run(run())


def test_board15_reaches_playing_after_full_roster(monkeypatch, tmp_path):
    _, storage15, _, _ = _reload_board15(monkeypatch, tmp_path)

    match = storage15.create_match(1, 1, "Игрок A")
    assert match.status == "waiting"

    storage15.join_match(match.match_id, 2, 2, "Игрок B")
    intermediate = storage15.get_match(match.match_id)
    assert intermediate.status == "waiting"

    storage15.join_match(match.match_id, 3, 3, "Игрок C")
    updated = storage15.get_match(match.match_id)
    assert updated.status == "playing"
    assert updated.turn == "A"


def test_board15_test_sets_playing(monkeypatch, tmp_path):
    commands_module, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        context = SimpleNamespace(
            user_data={commands_module.NAME_KEY: "Тест"},
            bot_data={},
            bot=SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)), send_message=AsyncMock()),
        )
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=1, first_name="Admin"),
            effective_chat=SimpleNamespace(id=1),
        )

        auto_play_mock = AsyncMock()
        monkeypatch.setattr(handlers15, "_auto_play_bots", auto_play_mock)

        await handlers15.board15_test(update, context)

        match = storage15.find_match_by_user(1, 1)
        assert match is not None
        assert match.status == "playing"
        auto_play_mock.assert_awaited()
        reply_messages = [call.args[0] for call in reply_text.call_args_list]
        assert any("Тестовый матч 15×15 создан" in text for text in reply_messages)

    asyncio.run(run())


def test_board15_join_requires_name_and_does_not_request_auto(monkeypatch, tmp_path):
    commands_module, storage15, _, router_module = _reload_board15(monkeypatch, tmp_path)

    async def run():
        match = storage15.create_match(1, 1, "Игрок A")

        reply_text_start = AsyncMock()
        update_start = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text_start),
            effective_user=SimpleNamespace(id=2, first_name="Игрок B"),
            effective_chat=SimpleNamespace(id=2),
        )
        context = SimpleNamespace(
            args=[f"b15_{match.match_id}"],
            bot=SimpleNamespace(send_message=AsyncMock()),
            user_data={},
            bot_data={},
        )

        await commands_module.start(update_start, context)

        prompts = [call.args[0] for call in reply_text_start.call_args_list]
        assert any("Перед присоединением" in text for text in prompts)
        assert any("Введите имя" in text for text in prompts)

        state = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert state.get("waiting") is True
        pending = state.get("pending") or {}
        assert pending.get("action") == commands_module.NAME_PENDING_BOARD15_JOIN
        assert pending.get("match_id") == match.match_id

        reply_text_name = AsyncMock()
        reply_photo_name = AsyncMock()
        update_name = SimpleNamespace(
            message=SimpleNamespace(
                text="Игрок Б",
                reply_text=reply_text_name,
                reply_photo=reply_photo_name,
            ),
            effective_user=update_start.effective_user,
            effective_chat=update_start.effective_chat,
        )

        await router_module.router_text(update_name, context)

        name_texts = [call.args[0] for call in reply_text_name.call_args_list]
        assert any("Имя сохранено" in text for text in name_texts)
        assert any("Вы присоединились к матчу 15×15" in text for text in name_texts)
        assert all('"авто"' not in text.lower() for text in name_texts)

        assert reply_photo_name.await_count == 1

        other_messages = [call.args[1] for call in context.bot.send_message.call_args_list]
        assert other_messages
        assert all('"авто"' not in text.lower() for text in other_messages)

        stored_name = context.user_data.get(commands_module.NAME_KEY)
        assert stored_name == "Игрок Б"
        state_after = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert not state_after.get("waiting")

    asyncio.run(run())
