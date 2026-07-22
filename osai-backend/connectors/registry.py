from connectors.base import Connector
from connectors.freshdesk import FreshdeskConnector
from connectors.google_drive import GoogleDriveConnector
from connectors.notion import NotionConnector
from connectors.slack import SlackConnector

# These keys may still exist in databases created by older releases, but they
# must never be presented as usable connections. Zoom remains hard-disabled
# until a tenant-bound authenticated ingestion design exists.
HARD_DISABLED_CONNECTOR_KEYS = frozenset({"zoom"})


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
connector_registry.register(NotionConnector())
connector_registry.register(SlackConnector())
connector_registry.register(FreshdeskConnector())
connector_registry.register(GoogleDriveConnector())
