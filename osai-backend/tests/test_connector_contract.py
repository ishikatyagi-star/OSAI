from connectors.registry import connector_registry


async def test_registry_contains_first_connectors() -> None:
    keys = {connector.key for connector in connector_registry.all()}
    assert {"notion", "slack", "freshdesk", "google_drive"}.issubset(keys)


async def test_registered_connectors_expose_contract_methods() -> None:
    for connector in connector_registry.all():
        assert connector.key
        assert connector.display_name
        assert connector.capabilities
        health = await connector.healthcheck("demo-org")
        assert health.connector_key == connector.key
        assert health.healthy is True
