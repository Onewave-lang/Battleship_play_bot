import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, call


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


def test_board15_find_match_ignores_finished(monkeypatch, tmp_path):
    _, storage15, _, _ = _reload_board15(monkeypatch, tmp_path)

    match = storage15.create_match(1, 1, "Игрок A")
    match.status = "finished"
    storage15.save_match(match)

    assert storage15.find_match_by_user(1, 1) is None


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
        bot_mock = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(username="TestBot"))
        )
        context = SimpleNamespace(user_data={}, bot_data={}, bot=bot_mock)

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

        markups = [
            call.kwargs.get("reply_markup")
            for call in reply_text_name.call_args_list
            if call.kwargs.get("reply_markup") is not None
        ]
        assert any(
            any(
                button.text == "Пригласить соперник-бота"
                for button in row
            )
            for markup in markups
            for row in getattr(markup, "inline_keyboard", [])
        )

        match = storage15.find_match_by_user(1, 1)
        assert match is not None
        assert match.players["A"].name == "Иван"
        assert match.status == "waiting"

        assert context.user_data.get(commands_module.NAME_KEY) == "Иван"
        state = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert not state.get("waiting")
        bot_mock.get_me.assert_awaited()

    asyncio.run(run())


def test_add_board15_bot_requires_second_human(monkeypatch, tmp_path):
    _, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        match = storage15.create_match(1, 1, "Игрок A")
        reply_text = AsyncMock()
        auto_play_mock = AsyncMock()
        monkeypatch.setattr(handlers15, "_auto_play_bots", auto_play_mock)

        query = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=1),
                reply_text=reply_text,
                edit_reply_markup=AsyncMock(),
            ),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={},
        )

        await handlers15.add_board15_bot(update, context)

        reply_messages = [call.args[0] for call in reply_text.call_args_list]
        assert any("Дождитесь подключения" in text for text in reply_messages)
        auto_play_mock.assert_not_awaited()
        assert storage15.get_match(match.match_id).status == "waiting"

    asyncio.run(run())


def test_add_board15_bot_fills_slot(monkeypatch, tmp_path):
    _, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        match = storage15.create_match(1, 1, "Игрок A")
        storage15.join_match(match.match_id, 2, 2, "Игрок B")
        auto_play_mock = AsyncMock()
        monkeypatch.setattr(handlers15, "_auto_play_bots", auto_play_mock)

        reply_text = AsyncMock()
        message = SimpleNamespace(
            chat=SimpleNamespace(id=1),
            reply_text=reply_text,
            edit_reply_markup=AsyncMock(),
        )
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            message=message,
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={},
        )

        await handlers15.add_board15_bot(update, context)

        refreshed = storage15.get_match(match.match_id)
        assert refreshed.status == "playing"
        assert "C" in refreshed.players
        assert refreshed.players["C"].user_id == 0

        reply_messages = [call.args[0] for call in reply_text.call_args_list]
        assert any("Бот присоединился" in text for text in reply_messages)
        context.bot.send_message.assert_called_once()
        args, _ = context.bot.send_message.call_args
        assert args[0] == refreshed.players["B"].chat_id

        auto_play_mock.assert_awaited_once()
        called_args = auto_play_mock.await_args
        assert called_args.args[0] is context
        assert called_args.args[1].match_id == match.match_id
        assert called_args.kwargs.get("human_keys") == ["A", "B"]

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


