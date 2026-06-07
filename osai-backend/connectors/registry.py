from connectors.base import Connector
from connectors.freshdesk import FreshdeskConnector
from connectors.google_drive import GoogleDriveConnector
from connectors.notion import NotionConnector
from connectors.slack import SlackConnector


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
