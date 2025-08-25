import os

# Flag to enable single-user test mode for the 15x15 three-player variant.
# When the environment variable ``B15_TEST_MODE`` is set to ``"1"`` or
# ``"true"`` (case-insensitive), all three players are controlled by the same
# Telegram user.  This allows sequential testing of turns without inviting
# additional participants.  In production the variable should be unset so that
# three separate users are required.
TEST_MODE = os.getenv("B15_TEST_MODE", "").lower() in {"1", "true", "yes"}

