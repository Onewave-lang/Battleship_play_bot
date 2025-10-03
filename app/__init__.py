from __future__ import annotations

from dataclasses import dataclass
from handlers.move_keyboard import move_keyboard as _move_keyboard_impl


@dataclass
class GameState:
    """Holds chat-specific game state such as the keyboard message id."""

    keyboard_msg_id: int | None = None


def move_keyboard(state: GameState | None = None):
    """Return the move selection keyboard.

    The ``state`` parameter is preserved for backwards compatibility but is
    not used by the current implementation.
    """

    return _move_keyboard_impl()


async def handle_text(update, context) -> None:
    """Handle a textual update by refreshing the move keyboard."""

    state = context.chat_data.setdefault("game_state", GameState())
    if state.keyboard_msg_id is not None:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id, message_id=state.keyboard_msg_id
        )

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Choose your move",
        reply_markup=move_keyboard(state),
    )
    state.keyboard_msg_id = message.message_id


__all__ = ["GameState", "move_keyboard", "handle_text"]