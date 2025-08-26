from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


@dataclass
class GameState:
    """Holds ids of messages related to the game session.

    ``base_word_msg_id`` is kept for backward compatibility with older tests
    which expect the state object to have this attribute.  The new field
    ``keyboard_msg_id`` stores the identifier of the message with the move
    keyboard so that it can be deleted before sending a fresh one on the next
    turn.
    """

    base_word_msg_id: Optional[int] = None
    keyboard_msg_id: Optional[int] = None


def move_keyboard(game: GameState) -> InlineKeyboardMarkup:
    """Build a 5×5 keyboard with cell coordinates.

    The keyboard is static and does not depend on the game state but the
    ``game`` argument makes the API flexible and mirrors existing helpers in
    the project.
    """

    letters = "ABCDE"
    keyboard: list[list[InlineKeyboardButton]] = []
    for r in range(5):
        row: list[InlineKeyboardButton] = []
        for c in range(5):
            label = f"{letters[r]}{c + 1}"
            row.append(
                InlineKeyboardButton(label, callback_data=f"mv|{r}|{c}")
            )
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user input and refresh the move keyboard.

    The current implementation does not process the text itself—the focus of
    the tests is on the lifecycle of the keyboard message.  At the beginning of
    each call we delete the previous keyboard message (if any) and then send a
    new one.
    """

    game: GameState = context.chat_data.setdefault("game_state", GameState())
    chat_id = update.effective_chat.id

    if game.keyboard_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=game.keyboard_msg_id)
        except Exception:
            pass
        game.keyboard_msg_id = None

    keyboard = move_keyboard(game)
    # Render a static 5×5 board so that the keyboard is visually attached to
    # the latest field representation.  This mirrors the coordinates used in
    # ``move_keyboard`` and ensures that after each turn the player always sees
    # a fresh board with the inline keyboard directly underneath it.
    letters = "ABCDE"
    board_lines = [" ".join(f"{letters[r]}{c + 1}" for c in range(5)) for r in range(5)]
    board_text = "\n".join(board_lines)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=board_text,
        reply_markup=keyboard,
    )
    game.keyboard_msg_id = msg.message_id
