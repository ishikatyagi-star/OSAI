"""Single policy gate for document visibility and data-tier clearance."""

from __future__ import annotations

TIER_ORDER = {"normal": 0, "amber": 1, "red": 2}


def allowed_tiers(requester_tier: str) -> list[str]:
    return [tier for tier, rank in TIER_ORDER.items() if rank <= TIER_ORDER.get(requester_tier, 2)]


def tier_visible(resource_tier: str | None, requester_tier: str) -> bool:
    return TIER_ORDER.get(resource_tier or "normal", 0) <= TIER_ORDER.get(requester_tier, 2)


def visible(resource_permissions: list[str] | None, requester_permissions: list[str]) -> bool:
    if not requester_permissions or "role:admin" in requester_permissions or "org:admin" in requester_permissions:
        return True
    permissions = resource_permissions or []
    if not permissions or "source:all" in permissions:
        return True
    if "source:all" in requester_permissions and any(permission.startswith("source:") for permission in permissions):
        return True
    return bool(set(permissions) & set(requester_permissions))


def can_access(
    resource_permissions: list[str] | None,
    resource_tier: str | None,
    requester_permissions: list[str],
    requester_tier: str,
) -> bool:
    return visible(resource_permissions, requester_permissions) and tier_visible(resource_tier, requester_tier)
