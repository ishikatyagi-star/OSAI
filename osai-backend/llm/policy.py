"""Central policy for model and connector egress.

The org's data-routing settings declare whether each source-data tier may reach
a cloud model and which connector destinations may receive data from that tier.
All policy reads and decisions fail closed: malformed or unavailable policy,
missing provenance, and unknown tiers or destinations are denied.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

logger = logging.getLogger("osai.policy")

_TIERS = ("normal", "amber", "red")
_CONNECTOR_SLUG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


def _normalize_connector_slug(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("connector destinations must be strings")
    slug = value.strip().lower()
    if not _CONNECTOR_SLUG.fullmatch(slug):
        raise ValueError("connector destinations must be bounded lowercase slugs")
    return slug


class TierRoutingPolicy(BaseModel):
    """Validated routing policy for one source-data tier."""

    model_config = ConfigDict(extra="forbid")

    allowed_connectors: list[str]
    llm_allowed: StrictBool

    @field_validator("allowed_connectors", mode="before")
    @classmethod
    def _validate_connectors(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("allowed_connectors must be a list")
        normalized: list[str] = []
        for connector in value:
            slug = _normalize_connector_slug(connector)
            if slug not in normalized:
                normalized.append(slug)
        return normalized


class DataRoutingPolicy(BaseModel):
    """Complete, typed data-routing settings accepted at the API boundary."""

    model_config = ConfigDict(extra="forbid")

    normal: TierRoutingPolicy
    amber: TierRoutingPolicy
    red: TierRoutingPolicy


DEFAULT_DATA_ROUTING: dict[str, dict] = DataRoutingPolicy.model_validate(
    {
        "normal": {
            "allowed_connectors": ["notion", "slack", "freshdesk", "google_drive"],
            "llm_allowed": True,
        },
        # Matches the Amber policy copy in the UI (only Notion and Google Drive).
        "amber": {
            "allowed_connectors": ["notion", "google_drive"],
            "llm_allowed": False,
        },
        "red": {"allowed_connectors": [], "llm_allowed": False},
    }
).model_dump(mode="python")

DENY_ALL_DATA_ROUTING: dict[str, dict] = DataRoutingPolicy.model_validate(
    {tier: {"allowed_connectors": [], "llm_allowed": False} for tier in _TIERS}
).model_dump(mode="python")


def normalize_data_routing(
    value: object,
    *,
    merge_defaults: bool = False,
) -> dict[str, dict]:
    """Validate and normalize a routing payload.

    API writes use the complete schema directly. Stored rows may predate fields
    in the schema, so reads can deep-merge known tier dictionaries with defaults
    before validation. Unknown tiers/fields and malformed values are never
    discarded by that merge; validation rejects them and enforcement denies all.
    """
    if not isinstance(value, dict):
        raise ValueError("data routing must be an object")
    candidate = deepcopy(value)
    if merge_defaults:
        merged = deepcopy(DEFAULT_DATA_ROUTING)
        for tier, tier_policy in candidate.items():
            if tier in merged and isinstance(tier_policy, dict):
                merged[tier] = {**merged[tier], **tier_policy}
            else:
                merged[tier] = tier_policy
        candidate = merged
    return DataRoutingPolicy.model_validate(candidate).model_dump(mode="python")


def load_data_routing(org_id: str) -> dict[str, dict]:
    """Load one org's validated routing policy.

    A successful read with no override uses the product defaults. A database
    outage or malformed stored policy returns deny-all, because availability of
    the policy is part of the authorization decision.
    """
    try:
        from db.models import Org
        from db.session import SessionLocal

        with SessionLocal() as session:
            org = session.get(Org, org_id)
            if org is None:
                logger.warning("Could not load data routing for unknown org (using deny-all)")
                return deepcopy(DENY_ALL_DATA_ROUTING)
            if org.data_routing is None or org.data_routing == {}:
                return deepcopy(DEFAULT_DATA_ROUTING)
            return normalize_data_routing(org.data_routing, merge_defaults=True)
    except Exception as exc:  # noqa: BLE001 - policy availability must fail closed
        logger.warning("Could not load valid data routing for org (using deny-all): %s", exc)
        return deepcopy(DENY_ALL_DATA_ROUTING)


def cloud_llm_allowed(routing: dict[str, dict], tier: str | None) -> bool:
    """Return whether known-tier content may be sent to a cloud model."""
    if not isinstance(routing, dict) or tier not in _TIERS:
        return False
    tier_policy = routing.get(tier)
    return isinstance(tier_policy, dict) and tier_policy.get("llm_allowed") is True


def connector_egress_allowed(
    routing: dict[str, dict],
    source_tiers: list[str | None],
    destination: str | None,
) -> bool:
    """Return whether every source tier allows one external destination.

    Missing provenance is intentionally unknown and therefore denied. Requiring
    every source tier to allow the destination makes the most restrictive source
    win when a result combines content from multiple tiers.
    """
    if not isinstance(source_tiers, list) or not source_tiers:
        return False
    try:
        destination_slug = _normalize_connector_slug(destination)
        policy = DataRoutingPolicy.model_validate(routing)
    except (TypeError, ValueError):
        return False
    for tier in source_tiers:
        if tier not in _TIERS:
            return False
        tier_policy = getattr(policy, tier)
        if destination_slug not in tier_policy.allowed_connectors:
            return False
    return True
