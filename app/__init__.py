from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GameState:
    """Chat-specific state used to track the latest prompt message."""

    prompt_msg_id: int | None = None


async def handle_text(update, context) -> None:
    """Handle a textual update by refreshing the textual move prompt."""

    state = context.chat_data.setdefault("game_state", GameState())
    if state.prompt_msg_id is not None:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id, message_id=state.prompt_msg_id
        )

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Введите координату выстрела (например, д5).",
    )
    state.prompt_msg_id = message.message_id


__all__ = ["GameState", "handle_text"]