"""Tests for Zoom Webhook validation and signature check routing."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from config import settings

client = TestClient(app)


def test_zoom_crc_validation() -> None:
    original_secret = settings.zoom_webhook_secret
    settings.zoom_webhook_secret = "test-secret"
    try:
        payload = {
            "event": "endpoint.url_validation",
            "payload": {
                "plainToken": "xyz123",
            },
        }

        # Computed HMAC using key 'test-secret'
        expected_hash = hmac.new(b"test-secret", b"xyz123", hashlib.sha256).hexdigest()

        response = client.post("/webhooks/zoom", json=payload)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["plainToken"] == "xyz123"
        assert res_json["encryptedToken"] == expected_hash
    finally:
        settings.zoom_webhook_secret = original_secret


def test_zoom_webhook_invalid_signature() -> None:
    original_secret = settings.zoom_webhook_secret
    settings.zoom_webhook_secret = "test-secret"
    try:
        payload = {
            "event": "recording.completed",
            "payload": {
                "object": {
                    "id": 99999,
                    "topic": "Test Meeting",
                    "recording_files": [],
                },
            },
        }

        headers = {
            "x-zm-signature": "v0=invalid-signature",
            "x-zm-request-timestamp": "123456789",
        }

        response = client.post("/webhooks/zoom", json=payload, headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid signature"
    finally:
        settings.zoom_webhook_secret = original_secret


@patch("api.routes.webhooks._zoom_org_id", return_value="org-zoom")
@patch("api.routes.webhooks.download_and_transcribe")
def test_zoom_webhook_valid_signature_recording_completed(mock_task, mock_org_id) -> None:
    original_secret = settings.zoom_webhook_secret
    settings.zoom_webhook_secret = "test-secret"
    try:
        payload = {
            "event": "recording.completed",
            "payload": {
                "account_id": "zoom-account-1",
                "object": {
                    "id": 99999,
                    "topic": "Test Meeting",
                    "recording_files": [
                        {
                            "file_type": "M4A",
                            "download_url": "http://example.com/recording.m4a",
                        },
                    ],
                },
            },
        }

        # Generate correct signature for this raw body
        raw_body = json.dumps(payload, separators=(",", ":"))
        timestamp = "123456789"
        message = f"v0:{timestamp}:{raw_body}"
        computed_hash = hmac.new(
            b"test-secret", message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        headers = {
            "x-zm-signature": f"v0={computed_hash}",
            "x-zm-request-timestamp": timestamp,
        }

        response = client.post("/webhooks/zoom", content=raw_body, headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Assert the task was enqueued with the correct params
        mock_task.delay.assert_called_once_with(
            meeting_id="99999",
            download_url="http://example.com/recording.m4a",
            topic="Test Meeting",
            org_id="org-zoom",
        )
        assert mock_org_id.call_args.args[1] == "zoom-account-1"
    finally:
        settings.zoom_webhook_secret = original_secret


def test_zoom_webhook_requires_secret_outside_demo_mode() -> None:
    original_secret = settings.zoom_webhook_secret
    original_env = settings.env
    settings.zoom_webhook_secret = None
    settings.env = "production"
    try:
        response = client.post("/webhooks/zoom", json={"event": "meeting.started", "payload": {}})
        assert response.status_code == 503
    finally:
        settings.zoom_webhook_secret = original_secret
        settings.env = original_env
