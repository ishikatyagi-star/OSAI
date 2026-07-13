from datetime import datetime
from typing import Any

import httpx

from api.schemas.connector import (
    ActionResult,
    AuthStatus,
    ConnectorAction,
    HealthcheckResult,
    PermissionSet,
    SourceDocument,
    SyncResult,
)
from config import settings
from connectors.base import Connector

NOTION_VERSION = "2022-06-28"


class NotionConnector(Connector):
    key = "notion"
    display_name = "Notion"
    capabilities = {"sync", "search", "execute"}

    def __init__(
        self,
        token: str | None = None,
        root_page_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token if token is not None else settings.notion_api_token
        self.root_page_id = (
            root_page_id if root_page_id is not None else settings.notion_root_page_id
        )
        self.client = client

    async def auth_status(self, org_id: str) -> AuthStatus:
        if not self.token:
            return AuthStatus(
                connector_key=self.key,
                connected=False,
                error="Set OSAI_NOTION_API_TOKEN to enable Notion sync.",
            )
        return AuthStatus(connector_key=self.key, connected=True, scopes=["read_content"])

    async def sync(self, org_id: str, cursor: str | None = None) -> SyncResult:
        auth = await self.auth_status(org_id)
        if not auth.connected:
            import sys
            if "pytest" in sys.modules:
                return SyncResult(connector_key=self.key, status="failed", error=auth.error)

            # Real connections come through Composio OAuth; the native connector
            # only syncs with its own credentials and must never emit demo data
            # into a customer workspace.
            return SyncResult(
                connector_key=self.key,
                status="failed",
                error=auth.error or "Not connected. Use Connect to authorize this source.",
            )

        try:
            objects = (
                [await self._request("GET", f"/pages/{self.root_page_id}")]
                if self.root_page_id
                else await self._search_pages(cursor)
            )
            documents = [
                await self._page_to_document(org_id, page)
                for page in objects
                if page.get("object") == "page"
            ]
            return SyncResult(connector_key=self.key, status="succeeded", documents=documents)
        except httpx.HTTPError as exc:
            return SyncResult(connector_key=self.key, status="failed", error=str(exc))

    async def get_permissions(self, document: SourceDocument) -> PermissionSet:
        return PermissionSet(principals=document.permissions, public=False)

    async def search(self, org_id: str, query: str) -> list[SourceDocument]:
        result = await self.sync(org_id)
        query_lower = query.lower()
        return [
            document
            for document in result.documents
            if query_lower in document.title.lower() or query_lower in document.text.lower()
        ]

    async def execute_action(self, org_id: str, action: ConnectorAction) -> ActionResult:
        if not self.token:
            return ActionResult(
                connector_key=self.key,
                status="skipped",
                error="Notion token is not configured.",
            )
        return ActionResult(
            connector_key=self.key,
            status="skipped",
            error="Notion task creation will be enabled after destination database config.",
        )

    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        auth = await self.auth_status(org_id)
        return HealthcheckResult(
            connector_key=self.key,
            healthy=auth.connected,
            message=auth.error or "Notion token configured",
        )

    async def _search_pages(self, cursor: str | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 25,
        }
        if cursor:
            payload["start_cursor"] = cursor
        response = await self._request("POST", "/search", json=payload)
        return list(response.get("results", []))

    async def _page_to_document(self, org_id: str, page: dict[str, Any]) -> SourceDocument:
        page_id = page["id"]
        blocks = await self._fetch_blocks(page_id)
        text = "\n".join(filter(None, [self._block_text(block) for block in blocks]))
        title = self._page_title(page)
        updated_at = _parse_notion_datetime(page.get("last_edited_time"))
        created_at = _parse_notion_datetime(page.get("created_time"))
        return SourceDocument(
            source_id=f"notion:{page_id}",
            source_type="notion",
            org_id=org_id,
            external_id=page_id,
            title=title,
            url=page.get("url"),
            author=page.get("created_by", {}).get("id"),
            created_at=created_at,
            updated_at=updated_at,
            text=text or title,
            metadata={"notion_object": page.get("object"), "parent": page.get("parent", {})},
            permissions=[f"notion:page:{page_id}"],
            data_tier="normal",
        )

    async def _fetch_blocks(self, page_id: str) -> list[dict[str, Any]]:
        response = await self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        return list(response.get("results", []))

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
        }
        if self.client:
            response = await self.client.request(
                method,
                f"https://api.notion.com/v1{path}",
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"https://api.notion.com/v1{path}",
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _page_title(page: dict[str, Any]) -> str:
        properties = page.get("properties", {})
        for property_value in properties.values():
            if property_value.get("type") == "title":
                title_parts = property_value.get("title", [])
                title = "".join(part.get("plain_text", "") for part in title_parts).strip()
                if title:
                    return title
        return "Untitled Notion page"

    @staticmethod
    def _block_text(block: dict[str, Any]) -> str:
        block_type = block.get("type")
        if not block_type:
            return ""
        value = block.get(block_type, {})
        rich_text = value.get("rich_text") or []
        text = "".join(part.get("plain_text", "") for part in rich_text).strip()
        if block_type == "to_do":
            prefix = "[x]" if value.get("checked") else "[ ]"
            return f"{prefix} {text}".strip()
        return text


def _parse_notion_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
