from connectors.composio_ingest import supports_sync


def test_catalog_sync_capability_matches_curated_fetchers():
    assert supports_sync("gmail")
    assert supports_sync("github")
    assert not supports_sync("jira")
