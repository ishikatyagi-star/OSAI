from __future__ import annotations

import httpx

from api.schemas.connector import ConnectorAction
from connectors.freshdesk import FreshdeskConnector
from connectors.google_drive import GoogleDriveConnector
from connectors.slack import SlackConnector


class _SlackClient:
    def __init__(self) -> None:
        self.request_data = None

    async def request(self, method, url, **kwargs):
        self.request_data = (method, url, kwargs)
        return httpx.Response(
            200,
            json={"ok": True, "ts": "1710000000.123"},
            request=httpx.Request(method, url),
        )


class _FreshdeskClient:
    def __init__(self) -> None:
        self.request_data = None

    async def post(self, url, **kwargs):
        self.request_data = (url, kwargs)
        return httpx.Response(
            200,
            json={"id": 42},
            request=httpx.Request("POST", url),
        )


async def test_slack_action_uses_provider_payload_contract() -> None:
    client = _SlackClient()
    result = await SlackConnector(token="test-token", client=client).execute_action(
        "org-a",
        ConnectorAction(
            action_type="post_message",
            payload={"channel": "C123", "text": "Ship it"},
            idempotency_key="d9a027ab-5715-54f9-a664-854276cac554",
        ),
    )

    method, url, kwargs = client.request_data
    assert (method, url) == ("POST", "https://slack.com/api/chat.postMessage")
    assert kwargs["json"] == {
        "channel": "C123",
        "text": "Ship it",
        "client_msg_id": "d9a027ab-5715-54f9-a664-854276cac554",
    }
    assert kwargs["headers"] == {"Authorization": "Bearer test-token"}
    assert result.status == "succeeded"
    assert result.external_id == "1710000000.123"


async def test_freshdesk_action_uses_provider_payload_contract() -> None:
    client = _FreshdeskClient()
    result = await FreshdeskConnector(
        domain="acme.freshdesk.com", api_key="test-key", client=client
    ).execute_action(
        "org-a",
        ConnectorAction(
            action_type="create_ticket",
            payload={"subject": "Outage", "description": "API is down", "priority": 4},
        ),
    )

    url, kwargs = client.request_data
    assert url == "https://acme.freshdesk.com/api/v2/tickets"
    assert kwargs["json"] == {
        "subject": "Outage",
        "description": "API is down",
        "email": "osai@internal.local",
        "priority": 4,
        "status": 2,
    }
    assert kwargs["headers"]["Authorization"].startswith("Basic ")
    assert result.status == "succeeded"
    assert result.external_id == "42"


def test_google_drive_file_maps_to_tenant_scoped_document() -> None:
    document = GoogleDriveConnector()._file_to_document(
        "org-a",
        {
            "id": "file-1",
            "name": "Roadmap",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://drive.google.com/file-1",
            "parents": ["folder-1"],
            "createdTime": "2026-07-01T10:00:00Z",
            "modifiedTime": "2026-07-02T11:00:00Z",
        },
        "Q3 priorities",
    )

    assert document.org_id == "org-a"
    assert document.source_id == "google_drive:file:file-1"
    assert document.permissions == ["google_drive:file:file-1"]
    assert document.text == "Q3 priorities"
    assert document.metadata == {
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["folder-1"],
    }
