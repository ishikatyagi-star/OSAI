from abc import ABC, abstractmethod

from api.schemas.connector import (
    ActionResult,
    AuthStatus,
    ConnectorAction,
    HealthcheckResult,
    PermissionSet,
    SourceDocument,
    SyncResult,
)


class Connector(ABC):
    key: str
    display_name: str
    capabilities: set[str]

    def summary(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "capabilities": sorted(self.capabilities),
            "auth_state": "not_configured",
            "last_sync": None,
        }

    @abstractmethod
    async def auth_status(self, org_id: str) -> AuthStatus:
        raise NotImplementedError

    @abstractmethod
    async def sync(self, org_id: str, cursor: str | None = None) -> SyncResult:
        raise NotImplementedError

    @abstractmethod
    async def get_permissions(self, document: SourceDocument) -> PermissionSet:
        raise NotImplementedError

    @abstractmethod
    async def search(self, org_id: str, query: str) -> list[SourceDocument]:
        raise NotImplementedError

    @abstractmethod
    async def execute_action(self, org_id: str, action: ConnectorAction) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        raise NotImplementedError
