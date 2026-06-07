from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from connectors.notion import NotionConnector


@dataclass
class FakeNotionClient:
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if url.endswith("/search"):
            payload = {
                "results": [
                    {
                        "object": "page",
                        "id": "page-1",
                        "created_time": "2026-06-04T05:00:00.000Z",
                        "last_edited_time": "2026-06-04T06:00:00.000Z",
                        "created_by": {"id": "user-1"},
                        "url": "https://notion.so/page-1",
                        "parent": {"type": "workspace"},
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Pilot Notes"}],
                            }
                        },
                    }
                ]
            }
            return _json_response(payload)
        if url.endswith("/blocks/page-1/children?page_size=100"):
            return _json_response(
                {
                    "results": [
                        {
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"plain_text": "Launch Notion sync."}]},
                        },
                        {
                            "type": "to_do",
                            "to_do": {
                                "checked": False,
                                "rich_text": [{"plain_text": "Create Freshdesk follow-up."}],
                            },
                        },
                    ]
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url} {kwargs}")


def _json_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode(),
        request=httpx.Request("GET", "https://api.notion.com"),
    )


async def test_notion_sync_normalizes_page_to_source_document() -> None:
    connector = NotionConnector(token="secret_test", client=FakeNotionClient())
    result = await connector.sync("demo-org")

    assert result.status == "succeeded"
    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.source_id == "notion:page-1"
    assert document.title == "Pilot Notes"
    assert "Launch Notion sync." in document.text
    assert "[ ] Create Freshdesk follow-up." in document.text
    assert document.permissions == ["notion:page:page-1"]


async def test_notion_without_token_reports_not_configured() -> None:
    connector = NotionConnector(token="")
    status = await connector.auth_status("demo-org")
    result = await connector.sync("demo-org")

    assert status.connected is False
    assert result.status == "failed"
    assert "OSAI_NOTION_API_TOKEN" in str(result.error)
