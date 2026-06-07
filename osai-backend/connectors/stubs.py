from api.schemas.connector import (
    ActionResult,
    AuthStatus,
    ConnectorAction,
    HealthcheckResult,
    PermissionSet,
    SourceDocument,
    SyncResult,
)
from connectors.base import Connector


class StubConnector(Connector):
    def __init__(self, key: str, display_name: str, capabilities: set[str]) -> None:
        self.key = key
        self.display_name = display_name
        self.capabilities = capabilities

    async def auth_status(self, org_id: str) -> AuthStatus:
        return AuthStatus(connector_key=self.key, connected=False)

    async def sync(self, org_id: str, cursor: str | None = None) -> SyncResult:
        return SyncResult(connector_key=self.key, status="failed", error="Connector not configured")

    async def get_permissions(self, document: SourceDocument) -> PermissionSet:
        return PermissionSet(principals=document.permissions, public=not document.permissions)

    async def search(self, org_id: str, query: str) -> list[SourceDocument]:
        return []

    async def execute_action(self, org_id: str, action: ConnectorAction) -> ActionResult:
        return ActionResult(
            connector_key=self.key,
            status="skipped",
            error="Connector not configured",
        )

    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        return HealthcheckResult(connector_key=self.key, healthy=True, message="Stub registered")
