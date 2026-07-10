from api.routes.integrations import _may_use_native_fallback
from config import settings


def test_only_the_configured_demo_org_may_use_native_fallback() -> None:
    assert _may_use_native_fallback(settings.default_org_id)
    assert not _may_use_native_fallback("real-org")
