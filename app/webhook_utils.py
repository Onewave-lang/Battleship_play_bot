"""Utilities for normalising webhook URLs."""


def normalize_webhook_base(raw_url: str) -> str:
    """Normalise a webhook base URL by removing trailing slashes and suffixes.

    Telegram expects the webhook endpoint to end with ``/webhook``. Operators
    may configure the environment variable with or without that suffix,
    potentially including extra trailing slashes. This helper ensures we always
    compute the effective base URL consistently so the final webhook path is
    predictable.

    Parameters
    ----------
    raw_url:
        The URL provided via configuration, typically the ``WEBHOOK_URL``
        environment variable.

    Returns
    -------
    str
        The normalised base URL without the ``/webhook`` suffix.
    """

    normalized = raw_url.rstrip("/")
    if normalized.endswith("/webhook"):
        normalized = normalized[: -len("/webhook")]
        normalized = normalized.rstrip("/")
    return normalized

