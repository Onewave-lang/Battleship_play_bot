import os
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

def test_healthz(monkeypatch):
    os.environ.setdefault("BOT_TOKEN", "test")
    os.environ.setdefault("WEBHOOK_URL", "http://example.com")

    from app import main

    monkeypatch.setattr(main.bot_app, "initialize", AsyncMock())
    monkeypatch.setattr(main.bot_app, "start", AsyncMock())
    monkeypatch.setattr(main.bot_app, "stop", AsyncMock())
    monkeypatch.setattr(main.bot_app, "shutdown", AsyncMock())
    bot_cls = main.bot_app.bot.__class__
    monkeypatch.setattr(bot_cls, "set_webhook", AsyncMock())
    monkeypatch.setattr(bot_cls, "delete_webhook", AsyncMock())

    with TestClient(main.app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

