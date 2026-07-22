"""Regression coverage for the intentionally disabled Zoom webhook."""

from fastapi.testclient import TestClient

from api.main import app
from config import settings


def test_zoom_webhook_cannot_be_enabled_without_tenant_auth_binding(monkeypatch) -> None:
    monkeypatch.setattr(settings, "zoom_webhook_enabled", True)
    monkeypatch.setattr(settings, "zoom_webhook_secret", "configured-secret")

    response = TestClient(app).post(
        "/webhooks/zoom",
        json={
            "event": "recording.completed",
            "payload": {
                "object": {
                    "id": "meeting-1",
                    "recording_files": [
                        {"download_url": "https://us02web.zoom.us/rec/download/test"}
                    ],
                }
            },
        },
    )

    assert response.status_code == 404
