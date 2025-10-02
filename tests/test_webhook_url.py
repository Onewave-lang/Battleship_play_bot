import pytest

from app.webhook_utils import normalize_webhook_base


@pytest.mark.parametrize(
    "raw_url, expected_base",
    [
        ("https://host", "https://host"),
        ("https://host/webhook", "https://host"),
        ("https://host/webhook/", "https://host"),
    ],
)
def test_normalize_webhook_base(raw_url: str, expected_base: str) -> None:
    assert normalize_webhook_base(raw_url) == expected_base


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://host",
        "https://host/webhook",
    ],
)
def test_webhook_path_has_single_suffix(raw_url: str) -> None:
    base = normalize_webhook_base(raw_url)
    webhook = f"{base}/webhook"

    assert webhook.endswith("/webhook")
    assert webhook.count("/webhook") == 1
    assert webhook == "https://host/webhook"