def test_board15_third_player_triggers_initial_boards(monkeypatch, tmp_path):
    commands_module, storage15, _, router_module = _reload_board15(monkeypatch, tmp_path)

    async def run():
        match = storage15.create_match(1, 1, "Игрок A")
        storage15.join_match(match.match_id, 2, 2, "Игрок Б")

        context = SimpleNamespace(
            args=[f"b15_{match.match_id}"],
            bot=SimpleNamespace(send_message=AsyncMock()),
            user_data={},
            bot_data={},
        )

        reply_text_start = AsyncMock()
        update_start = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text_start),
            effective_user=SimpleNamespace(id=3, first_name="Игрок С"),
            effective_chat=SimpleNamespace(id=3),
        )

        await commands_module.start(update_start, context)

        prompts = [call.args[0] for call in reply_text_start.call_args_list]
        assert any("Введите имя" in text for text in prompts)

        reply_text_name = AsyncMock()
        reply_photo_name = AsyncMock()
        update_name = SimpleNamespace(
            message=SimpleNamespace(
                text="Игрок С",
                reply_text=reply_text_name,
                reply_photo=reply_photo_name,
            ),
            effective_user=update_start.effective_user,
            effective_chat=update_start.effective_chat,
        )

        send_state_mock = AsyncMock()
        monkeypatch.setattr(router_module, "_send_state", send_state_mock)
        router15_module = importlib.import_module("game_board15.router")
        monkeypatch.setattr(router15_module, "_send_state", send_state_mock)

        await router_module.router_text(update_name, context)

        joiner_messages = [call.args[0] for call in reply_text_name.call_args_list]
        assert any("Игрок С" in text for text in joiner_messages)
        assert any("ходит Игрок A" in text for text in joiner_messages)

        other_messages = [call.args[1] for call in context.bot.send_message.call_args_list]
        assert any("Игрок Игрок С присоединился." in text for text in other_messages)
        assert any("Ваш ход" in text for text in other_messages)

        assert send_state_mock.await_count == 3
        called_players = [record.args[2] for record in send_state_mock.await_args_list]
        assert set(called_players) == {"A", "B", "C"}

        captions_by_player = {
            record.args[2]: record.args[3]
            for record in send_state_mock.await_args_list
        }
        assert "Ваш ход" in captions_by_player["A"]
        assert "Ходит Игрок A" in captions_by_player["B"]
        assert "Ходит Игрок A" in captions_by_player["C"]

    asyncio.run(run())


def test_board15_test_sets_playing(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_ID", "1")
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


def test_board15_test_fast_uses_zero_delay(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_ID", "1")
    commands_module, storage15, handlers15, _ = _reload_board15(monkeypatch, tmp_path)

    async def run():
        context = SimpleNamespace(
            user_data={commands_module.NAME_KEY: "Тест"},
            bot_data={},
            bot=SimpleNamespace(
                send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                send_message=AsyncMock(),
            ),
        )
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=1, first_name="Admin"),
            effective_chat=SimpleNamespace(id=1),
        )

        auto_play_mock = AsyncMock()
        monkeypatch.setattr(handlers15, "_auto_play_bots", auto_play_mock)

        await handlers15.board15_test_fast(update, context)

        match = storage15.find_match_by_user(1, 1)
        assert match is not None
        assert match.status == "playing"
        auto_play_mock.assert_awaited()
        args, kwargs = auto_play_mock.await_args
        assert kwargs.get("delay") == 0.0
        assert args[0] is context
    asyncio.run(run())


def test_board15_test_denies_without_admin(monkeypatch, tmp_path):
    monkeypatch.delenv("ADMIN_ID", raising=False)
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
            effective_user=SimpleNamespace(id=999, first_name="Tester"),
            effective_chat=SimpleNamespace(id=1),
        )

        await handlers15.board15_test(update, context)

        assert storage15.find_match_by_user(999, 1) is None
        replies = [record.args[0] for record in reply_text.call_args_list]
        assert any("Команда доступна только администратору." in text for text in replies)

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

        send_state_mock = AsyncMock()
        monkeypatch.setattr(router_module, "_send_state", send_state_mock)
        router15_module = importlib.import_module("game_board15.router")
        monkeypatch.setattr(router15_module, "_send_state", send_state_mock)

        await router_module.router_text(update_name, context)

        name_texts = [call.args[0] for call in reply_text_name.call_args_list]
        assert any("Имя сохранено" in text for text in name_texts)
        assert any("Вы присоединились к матчу 15×15" in text for text in name_texts)
        assert all('"авто"' not in text.lower() for text in name_texts)

        assert reply_photo_name.await_count == 1

        other_messages = [call.args[1] for call in context.bot.send_message.call_args_list]
        assert other_messages
        assert any("Игрок Игрок Б присоединился." in text for text in other_messages)
        assert all('"авто"' not in text.lower() for text in other_messages)

        send_state_mock.assert_not_awaited()

        stored_name = context.user_data.get(commands_module.NAME_KEY)
        assert stored_name == "Игрок Б"
        state_after = context.user_data.get(commands_module.NAME_STATE_KEY, {})
        assert not state_after.get("waiting")

    asyncio.run(run())
