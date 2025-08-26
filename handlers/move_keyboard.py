from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def move_keyboard() -> InlineKeyboardMarkup:
    """Return a static 5×5 inline keyboard for choosing moves.

    Buttons are labelled with coordinates (A1..E5) and include callback data
    identifying the selected cell.  The callback format is ``mv|row|col`` to
    mirror conventions in other parts of the project.
    """
    letters = "ABCDE"
    keyboard: list[list[InlineKeyboardButton]] = []
    for r in range(5):
        row: list[InlineKeyboardButton] = []
        for c in range(5):
            label = f"{letters[r]}{c + 1}"
            row.append(InlineKeyboardButton(label, callback_data=f"mv|{r}|{c}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)
