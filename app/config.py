"""Runtime configuration helpers for environment-driven flags."""
from __future__ import annotations

import os
from typing import Final


def env_flag(name: str, *, default: bool = False) -> bool:
    """Return a boolean flag from environment variables.

    The helper treats common truthy values (``1``, ``true``, ``yes``, ``on``)
    as ``True`` and common falsy ones (``0``, ``false``, ``no``, ``off``) as
    ``False``.  If the variable is unset or contains an unrecognised value, the
    provided ``default`` is used.  This allows feature flags to be configured
    explicitly while still having sensible fallbacks in local environments.
    """
    value = os.getenv(name)
    if value is None:
        return default

    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    return default


BOARD15_ENABLED: Final[bool] = env_flag("BOARD15_ENABLED", default=True)
BOARD15_TEST_ENABLED: Final[bool] = env_flag("BOARD15_TEST_ENABLED", default=True)

__all__ = [
    "BOARD15_ENABLED",
    "BOARD15_TEST_ENABLED",
    "env_flag",
]
