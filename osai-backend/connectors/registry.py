from connectors.base import Connector
from connectors.stubs import StubConnector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.key] = connector

    def get(self, key: str) -> Connector:
        return self._connectors[key]

    def all(self) -> list[Connector]:
        return list(self._connectors.values())


connector_registry = ConnectorRegistry()
connector_registry.register(StubConnector("notion", "Notion", {"sync", "search", "execute"}))
connector_registry.register(StubConnector("slack", "Slack", {"sync", "search", "execute"}))
connector_registry.register(StubConnector("freshdesk", "Freshdesk", {"sync", "search", "execute"}))
connector_registry.register(StubConnector("google_drive", "Google Drive", {"sync", "search"}))
